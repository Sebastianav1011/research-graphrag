"""Bounded mocked regressions; no server, model, or historical run writes."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tests.test_ollama_provider import sample, live_run, response, runtime, provider_case
from tests.test_context_budget import corpus, packed, install_plan
from layer2_processing.preprocessing.adapters import read, write, sha
from layer4_evaluation import live_execution as live
from layer4_evaluation.indicators import context_budget as cb, ollama_provider as transport


@pytest.mark.parametrize('failures', [1, 3])
def test_limit_recovery_or_isolation_continues_next_indicator_and_project(live_run, corpus, sample, failures):
    directory, client = live_run
    corpus.hits = corpus.hits[:2]
    requests, _ = packed(corpus)
    install_plan(directory, corpus, requests)
    plan = read(directory/'plan.json')
    second = deepcopy(corpus.project)
    second.update(project_id='NEXT_PROJECT', siap_id='NEXT')
    second_requests = deepcopy(requests['TEST_PROJECT'])
    for request in second_requests.values():
        request['project_id'] = 'NEXT_PROJECT'
        request['payload']['project']['project_id'] = 'NEXT_PROJECT'
        request['prompt'] = request['prompt'].replace('TEST_PROJECT', 'NEXT_PROJECT')
        request['context_budget'] = cb.estimate(request['prompt'], live.v3.schemas(second['fields'])['assessment_batch'], corpus.settings)
    plan['projects'].append(second)
    plan['context_requests']['NEXT_PROJECT'] = second_requests
    plan.update(isolate_indicator_errors=True, token_limit_retries=2, maximum_calls=288,
                total_token_reservation_cap=288*8192,
                budgets=dict(assessment_reservation=3*8192, assessment_postcall_review_threshold=3*8192))
    write(directory/'plan.json', plan)
    manifest = read(directory/'manifest.json')
    manifest['plan_sha256'] = sha(directory/'plan.json')
    write(directory/'manifest.json', manifest)
    client.inspect.return_value = runtime(corpus.settings)
    target_calls = []

    def reply(method, path, payload):
        body = json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n')[1])
        pid, iid = body['project']['project_id'], body['indicators'][0]['indicator_id']
        value = response(dict(project_id=pid, assessments=[dict(indicator_id=iid, **sample['assessment'])]))
        if (pid, iid) == ('TEST_PROJECT', 'I00'):
            target_calls.append(payload['options']['num_predict'])
            if len(target_calls) <= failures:
                value.update(done_reason='length', eval_count=payload['options']['num_predict'])
                value['message']['content'] = '{"incomplete":'
        return value

    client.request.side_effect = reply
    result = live.execute(SimpleNamespace(run='batch_test', authorize=True))
    assert client.request.call_count == (4 + min(failures, 2))
    assert len(target_calls) == min(failures + 1, 3)
    assert target_calls[0] == 4096 and 4096 < target_calls[1] <= 6144
    first, second_state = live.verify_run(directory)['projects']
    assert len(second_state['rows']) == 2
    assert len(first['rows']) == (2 if failures == 1 else 1)
    assert first['blocked_indicators'] == ({} if failures == 1 else {'I00': 'BLOCKED_ERROR'})
    assert result['status'] != 'COMPLETE' and not result['blocking_errors']
    receipt = read(directory/'calls/TEST_PROJECT/assessment_1/verification.json')
    record = read(directory/'calls/TEST_PROJECT/assessment_1/records/assessment/TEST_PROJECT.json')
    assert receipt['retries'] == min(failures, 2)
    assert receipt['tokens']['output_tokens'] == sum(c['usage_observations'][0]['output_tokens'] for c in record['calls'])
    assert [c['retry'] for c in record['calls']] == list(range(len(record['calls'])))
    live.execute(SimpleNamespace(run='batch_test', authorize=False))
    assert client.request.call_count == (4 + min(failures, 2))


def test_stop_at_output_cap_is_not_accepted_as_valid(provider_case):
    provider, client, project, profile, _, wrapper = provider_case
    client.request.return_value = response(wrapper) | dict(eval_count=provider.settings['num_predict'])
    with pytest.raises(transport.OllamaError, match='TOKEN_LIMIT'):
        provider.evaluate(project, [profile])
    assert provider.last_output is None and client.request.call_count == 1


def test_shared_configuration_and_retry_bound():
    settings = transport.configuration()
    assert (settings['num_ctx'], settings['num_predict'], settings['token_limit_retries']) == (8192, 4096, 2)
    with pytest.raises(ValueError, match='maximo dos'):
        transport.configuration(dict(token_limit_retries=3))
    with pytest.raises(ValueError, match='Contexto insuficiente'):
        transport.configuration(dict(num_ctx=4096))
