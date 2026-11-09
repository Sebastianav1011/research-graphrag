"""V4 offline regressions. Model outputs remain observations, never human labels."""
from copy import deepcopy
from pathlib import Path
import json

import pytest
from autonomous_execution import policy as p, phase12, phase11, followup, comparison, store as s
from autonomous_execution.engine import gate
from autonomous_execution.packing import pack
from layer4_evaluation.indicators import assessment_v3 as v3, context_budget as cb
from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError
from tests.test_autonomous_execution import environment, ClientFactory, authorize, execute
from tests.test_ollama_provider import sample
from tests.test_context_budget import corpus

ROOT=Path(__file__).resolve().parents[1]
V3=ROOT/followup.PHASE12_PREVIOUS
CASES=s.read(V3/'assets/cases.json')
MANIFEST=s.read(V3/'corrected/manifest.json')


def historical(cid,attempt=1):
    case=next(c for c in CASES if c['case_id']==cid)
    pid=case['data']['project']['project_id'];iid=case['indicator_id']
    folder=V3/'corrected/attempts'/pid/iid/'r0_full'/str(attempt)
    return case,s.read(folder/'step.json'),s.read(folder/'transport'/pid/'attempt_1/response.raw.txt')


def setup(cid,*,reevaluate=False):
    case,desc,raw=historical(cid);project=case['data']['project'];iid=case['indicator_id']
    profile=MANIFEST['profiles'][iid];rubric=MANIFEST['rubrics'][iid]
    limits=p.validate(s.read(ROOT/'config/autonomous_phase12.json'))
    schema=p.schema(project['fields'],limits,criterion_ids=[c['criterion_id'] for c in rubric['criteria']])
    request=pack(case['data'],profile,rubric,p.settings(MANIFEST['llm'],limits,2),schema,preserve=True,integral=True,concise=True)
    issues=phase12.diagnose(project,profile,rubric,request,raw)
    patched,transport=phase12.patch_request(request,schema,raw,issues,project,profile,rubric,reevaluate=reevaluate)
    return project,profile,rubric,raw,patched,transport


def patch(raw,changes,**kwargs):
    return dict(project_id=raw['project_id'],assessments=[dict(indicator_id=raw['assessments'][0]['indicator_id'],
        changes=changes,reason='Correccion offline del contrato; no es adjudicacion humana.',**kwargs)])


def test_integral_tec04_collects_provenance_temporal_and_decision_errors():
    project,profile,rubric,raw,request,_=setup('PROJ_5501__TEC-04')
    issues=request['repair_contract']['before'];rules=[i['rule'] for i in issues]
    assert 'QUOTE_NOT_IN_SENT_CONTEXT' in rules
    assert 'support_strength:INCONSISTENT_DECISION' in rules
    temporal=[i for i in issues if 'CLEAR_REQUIRES_COMPATIBLE' in i['rule']]
    assert {i['criterion_id'] for i in temporal}=={'C01','C03','C05'}
    allowed=request['repair_contract']['allowed_paths']
    assert '$.evidence[0].field' in allowed and '$.evidence[1].stage' in allowed
    assert '$.criterion_assessments[2].support' in allowed and '$.criterion_assessments[4].support' in allowed
    assert '$.criterion_assessments[1].support' not in allowed
    assert '$.criterion_assessments[3].support' not in allowed
    # The quote really exists in the other field. Preserve exact source coordinates.
    q=raw['assessments'][0]['evidence'][0]['text']
    assert project['fields']['summary']=='' and project['fields']['text__descripcion_objetivo'].find(q)==1174


@pytest.mark.parametrize('cid',['PROJ_5501__TEC-03','PROJ_5501__TEC-04'])
def test_historical_noop_patches_are_explicitly_rejected(cid):
    project,profile,rubric,raw,request,_=setup(cid)
    old_patch=historical(cid,2)[2]
    with pytest.raises(AssessmentValidationError) as error:
        phase12.apply_patch(request,old_patch,project,profile,rubric)
    assert error.value.issues[0]['rule']=='REPAIR_NO_EFFECT'
    assert error.value.diagnostics['before']==error.value.diagnostics['after']
    assert error.value.diagnostics['changed_paths']==[]


def test_income_historical_downgrade_cannot_hide_temporal_failure():
    project,profile,rubric,raw,request,_=setup('SYNTH_INCOME_POSITIVE__ECO-01')
    with pytest.raises(AssessmentValidationError) as error:
        phase12.apply_patch(request,historical('SYNTH_INCOME_POSITIVE__ECO-01',2)[2],project,profile,rubric)
    rules=[i['rule'] for i in error.value.issues]
    assert 'AFFECTED_CRITERION_REEVALUATION_REQUIRED' in rules
    assert 'V3_SUPPORTED:REQUIRED_CRITERION_NOT_CLEAR' in rules
    assert any('CLEAR_REQUIRES_COMPATIBLE' in x for x in rules)


def test_income_metadata_only_repair_preserves_all_459_chars_and_judgments():
    project,profile,rubric,raw,request,transport=setup('SYNTH_INCOME_POSITIVE__ECO-01')
    # Explicit fixture annotations test the validator, not live model quality.
    proposal=patch(raw,{'$.evidence[0].stage':'ACTIVITY_EXECUTED','$.evidence[1].stage':'RESULT_DEMONSTRATED'})
    candidate=phase12.apply_patch(request,proposal,project,profile,rubric)
    assert phase12.diagnose(project,profile,rubric,request,candidate)==[]
    assert candidate['assessments'][0]['criterion_assessments']==raw['assessments'][0]['criterion_assessments']
    assert candidate['assessments'][0]['decision']=='SUPPORTED'
    assert request['payload']['project']['fields']['summary']==project['fields']['summary']
    assert len(project['fields']['summary'])==459
    assert [e['text'] for e in candidate['assessments'][0]['evidence']]==[e['text'] for e in raw['assessments'][0]['evidence']]
    assert cb.estimate(request['prompt'],transport,p.settings(MANIFEST['llm'],s.read(ROOT/'config/autonomous_phase12.json'),2))['fits']


def test_tec04_bounded_reevaluation_can_reconsider_only_affected_judgments():
    project,profile,rubric,raw,request,_=setup('PROJ_5501__TEC-04',reevaluate=True)
    changes={'$.evidence[0].field':'text__descripcion_objetivo','$.support_strength':2}
    reasons=[]
    for index in (0,2,4):
        c=raw['assessments'][0]['criterion_assessments'][index]
        q=raw['assessments'][0]['evidence'][c['evidence_indices'][0]]['text']
        changes[f'$.criterion_assessments[{index}].support']='PARTIAL'
        changes[f'$.criterion_assessments[{index}].explanation']='La finalidad descrita no demuestra por si sola la ejecucion del uso.'
        reasons.append(dict(criterion_id=c['criterion_id'],source_field='text__descripcion_objetivo',source_text=q,
                            reason='La cita describe finalidad y mecanismo; reconsideracion simulada, pendiente de referencia humana.'))
    candidate=phase12.apply_patch(request,patch(raw,changes,reconsiderations=reasons),project,profile,rubric)
    gate(project,profile,rubric,request,candidate,integral=True)
    for i in (1,3):assert candidate['assessments'][0]['criterion_assessments'][i]==raw['assessments'][0]['criterion_assessments'][i]
    assert request['payload']['project']['fields']['text__descripcion_objetivo']==project['fields']['text__descripcion_objetivo']
    assert request['repair_contract']['prior']==raw
    receipt=phase12.repair_receipt(request,patch(raw,changes,reconsiderations=reasons),candidate)
    assert receipt['before'] and receipt['after']==[] and receipt['sources_removed']==[]
    # No silent downgrade: missing or fabricated grounding remains a technical error.
    for bad in ([],[dict(x,source_text='Texto inventado') for x in reasons]):
        with pytest.raises(AssessmentValidationError,match='GROUNDED_RECONSIDERATION_REQUIRED'):
            phase12.apply_patch(request,patch(raw,changes,reconsiderations=bad),project,profile,rubric)


def test_unrelated_edits_and_source_changes_rejected():
    project,profile,rubric,raw,request,_=setup('PROJ_5501__TEC-04')
    with pytest.raises(AssessmentValidationError,match='OUTSIDE_SCOPE'):
        phase12.apply_patch(request,patch(raw,{'$.criterion_assessments[1].support':'CLEAR'}),project,profile,rubric)
    request['payload']['project']['fields']['text__descripcion_objetivo']='Cambio no autorizado'
    with pytest.raises(AssessmentValidationError,match='REPAIR_SOURCE_COVERAGE_CHANGED'):
        phase12.apply_patch(request,patch(raw,{'$.evidence[0].stage':'ACTIVITY_EXECUTED'}),project,profile,rubric)


def test_new_contradiction_is_rejected_and_recorded():
    project,profile,rubric,raw,request,_=setup('SYNTH_INCOME_POSITIVE__ECO-01')
    proposal=patch(raw,{'$.evidence[0].stage':'ACTIVITY_EXECUTED','$.evidence[1].stage':'RESULT_DEMONSTRATED','$.decision':'NOT_SUPPORTED'})
    with pytest.raises(AssessmentValidationError) as error:phase12.apply_patch(request,proposal,project,profile,rubric)
    assert any('NOT_SUPPORTED' in i['rule'] for i in error.value.diagnostics['introduced_issues'])


@pytest.mark.parametrize('kind',['missing_quote','negative_with_quote','orientation_only','out_of_range','missing_criterion'])
def test_other_contract_errors_have_actionable_scopes_without_relaxing_rules(kind):
    case,desc,raw=historical('SYNTH_INCOME_POSITIVE__ECO-01')
    project=case['data']['project'];profile=MANIFEST['profiles']['ECO-01'];rubric=MANIFEST['rubrics']['ECO-01']
    item=raw['assessments'][0]
    if kind=='missing_quote':item['criterion_assessments'][0]['evidence_indices']=[]
    elif kind=='negative_with_quote':item['criterion_assessments'][0]['support']='NOT_DEMONSTRATED'
    elif kind=='orientation_only':
        item['evidence'][0]['field']='title';item['evidence'][0]['stage']='ACTIVITY_EXECUTED'
        project=deepcopy(project);project['fields']['title']=item['evidence'][0]['text']
        desc=deepcopy(desc);desc['request']['payload']['project']['fields']['title']=item['evidence'][0]['text']
    elif kind=='out_of_range':item['criterion_assessments'][0]['evidence_indices']=[99]
    else:item['criterion_assessments'].pop()
    issues=phase12.diagnose(project,profile,rubric,desc['request'],raw)
    assert issues
    schema=p.schema(project['fields'],s.read(ROOT/'config/autonomous_phase12.json'))
    repaired=phase12.patch_request(desc['request'],schema,raw,issues,project,profile,rubric)
    if kind=='missing_criterion':assert repaired is None
    else:
        paths=repaired[0]['repair_contract']['allowed_paths']
        assert '$.criterion_assessments[0].evidence_indices' in paths
        if kind=='missing_quote':assert '$.evidence[+]' in paths
        if kind=='orientation_only':assert '$.evidence[0].field' in paths


def test_orientation_quote_can_coexist_with_compatible_substantive_quote():
    case,desc,raw=historical('SYNTH_INCOME_POSITIVE__ECO-01')
    project=deepcopy(case['data']['project']);request=deepcopy(desc['request']);item=raw['assessments'][0]
    item['evidence'][0]['stage']='ACTIVITY_EXECUTED';item['evidence'][1]['stage']='RESULT_DEMONSTRATED'
    title_quote=deepcopy(item['evidence'][0]);title_quote['field']='title';item['evidence'].append(title_quote)
    project['fields']['title']=title_quote['text'];request['payload']['project']['fields']['title']=title_quote['text']
    item['criterion_assessments'][0]['evidence_indices'].append(2)
    assert phase12.diagnose(project,MANIFEST['profiles']['ECO-01'],MANIFEST['rubrics']['ECO-01'],request,raw)==[]


def test_asc01_comparison_does_not_turn_python_into_semantic_classifier():
    case,desc,negative=historical('SYNTH_DIALOGUE_POSITIVE__ASC-01')
    pid=case['data']['project']['project_id'];profile=MANIFEST['profiles']['ASC-01'];rubric=MANIFEST['rubrics']['ASC-01']
    positive=s.read(ROOT/followup.PREVIOUS/'corrected/results'/pid/'ASC-01.json')['wrapper']
    request=deepcopy(desc['request']);phase12.catalog_prompt(request,rubric)
    # Both outputs meet deterministic contracts. The real semantic contrast must be measured by Qwen/humans.
    assert phase12.diagnose(case['data']['project'],profile,rubric,request,positive)==[]
    assert phase12.diagnose(case['data']['project'],profile,rubric,request,negative)==[]
    assert 'Contrasta tambien los hechos' in request['prompt'] and 'No presupongas ninguna categoria' in request['prompt']
    assert 'Responde JSON completo' not in request['prompt']
    assert request['payload']['project']['fields']['summary']==case['data']['project']['fields']['summary']
    assert v3.confidence(case['data']['project']['fields'],profile,{k:v for k,v in positive['assessments'][0].items() if k!='indicator_id'},rubric)['confidence_raw_score']==86.25


@pytest.mark.parametrize('cid',[c['case_id'] for c in CASES if (V3/'corrected/results'/c['data']['project']['project_id']/(c['indicator_id']+'.json')).exists()])
def test_all_five_v3_passes_remain_structurally_acceptable(cid):
    case,desc,raw=historical(cid);iid=case['indicator_id'];project=case['data']['project']
    profile=MANIFEST['profiles'][iid];rubric=MANIFEST['rubrics'][iid]
    assert phase12.diagnose(project,profile,rubric,desc['request'],raw)==[]
    a={k:v for k,v in raw['assessments'][0].items() if k!='indicator_id'}
    result=s.read(V3/'corrected/results'/project['project_id']/(iid+'.json'))
    assert v3.confidence(project['fields'],profile,a,rubric)['confidence_raw_score']==result['row']['confidence_raw_score']


def enable(e):
    m=s.read(e.directory/'manifest.json');m['policy']['version']=p.PHASE12;m['policy']['attempts_per_step']=3
    s.write(e.directory/'manifest.json',m);e.prepared['manifest_sha256']=s.sha(e.directory/'manifest.json');return m


def test_worker_noop_escalates_once_and_resume_uses_pass_without_inference(environment):
    e=environment;enable(e);calls=[]
    def behavior(data,payload,result,n):
        calls.append(data.get('repair_mode','INITIAL'))
        if 'repair_state' not in data:
            wrapper=json.loads(result['message']['content']);wrapper['assessments'][0]['evidence'][0]['stage']='RESULT_EXPECTED'
            result['message']['content']=json.dumps(wrapper)
        else:
            stage='RESULT_EXPECTED' if data['repair_mode']=='LOCAL_PATCH' else 'DESIGN_DOCUMENTED'
            result['message']['content']=json.dumps(dict(project_id=data['project']['project_id'],assessments=[dict(
                indicator_id=data['indicators'][0]['indicator_id'],changes={'$.evidence[0].stage':stage},reason='Etapa de la evidencia en el caso simulado.')]))
    factory=ClientFactory(e.sample,behavior);authorize(e)
    result=execute(e,factory)
    assert result['status']=='COMPLETE' and len(factory.calls)==6
    assert calls==['INITIAL','LOCAL_PATCH','AFFECTED_CRITERIA_REEVALUATION']*2
    assert len(list(e.directory.rglob('repair.receipt.json')))==2
    assert execute(e,factory)['status']=='COMPLETE' and len(factory.calls)==6
    assert factory.maximum==1


def test_worker_three_failed_attempts_block_without_false_negative(environment):
    e=environment;enable(e)
    def behavior(data,payload,result,n):
        if 'repair_state' not in data:
            wrapper=json.loads(result['message']['content']);wrapper['assessments'][0]['evidence'][0]['stage']='RESULT_EXPECTED';result['message']['content']=json.dumps(wrapper)
        else:result['message']['content']=json.dumps(dict(project_id=data['project']['project_id'],assessments=[dict(
            indicator_id=data['indicators'][0]['indicator_id'],changes={'$.evidence[0].stage':'RESULT_EXPECTED'},reason='Parche sin cambio simulado.')]))
    factory=ClientFactory(e.sample,behavior);authorize(e);result=execute(e,factory)
    assert result['blocked']==2 and len(factory.calls)==6 and result['evaluated']==0
    assert all(x['error']=='SEMANTIC_REPAIR_UNRESOLVED' for x in result['recent_errors'])
    assert not list((e.directory/'results').rglob('*.json'))


def test_interrupted_repair_receipt_recovers_transport_without_extra_inference(environment,monkeypatch):
    e=environment;enable(e);interrupted=False
    def behavior(data,payload,result,n):
        if 'repair_state' not in data:
            wrapper=json.loads(result['message']['content']);wrapper['assessments'][0]['evidence'][0]['stage']='RESULT_EXPECTED';result['message']['content']=json.dumps(wrapper)
        else:result['message']['content']=json.dumps(dict(project_id=data['project']['project_id'],assessments=[dict(
            indicator_id=data['indicators'][0]['indicator_id'],changes={'$.evidence[0].stage':'DESIGN_DOCUMENTED'},reason='Correccion de etapa en simulacion.')]))
    factory=ClientFactory(e.sample,behavior);original=s.write
    def interrupt(path,value):
        nonlocal interrupted
        if Path(path).name=='repair.receipt.json' and not interrupted:
            interrupted=True;raise KeyboardInterrupt()
        original(path,value)
    authorize(e);monkeypatch.setattr(s,'write',interrupt)
    assert execute(e,factory)['status']=='INTERRUPTED'
    assert len(factory.calls)==2
    assert execute(e,factory)['status']=='COMPLETE' and len(factory.calls)==4


def test_six_case_preparation_requires_new_authorization_and_pins_both_observations(tmp_path,monkeypatch):
    monkeypatch.setattr(comparison,'location',lambda root,name:tmp_path/name)
    result=followup.prepare(ROOT,'six',phase12=True);directory=tmp_path/'six'
    m=comparison.verify(ROOT,directory,authorized=False)
    assert m['cases']==6 and m['case_ids']==followup.PHASE12_IDS and m['arms']==['corrected']
    assert result['inference_calls']==0 and not (directory/'authorization.json').exists()
    assert len(s.read(directory/'assets/previous_v2.json'))==6
    assert len(s.read(directory/'assets/previous_corrected.json'))==6
    assert all(c['reference']['status']=='PENDING_HUMAN_REVIEW' for c in s.read(directory/'assets/cases.json'))
    metrics=comparison.metrics(ROOT,'six')
    assert metrics['arms']['corrected']['accuracy_by_category']=={}
    assert metrics['arms']['corrected']['totals']['successful_repairs']==0
    with pytest.raises(ValueError,match='autorizacion'):comparison.execute(ROOT,'six','corrected')
    comparison.authorize(ROOT,'six',result['manifest_sha256'])
    with pytest.raises(ValueError,match='no autorizado'):comparison.execute(ROOT,'six','baseline')
    arm=s.read(directory/'corrected/manifest.json');arm['policy']['attempts_per_step']=1;s.write(directory/'corrected/manifest.json',arm)
    with pytest.raises(ValueError,match='INTEGRITY_MISMATCH'):comparison.verify(ROOT,directory)
