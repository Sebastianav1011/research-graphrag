"""Deterministic state derivation; never contact a model or change stored traces."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.test_prospective_v2 import prospective, case, make_na, reference_answer
from tests.test_ollama_provider import provider_case, sample, response
from layer4_evaluation import live_execution as live, thesis_output as output
from layer4_evaluation.indicators import prospective_v2 as p2, assessment_v3 as v3
from layer4_evaluation.indicators import context_budget as cb, evidence_references as refs
from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError

ROOT = Path(__file__).resolve().parents[1]


def resolve(x):
    return p2.resolve_decision(x['fields'], x['profile'], x['assessment'], x['rubric'])


def partial(x):
    a = x['assessment']
    a.update(decision='SUPPORTED', support_strength=2)
    a['criterion_assessments'][0].update(support='PARTIAL', coverage=3)
    a['strength_rubric'].update(dict.fromkeys(v3.STRENGTH_DIMENSIONS, 4))
    return x


def test_supported_overrides_only_wrong_model_decision(prospective):
    x = prospective
    x['assessment']['decision'] = 'INSUFFICIENT_EVIDENCE'
    before = deepcopy(x)
    a, receipt = resolve(x)
    assert a['decision'] == 'SUPPORTED'
    assert receipt['original_decision'] == 'INSUFFICIENT_EVIDENCE'
    assert x == before
    assert {k:v for k,v in a.items() if k not in ('decision','explanation')} == {
        k:v for k,v in x['assessment'].items() if k not in ('decision','explanation')}
    assert v3.confidence(x['fields'],x['profile'],a,x['rubric'])['confidence_raw_score'] == 96.56


def test_high_confidence_incomplete_essential_is_insufficient(prospective):
    x = partial(prospective)
    a, receipt = resolve(x)
    assert a['decision'] == 'INSUFFICIENT_EVIDENCE'
    assert receipt['required_blockers'] == ['C01']
    assert v3.confidence(x['fields'],x['profile'],a,x['rubric'])['confidence_raw_score'] == 94.38


def test_alternative_groups_are_required_but_complementary_is_not(prospective):
    # Synthetic frozen catalog: C01 REQUIRED, C02/C03 alternatives, C04 complementary.
    x = prospective
    for cid in ('C02','C03'):
        c = next(c for c in x['assessment']['criterion_assessments'] if c['criterion_id']==cid)
        c.update(support='NOT_DEMONSTRATED', coverage=0, evidence_indices=[], evidence_relation='NO_SUPPORT')
    x['assessment']['support_strength'] = 2
    a, receipt = resolve(x)
    assert a['decision'] == 'INSUFFICIENT_EVIDENCE' and receipt['alternative_blockers'] == ['G1']


def test_documented_na_overrides_model_advice_and_has_no_score(prospective):
    x = make_na(prospective)
    x['assessment']['decision'] = 'SUPPORTED'
    a, receipt = resolve(x)
    assert a['decision'] == 'NOT_APPLICABLE' and receipt['changed']
    assert v3.confidence(x['fields'],x['profile'],a,x['rubric'])['confidence_raw_score'] is None


def test_no_support_unknown_scope_is_insufficient_not_na(prospective):
    x = make_na(prospective)
    x['assessment']['applicability'].update(status='UNDETERMINED', basis='UNKNOWN', evidence_indices=[])
    a, _ = resolve(x)
    assert a['decision'] == 'INSUFFICIENT_EVIDENCE'
    assert v3.confidence(x['fields'],x['profile'],a,x['rubric'])['confidence_raw_score'] == 0


@pytest.mark.parametrize('mutation', [
    lambda a:a['criterion_assessments'].pop(),
    lambda a:a['criterion_assessments'].append(deepcopy(a['criterion_assessments'][0])),
    lambda a:a['criterion_assessments'][0].update(coverage=2),
    lambda a:a['criterion_assessments'][0].update(evidence_indices=[999]),
    lambda a:a['criterion_assessments'][0].update(evidence_relation='UNRELATED'),
    lambda a:a['criterion_assessments'][2].update(evidence_indices=[0]),
    lambda a:a['evidence'][0].update(text='An invented quote absent from project fields.'),
    lambda a:a['evidence'][0].update(stage='CONTEXT'),
    lambda a:a['applicability'].update(evidence_indices=[]),
    lambda a:a.update(support_strength=0),
])
def test_invalid_components_remain_technical(prospective, mutation):
    x = prospective
    mutation(x['assessment'])
    before = deepcopy(x)
    with pytest.raises(AssessmentValidationError):
        resolve(x)
    assert x == before


@pytest.mark.parametrize('complete', [True,False])
def test_strength_state_rules_not_repaired(prospective, complete):
    x = prospective if complete else partial(prospective)
    x['assessment']['support_strength'] = 2 if complete else 4
    with pytest.raises(AssessmentValidationError):
        resolve(x)


def test_na_without_documented_scope_remains_invalid(prospective):
    x = make_na(prospective)
    x['assessment']['applicability']['evidence_indices'] = []
    with pytest.raises(AssessmentValidationError):
        resolve(x)


def stored_case(folder, pid, attempt):
    directory = ROOT/'outputs/pilotos'/folder/'evaluation/batch_pilot_tec04'
    plan = json.loads((directory/'plan.json').read_text(encoding='utf-8'))
    project = next(p for p in plan['projects'] if p['project_id']==pid)
    request = plan['context_requests'][pid]['TEC-04']
    path = directory/'calls'/pid/'assessment_1/assessment/ollama_runs'/pid/attempt/'response.raw.txt'
    selection = json.loads(path.read_text(encoding='utf-8'))
    a = refs.materialize(request,selection)['assessments'][0]
    a.pop('indicator_id')
    return dict(fields=project['fields'],profile=plan['profiles']['TEC-04'],
        rubric=plan['rubrics']['TEC-04'],assessment=a)


def test_pilot_positive_and_negative_replayed_without_model():
    positive = stored_case('prospective_v2_tec04_r2','PROJ_21869','attempt_1')
    a, _ = resolve(positive)
    assert a['decision']=='SUPPORTED'
    assert v3.confidence(positive['fields'],positive['profile'],a,positive['rubric'])['confidence_raw_score']==100
    negative = stored_case('prospective_v2_tec04_r2','PROJ_21844','attempt_2')
    a, receipt = resolve(negative)
    assert receipt['original_decision']=='NOT_APPLICABLE'
    assert a['decision']=='INSUFFICIENT_EVIDENCE'
    assert receipt['required_blockers']==['C01','C03','C05']
    assert v3.confidence(negative['fields'],negative['profile'],a,negative['rubric'])['confidence_raw_score']==73


@pytest.mark.parametrize('attempt',['attempt_1','attempt_2'])
def test_latest_negative_component_errors_are_not_hidden(attempt):
    x = stored_case('prospective_v2_tec04_cierre','PROJ_21844',attempt)
    with pytest.raises(AssessmentValidationError):
        resolve(x)


@pytest.mark.parametrize('advice',['SUPPORTED','NOT_APPLICABLE'])
def test_transport_and_audit_replay_share_resolver_and_keep_original(provider_case, prospective, advice):
    provider, client, *_ = provider_case
    x = partial(prospective)
    project = dict(project_id='P',siap_id='SYNTHETIC',fields=x['fields'])
    request = cb.make_request(project,x['profile'],x['rubric'],x['fields'], evidence_references=True,
        assessment_version=p2.VERSION,evaluation_mode=p2.MODE,prompt_version=p2.PROMPT)
    plan = dict(assessment_version=p2.VERSION,evaluation_policy=v3.evaluation_policy(base=True),
        profiles={x['profile']['indicator_id']:x['profile']},rubrics={x['profile']['indicator_id']:x['rubric']})
    schema = refs.response_schema(request,x['fields'])
    provider.schema.write_text(json.dumps(schema),encoding='utf-8')
    provider.input_factory = lambda *_:deepcopy(request)
    provider.wrapper_resolver = lambda w:live.resolve_wrapper(plan,project,request,w)
    provider.wrapper_validator = lambda w,pid,ids:live.check_wrapper(plan,project,request,pid,ids,w)
    selection = reference_answer(x)
    selection['assessments'][0]['decision'] = advice
    client.request.return_value = response(selection)
    answer = provider.evaluate(project,[x['profile']])[0]['assessment']
    assert answer['decision']=='INSUFFICIENT_EVIDENCE'
    saved = provider.directory.parent/provider.calls[0]['working_directory']
    assert json.loads((saved/'response.raw.txt').read_text(encoding='utf-8'))==selection
    replay, receipts = live.materialize_output(plan,project,request,selection)
    assert replay == provider.last_output
    assert json.loads((saved/'decision.json').read_text(encoding='utf-8')) == receipts
    assert receipts[0]['original_decision']==advice
    row = live.indicator_row(plan,project,replay['assessments'][0])
    assert row['assessment_validation_status']=='VALID' and row['confidence_raw_score']==94.38
    assert output.indicator_record(project,row['indicator_id'],row=row)['estado_cumplimiento']=='INSUFFICIENT_EVIDENCE'
