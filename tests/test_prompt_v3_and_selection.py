"""Prompt V3 (audit A3/A4) and optional indicator selection; offline, mocked transport only."""
import json
from types import SimpleNamespace

import pytest

from .test_ollama_provider import sample, live_run, response  # noqa: F401  (fixtures)
from .test_context_budget import corpus, install_plan, planner, relational_fixture  # noqa: F401  (fixtures)
from .test_unified_runner import system  # noqa: F401  (fixture)
from layer4_evaluation import live_execution as live
from layer4_evaluation.indicators import context_budget as cb, assessment_v3 as v3, ollama_provider as transport
from layer4_evaluation.indicators.evidence_references import response_schema
from layer4_evaluation.indicators.token_budget import count
from layer2_processing.preprocessing.adapters import read, write, sha
from scripts import pipeline_coordinator as runner

V3 = v3.PROSPECTIVE_PROMPT_V3
WIDE = dict(num_ctx=16384, num_predict=4096, context_margin_tokens=1024)
TITLE = 'Titulo sintetico del proyecto evaluado'


def prospective(corpus, ids=('I00',)):
    corpus.rubrics, _ = v3.catalog_for_mode(corpus.profiles, corpus.rubrics, v3.PROSPECTIVE)
    corpus.project['fields']['title'] = TITLE
    return {iid: corpus.profiles[iid] for iid in ids}


def contexts(corpus, profiles, tokenizer, prompt_version=V3):
    return cb.prepare_contexts([corpus.project], profiles, corpus.rubrics, corpus.settings | WIDE, corpus.hits,
        corpus.chunks, corpus.sections, evidence_references=True, assessment_version=v3.SK_VERSION,
        evaluation_mode=v3.PROSPECTIVE, context_mode=v3.RETRIEVED_CONTEXT, tokenizer=tokenizer,
        prompt_version=prompt_version)


def test_v3_prompt_replaces_contradictions_and_keeps_validators_contract(corpus, tokenizer_stub):
    requests, _ = contexts(corpus, prospective(corpus), tokenizer_stub)
    request = requests['TEST_PROJECT']['I00']
    prompt = request['prompt']
    # A3: one temporal scale (prospective), coherence rule, prospective stage sentence.
    assert v3.PROSPECTIVE_TEMPORAL_SCALE in prompt and v3.SK_TEMPORAL_SCALE not in prompt
    assert prompt.count(v3.SK_COHERENCE) == 1
    assert v3.PROSPECTIVE_STAGE_LINE in prompt and v3.DEMONSTRATED_STAGE_LINE not in prompt
    assert 'EXECUTED_ACTIVITY exige actividad realizada' not in prompt
    assert request['prompt_version'] == V3 and request['context_selection']['status'] == 'READY'
    # Budget is still the calibrated one and the transport reproduces it.
    budget = request['context_budget']
    assert budget['estimated_input_tokens'] == count(prompt, tokenizer_stub) + 12 and budget['input_cap'] == 8000
    transport.context_guard(prompt, response_schema(request, corpus.project['fields']), corpus.settings | WIDE, budget=budget)


def test_v3_title_is_identification_context_never_a_citable_fragment(corpus, tokenizer_stub):
    requests, _ = contexts(corpus, prospective(corpus), tokenizer_stub)
    request = requests['TEST_PROJECT']['I00']
    project = request['payload']['project']
    assert project['title'] == TITLE and v3.TITLE_NOTE in request['prompt']
    assert all(f['field'] != 'title' and TITLE not in f['text'] for f in project['fragments'])
    schema = json.dumps(response_schema(request, corpus.project['fields']), ensure_ascii=False)
    assert TITLE not in schema  # Only fragment IDs are admissible references.
    assert {s['field'] for s in request['context_selection']['selected']} == {'methodology'}


def test_default_and_v2_prompts_are_unchanged(corpus, tokenizer_stub):
    profiles = prospective(corpus)
    default, _ = contexts(corpus, profiles, tokenizer_stub, prompt_version=None)
    v2, _ = contexts(corpus, profiles, tokenizer_stub, prompt_version='PROSPECTIVE_SK_PROMPT_V2_PARTIAL')
    a, b = default['TEST_PROJECT']['I00'], v2['TEST_PROJECT']['I00']
    assert a['prompt'] == b['prompt'] and v3.SK_TEMPORAL_SCALE in a['prompt']
    assert 'title' not in a['payload']['project'] and 'prompt_version' not in a


def test_v3_is_only_valid_for_prospective_reference_prompts(corpus):
    corpus.project['fields']['title'] = TITLE
    with pytest.raises(ValueError, match='Prompt V3'):
        cb.make_request(corpus.project, corpus.profiles['I00'], corpus.rubrics['I00'], corpus.project['fields'],
            evidence_references=True, assessment_version=v3.SK_VERSION, evaluation_mode=v3.DEMONSTRATED,
            context_mode=v3.RETRIEVED_CONTEXT, prompt_version=V3)
    with pytest.raises(ValueError, match='desconocida'):
        cb.make_request(corpus.project, corpus.profiles['I00'], corpus.rubrics['I00'], corpus.project['fields'],
            prompt_version='OTHER')


def test_new_prospective_policy_uses_v3_and_old_policies_stay_frozen():
    new = v3.evaluation_policy(base=True)
    assert new['instructions_version'] == V3 and new['evaluation_mode'] == v3.PROSPECTIVE
    assert v3.evaluation_policy('demonstrated', 'graphrag')['instructions_version'] == 'DEMONSTRATED_SK_PROMPT_V2_PARTIAL'
    old = {k: v for k, v in new.items() if k != 'sha256'} | dict(instructions_version='PROSPECTIVE_SK_PROMPT_V2_PARTIAL')
    old['sha256'] = v3.canonical_hash(old)
    assert v3.evaluation_policy(saved=old) == old  # Resume keeps the sealed V2 policy.


def test_selection_dispatches_only_selected_indicators_and_keeps_catalog(live_run, corpus, sample):
    directory, client = live_run
    selection = ['I00', 'I05', 'I47']
    requests, _ = cb.prepare_contexts([corpus.project], {i: corpus.profiles[i] for i in selection}, corpus.rubrics,
        corpus.settings, corpus.hits, corpus.chunks, corpus.sections)
    install_plan(directory, corpus, requests)
    plan = read(directory / 'plan.json'); plan['indicator_selection'] = selection; write(directory / 'plan.json', plan)
    manifest = read(directory / 'manifest.json'); manifest['plan_sha256'] = sha(directory / 'plan.json'); write(directory / 'manifest.json', manifest)
    live.check(directory)
    binding = client.inspect.return_value
    binding['configuration'] = corpus.settings
    binding['configuration_sha256'] = v3.canonical_hash(corpus.settings)
    def reply(method, path, payload):
        body = json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n')[1])
        iid = body['indicators'][0]['indicator_id']
        return response(dict(project_id='TEST_PROJECT', assessments=[dict(indicator_id=iid, **sample['assessment'])]))
    client.request.side_effect = reply
    live.execute(SimpleNamespace(run='batch_test', authorize=True))
    state = live.verify_run(directory)['projects'][0]
    assert client.request.call_count == 3 and len(plan['profiles']) == 48
    assert state['selected'] == selection and {r['indicator_id'] for r in state['rows']} == set(selection)
    assert state['complete'] and not state.get('context_limits')


def test_selection_rejects_unsealed_or_foreign_subsets(live_run, corpus):
    directory, _ = live_run
    requests, _ = cb.prepare_contexts([corpus.project], {'I00': corpus.profiles['I00']}, corpus.rubrics,
        corpus.settings, corpus.hits, corpus.chunks, corpus.sections)
    install_plan(directory, corpus, requests)
    with pytest.raises(ValueError, match='48 indicadores'):
        live.check(directory)  # A partial plan without a declared selection is incomplete.
    for bad in (['I00', 'I00'], ['ZZ-99'], []):
        plan = read(directory / 'plan.json'); plan['indicator_selection'] = bad; write(directory / 'plan.json', plan)
        manifest = read(directory / 'manifest.json'); manifest['plan_sha256'] = sha(directory / 'plan.json'); write(directory / 'manifest.json', manifest)
        with pytest.raises(ValueError):
            live.check(directory)


def test_coordinator_seals_selection_in_plan_and_refuses_unknown_ids(planner, corpus, monkeypatch):
    root, run, module = planner
    policy = v3.evaluation_policy(base=True)
    corpus.project['fields']['title'] = TITLE
    corpus.sections[:] = [dict(section_id='SECTION' if f == 'methodology' else 'S_' + f, source_id='TEST_PROJECT', field_name=f,
        text_original=t or '', text_hash_original='fixture', provenance_json=json.dumps({'layer1': []}))
        for f, t in corpus.project['fields'].items()]
    monkeypatch.setattr('layer4_evaluation.indicators.scoped_retrieval.project_relations',
        lambda workspace, projects: {p['project_id']: relational_fixture(p['project_id']) for p in projects})
    seen = []
    def retrieved(workspace, projects, profiles, chunks, **kwargs):
        seen.append(sorted(profiles))
        return [c for c in corpus.hits if c['indicator_id'] in profiles], {'model_calls': 0}
    monkeypatch.setattr('layer4_evaluation.indicators.scoped_retrieval.from_published_cache', retrieved)
    write(runner.run_file(run, 'execution.json'), dict(llm=corpus.settings | dict(num_ctx=16384, context_margin_tokens=1024),
        evaluation_policy=policy, indicator_ids=['I02', 'I01']))
    batch = runner.prepare_evaluation(root, run, ['TEST']); plan = read(module.BASE / batch / 'plan.json')
    assert plan['indicator_selection'] == ['I01', 'I02'] and seen == [['I01', 'I02']]
    assert set(plan['context_requests']['TEST_PROJECT']) == {'I01', 'I02'} and len(plan['profiles']) == 48
    assert plan['maximum_calls'] == 2 * (1 + max(plan['token_limit_retries'], plan['corrective_retries']))
    request = plan['context_requests']['TEST_PROJECT']['I01']
    assert request['prompt_version'] == V3 and request['payload']['project']['title'] == TITLE
    assert 'Validacion acotada' in read(module.BASE / batch / 'review.json')['warnings'][0]
    write(runner.run_file(run, 'execution.json'), dict(llm=corpus.settings | dict(num_ctx=16384, context_margin_tokens=1024),
        evaluation_policy=policy, indicator_ids=['I03']))
    with pytest.raises(ValueError, match='Seleccion de indicadores incompatible'):
        runner.prepare_evaluation(root, run, ['TEST'])


def test_cli_parses_indicator_subset_exactly():
    import run as cli
    parse = lambda value: cli.selected_indicators(SimpleNamespace(indicators=value))
    assert parse(None) is None and parse(' DIV-04, POL-01 ,AMB-01') == ['DIV-04', 'POL-01', 'AMB-01']
    for bad in ('DIV-04,DIV-04', 'DIV-04,,AMB-01', ''):
        with pytest.raises(ValueError):
            parse(bad)


def test_execute_pipeline_freezes_indicator_selection_on_resume(system, monkeypatch):
    monkeypatch.setattr(runner.processing, 'reuse_global_base', lambda *a, **kw: 'outputs/runs/global-original')
    original = runner.prepare
    def prepare(root, run, raw, dataset, config, through):
        original(root, run, raw, dataset, config, through)
        path = runner.run_file(run, 'run.json'); value = read(path)
        value.update(status='PREPARED', global_reuse={'source_run': 'global-original', 'graph_reused': True})
        write(path, value)
    monkeypatch.setattr(runner, 'prepare', prepare)
    result = runner.execute_pipeline(system.root, source='base', project_ids=['001'], through='knowledge',
        run_id='selection', indicator_ids=['I01', 'I02'])
    assert result['status'] == 'COMPLETE'
    execution = runner.run_file(system.run(), 'execution.json')
    assert read(execution)['indicator_ids'] == ['I01', 'I02']
    with pytest.raises(ValueError, match='Seleccion de indicadores distinta'):
        runner.execute_pipeline(system.root, run_id='selection', resume=True, through='knowledge', indicator_ids=['I03'])
    assert runner.execute_pipeline(system.root, run_id='selection', resume=True, through='knowledge')['status'] == 'COMPLETE'
    assert read(execution)['indicator_ids'] == ['I01', 'I02']
