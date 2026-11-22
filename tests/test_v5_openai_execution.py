"""OpenAI execution safeguards (offline: fake SDK, synthetic IDs, no network or credential)."""
import json
from types import SimpleNamespace

from layer4_evaluation.indicators.ollama_provider import configuration
from layer4_evaluation.indicators.openai_provider import OpenAIClient
from scripts import pipeline_coordinator as coordinator


def test_api_requests_pseudonymize_researcher_names_only():
    context = dict(project_id='PROJ_1', seed_entity_id='PROJECT:PROJ_1', relations=[dict(relation_id='R1')], support_paths={'X': ['R1']},
                   entities=[dict(entity_id='PROJECT:PROJ_1', entity_type='PROJECT', canonical_id='PROJ_1', label='Titulo'),
                             dict(entity_id='RESEARCHER:RES_a', entity_type='RESEARCHER', canonical_id='RES_a', label='Apellido, Nombre')])
    candidate = dict(candidate_id='C', relational_context=context)
    result = coordinator.pseudonymize_researchers(candidate)
    labels = {e['entity_id']: e['label'] for e in result['relational_context']['entities']}
    assert labels == {'PROJECT:PROJ_1': 'Titulo', 'RESEARCHER:RES_a': 'Investigador (seudonimizado)'}
    assert result['relational_context']['relations'] == context['relations'] and result['relational_context']['support_paths'] == context['support_paths']
    assert candidate['relational_context']['entities'][1]['label'] == 'Apellido, Nombre'  # input not mutated
    assert coordinator.pseudonymize_researchers(dict(candidate_id='A')) == dict(candidate_id='A')  # articles: no relational context


class Completed:
    def __init__(self, text):
        self.output_text = text; self.id = 'r'; self._request_id = None
    def model_dump(self, mode='json'):
        return dict(id='r', status='completed', model='gpt-6.1-terra', usage=dict(input_tokens=10, output_tokens=5))


def test_openai_transport_sends_the_attempt_output_allowance(tmp_path):
    settings = configuration(dict(provider='openai', api=dict(budget_usd=1, retry_seconds=0)))
    sent = []
    client = OpenAIClient(settings, sdk=SimpleNamespace(responses=SimpleNamespace(create=lambda **r: sent.append(r) or Completed('{}'))), root=tmp_path)
    client.attach(tmp_path); client.project_id = 'P'
    schema = {'type': 'object', 'properties': {}, 'additionalProperties': False}
    for n, allowance in enumerate((4096, 6144)):
        client.attempt = tmp_path / f'a{n}'; client.attempt.mkdir()
        client.request('POST', '/api/chat', dict(messages=[dict(role='user', content='x')], format=schema, options=dict(num_predict=allowance)))
    assert [r['max_output_tokens'] for r in sent] == [4096, 6144]
    assert all(r['store'] is False and r['reasoning'] == {'effort': 'low'} for r in sent)
    assert not json.dumps(sent).count('SIMULATED')


def test_tokenizer_drift_check_applies_to_local_model_only(monkeypatch):
    import pytest
    from layer4_evaluation.indicators import context_budget, ollama_provider as op
    budget = dict(tokenizer=dict(model_metadata_sha256='qwen-meta', model_digest='qwen-digest'), fits=True, estimated_input_tokens=10)
    monkeypatch.setattr(context_budget, 'rebudget', lambda *a: budget)
    settings = dict(num_predict=4096, context_margin_tokens=1024)
    api = dict(provider='openai', digest='API_MODEL_ALIAS', model_metadata_sha256='x', template_bytes=0)
    assert op.context_guard('p', {}, settings, api, budget) == 10 + 4096 + 1024
    local = dict(provider='ollama', digest='other', model_metadata_sha256='qwen-meta', template_bytes=0)
    with pytest.raises(op.OllamaError, match='RUNTIME_DRIFT'):
        op.context_guard('p', {}, settings, local, budget)


def test_unlimited_budget_has_no_internal_cap_and_still_records_spend(tmp_path):
    from layer4_evaluation.indicators.openai_provider import Ledger
    api = configuration(dict(provider='openai', api=dict(retry_seconds=0)))['api']
    assert 'budget_usd' not in api
    ledger = Ledger(tmp_path / 'api-ledger.sqlite', api)
    ledger.reserve('a', 'P', 1e6)  # no internal cap: only the OpenAI account limit applies
    ledger.finish('a', dict(input_tokens=1000, output_tokens=100))
    summary = ledger.summary()
    assert summary['budget_usd'] is None and summary['available_usd'] is None and summary['estimated_cost_usd'] > 0


def test_defined_budget_keeps_a_margin_and_stops_before_any_claim(tmp_path):
    import pytest as _pytest
    from layer4_evaluation.indicators.ollama_provider import OllamaError
    from layer4_evaluation.indicators.openai_provider import Ledger, budget_margin
    settings = configuration(dict(provider='openai', api=dict(budget_usd=1, retry_seconds=0)))
    assert budget_margin(1) == 0.10 and budget_margin(40) == 2.0
    client = OpenAIClient(settings, sdk=object(), root=tmp_path)
    messages, schema = [dict(role='user', content='x' * 2000)], {'type': 'object'}
    assert client.budget_check(tmp_path, messages, schema) > 0
    Ledger(tmp_path / 'api-ledger.sqlite', settings['api']).reserve('spent', 'P', 0.89)  # 0.89 + margin 0.10 leaves 0.01, less than one request
    with _pytest.raises(OllamaError, match='API_BUDGET'):
        client.budget_check(tmp_path, messages, schema)
    unlimited = OpenAIClient(configuration(dict(provider='openai', api=dict(retry_seconds=0))), sdk=object(), root=tmp_path)
    assert unlimited.budget_check(tmp_path, messages, schema) is None


def test_menu_asks_unlimited_or_defined_budget_without_default(monkeypatch, capsys):
    import run
    answers = iter(['1'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(answers))
    assert run.choose_budget() == (None, True)
    answers = iter(['', '9', '2', '', 'abc', '-3', '20'])  # Enter alone is never accepted as an amount
    monkeypatch.setattr('builtins.input', lambda prompt='': next(answers))
    assert run.choose_budget() == (20.0, False)
    assert 'USD 19.00' in capsys.readouterr().out


def test_binding_records_unlimited_or_defined_budget(tmp_path):
    from experiment_runtime import binding, options
    from pathlib import Path
    import pytest as _pytest
    root = Path(__file__).resolve().parents[1]  # real config/openai.json (read-only)
    for requested, expected in ((dict(provider='openai', unlimited_budget=True), None), (dict(provider='openai', budget_usd=12.5), 12.5)):
        token = options.set(requested)
        try:
            run_dir = tmp_path / str(expected); run_dir.mkdir()
            assert binding(root, run_dir, {})['llm']['api'].get('budget_usd') == expected
        finally:
            options.reset(token)
    token = options.set(dict(provider='openai', unlimited_budget=True, budget_usd=5))
    try:
        with _pytest.raises(ValueError, match='no ambos'):
            (tmp_path / 'both').mkdir(); binding(root, tmp_path / 'both', {})
    finally:
        options.reset(token)
