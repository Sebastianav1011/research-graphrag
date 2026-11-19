"""V2 regression: immutable evidence, strict gates and versioned instructions.

Semantic improvement is measured separately with real inference, not asserted
from the presence of instructions or an optimistic historical model label.
"""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator,ValidationError
from tests.semantic_validation.harness import ROOT,read,digest
from layer4_evaluation.indicators import prospective_v2 as p2,assessment_v3 as v3,context_budget as cb,evidence_references as refs
from layer4_evaluation.indicators.ollama_provider import corrective_request
from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError
from layer4_evaluation import live_execution as live
from layer4_evaluation.indicators import ollama_provider as transport
from unittest.mock import Mock

AUDIT=ROOT/'outputs/audits/validacion_real_corregida_v1'

def saved(case):
    r=next(r for r in read(AUDIT/'resultados_consolidados.json') if r['case_id']==case)
    p=ROOT/r['path'];return r,p,read(p/'project.json'),read(p/'plan.json'),read(p/'request_original.json')

def build(case,version):
    _,_,project,plan,_=saved(case);iid=next(iter(plan['profiles']))
    return cb.make_request(project,plan['profiles'][iid],plan['rubrics'][iid],project['fields'],
        evidence_references=True,assessment_version=p2.VERSION,evaluation_mode=p2.MODE,
        context_mode=v3.FULL_CONTEXT,prompt_version=version)

@pytest.mark.parametrize('case',['CUL-02__positivo','TEC-02__positivo','ECO-02__positivo','CUL-02__plan_concreto__PROSPECTIVE_V2','TEC-02__tematico','SOC-04__financiador'])
def test_old_prompt_and_payload_reconstruct_exactly_while_new_version_changes_only_instructions(case):
    _,_,_,_,old=saved(case)
    legacy=build(case,p2.PROMPT_CRITERIA_V1);new=build(case,p2.PROMPT_CONCISE_V4)
    assert legacy['prompt']==old['prompt']
    assert legacy['payload']==new['payload']==old['payload']
    assert new['decision_policy']==legacy['decision_policy']==p2.DECISION_POLICY
    assert new['prompt']!=old['prompt'] and p2.instructions_for(p2.PROMPT_CONCISE_V4) in new['prompt']
    assert '4 requisito integro demostrado (CLEAR)' not in new['prompt']
    a=refs.response_schema(legacy,saved(case)[2]['fields']);b=refs.response_schema(new,saved(case)[2]['fields'])
    assert set(a['properties'])==set(b['properties'])
    assert new['component_protocol']==p2.COMPONENT_PROTOCOL

@pytest.mark.parametrize('rule,needle',[
    ('P2_APPLICABILITY:SUBSTANTIVE_SCOPE_EVIDENCE_REQUIRED','UNDETERMINED/UNKNOWN'),
    ('V3_CRITERION:UNSUPPORTED_CANNOT_CLAIM_EVIDENCE','no conviertas ND en positivo'),
    ('support_strength:INCONSISTENT_DECISION','No promociones criterios'),
    ('P2_CRITERION:CONTEXT_ONLY_REFERENCES','No exijas ejecucion')])
def test_localized_correction_keeps_entailment_and_immutable_evidence(rule,needle):
    request=build('CUL-02__positivo',p2.PROMPT_CONCISE_V4)
    settings=read(AUDIT/'inferencia_local/baseline_v1/preflight.json')['runtime']['configuration']
    schema=refs.response_schema(request,saved('CUL-02__positivo')[2]['fields'])
    revised=corrective_request(request,schema,settings,[dict(rule=rule,path='$')],version=p2.CORRECTION)
    assert revised['payload']==request['payload']
    assert revised['prompt'].split('INPUT_JSON:\n')[1]==request['prompt'].split('INPUT_JSON:\n')[1]
    assert p2.instructions_for(p2.PROMPT_CONCISE_V4) in revised['prompt'] and needle in revised['prompt']
    assert revised['context_budget']['fits']

@pytest.mark.parametrize('case',[
    'CUL-02__plan_concreto__PROSPECTIVE_V2','TEC-02__tematico','TEC-02__plan_concreto__PROSPECTIVE_V2',
    'ECO-02__negacion','TEC-07__publicacion_sin_adopcion','SOC-04__financiador','HIST_21736_CUL-02'])
def test_original_seven_component_failures_are_still_rejected_without_repair(case):
    _,path,project,plan,req=saved(case)
    selection=read(sorted(path.rglob('selection.json'))[-1]);before=deepcopy(selection)
    with pytest.raises(AssessmentValidationError):live.resolve_wrapper(plan,project,req,refs.materialize(req,selection))
    assert selection==before

@pytest.mark.parametrize('case',['CUL-02__positivo','TEC-02__positivo','ECO-02__positivo'])
def test_documented_positive_controls_and_confidence_are_preserved(case):
    r,path,project,plan,req=saved(case);wrapper=read(sorted(path.rglob('response.json'))[-1])
    result,_=live.resolve_wrapper(plan,project,req,wrapper)
    a={k:v for k,v in result['assessments'][0].items() if k!='indicator_id'}
    assert a['decision']=='SUPPORTED'
    assert v3.confidence(project['fields'],plan['profiles'][r['indicator_id']],a,plan['rubrics'][r['indicator_id']])==r['confidence']

@pytest.mark.parametrize('case',['TEC-02__tematico','ECO-02__negacion','TEC-07__publicacion_sin_adopcion','SOC-04__financiador'])
def test_no_support_can_be_a_valid_negative_without_invented_quotes(case):
    r,path,project,plan,req=saved(case);selection=read(next(path.rglob('selection.json')))
    # Explicit test fixture, not an automatic production repair or semantic label.
    a=selection['assessments'][0]
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=0)
    a['applicability'].update(status='UNDETERMINED',basis='UNKNOWN',evidence_refs=[])
    for c in a['criterion_assessments']:c.update(support='NOT_DEMONSTRATED',coverage=0,evidence_refs=[],evidence_relation='NO_SUPPORT')
    a['strength_rubric'].update({k:0 for k in v3.STRENGTH_DIMENSIONS},evidence_refs=[])
    result,_=live.resolve_wrapper(plan,project,req,refs.materialize(req,selection))
    a={k:v for k,v in result['assessments'][0].items() if k!='indicator_id'}
    assert a['decision']=='INSUFFICIENT_EVIDENCE' and a['evidence']==[]
    assert v3.confidence(project['fields'],plan['profiles'][r['indicator_id']],a,plan['rubrics'][r['indicator_id']])['confidence_raw_score']==0

@pytest.mark.parametrize('case',['HIST_21844_AMB-01','HIST_21750_TEC-02'])
def test_two_real_promotions_remain_pending_independent_review(tmp_path,case):
    r,path,project,plan,req=saved(case)
    runtime=read(AUDIT/'inferencia_local/baseline_v1/preflight.json')['runtime']
    native=[read(p) for p in sorted(path.rglob('native_response.json'))]
    client=Mock(spec=transport.OllamaClient);client.inspect.return_value=runtime;client.request.side_effect=native
    provider=transport.OllamaAssessmentProvider(tmp_path/'ollama_runs',path/'schema.json',lambda p,ids:req,
        settings=runtime['configuration'],runtime=runtime,client=client,max_indicators=1,corrective_retries=2,token_limit_retries=2,correction_version=p2.CORRECTION,
        wrapper_validator=lambda w,pid,ids:live.check_wrapper(plan,project,req,pid,ids,w),wrapper_resolver=lambda w:live.resolve_wrapper(plan,project,req,w))
    with pytest.raises(transport.OllamaError,match='INDEPENDENT_ADJUDICATION_REQUIRED'):provider.evaluate(project,[plan['profiles'][r['indicator_id']]])
    receipt=read(next((tmp_path/'ollama_runs').rglob('retry_decision.json')))
    assert receipt['status']=='PENDING_REVIEW' and receipt['same_evidence']
    assert receipt['promoted_criteria']==['C01','C02','C03','C04']
    assert client.request.call_count==len(native) and provider.last_output is None

def test_coherent_decoding_rejects_nd_references_and_preserves_valid_component_values():
    _,path,project,_,old=saved('CUL-02__positivo')
    wrapper=read(next(path.rglob('selection.json')));new=deepcopy(old);new['component_protocol']=p2.COMPONENT_PROTOCOL
    schema=refs.response_schema(new,project['fields']);Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(wrapper)
    c=wrapper['assessments'][0]['criterion_assessments'][0]
    c.update(support='NOT_DEMONSTRATED',coverage=0,evidence_relation='NO_SUPPORT')
    with pytest.raises(ValidationError):Draft202012Validator(schema).validate(wrapper)
    c['evidence_refs']=[];Draft202012Validator(schema).validate(wrapper)
    branch=schema['properties']['assessments']['items']['properties']['criterion_assessments']['items']['anyOf'][0]
    order=list(branch['properties'])
    assert order.index('explanation')<order.index('support')<order.index('evidence_refs')

@pytest.mark.parametrize('case',['CUL-02__positivo','TEC-02__positivo','ECO-02__positivo','CUL-02__tematico','CUL-02__negacion','CUL-02__prospectivo_vago','TEC-07__sin_informacion','HIST_21844_CUL-02'])
def test_coherent_transport_is_not_a_semantic_classifier_and_keeps_valid_prior_selections(case):
    _,path,project,_,old=saved(case)
    selection=read(sorted(path.rglob('selection.json'))[-1]);new=deepcopy(old);new['component_protocol']=p2.COMPONENT_PROTOCOL
    Draft202012Validator(refs.response_schema(new,project['fields'])).validate(selection)
    # Includes the old false positive deliberately: only a new semantic judgment,
    # not this grammar, can reject its otherwise coherent optimistic components.

def test_stricter_grammar_failure_cannot_erase_a_complete_unfavorable_retry_baseline(tmp_path):
    from tests.test_precision_correction_v1 import provider_for
    provider,project,profiles,_=provider_for(tmp_path)
    request=deepcopy(provider.input_factory(project,profiles));request['component_protocol']=p2.COMPONENT_PROTOCOL
    schema=refs.response_schema(request,project['fields'])
    request['context_budget']=cb.rebudget(request['prompt'],schema,provider.settings,request.get('context_budget'))
    schema_path=tmp_path/'schema.json';schema_path.write_text(json.dumps(schema),encoding='utf8')
    provider.schema=schema_path;provider.input_factory=lambda *a:request
    with pytest.raises(transport.OllamaError,match='INDEPENDENT_ADJUDICATION_REQUIRED'):provider.evaluate(project,profiles)
    receipt=read(next((tmp_path/'ollama_runs').rglob('retry_decision.json')))
    assert receipt['status']=='PENDING_REVIEW' and receipt['promoted_criteria']==['C01']
    assert len(list((tmp_path/'ollama_runs').rglob('selection.json')))==2

def test_coherent_protocol_still_allows_a_hash_bound_justified_review_fixture(tmp_path):
    from tests.test_precision_correction_v1 import provider_for,controlled_pair
    from layer4_evaluation.indicators import retry_review
    provider,project,profiles,approval=provider_for(tmp_path)
    _,_,before,candidate,_,_,_,_=controlled_pair()
    request=deepcopy(provider.input_factory(project,profiles));request['component_protocol']=p2.COMPONENT_PROTOCOL
    schema=refs.response_schema(request,project['fields'])
    request['context_budget']=cb.rebudget(request['prompt'],schema,provider.settings,request.get('context_budget'))
    schema_path=tmp_path/'schema.json';schema_path.write_text(json.dumps(schema),encoding='utf8')
    provider.schema=schema_path;provider.input_factory=lambda *a:request
    receipt=retry_review.compare(before,candidate,request,request,schema,schema,'SUPPORTED')
    approval['review_fingerprint']=receipt['review_fingerprint']
    assert approval['reviewer']=='SYNTHETIC_TEST_REVIEWER_NOT_REAL_ADJUDICATION'
    provider.retry_review=approval
    assert provider.evaluate(project,profiles)[0]['assessment']['decision']=='SUPPORTED'
    saved_receipt=read(next((tmp_path/'ollama_runs').rglob('retry_decision.json')))
    assert saved_receipt['status']=='APPROVED_REINTERPRETATION'
