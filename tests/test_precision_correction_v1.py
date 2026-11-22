"""Regression tests for correction V1; historical data read-only, no model/API."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock
import pytest

from tests.semantic_validation import test_baseline as baseline
from tests.semantic_validation.harness import ROOT,RUN,read
from layer4_evaluation.indicators import retry_review as review
from layer4_evaluation.indicators import ollama_provider as transport
from layer4_evaluation.indicators import assessment_v3 as v3
from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError


def controlled_pair():
    case,wrapper=baseline.trusted_case()
    directory=ROOT/case['calls'][0]
    dirs=sorted(directory.glob('assessment/ollama_runs/*/attempt_*'),key=lambda p:int(p.name.split('_')[-1]))
    candidate=read(dirs[-1]/'selection.json');before=deepcopy(candidate)
    c=before['assessments'][0]['criterion_assessments'][0]
    c.update(support='NOT_DEMONSTRATED',coverage=0)  # same reference, contradictory label
    schema=read(directory/'schema.json');request=case['context']
    report=review.compare(before,candidate,request,request,schema,schema,'SUPPORTED')
    fragments={f['fragment_id']:f for f in request['payload']['project']['fragments']}
    item=candidate['assessments'][0];judgments={c['criterion_id']:c for c in item['criterion_assessments']}
    judgments.update({k:item[k] for k in ('applicability','strength_rubric')})
    approval=dict(authority='HUMAN',verdict='APPROVE_REINTERPRETATION',reviewer='SYNTHETIC_TEST_REVIEWER_NOT_REAL_ADJUDICATION',
        rationale='Synthetic authorization fixture: correct the deliberately wrong ND label using the same cited fragment.',review_fingerprint=report['review_fingerprint'],judgments=[])
    for field in report['promoted_criteria']+report['promoted_global_fields']:
        ref=judgments[field]['evidence_refs'][0]
        approval['judgments'].append(dict(field=field,rationale='Synthetic criterion-specific review of the supplied documentary witness.',
            witnesses=[dict(**ref,span=fragments[ref['fragment_id']]['text'])]))
    native=read(dirs[-1]/'native_response.json')
    return case,directory,before,candidate,schema,report,approval,native


def provider_for(tmp_path,approval=None):
    case,directory,before,candidate,schema,report,valid_review,native=controlled_pair()
    runtime=read(next(directory.glob('records/assessment/*.json')))['calls'][0]['runtime']
    client=Mock(spec=transport.OllamaClient);client.inspect.return_value=runtime
    def answer(value):
        body=deepcopy(native);body['message']['content']=json.dumps(value,ensure_ascii=False);return body
    client.request.side_effect=[answer(before),answer(candidate)]
    from layer4_evaluation import live_execution as live
    from layer4_evaluation.indicators import prospective_v2 as p2
    iid=case['row']['indicator_id'];p=case['project'];req=case['context']
    plan=dict(profiles={iid:case['profile']},rubrics={iid:case['rubric']},assessment_version=p2.VERSION,evaluation_policy=dict(decision_policy=p2.DECISION_POLICY))
    provider=transport.OllamaAssessmentProvider(tmp_path/'ollama_runs',directory/'schema.json',lambda p,i:req,
        settings=runtime['configuration'],runtime=runtime,client=client,corrective_retries=2,token_limit_retries=2,
        correction_version=p2.CORRECTION,max_indicators=1,retry_review=valid_review if approval=='valid' else approval,
        wrapper_resolver=lambda w:live.resolve_wrapper(plan,p,req,w),wrapper_validator=lambda w,pid,ids:live.check_wrapper(plan,p,req,pid,ids,w))
    return provider,p,[case['profile']],valid_review


def test_same_fragment_can_correct_a_false_negative_with_explicit_review(tmp_path):
    provider,project,profiles,_=provider_for(tmp_path,'valid')
    result=provider.evaluate(project,profiles)
    assert result[0]['assessment']['decision']=='SUPPORTED'
    receipt=read(next((tmp_path/'ollama_runs').glob('*/attempt_2/retry_decision.json')))
    assert receipt['same_evidence'] and receipt['status']=='APPROVED_REINTERPRETATION'
    assert receipt['review']['authority']=='HUMAN'
    assert provider.client.request.call_count==2


def test_unreviewed_promotion_is_preserved_and_stops_without_third_generation(tmp_path):
    provider,p,profiles,_=provider_for(tmp_path)
    with pytest.raises(transport.OllamaError,match='INDEPENDENT_ADJUDICATION_REQUIRED'):provider.evaluate(p,profiles)
    assert provider.client.request.call_count==2 and provider.last_output is None
    last=next((tmp_path/'ollama_runs').glob('*/attempt_2'))
    assert (last/'selection.json').exists() and not (last/'response.json').exists()
    assert read(last/'retry_decision.json')['status']=='PENDING_REVIEW'


def test_invalid_json_without_prior_judgment_can_recover_normally(tmp_path):
    provider,p,profiles,_=provider_for(tmp_path)
    _,_,_,candidate,_,_,_,native=controlled_pair()
    first=deepcopy(native);first['message']['content']='{ incomplete JSON'
    second=deepcopy(native);second['message']['content']=json.dumps(candidate,ensure_ascii=False)
    provider.client.request.side_effect=[first,second]
    assert provider.evaluate(p,profiles)[0]['assessment']['decision']=='SUPPORTED'
    assert provider.client.request.call_count==2


@pytest.mark.parametrize('approved',[True,False])
def test_saved_candidate_review_needs_no_new_generation_or_original_writes(tmp_path,approved):
    from layer4_evaluation import live_execution as live
    from layer4_evaluation.indicators import prospective_v2 as p2
    from tests.semantic_validation.harness import filehash
    provider,p,profiles,approval=provider_for(tmp_path)
    with pytest.raises(transport.OllamaError):provider.evaluate(p,profiles)
    directory=next((tmp_path/'ollama_runs').glob('*/attempt_2'))
    hashes={str(f):filehash(f) for f in (tmp_path/'ollama_runs').rglob('*') if f.is_file()}
    case,_=baseline.trusted_case();iid=profiles[0]['indicator_id']
    plan=dict(assessment_version=p2.VERSION,profiles={iid:case['profile']},rubrics={iid:case['rubric']},evaluation_policy={'decision_policy':p2.DECISION_POLICY})
    if approved:
        wrapper,receipt=live.review_persisted_retry(plan,p,case['context'],directory,approval)
        assert wrapper['assessments'][0]['decision']=='SUPPORTED'
        assert receipt['status']=='APPROVED_REINTERPRETATION' and receipt['validation_code_hashes']
    else:
        with pytest.raises(AssessmentValidationError):live.review_persisted_retry(plan,p,case['context'],directory,None)
    assert provider.client.request.call_count==2
    assert hashes=={str(f):filehash(f) for f in (tmp_path/'ollama_runs').rglob('*') if f.is_file()}


@pytest.mark.parametrize('mutation',['hash','reviewer','authority','rationale','missing_criterion','invented_span','invented_fragment','different_stage','malformed_id'])
def test_invalid_or_unbound_review_cannot_approve_promotion(mutation):
    case,_,before,candidate,schema,report,approval,_=controlled_pair()
    if mutation=='hash':approval['review_fingerprint']='wrong'
    if mutation=='reviewer':approval['reviewer']=''
    if mutation=='authority':approval['authority']='MODEL'
    if mutation=='rationale':approval['rationale']=''
    if mutation=='missing_criterion':approval['judgments']=[]
    if mutation=='invented_span':approval['judgments'][0]['witnesses'][0]['span']='NONEXISTENT_QUOTE'
    if mutation=='invented_fragment':approval['judgments'][0]['witnesses'][0]['fragment_id']='F999999'
    if mutation=='different_stage':approval['judgments'][0]['witnesses'][0]['stage']='WRONG_STAGE'
    if mutation=='malformed_id':approval['judgments'][0]['witnesses'][0]['fragment_id']=[]
    assert not review.validate_review(report,approval,candidate,case['context'])


def test_changed_candidate_invalidates_old_human_approval():
    case,_,before,candidate,schema,report,approval,_=controlled_pair()
    candidate['assessments'][0]['explanation']+=' Different judgment.'
    changed=review.compare(before,candidate,case['context'],case['context'],schema,schema,'SUPPORTED')
    assert not review.validate_review(changed,approval,candidate,case['context'])


def test_only_recommendation_changes_do_not_require_review():
    case,_,_,candidate,schema,_,_,_=controlled_pair();before=deepcopy(candidate)
    before['assessments'][0]['decision']='INSUFFICIENT_EVIDENCE'
    report=review.compare(before,candidate,case['context'],case['context'],schema,schema,'SUPPORTED')
    assert not report['review_required']


def test_valid_negative_is_not_blocked_for_partial_grade_repair():
    case,_,before,candidate,schema,_,_,_=controlled_pair()
    assert not review.compare(before,candidate,case['context'],case['context'],schema,schema,'INSUFFICIENT_EVIDENCE')['review_required']


def test_new_evidence_or_rubric_is_not_silently_the_same_retry():
    case,_,before,candidate,schema,_,_,_=controlled_pair();req=deepcopy(case['context'])
    req['payload']['project']['fragments'][0]['text']+=' New source data.'
    report=review.compare(before,candidate,case['context'],req,schema,schema,'SUPPORTED')
    assert not report['same_evidence'] and not report['same_payload']
    req=deepcopy(case['context']);req['payload']['indicators'][0]['rubric']['criteria'][0]['criterion']='Changed definition'
    assert not review.compare(before,candidate,case['context'],req,schema,schema,'SUPPORTED')['same_payload']


def test_complete_consistent_first_positive_is_preserved():
    case,wrapper=baseline.trusted_case();result,_=baseline.gate(case,wrapper)
    assert result['assessments'][0]['decision']=='SUPPORTED'


def test_na_remains_valid_with_a_coherent_new_document_and_prompt():
    case,w=baseline.trusted_case();a=baseline.zero_support(case,w,na=True)
    text='El alcance excluye expresamente acciones sobre patrimonio; el proyecto sólo calibra sensores.'
    e=a['evidence'][0];e.update(text=text,stage='CONTEXT');a['evidence']=[e]
    case['project']['fields'][e['field']]=text
    req=case['context'];req['payload']['project']['fragments']=[dict(fragment_id='F000',field=e['field'],text=text)]
    req['prompt']=req['prompt'].split('INPUT_JSON:\n',1)[0]+'INPUT_JSON:\n'+json.dumps(req['payload'],ensure_ascii=False)
    result,_=baseline.gate(case,w);a={k:v for k,v in result['assessments'][0].items() if k!='indicator_id'}
    assert a['decision']=='NOT_APPLICABLE'
    assert v3.confidence(case['project']['fields'],case['profile'],a,case['rubric'])['confidence_raw_score'] is None


def test_coherent_negation_still_exposes_semantic_boundary_not_a_claim_of_precision():
    """Document unresolved entailment; no lexical rule pretends to fix Qwen."""
    case,w=baseline.trusted_case();a=w['assessments'][0]
    text='El proyecto no conserva ni propone conservar patrimonio; esa atribución está negada.'
    field=a['evidence'][0]['field'];case['project']['fields']={field:text}
    for e in a['evidence']:e.update(field=field,text=text)
    req=case['context'];req['payload']['project']['fragments']=[dict(fragment_id='F000',field=field,text=text)]
    req['prompt']=req['prompt'].split('INPUT_JSON:\n',1)[0]+'INPUT_JSON:\n'+json.dumps(req['payload'],ensure_ascii=False)
    result,_=baseline.gate(case,w)
    assert result['assessments'][0]['decision']=='SUPPORTED'  # observed limitation, NOT a correct semantic label


def test_diagnostics_locate_existing_contradiction_without_repair():
    _,_,before,_,_,_,_,_=controlled_pair();original=deepcopy(before)
    details=review.diagnostic_details([dict(rule='V3_CRITERION:UNSUPPORTED_CANNOT_CLAIM_EVIDENCE',path='$')],before)
    assert details[0]['criterion_id']==before['assessments'][0]['criterion_assessments'][0]['criterion_id']
    assert before==original
