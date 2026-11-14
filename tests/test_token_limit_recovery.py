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
    assert client.request.call_count == 5
    assert len(target_calls) == 2
    assert target_calls[0] == 4096 and 4096 < target_calls[1] <= 6144
    first, second_state = live.verify_run(directory)['projects']
    assert len(second_state['rows']) == 2
    assert len(first['rows']) == (2 if failures == 1 else 1)
    assert first['blocked_indicators'] == ({} if failures == 1 else {'I00': 'BLOCKED_ERROR'})
    assert result['status'] != 'COMPLETE' and not result['blocking_errors']
    receipt = read(directory/'calls/TEST_PROJECT/assessment_1/verification.json')
    record = read(directory/'calls/TEST_PROJECT/assessment_1/records/assessment/TEST_PROJECT.json')
    assert receipt['retries'] == 1
    assert receipt['tokens']['output_tokens'] == sum(c['usage_observations'][0]['output_tokens'] for c in record['calls'])
    assert [c['retry'] for c in record['calls']] == list(range(len(record['calls'])))
    live.execute(SimpleNamespace(run='batch_test', authorize=False))
    # Resume does not reset an exhausted deterministic output/correction budget.
    assert client.request.call_count == 5


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


@pytest.mark.parametrize('constraint',['configured_cap','available_context'])
def test_truncated_request_is_not_repeated_without_more_output_room(provider_case,constraint):
    provider,client,project,profile,_,wrapper=provider_case
    provider.token_limit_retries=2
    if constraint=='configured_cap':
        provider.settings['max_predict']=provider.settings['num_predict']
        client.inspect.return_value=runtime(provider.settings)
    value=response(wrapper)|dict(done_reason='length',eval_count=provider.settings['num_predict'])
    if constraint=='available_context':
        value['prompt_eval_count']=provider.settings['num_ctx']-provider.settings['context_margin_tokens']-provider.settings['num_predict']
    client.request.return_value=value
    with pytest.raises(transport.OllamaError,match='TOKEN_LIMIT'):provider.evaluate(project,[profile])
    assert client.request.call_count==1 and provider.last_output is None
    assert provider.calls[0]['usage_observations'][0]['output_tokens']==provider.settings['num_predict']


def test_identical_failed_correction_is_not_dispatched_twice(provider_case):
    provider,client,project,profile,_,wrapper=provider_case
    provider.corrective_retries=2
    client.request.return_value=response(wrapper)
    client.request.return_value['message']['content']='{"unfinished":'
    with pytest.raises(transport.OllamaError,match='INVALID_ASSESSMENT'):provider.evaluate(project,[profile])
    sent=[call.args[2] for call in client.request.call_args_list]
    assert len(sent)==2 and sent[0]['messages']!=sent[1]['messages']
    assert provider.last_output is None
    assert all(c['validation_issues'][0]['category']=='INVALID_JSON' for c in provider.calls)


def test_preflight_context_limit_never_dispatches_or_retries(provider_case):
    provider,client,project,profile,request,_=provider_case
    provider.token_limit_retries=provider.corrective_retries=2
    request['prompt']='x'*(provider.settings['num_ctx']+1)
    with pytest.raises(transport.OllamaError,match='CONTEXT_TOO_LONG'):provider.evaluate(project,[profile])
    client.request.assert_not_called()
    assert provider.last_output is None and provider.calls==[]


def test_different_targeted_corrections_can_recover_within_existing_limit(provider_case):
    provider,client,project,profile,_,wrapper=provider_case
    provider.corrective_retries=2
    incomplete=response(wrapper);incomplete['message']['content']='{'
    missing=deepcopy(wrapper);del missing['assessments'][0]['decision']
    client.request.side_effect=[incomplete,response(missing),response(wrapper)]
    result=provider.evaluate(project,[profile])
    sent=[call.args[2]['messages'] for call in client.request.call_args_list]
    assert len(sent)==3 and sent[1]!=sent[2] and result
    assert provider.last_output==wrapper and [c['retry'] for c in provider.calls]==[0,1,2]
    assert sum(c['usage_observations'][0]['output_tokens'] for c in provider.calls)==150


@pytest.mark.parametrize('failure,code',[('incomplete','INCOMPLETE_RESPONSE'),('timeout','TIMEOUT'),('context','CONTEXT_TOO_LONG')])
def test_definitive_or_uncertain_failures_do_not_enter_correction_retries(provider_case,failure,code):
    provider,client,project,profile,_,wrapper=provider_case
    provider.token_limit_retries=provider.corrective_retries=2
    if failure=='incomplete':client.request.return_value=response(wrapper)|dict(done=False,done_reason=None)
    else:client.request.side_effect=transport.OllamaError(code,'Simulado')
    with pytest.raises(transport.OllamaError,match=code):provider.evaluate(project,[profile])
    assert client.request.call_count==1 and provider.last_output is None


@pytest.mark.parametrize('failure',['TOKEN_LIMIT','CONTEXT_TOO_LONG','SERVER_BUSY'])
def test_autonomous_last_tier_only_repeats_transient_service_failures(tmp_path,corpus,sample,failure):
    from unittest.mock import Mock
    from pathlib import Path
    from autonomous_execution import engine, store as s
    from layer4_evaluation.indicators import assessment_v3 as v3
    policy=s.read(Path(__file__).resolve().parents[1]/'config/autonomous.json')
    policy.update(tiers=[dict(num_ctx=8192,num_predict=4096)],max_context=8192,cooldown_seconds=0)
    manifest=dict(policy=policy,llm=corpus.settings,runtime=runtime(corpus.settings),execution_id='SYNTHETIC')
    s.write(tmp_path/'manifest.json',manifest)
    sent=[]
    def factory(settings):
        client=Mock(spec=transport.OllamaClient);client.inspect.return_value=runtime(settings)
        def reply(method,path,payload):
            sent.append(payload)
            wrapper=dict(project_id='TEST_PROJECT',assessments=[dict(indicator_id='I00',**sample['assessment'])])
            if failure=='TOKEN_LIMIT':return response(wrapper)|dict(done_reason='length',eval_count=settings['num_predict'])
            if len(sent)==1:raise transport.OllamaError(failure,'Simulado')
            return response(wrapper)
        client.request.side_effect=reply
        return client
    worker=engine.Worker(tmp_path,manifest,client_factory=factory,ram=lambda:99999,sleep=lambda _:None)
    profile=corpus.profiles['I00'];rubric=corpus.rubrics['I00']
    def build(settings,attempt):
        return cb.make_request(corpus.project,profile,rubric,corpus.project['fields']),v3.schemas(corpus.project['fields'])['assessment_batch']
    try:
        if failure=='SERVER_BUSY':
            wrapper,_=worker._step(corpus.project,profile,rubric,'synthetic',build)
            assert wrapper and len(sent)==2
        else:
            with pytest.raises(engine.JobError,match=failure):worker._step(corpus.project,profile,rubric,'synthetic',build)
            assert len(sent)==1
            with pytest.raises(engine.JobError,match=failure):worker._step(corpus.project,profile,rubric,'synthetic',build)
            assert len(sent)==1  # Existing failure is recovered offline, never resent.
        assert worker.db.execute('SELECT COUNT(*) FROM usage').fetchone()[0]==len(sent)
    finally:worker.close()
