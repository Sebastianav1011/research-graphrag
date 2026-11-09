"""Phase 1.1 checks: literal coverage, scoped repairs, no real model calls."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from jsonschema import Draft202012Validator
from autonomous_execution import policy as p,phase11,phase1,store as s,comparison,followup
from autonomous_execution.packing import pack
from autonomous_execution.engine import JobError,gate
from layer4_evaluation.indicators import assessment_v3 as v3,context_budget as cb
from layer4_evaluation.indicators.selection import canonical_hash
from layer4_evaluation.indicators.validation_diagnostics import semantic_issues,AssessmentValidationError
from tests.test_autonomous_execution import environment,ClientFactory,authorize,execute
from tests.test_ollama_provider import sample
from tests.test_context_budget import corpus

ROOT=Path(__file__).resolve().parents[1]
PREVIOUS=ROOT/followup.PREVIOUS


def policy():return s.read(ROOT/'config/autonomous_phase11.json')
def source(cid):return next(c for c in s.read(PREVIOUS/'assets/cases.json') if c['case_id']==cid)
def old_manifest():return s.read(PREVIOUS/'corrected/manifest.json')
def income():
    c=source('SYNTH_INCOME_POSITIVE__ECO-01');m=old_manifest();project=c['data']['project']
    raw=s.read(PREVIOUS/'corrected/attempts/SYNTH_INCOME_POSITIVE/ECO-01/r0_full/1/transport/SYNTH_INCOME_POSITIVE/attempt_1/response.raw.txt')
    return c,m,project,raw


def enable(e):
    m=s.read(e.directory/'manifest.json');m['policy']['version']=p.PHASE11
    s.write(e.directory/'manifest.json',m);e.prepared['manifest_sha256']=s.sha(e.directory/'manifest.json')
    return m


@pytest.mark.parametrize('ids',[['C01','C02','C03'],['C04','C05']])
def test_income_source_never_repeats_129_or_308_character_crop(ids):
    c,m,project,raw=income();limits=policy();schema=p.schema(project['fields'],limits,ids=ids)
    for tier in range(3):
        try:r=pack(c['data'],m['profiles']['ECO-01'],m['rubrics']['ECO-01'],p.settings(m['llm'],limits,tier),schema,criterion_ids=ids,concise=True,preserve=True)
        except JobError as exc:
            assert exc.code in ('STATIC_CONTEXT_TOO_LONG','EVIDENCE_COVERAGE_BUDGET');continue
        assert len(r['payload']['project']['fields']['summary'])==459
        assert r['coverage_receipt']['all_retrieved_intervals_preserved']
        assert r['coverage_receipt']['removed']==[]
        assert not any(o['reason']=='PARENT_CHUNK_SUBSPAN_SELECTED' for o in r['context_selection']['omitted'])
        break
    else:pytest.fail('No safe bounded budget fits the complete synthetic evidence')


def test_temporal_patch_repairs_only_stage_preserving_positive_judgments_and_literal_evidence():
    c,m,project,raw=income();limits=policy();rubric=m['rubrics']['ECO-01'];profile=m['profiles']['ECO-01']
    schema=p.schema(project['fields'],limits,criterion_ids=[c['criterion_id'] for c in rubric['criteria']])
    request=pack(c['data'],profile,rubric,p.settings(m['llm'],limits,2),schema,concise=True,preserve=True)
    a={k:v for k,v in raw['assessments'][0].items() if k!='indicator_id'}
    issues=semantic_issues(v3.validate(project['fields'],profile,a,rubric),a,'ECO-01',rubric,project['fields'])
    repaired,transport=phase11.patch_request(request,schema,raw,issues,project)
    patch=dict(project_id=raw['project_id'],assessments=[dict(indicator_id='ECO-01',changes={'$.evidence[0].stage':'ACTIVITY_EXECUTED'},reason='La cita relata desarrollo, validacion e implementacion realizados.')])
    Draft202012Validator(transport).validate(patch)
    result=phase11.apply_patch(repaired,patch)
    gate(project,profile,rubric,repaired,result,coherent=True)
    assert result['assessments'][0]['criterion_assessments']==raw['assessments'][0]['criterion_assessments']
    assert result['assessments'][0]['decision']==raw['assessments'][0]['decision']
    assert [e['text'] for e in result['assessments'][0]['evidence']]==[e['text'] for e in raw['assessments'][0]['evidence']]
    assert repaired['payload']['project']['fields']==request['payload']['project']['fields']
    assert cb.estimate(repaired['prompt'],transport,p.settings(m['llm'],limits,2))['fits']
    receipt=phase11.repair_receipt(repaired,patch,result)
    assert receipt['sources_removed']==[] and len(receipt['unchanged_criterion_ids'])==5
    # Immutable catalog: literal definitions and original roles remain intact.
    assert repaired['payload']['indicators'][0]['descripcion_ampliada']==profile['descripcion_ampliada']
    assert [v['temporal_requirement'] for v in repaired['payload']['indicators'][0]['rubric']['criteria']]==[v['temporal_requirement'] for v in rubric['criteria']]


@pytest.mark.parametrize('kind',['outside','duplicate','erase_positive'])
def test_scoped_repairs_reject_unrelated_edits_and_grounded_support_regression(sample,kind):
    project=dict(project_id='TEST_PROJECT',fields=sample['fields']);profile=sample['profile'];rubric=sample['rubric']
    limits=policy();raw=dict(project_id='TEST_PROJECT',assessments=[dict(indicator_id=profile['indicator_id'],**deepcopy(sample['assessment']))])
    schema=p.schema(project['fields'],limits);request=cb.make_request(project,profile,rubric,project['fields'])
    issues=[dict(rule='V3_CRITERION:CLEAR_REQUIRES_COMPATIBLE_SUBSTANTIVE_EVIDENCE',path='$.criterion_assessments[0].support',criterion_id='C01')]
    request,_=phase11.patch_request(request,schema,raw,issues,project)
    change=dict(path='$.criterion_assessments[0].support',value='NOT_DEMONSTRATED',reason='Intento de regresion simulado.')
    if kind=='outside':change['path']='$.criterion_assessments[2].support'
    changes=[change,deepcopy(change)] if kind=='duplicate' else [change]
    patch=dict(assessments=[dict(changes=changes)])
    with pytest.raises(AssessmentValidationError):phase11.apply_patch(request,patch)


def test_decision_patch_cannot_erase_frozen_partial(sample):
    a=deepcopy(sample['assessment']);a.update(decision='NOT_SUPPORTED',support_strength=0)
    a['criterion_assessments'][0]['support']='PARTIAL'
    raw=dict(project_id='TEST_PROJECT',assessments=[dict(indicator_id='SYNTH_I',**a)])
    project=dict(project_id='TEST_PROJECT',fields=sample['fields'])
    schema=p.schema(project['fields'],policy())
    request=cb.make_request(project,sample['profile'],sample['rubric'],project['fields'])
    request,patch_schema=phase11.patch_request(request,schema,raw,[dict(rule='V3_NOT_SUPPORTED:CANNOT_CLAIM_POSITIVE_CONCEPTUAL_SUPPORT',path='$.decision')],project)
    assert all(path in ('$.decision','$.support_strength','$.explanation') for path in request['repair_contract']['allowed_paths'])
    patch=dict(project_id='TEST_PROJECT',assessments=[dict(indicator_id='SYNTH_I',changes={'$.decision':'INSUFFICIENT_EVIDENCE','$.support_strength':1},reason='Soporte parcial conservado y fuerza compatible.')])
    Draft202012Validator(patch_schema).validate(patch)
    result=phase11.apply_patch(request,patch)
    gate(project,sample['profile'],sample['rubric'],request,result,coherent=True)
    assert result['assessments'][0]['criterion_assessments']==a['criterion_assessments']


def test_lossless_intervals_same_field_and_irreducible_source(corpus):
    data=dict(project=deepcopy(corpus.project),sections=deepcopy(corpus.sections),chunks=deepcopy(corpus.chunks),candidates=deepcopy(corpus.hits))
    text=data['project']['fields']['methodology'];split=len(text)//2
    data['chunks'][0].update(text=text[:split],char_end=split)
    other=deepcopy(data['chunks'][0]);other.update(chunk_id='SECOND',text=text[split:],char_start=split,char_end=len(text));data['chunks'].append(other)
    data['candidates'][0]['discovery_chunks'].append(dict(data['candidates'][0]['discovery_chunks'][0],chunk_id='SECOND'))
    limits=policy();schema=p.schema(data['project']['fields'],limits)
    request=pack(data,corpus.profiles['I00'],corpus.rubrics['I00'],p.settings({},limits,2),schema,preserve=True)
    assert request['payload']['project']['fields']['methodology']==text
    assert request['context_selection']['selected'][0]['included_chunk_ids']==['CHUNK','SECOND']
    data['chunks']=data['chunks'][:1];large='Una oracion de prueba. '*10000
    data['project']['fields']['methodology']=large;data['sections'][0]['text_original']=large
    data['chunks'][0].update(text=large,char_start=0,char_end=len(large));data['candidates'][0]['discovery_chunks']=data['candidates'][0]['discovery_chunks'][:1]
    with pytest.raises(JobError,match='EVIDENCE_COVERAGE_BUDGET'):
        pack(data,corpus.profiles['I00'],corpus.rubrics['I00'],p.settings({},limits,2),schema,preserve=True)


def test_scoped_transport_integration_and_restart_no_repeated_pass(environment):
    e=environment;enable(e)
    def stage_then_patch(data,payload,result,n):
        if n==1:
            raw=json.loads(result['message']['content']);raw['assessments'][0]['evidence'][0]['stage']='RESULT_EXPECTED';result['message']['content']=json.dumps(raw)
        if 'repair_state' in data:
            item=dict(indicator_id=data['indicators'][0]['indicator_id'],changes={'$.evidence[0].stage':'DESIGN_DOCUMENTED'},reason='El texto dice diseno vigente, no resultado esperado.')
            result['message']['content']=json.dumps(dict(project_id=data['project']['project_id'],assessments=[item]))
    factory=ClientFactory(e.sample,stage_then_patch);authorize(e)
    assert execute(e,factory)['status']=='COMPLETE'
    assert len(factory.calls)==3
    receipts=list(e.directory.rglob('repair.receipt.json'));assert len(receipts)==1
    assert s.read(receipts[0])['sources_removed']==[]
    assert execute(e,factory)['status']=='COMPLETE' and len(factory.calls)==3


def test_regressive_patch_remains_technical_block_not_false_negative(environment):
    e=environment;enable(e)
    def regressive(data,payload,result,n):
        if 'repair_state' in data:
            item=dict(indicator_id=data['indicators'][0]['indicator_id'],changes={'$.criterion_assessments[0].support':'NOT_DEMONSTRATED'},reason='Regresion simulada.')
            result['message']['content']=json.dumps(dict(project_id=data['project']['project_id'],assessments=[item]))
        else:
            raw=json.loads(result['message']['content']);raw['assessments'][0]['evidence'][0]['stage']='RESULT_EXPECTED';result['message']['content']=json.dumps(raw)
    authorize(e);result=execute(e,ClientFactory(e.sample,regressive))
    assert result['blocked']==2 and result['evaluated']==0
    assert all(v['error']=='SEMANTIC_REPAIR_UNRESOLVED' for v in result['recent_errors'])
    assert not list((e.directory/'results').rglob('*.json'))


def test_patch_transport_recovers_after_receipt_interruption_without_new_inference(environment,monkeypatch):
    e=environment;enable(e);flag={'interrupt':True}
    def repair(data,payload,result,n):
        if n==1:
            raw=json.loads(result['message']['content']);raw['assessments'][0]['evidence'][0]['stage']='RESULT_EXPECTED';result['message']['content']=json.dumps(raw)
        if 'repair_state' in data:
            result['message']['content']=json.dumps(dict(project_id=data['project']['project_id'],assessments=[dict(
                indicator_id=data['indicators'][0]['indicator_id'],changes={'$.evidence[0].stage':'DESIGN_DOCUMENTED'},reason='Diseno documentado.')]))
    factory=ClientFactory(e.sample,repair);authorize(e);original=s.write
    def interrupt(path,value):
        if Path(path).name=='repair.receipt.json' and flag['interrupt']:
            flag['interrupt']=False;raise KeyboardInterrupt()
        original(path,value)
    monkeypatch.setattr(s,'write',interrupt)
    assert execute(e,factory)['status']=='INTERRUPTED'
    assert len(factory.calls)==2
    assert execute(e,factory)['status']=='COMPLETE' and len(factory.calls)==3


def test_synthesis_repair_keeps_partial_and_llm_supplies_compatible_decision(environment):
    e=environment;enable(e);e.sample['assessment']['criterion_assessments'][0]['support']='PARTIAL'
    def split_then_decide(data,payload,result,n):
        keys=payload['format']['properties']['assessments']['items']['properties']
        if 'decision' in keys and 'criterion_assessments' in keys:result['done_reason']='length'
        elif 'repair_state' in data:
            result['message']['content']=json.dumps(dict(project_id=data['project']['project_id'],assessments=[dict(
                indicator_id=data['indicators'][0]['indicator_id'],changes={'$.decision':'INSUFFICIENT_EVIDENCE','$.support_strength':1},reason='Los juicios conservan soporte parcial y la fuerza es compatible.')]))
        elif 'decision' in keys:
            raw=json.loads(result['message']['content']);raw['assessments'][0].update(decision='NOT_SUPPORTED',support_strength=0);result['message']['content']=json.dumps(raw)
    factory=ClientFactory(e.sample,split_then_decide);authorize(e)
    assert execute(e,factory)['status']=='COMPLETE'
    for path in (e.directory/'results').rglob('*.json'):
        row=s.read(path)['row'];assert row['decision']=='INSUFFICIENT_EVIDENCE'
        assert row['criterion_assessments'][0]['support']=='PARTIAL' and row['confidence_raw_score']>0


def test_followup_prepares_exact_eight_without_baseline_or_implicit_labels(tmp_path,monkeypatch):
    monkeypatch.setattr(comparison,'location',lambda root,name:tmp_path/name)
    result=followup.prepare(ROOT,'eight');directory=tmp_path/'eight'
    assert result['cases']==8 and result['baseline_calls_planned']==0
    m=comparison.verify(ROOT,directory,authorized=False)
    assert m['arms']==['corrected'] and not (directory/'baseline').exists()
    old={c['case_id']:c for c in s.read(PREVIOUS/'assets/cases.json')}
    cases=s.read(directory/'assets/cases.json')
    assert len(cases)==8 and all(c['data']==old[c['case_id']]['data'] for c in cases)
    assert all(c['reference']['status']=='PENDING_HUMAN_REVIEW' for c in cases)
    with pytest.raises(ValueError,match='autorizacion'):comparison.execute(ROOT,'eight','corrected')
    comparison.authorize(ROOT,'eight',result['manifest_sha256'])
    with pytest.raises(ValueError,match='no autorizado'):comparison.execute(ROOT,'eight','baseline')
    report=comparison.metrics(ROOT,'eight')
    assert report['arms']['corrected']['cases']==8 and report['arms']['corrected']['accuracy_by_category']=={}
    assert not (directory/'baseline').exists()


def test_criterion_subdivision_preserves_every_id_and_source(environment,monkeypatch):
    from autonomous_execution.engine import Worker
    e=environment;m=enable(e);data=s.read(e.directory/'inputs/TEST_PROJECT.json')
    # Use exactly the already retrieved context; no retrieval or model provider.
    import sqlite3
    db=sqlite3.connect(e.directory/'candidate_index.sqlite') if (e.directory/'candidate_index.sqlite').exists() else None
    if db:
        data['candidates']=[json.loads(r[0]) for r in db.execute("SELECT value FROM rows WHERE kind='candidates' AND pid=?",('TEST_PROJECT',))];db.close()
    else:data['candidates']=deepcopy(e.corpus.hits)
    w=Worker(e.directory,m,ram=lambda:100000,sleep=lambda _:None);single=[]
    def simulated_step(project,profile,rubric,name,build,**kw):
        ids=kw.get('ids')
        if name.endswith('full') or ids and len(ids)>1:raise JobError('EVIDENCE_COVERAGE_BLOCKED')
        request,schema=build(p.settings(m['llm'],m['policy'],2,decision_only=kw.get('decision_only',False)),1)
        a=deepcopy(e.sample['assessment']);a['indicator_id']=profile['indicator_id']
        if ids:
            single.extend(ids);a['criterion_assessments']=[c for c in a['criterion_assessments'] if c['criterion_id'] in ids]
            assert request['coverage_receipt']['removed']==[]
        keys=schema['properties']['assessments']['items']['properties'];a={k:v for k,v in a.items() if k in keys}
        wrapper=dict(project_id=project['project_id'],assessments=[a])
        if kw.get('extra_gate'):kw['extra_gate'](wrapper)
        return wrapper,request
    monkeypatch.setattr(w,'_step',simulated_step)
    try:
        result=w.evaluate(data,'I00',0)
        assert single==['C01','C02','C03','C04']
        assert [c['criterion_id'] for c in result['row']['criterion_assessments']]==single
        assert all(r['payload']['project']['fields']['methodology']==e.corpus.chunks[0]['text'] for r in result['shard_requests'])
    finally:w.close()
