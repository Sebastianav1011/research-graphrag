"""Synthetic, offline coverage for exact failure, review and retry boundaries."""
from copy import deepcopy
import json
import shutil
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.test_ollama_provider import sample, provider_case, response, runtime
from tests.test_context_budget import corpus, packed
from scripts import recover_invalid_assessment as recovery
from layer4_evaluation import live_execution as live
from layer4_evaluation.indicators import assessment_v3 as v3, ollama_provider as transport
from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError, semantic_issues


def test_exact_invalid_indices_also_report_decision_contradiction(sample):
    a = deepcopy(sample['assessment'])
    a.update(decision='NOT_SUPPORTED', support_strength=0)
    a['evidence'].append(deepcopy(a['evidence'][0]))
    for c in a['criterion_assessments'][:2]:
        c.update(support='CLEAR', evidence_indices=[1, 2, 3])
    issues = semantic_issues(v3.validate(sample['fields'], sample['profile'], a, sample['rubric']), a, 'TEST')
    bad = [i for i in issues if i['category'] == 'EVIDENCE_ID_NOT_FOUND']
    assert len(bad) == 2 and all(i['evidence_indices'] == [2,3] and i['evidence_count'] == 2 for i in bad)
    assert any(i['category'] == 'DECISION_CRITERIA_INCONSISTENCY' for i in issues)


@pytest.mark.parametrize('kind,category', [('json','INVALID_JSON'), ('schema','INVALID_FIELD_VALUE'),
    ('index','EVIDENCE_ID_NOT_FOUND'), ('internal','INTERNAL_VALIDATION_ERROR')])
def test_transport_safe_diagnostics(provider_case, sample, kind, category):
    provider, client, project, profile, _, wrapper = provider_case
    if kind == 'json':
        client.request.return_value['message']['content'] = '{'
    elif kind == 'schema':
        del wrapper['assessments'][0]['decision']
        client.request.return_value = response(wrapper)
    else:
        def gate(w, pid, ids):
            if kind == 'internal':
                raise TypeError('SENSITIVE NARRATIVE MUST NOT ESCAPE')
            a = w['assessments'][0]
            a['criterion_assessments'][0]['evidence_indices'] = [100]
            issues = semantic_issues(v3.validate(project['fields'], profile,
                {k:v for k,v in a.items() if k!='indicator_id'}, sample['rubric']), a, profile['indicator_id'])
            raise AssessmentValidationError(issues)
        provider.wrapper_validator = gate
    with pytest.raises(transport.OllamaError) as error:
        provider.evaluate(project, [profile])
    assert 'SENSITIVE' not in str(error.value)
    assert any(i['category'] == category for i in provider.calls[0]['validation_issues'])
    assert provider.last_output is None and client.request.call_count == 1


@pytest.fixture
def failed_batch(tmp_path, monkeypatch, corpus, sample):
    root = tmp_path.resolve()
    directory = root/'outputs/runs/test/workspace/outputs/layer4/batch_test'
    directory.mkdir(parents=True)
    for name in [*recovery.BASELINE, 'src/layer4_evaluation/indicators/validation_diagnostics.py', 'scripts/recover_invalid_assessment.py']:
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(recovery.ROOT/name, target)
    monkeypatch.setattr(live, 'ROOT', root)
    monkeypatch.setattr(live, 'BASE', directory.parent)
    requests, report = packed(corpus)
    # Only one runnable indicator keeps this a lightweight recovery test.
    for iid, request in requests['TEST_PROJECT'].items():
        if iid != 'I00':
            request['context_selection']['status'] = 'NO_RETRIEVED_EVIDENCE'
    plan = dict(projects=[corpus.project], profiles=corpus.profiles, rubrics=corpus.rubrics,
        request_protocol=live.CONTEXT_VERSION, context_requests=requests, rules={}, source_hashes={},
        runtime=dict(provider='ollama', configuration=corpus.settings), requested_model=corpus.settings['model'],
        execution_id='test', maximum_calls=48, total_token_reservation_cap=48*4096, timeout_seconds=600,
        budgets=dict(assessment_reservation=4096, assessment_postcall_review_threshold=4096),
        discovery_version=live.gd.VERSION, assessment_version=v3.VERSION)
    for name,value in [('plan.json',plan),('cache.json',{}),('context_selection.json',report),
        ('review.json',dict(requests=requests, context_selection=report))]:
        live.write(directory/name,value)
    (directory/'review.txt').write_text('Synthetic review', encoding='utf-8')
    live.write(directory/'manifest.json',dict(plan_sha256=recovery.digest(directory/'plan.json'),
        files={n:recovery.digest(directory/n) for n in ('cache.json','context_selection.json','review.json','review.txt')}))
    live.write(directory.parents[3]/'run.json', dict(code_hashes={n:recovery.digest(root/n) for n in recovery.BASELINE}))
    wrapper = dict(project_id='TEST_PROJECT', assessments=[dict(indicator_id='I00', **deepcopy(sample['assessment']))])
    wrapper['assessments'][0]['criterion_assessments'][0]['evidence_indices'] = [99]
    client = Mock(spec=transport.OllamaClient)
    client.inspect.return_value = runtime(corpus.settings)
    client.request.return_value = response(wrapper)
    monkeypatch.setattr(live, 'OllamaClient', lambda settings:client)
    with pytest.raises(ValueError, match='BLOCKED_ERROR'):
        live.execute(SimpleNamespace(run=directory.name, authorize=True))
    return root,directory,client,wrapper


def test_failed_checkpoint_cannot_succeed_or_repeat_without_recovery(failed_batch):
    _, directory, client, _ = failed_batch
    state = live.verify_run(directory)
    assert state['status'] == 'BLOCKED' and not state['projects'][0]['rows']
    with pytest.raises(ValueError, match='detenida'):
        live.execute(SimpleNamespace(run=directory.name, authorize=False))
    assert client.request.call_count == 1


def test_recovery_preserves_authorization_hashes_requires_review_and_limits_retry(failed_batch):
    root,directory,client,wrapper = failed_batch
    original_auth = (directory/'authorization.json').read_bytes()
    original_request = live.read(directory/'plan.json')['context_requests']['TEST_PROJECT']['I00']
    assert recovery.prepare(root,directory)['status'] == 'RECOVERABLE'
    assert (directory/'authorization.json').read_bytes() == original_auth
    result = recovery.prepare(root,directory,apply=True)
    assert result['status'] == 'REVIEW_REQUIRED' and client.request.call_count == 1
    archive = directory.parent/'assessment_recovery_history'/directory.name
    archived_auth = next(archive.rglob('authorization.json'))
    assert archived_auth.read_bytes() == original_auth
    assert not (directory/'authorization.json').exists()
    plan = live.check(directory)
    revised = plan['context_requests']['TEST_PROJECT']['I00']
    assert revised['payload'] == original_request['payload']
    assert revised['prompt'] != original_request['prompt']
    assert live.verify_run(directory)['new_calls'] == 1
    with pytest.raises(ValueError, match='Falta autorizacion'):
        live.execute(SimpleNamespace(run=directory.name, authorize=False))
    with pytest.raises(ValueError, match='Limite'):
        recovery.prepare(root,directory,apply=True)
    # A second invalid result remains blocked and is never retried automatically.
    with pytest.raises(ValueError, match='BLOCKED_ERROR'):
        live.execute(SimpleNamespace(run=directory.name, authorize=True))
    state = live.verify_run(directory)
    assert state['status'] == 'BLOCKED' and state['new_calls'] == 2
    verification = next((directory/'calls').rglob('verification.json'))
    assert live.read(verification)['retries'] == 1
    with pytest.raises(ValueError, match='detenida'):
        live.execute(SimpleNamespace(run=directory.name, authorize=False))
    assert client.request.call_count == 2
    # Historical authorization tampering is detected on resume.
    archived_auth.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='Fingerprint'):
        live.check(directory)


def test_recovered_valid_evaluation_resumes_without_duplicate_calls(failed_batch, sample):
    root,directory,client,_ = failed_batch
    recovery.prepare(root,directory,apply=True)
    def valid_response(method, path, payload):
        raw_input = payload['messages'][0]['content'].split('INPUT_JSON:\n',1)[1]
        data,_ = json.JSONDecoder().raw_decode(raw_input)
        iid = data['indicators'][0]['indicator_id']
        return response(dict(project_id='TEST_PROJECT', assessments=[dict(indicator_id=iid, **deepcopy(sample['assessment']))]))
    client.request.side_effect = valid_response
    result = live.execute(SimpleNamespace(run=directory.name, authorize=True))
    assert result['status'] == 'PARTIAL' and result['valid_assessments'] == 1
    assert result['new_calls'] == 2 and client.request.call_count == 2
    first = live.read(directory/'calls/TEST_PROJECT/assessment_1/verification.json')
    assert first['retries'] == 1 and first['status'] == 'PASS'
    client.inspect.side_effect = AssertionError('No runnable work: checkpoint must verify offline')
    resumed = live.execute(SimpleNamespace(run=directory.name, authorize=False))
    assert resumed['status'] == 'PARTIAL' and resumed['valid_assessments'] == 1
    assert client.request.call_count == 2


def test_pending_sibling_review_is_preserved_during_code_migration(failed_batch):
    root,directory,_,_ = failed_batch
    sibling = directory.parent/'batch_pending'
    sibling.mkdir()
    for name in ('plan.json','manifest.json','cache.json','review.json','review.txt','context_selection.json'):
        shutil.copy2(directory/name, sibling/name)
    original_review = (sibling/'review.json').read_bytes()
    recovery.prepare(root,directory,apply=True)
    assert (sibling/'review.json').read_bytes() == original_review
    assert not (sibling/'authorization.json').exists()
    assert live.check(sibling)['checkpoint_migration']['archive_hashes']


@pytest.mark.parametrize('change', ['uncertain','incomplete','unauthorized','source'])
def test_recovery_refuses_uncertain_incomplete_or_incompatible_artifacts(failed_batch, change):
    root,directory,_,_ = failed_batch
    if change == 'source':
        state = live.read(directory.parents[3]/'run.json')
        state['code_hashes']['src/layer4_evaluation/live_execution.py'] = 'unknown-digest'
        live.write(directory.parents[3]/'run.json',state)
    elif change == 'unauthorized':
        auth = live.read(directory/'authorization.json'); auth['authorized'] = False
        live.write(directory/'authorization.json',auth)
    else:
        record_path = next((directory/'calls').rglob('records/assessment/*.json'))
        record = live.read(record_path)
        record['calls'][0]['exit_status'] = 'TIMEOUT' if change=='uncertain' else 'INCOMPLETE_RESPONSE'
        live.write(record_path,record)
    with pytest.raises(ValueError):
        recovery.prepare(root,directory,apply=True)
    assert (directory/'authorization.json').exists() and not (directory/'recovery.pending.json').exists()
