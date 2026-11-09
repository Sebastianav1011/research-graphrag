"""Small offline regressions: mocked transport, disposable checkpoints only."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tests.test_ollama_provider import sample, live_run, response, runtime
from tests.test_context_budget import corpus, packed, install_plan
from layer2_processing.preprocessing.adapters import read, write, sha
from layer4_evaluation import live_execution as live


def configured(directory, corpus):
    corpus.hits = corpus.hits[:2]
    requests, _ = packed(corpus)
    install_plan(directory, corpus, requests)
    plan = read(directory/'plan.json')
    plan.update(isolate_indicator_errors=True, token_limit_retries=2, maximum_calls=144,
        total_token_reservation_cap=144*8192,
        budgets=dict(assessment_reservation=3*8192, assessment_postcall_review_threshold=3*8192))
    write(directory/'plan.json', plan)
    manifest = read(directory/'manifest.json')
    manifest['plan_sha256'] = sha(directory/'plan.json')
    write(directory/'manifest.json', manifest)


def wrapper(payload, sample, invalid=None):
    body = json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n')[1])
    iid = body['indicators'][0]['indicator_id']
    assessment = dict(indicator_id=iid, **deepcopy(sample['assessment']))
    if invalid == 'quote':
        assessment['evidence'][0]['text'] = 'Invented quote absent from the sent fragments.'
    elif invalid == 'index':
        assessment['criterion_assessments'][0]['evidence_indices'] = [999]
    elif invalid == 'criteria':
        assessment.update(decision='NOT_SUPPORTED', support_strength=0)
    return response(dict(project_id=body['project']['project_id'], assessments=[assessment]))


@pytest.mark.parametrize('invalid', ['quote', 'index', 'criteria'])
def test_invalid_output_gets_corrective_feedback_and_validates(live_run, corpus, sample, invalid):
    directory, client = live_run
    configured(directory, corpus)
    client.inspect.return_value = runtime(corpus.settings)
    prompts = []
    def reply(method, path, payload):
        prompts.append(payload['messages'][0]['content'])
        return wrapper(payload, sample, invalid if len(prompts) == 1 else None)
    client.request.side_effect = reply
    result = live.execute(SimpleNamespace(run='batch_test', authorize=True))
    assert result['valid_assessments'] == 2 and client.request.call_count == 3
    assert 'ERRORES:' in prompts[1]
    assert not live.verify_run(directory)['errors']


@pytest.mark.parametrize('still_invalid', [False, True])
def test_resume_dispatches_blocked_only_preserves_valid_and_bounds_failures(live_run, corpus, sample, still_invalid):
    directory, client = live_run
    configured(directory, corpus)
    client.inspect.return_value = runtime(corpus.settings)
    bad = True
    def reply(method, path, payload):
        body = json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n')[1])
        return wrapper(payload, sample, 'index' if bad and body['indicators'][0]['indicator_id']=='I00' else None)
    client.request.side_effect = reply
    first = live.execute(SimpleNamespace(run='batch_test', authorize=True))
    assert first['valid_assessments']==1 and client.request.call_count==4
    protected = {p:p.read_bytes() for p in (directory/'calls').rglob('*') if p.is_file()}
    bad = still_invalid
    resumed = live.execute(SimpleNamespace(run='batch_test', authorize=False))
    assert client.request.call_count == (7 if still_invalid else 5)
    assert resumed['valid_assessments'] == (1 if still_invalid else 2)
    assert all(p.read_bytes()==value for p,value in protected.items())
    state=live.verify_run(directory)
    assert bool(state['projects'][0]['blocked_indicators']) == still_invalid
    assert state['new_calls']==client.request.call_count
    if not still_invalid:
        assert not state['errors']
        live.execute(SimpleNamespace(run='batch_test', authorize=False))
        assert client.request.call_count==5
