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
