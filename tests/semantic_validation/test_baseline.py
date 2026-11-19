"""Run with pytest tests/semantic_validation --junitxml=... .

Contract reproduction is explicitly NOT semantic ground truth. Semantic safety
assertions below deliberately fail when production accepts a contradictory
judgment; failures are the baseline, never hidden with xfail or relaxed gates.
"""
from copy import deepcopy
from decimal import Decimal,ROUND_HALF_UP
from functools import lru_cache
import json
import pytest
import numpy as np
from .harness import *
from layer4_evaluation import live_execution as live
from layer4_evaluation.indicators import assessment_v3 as v3,prospective_v2 as p2,evidence_references as refs
from layer4_evaluation.indicators.ollama_provider import strict_json,merge_candidates,scope_issues,OllamaAssessmentProvider,OllamaError
from layer4_evaluation.indicators.scoped_retrieval import rank_project_passages
from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError

@lru_cache(maxsize=1)
def positives():return read(AUDIT/'casos_supported_fuentes.json')
def trusted_case():
    c=deepcopy(next(c for c in positives() if c['row']['siap_id']=='21736' and c['row']['indicator_id']=='CUL-02'))
    base=ROOT/c['calls'][0];response=read(next(base.glob('records/assessment/*.json')))['wrapper'];return c,response
def gate(c,w):
    p=c['project'];plan=dict(assessment_version=p2.VERSION,profiles={c['row']['indicator_id']:c['profile']},rubrics={c['row']['indicator_id']:c['rubric']},evaluation_policy={'decision_policy':p2.DECISION_POLICY})
    return live.resolve_wrapper(plan,p,c['context'],w)

@pytest.mark.parametrize('iid',sorted(read(Path(__file__).with_name('catalog_cases.json'))))
def test_independent_corpus_has_all_scenarios_and_minimal_pair(iid):
    cases=[x for x in corpus() if x['indicator_id']==iid];by={c['scenario']:c for c in cases}
    assert set(('positivo','tematico','prospectivo_vago','parcial','sin_informacion','negacion','otro_proyecto','sin_condicion'))<=by.keys()
    assert by['positivo']['text']==by['sin_condicion']['text']+' '+by['positivo']['critical_span']
    assert by['positivo']['expected']=='SUPPORTED' and by['sin_condicion']['expected']=='INSUFFICIENT_EVIDENCE'
    assert all(c['data_type']=='SYNTHETIC_TEST_ONLY' for c in cases)

@pytest.mark.parametrize('mutant',['missing_quote','invented_quote','wrong_project','wrong_fragment_id','foreign_fragment'])
def test_provenance_mutations_are_rejected(mutant):
    c,w=trusted_case();before=deepcopy(c)
    if mutant=='wrong_project':w['project_id']='PROJ_FOREIGN'
    elif mutant=='missing_quote':w['assessments'][0]['evidence']=[]
    elif mutant=='invented_quote':w['assessments'][0]['evidence'][0]['text']='Esta cita NO existe en las fuentes suministradas.'
    elif mutant=='wrong_fragment_id':
        selection=read(next((ROOT/c['calls'][0]).glob('assessment/ollama_runs/*/attempt_*/selection.json')))
        selection['assessments'][0]['criterion_assessments'][0]['evidence_refs']=[dict(fragment_id='F999999',stage='ACTIVITY_PROPOSED')]
        with pytest.raises(AssessmentValidationError):refs.materialize(c['context'],selection)
        assert c==before;return
    else:
        # Source text exists in the descriptor clone but not in sent own-project fragments.
        text='El proyecto Q conservó exclusivamente su propio archivo, sin atribución a P.'
        w['assessments'][0]['evidence'][0]['text']=text
        c['project']['fields'][w['assessments'][0]['evidence'][0]['field']]+=' '+text
    with pytest.raises((AssessmentValidationError,IndexError)):gate(c,w)

def zero_support(c,w,na=False):
    a=w['assessments'][0]
    a.update(decision='NOT_APPLICABLE' if na else 'INSUFFICIENT_EVIDENCE',support_strength=0)
    for j in a['criterion_assessments']:j.update(support='NOT_DEMONSTRATED',coverage=0,evidence_indices=[],evidence_relation='NO_SUPPORT')
    a['strength_rubric'].update({d:0 for d in v3.STRENGTH_DIMENSIONS});a['strength_rubric']['evidence_indices']=[]
    a['applicability'].update(status='NOT_APPLICABLE' if na else 'UNDETERMINED',basis='EXPLICIT_EXCLUSION' if na else 'UNKNOWN',evidence_indices=[0] if na else [])
    return a

def test_valid_negative_without_quotes_is_not_technical_error_or_na():
    c,w=trusted_case();a=zero_support(c,w);a['evidence']=[]
    resolved,_=gate(c,w);a=resolved['assessments'][0];a={k:v for k,v in a.items() if k!='indicator_id'}
    assert a['decision']=='INSUFFICIENT_EVIDENCE'
    assert v3.confidence(c['project']['fields'],c['profile'],a,c['rubric'])['confidence_raw_score']==0

def test_documented_exclusion_is_na_with_null_confidence():
    c,w=trusted_case();a=zero_support(c,w,na=True)
    text='El proyecto excluye expresamente cualquier acción sobre patrimonio material o inmaterial y se limita a calibración de sensores.'
    e=a['evidence'][0];e.update(text=text,stage='CONTEXT');c['project']['fields'][e['field']]=text
    # Independent fixture updates its own sent context; no historical artifact changes.
    c['context']['payload']['project']['fragments']=[dict(fragment_id='F000',field=e['field'],text=text)]
    a['evidence']=[e];a['applicability']['explanation']='El alcance excluye el objeto patrimonial obligatorio.'
    resolved,_=gate(c,w);a={k:v for k,v in resolved['assessments'][0].items() if k!='indicator_id'}
    assert a['decision']=='NOT_APPLICABLE'
    assert v3.confidence(c['project']['fields'],c['profile'],a,c['rubric'])['confidence_raw_score'] is None

def test_score_cannot_compensate_incomplete_required():
    c,w=trusted_case();a=w['assessments'][0]
    a['criterion_assessments'][0].update(support='PARTIAL',coverage=3)
    a['support_strength']=2
    for d in v3.STRENGTH_DIMENSIONS:a['strength_rubric'][d]=4
    result,_=gate(c,w);a={k:v for k,v in result['assessments'][0].items() if k!='indicator_id'}
    assert a['decision']=='INSUFFICIENT_EVIDENCE'
    assert v3.confidence(c['project']['fields'],c['profile'],a,c['rubric'])['confidence_raw_score']>90

@pytest.mark.parametrize('s,k,expected',[(Decimal(1),Decimal(1),'100.00'),(Decimal(14)/16,Decimal(1),'93.13'),(Decimal(15)/16,Decimal(1),'96.56'),(Decimal(0),Decimal(0),'0.00')])
def test_independent_arithmetic_anchors(s,k,expected):
    # Mathematical anchors are independent of model output, not semantic labels.
    assert str((100*(Decimal('0.55')*s+Decimal('0.45')*k)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))==expected

@pytest.mark.parametrize('c',read(AUDIT/'casos_supported_fuentes.json'),ids=lambda c:c['row']['siap_id']+':'+c['row']['indicator_id'])
def test_production_formula_matches_independent_historical_calculation(c):
    w=read(next((ROOT/c['calls'][0]).glob('records/assessment/*.json')))['wrapper']
    a={k:v for k,v in w['assessments'][0].items() if k!='indicator_id'}
    strength=sum(Decimal(a['strength_rubric'][d]) for d in v3.STRENGTH_DIMENSIONS)/16
    values={x['criterion_id']:Decimal(x['coverage'])/4 for x in a['criterion_assessments']};rub=c['rubric']['criteria']
    units=[values[x['criterion_id']] for x in rub if x['role']=='REQUIRED']
    for group in {x['alternative_group'] for x in rub if x['role']=='ALTERNATIVE'}:units.append(max(values[x['criterion_id']] for x in rub if x.get('alternative_group')==group))
    expected=(100*(Decimal('.55')*strength+Decimal('.45')*sum(units)/len(units))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    assert v3.confidence(c['project']['fields'],c['profile'],a,c['rubric'])['confidence_raw_score']==float(expected)

@pytest.mark.parametrize('mutation',['explicit_negation','foreign_attribution','achieved_to_intention','missing_required_content'])
def test_semantic_safety_contract_must_not_accept_incompatible_quote(mutation):
    """Known boundary probe: production trusts the LLM's semantic labels.

    Expected FAIL documents missing guarantee. This is NOT a new classifier or
    a claim that Qwen itself was run on the mutated text.
    """
    c,w=trusted_case();a=w['assessments'][0]
    texts={
      'explicit_negation':'El proyecto NO conservó ni propone conservar patrimonio cultural; esa atribución es falsa.',
      'foreign_attribution':'Sólo el proyecto Q, ajeno al proyecto P evaluado, conservó el patrimonio de su comunidad.',
      'achieved_to_intention':'Se estudiará si algún día sería posible conservar algo; no hay patrimonio identificado ni mecanismo propuesto.',
      'missing_required_content':'El proyecto registra temperatura de sensores; no se describe una acción sobre patrimonio.'}
    text=texts[mutation]
    # Keep Qwen's optimistic labels and make the NEW contradictory quote literal.
    # This isolates semantic entailment from citation existence.
    field=a['evidence'][0]['field'];c['project']['fields']={field:text}
    for e in a['evidence']:e.update(field=field,text=text)
    c['context']['payload']['project']['fragments']=[dict(fragment_id='F000',field=field,text=text)]
    accepted=True
    try:result,_=gate(c,w);accepted=result['assessments'][0]['decision']=='SUPPORTED'
    except (AssessmentValidationError,IndexError):accepted=False
    assert not accepted,'Production accepted literal but semantically incompatible evidence with unchanged optimistic judgments: '+mutation

PROMOTIONS=read(AUDIT/'positivos_tras_correccion.json')
@pytest.mark.parametrize('record',PROMOTIONS,ids=lambda r:r['caso'])
def test_historical_retry_promotion_has_explicit_new_evidence_or_adjudication(record,tmp_path):
    """Expected FAIL: expose promotions; first invalid reply is not human truth."""
    first=Path(record['primer_intento']);attempts=sorted(first.parent.glob('attempt_*'),key=lambda p:int(p.name.split('_')[-1]))
    old=read(first/'selection.json')['assessments'][0];new=read(attempts[-1]/'selection.json')['assessments'][0]
    before_request=read(first/'request.json');after_request=read(attempts[-1]/'request.json')
    payload=lambda req:json.loads(req['messages'][0]['content'].split('INPUT_JSON:\n',1)[1])
    before_payload=payload(before_request);after_payload=payload(after_request)
    assert before_payload==after_payload,'This promotion has NEW input; inspect separately, do not assume identical evidence.'
    assert before_request['format']==after_request['format']
    result=promotion_findings(old,new,before_payload['project'],after_payload['project'])
    # Exercise the actual retry provider with historical native answers, zero network.
    # A future production correction guard can reject this promotion and pass
    # this regression without changing immutable historical files.
    base=first.parents[3];plan=read(base.parents[2]/'plan.json');pid=read(first/'selection.json')['project_id'];iid=old['indicator_id']
    project=next(p for p in plan['projects'] if p['project_id']==pid);req=plan['context_requests'][pid][iid]
    rec=read(base/'records/assessment'/ (pid+'.json'));runtime=rec['calls'][0]['runtime']
    class HistoricalClient:
        def __init__(self):self.index=0
        def inspect(self):return runtime
        def request(self,method,path,payload):
            assert (method,path)==('POST','/api/chat')
            answer=read(attempts[self.index]/'native_response.json');self.index+=1;return answer
    provider=OllamaAssessmentProvider(tmp_path/'historical_transport',base/'schema.json',lambda p,ids:req,
        settings=plan['runtime']['configuration'],runtime=runtime,client=HistoricalClient(),max_indicators=1,
        corrective_retries=plan['corrective_retries'],token_limit_retries=plan['token_limit_retries'],correction_version=plan['correction_protocol'],
        wrapper_validator=lambda w,p,ids:live.check_wrapper(plan,project,req,p,ids,w),wrapper_resolver=lambda w:live.resolve_wrapper(plan,project,req,w))
    try:decision=provider.evaluate(project,[plan['profiles'][iid]])[0]['assessment']['decision']
    except OllamaError as exc:
        assert exc.code=='INVALID_ASSESSMENT','Unexpected transport/harness error: '+str(exc)
        decision='BLOCKED_ERROR'
    assert not (result['requires_adjudication'] and decision=='SUPPORTED'),'Production retry accepted unadjudicated promotion with unchanged evidence: '+str(result['promoted_criteria'])

def test_future_stage_is_not_executed_when_original_rubric_requires_execution():
    c,w=trusted_case();a=deepcopy(w['assessments'][0]);a.pop('indicator_id');a=p2.common_assessment(a)
    original=read(next(RUN.glob('evaluation/batch_*/plan.json')))['catalog_derivation']['interpretations']['CUL-02']['original_rubric']
    for e in a['evidence']:e['stage']='ACTIVITY_PROPOSED'
    assert any('COMPATIBLE_SUBSTANTIVE' in e for e in v3.validate(c['project']['fields'],c['profile'],a,original))

def test_monitor_detects_promotions_but_does_not_classify():
    before=dict(criterion_assessments=[dict(criterion_id='C01',support='NOT_DEMONSTRATED',coverage=0)])
    after=dict(criterion_assessments=[dict(criterion_id='C01',support='CLEAR',coverage=4)])
    r=promotion_findings(before,after,'same fragment','same fragment')
    assert r['requires_adjudication'] and r['promoted_criteria']==['C01']
    assert not promotion_findings(before,before,'same','same')['requires_adjudication']
    assert not promotion_findings(before,after,'old','new')['same_evidence']

def test_existing_targeted_scope_detects_grade_mutation():
    before={'assessments':[{'criterion_assessments':[dict(criterion_id='C01',support='NOT_DEMONSTRATED',coverage=0,evidence_refs=[])]}]}
    after=deepcopy(before);after['assessments'][0]['criterion_assessments'][0].update(support='CLEAR',coverage=4)
    issues=scope_issues(before,['C01'],after)
    assert any(x['rule']=='TARGETED_CORRECTION:FLAGGED_CRITERION_INCREASED' for x in issues)

def test_existing_merge_preserves_unflagged_judgment():
    before={'assessments':[{'criterion_assessments':[dict(criterion_id='C01',support='PARTIAL',coverage=2),dict(criterion_id='C02',support='NOT_DEMONSTRATED',coverage=0)]}]}
    after=deepcopy(before);after['assessments'][0]['criterion_assessments'][1].update(support='CLEAR',coverage=4)
    candidate,origin=next(merge_candidates(before,['C01'],False,after))
    assert candidate['assessments'][0]['criterion_assessments'][1]['support']=='NOT_DEMONSTRATED'
    assert origin['criteria_origin']['C02']=='first_judgment'

def test_metrics_only_use_validated_independent_labels_and_report_abstention():
    rows=[dict(expected=e,actual=a,validated=True) for e,a in [('SUPPORTED','SUPPORTED'),('INSUFFICIENT_EVIDENCE','SUPPORTED'),('SUPPORTED','INSUFFICIENT_EVIDENCE'),('INSUFFICIENT_EVIDENCE','INSUFFICIENT_EVIDENCE'),('SUPPORTED','BLOCKED_ERROR')]]
    rows.append(dict(expected='SUPPORTED',actual='SUPPORTED',validated=False))
    m=binary_metrics(rows)
    assert (m['TP'],m['FP'],m['FN'],m['TN'])==(1,1,1,1)
    assert m['precision']==m['recall']==m['F1']==0.5
    assert m['validated']==5 and m['scored']==4 and m['abstentions']==1
    assert binary_metrics([rows[-1]])['precision'] is None

def test_read_only_retrieval_rejects_cross_project_rank_competition():
    projects=[dict(project_id='P',fields={'methodology':'Own negative context.'})]
    profiles={'TEC-07':{}}
    chunks=[dict(chunk_id='own',source_id='P',source_type='PROJECT',field_name='methodology',text='Own negative context.'),dict(chunk_id='foreign',source_id='Q',source_type='PROJECT',field_name='methodology',text='Q adopted its own software.')]
    records=[dict(chunk_id='own'),dict(chunk_id='foreign')]
    # Q is graph-connected through a shared investigator; its relevant text
    # must remain relational context, never become direct evidence of P.
    package=dict(seed_entity_id='PROJECT:P',entities=[
        dict(entity_id='PROJECT:P',entity_type='PROJECT',canonical_id='P',label='P'),
        dict(entity_id='PROJECT:Q',entity_type='PROJECT',canonical_id='Q',label='Q'),
        dict(entity_id='RESEARCHER:R',entity_type='RESEARCHER',canonical_id='R',label='R')],
        relations=[dict(relation_id='PR',source_entity_id='PROJECT:P',target_entity_id='RESEARCHER:R'),dict(relation_id='QR',source_entity_id='PROJECT:Q',target_entity_id='RESEARCHER:R')],
        support_paths={'PROJECT:Q':['PR','QR'],'RESEARCHER:R':['PR']})
    ranked=rank_project_passages(projects,profiles,chunks,records,np.array([[0.,1.],[1.,0.]]),{'TEC-07':(['ref'],np.array([[1.,0.]]))},{'P':package})
    assert [x['chunk_id'] for x in ranked[0]['discovery_chunks']]==['own']
    assert any(n['canonical_id']=='Q' for n in ranked[0]['relational_context']['entities'])

@pytest.mark.parametrize('bad',['{"x":1,"x":2}','{"x":NaN}','{"x":1} trailing'])
def test_invalid_transport_cannot_be_negative_evidence(bad):
    with pytest.raises(ValueError):strict_json(bad)

def test_oracle_detects_favorable_output_mutation():
    c=next(c for c in corpus() if c['case_id']=='TEC-07__publicacion_sin_adopcion')
    assert compare_expected(c,'INSUFFICIENT_EVIDENCE')=='PASS'
    assert compare_expected(c,'SUPPORTED')=='FAIL'

@lru_cache(maxsize=1)
def historical_plan(path):return read(path)

@pytest.mark.parametrize('path',sorted(RUN.glob('evaluation/batch_*/calls/*/*/records/assessment/*.json')),ids=lambda p:p.parents[5].name+'/'+p.parents[3].name+'/'+p.parents[2].name)
def test_historical_contract_reproduction_is_not_semantic_ground_truth(path):
    plan=historical_plan(str(path.parents[5]/'plan.json'));rec=read(path);project=next(p for p in plan['projects'] if p['project_id']==rec['project_id'])
    dirs=sorted(path.parents[2].glob('assessment/ollama_runs/*/attempt_*'),key=lambda p:int(p.name.split('_')[-1]));accepted=[]
    for d in dirs:
        selection=read(d/'selection.json');iid=selection['assessments'][0]['indicator_id'];req=plan['context_requests'][rec['project_id']][iid]
        try:live.materialize_output(plan,project,req,selection);accepted.append(d.name)
        except AssessmentValidationError:pass
    assert bool(accepted)==(rec['status']=='VALID')
    assert len(accepted)<=1
