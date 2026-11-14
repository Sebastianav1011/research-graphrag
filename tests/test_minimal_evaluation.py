"""Same three existing controls; simulated outputs only, never human labels or Ollama."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from autonomous_execution import minimal as m, comparison, store as s
from autonomous_execution.engine import ScopeError
from layer4_evaluation.indicators import assessment_v3 as v3
from layer4_evaluation.indicators.selection import canonical_hash
from tests.test_autonomous_execution import environment
from tests.test_context_budget import corpus
from tests.test_ollama_provider import sample

from tests import historical

ROOT=Path(__file__).resolve().parents[1]
# Read lazily from the resolved historical run: nothing is read at import time.
CASES=historical.Lazy(lambda:{c['case_id']:c for c in s.read(historical.require(m.PREVIOUS)/'assets/cases.json') if c['case_id'] in m.IDS})
MANIFEST=historical.Lazy(lambda:s.read(historical.require(m.PREVIOUS)/'corrected/manifest.json'))
COMPACTED_MINIMAL='outputs/runs/run_institutional_minimal_3x3_20261102'  # compacted by retention
MINIMAL_V1='outputs/runs/minimal_3_v1'


def answer(case):
    """A contract fixture, not a prediction or approved reference."""
    iid=case['indicator_id'];registry=m.registry(case['data'],iid);eid=next(iter(registry));positive='NEGATIVE' not in case['case_id']
    stages=({'C01':'CONTEXT','C02':'ACTIVITY_EXECUTED','C03':'RESULT_DEMONSTRATED','C04':'CONTEXT','C05':'RESULT_DEMONSTRATED'}
            if iid=='ECO-01' else dict.fromkeys(['C01','C02','C03','C04','C05'],'MECHANISM_ESTABLISHED'))
    if iid=='ECO-01':stages['C01']='ACTIVITY_EXECUTED'
    return dict(criteria={c['criterion_id']:dict(judgment='CLEAR__'+stages[c['criterion_id']] if positive else 'NOT_DEMONSTRATED',
        evidence_ids=[eid],why='Juicio simulado basado en la fuente original, pendiente de revision humana.') for c in MANIFEST['rubrics'][iid]['criteria']},
        conclusion='SUPPORTED__3' if positive else 'NOT_SUPPORTED__0',why='Conclusion simulada; no es una etiqueta humana.')


@pytest.fixture
def experiment(tmp_path,monkeypatch):
    monkeypatch.setattr(comparison,'location',lambda root,name:tmp_path/name)
    prepared=m.prepare(ROOT,'three')
    return tmp_path/'three',prepared


class Factory:
    def __init__(self,behavior=None):self.calls=[];self.behavior=behavior
    def __call__(self,settings):
        factory=self
        class Client:
            def inspect(self):return MANIFEST['runtime']|dict(configuration=settings,configuration_sha256=canonical_hash(settings))
            def request(self,method,path,payload):
                assert (method,path)==('POST','/api/chat')
                data=json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n',1)[1]);factory.calls.append(data)
                # Match the existing source ID, never create another control/source.
                case=next(c for c in CASES.values() if set(m.registry(c['data'],c['indicator_id']))=={e['id'] for e in data['evidence']})
                value=answer(case)
                if 'previous' in data:value['criteria']={cid:value['criteria'][cid] for cid in data['requested_criteria']}
                if factory.behavior:factory.behavior(data,value,len(factory.calls))
                return dict(model=settings['model'],done=True,done_reason='stop',prompt_eval_count=200,eval_count=180,
                            message=dict(content=json.dumps(value)))
        return Client()


def execute(factory):return comparison.execute(ROOT,'three','corrected',client_factory=factory,ram=lambda:100000,sleep=lambda _:None)


@pytest.mark.parametrize('cid',m.IDS)
def test_adapter_preserves_source_rubric_and_existing_confidence(cid):
    c=CASES[cid];data=c['data'];iid=c['indicator_id'];r=MANIFEST['rubrics'][iid];profile=MANIFEST['profiles'][iid]
    registry=m.registry(data,iid);raw=answer(c);Draft202012Validator(m.schema(r,registry)).validate(raw)
    wrapper=m.assemble(data['project'],iid,r,registry,raw);a={k:v for k,v in wrapper['assessments'][0].items() if k!='indicator_id'}
    assert not v3.validate(data['project']['fields'],profile,a,r)
    assert v3.confidence(data['project']['fields'],profile,a,r)['confidence_raw_score']==(0 if 'NEGATIVE' in cid else 86.25)
    assert registry==m.registry(deepcopy(data),iid)
    assert all(e['text'] in data['project']['fields'][e['field']] for e in a['evidence'])
    assert len(next(iter(registry.values()))['text'])==({'SYNTH_DIALOGUE_POSITIVE__ASC-01':390,'SYNTH_INCOME_POSITIVE__ECO-01':459,'SYNTH_INCOME_NEGATIVE__ECO-01':279}[cid])


@pytest.mark.parametrize('conclusion',['NOT_SUPPORTED__0','INSUFFICIENT_EVIDENCE__1','INSUFFICIENT_EVIDENCE__2','SUPPORTED__3'])
def test_existing_categories_do_not_force_all_criteria_to_follow_global_decision(conclusion):
    """Contract fixtures, never retrospective semantic labels or migrations."""
    case=CASES['SYNTH_INCOME_POSITIVE__ECO-01'];data=case['data'];iid=case['indicator_id']
    raw=answer(case);rubric=MANIFEST['rubrics'][iid];reg=m.registry(data,iid)
    raw['conclusion']=conclusion
    if not conclusion.startswith('SUPPORTED'):
        for c in raw['criteria'].values():c['judgment']='NOT_DEMONSTRATED'
        if conclusion.startswith('INSUFFICIENT'):
            raw['criteria']['C01']['judgment']='PARTIAL__ACTIVITY_EXECUTED'
    original=deepcopy(raw)
    Draft202012Validator(m.schema(rubric,reg)).validate(raw)
    wrapper=m.assemble(data['project'],iid,rubric,reg,raw);a=wrapper['assessments'][0]
    assert raw==original and a['decision']==m.CONCLUSIONS[conclusion][0]
    computed=v3.confidence(data['project']['fields'],MANIFEST['profiles'][iid],{k:v for k,v in a.items() if k!='indicator_id'},rubric)
    assert computed['confidence_status']=='COMPUTED'
    if conclusion.startswith('INSUFFICIENT'):
        assert a['criterion_assessments'][0]['support']=='PARTIAL'
        assert computed['confidence_raw_score'] in (18.25,32.0)
    elif conclusion.startswith('NOT_SUPPORTED'):assert computed['confidence_raw_score']==0
    else:assert computed['confidence_raw_score']==86.25


def test_title_only_clear_is_rejected_without_reclassifying_evidence():
    """Historical replay (opt-in). The rule itself is covered synthetically in
    test_title_only_clear_rule_is_enforced_on_synthetic_evidence."""
    root=historical.require(COMPACTED_MINIMAL,compacted=True)/'autonomous/main'
    step=s.read(root/'attempts/PROJ_4636/TEC-03/minimal/1/step.json')
    manifest=s.read(root/'manifest.json');reg=step['request']['evidence_registry']
    raw=s.read(root/'attempts/PROJ_4636/TEC-03/minimal/1/transport/PROJ_4636/attempt_1/response.raw.txt')
    transport=m.schema(manifest['rubrics']['TEC-03'],reg)
    assert not list(Draft202012Validator(transport).iter_errors(raw))
    def validate(value):
        wrapper=m.assemble(step['request']['payload']['project'],'TEC-03',manifest['rubrics']['TEC-03'],reg,value)
        a={k:v for k,v in wrapper['assessments'][0].items() if k!='indicator_id'}
        return v3.validate(step['request']['payload']['project']['fields'],manifest['profiles']['TEC-03'],a,manifest['rubrics']['TEC-03'])
    assert validate(raw).count('V3_CRITERION:CLEAR_REQUIRES_COMPATIBLE_SUBSTANTIVE_EVIDENCE')==2
    title_id=next(k for k,e in reg.items() if e['field']=='title')
    body_id=next(k for k,e in reg.items() if e['field']=='text__descripcion_objetivo')
    for cid in ('C02','C04'):raw['criteria'][cid]['evidence_ids']=[title_id,body_id]
    assert not list(Draft202012Validator(transport).iter_errors(raw))
    # This only verifies references/fields. The contradictory conclusion still fails V3.
    assert raw['conclusion']=='NOT_SUPPORTED__0'
    assert validate(raw)==['V3_NOT_SUPPORTED:CANNOT_CLAIM_POSITIVE_CONCEPTUAL_SUPPORT']


def test_historical_v4_temporal_errors_are_prevented_by_enum_not_python_relabeling():
    for cid in m.IDS[:2]:
        case=CASES[cid];iid=case['indicator_id'];pid=case['data']['project']['project_id'];r=MANIFEST['rubrics'][iid]
        raw=s.read(historical.require(m.PREVIOUS)/'corrected/attempts'/pid/iid/'r0_full/1/transport'/pid/'attempt_1/response.raw.txt')['assessments'][0]
        assert raw['decision']=='SUPPORTED' and all(e['stage']=='CONTEXT' for e in raw['evidence'])
        proposed=answer(case);proposed['criteria']['C02']['judgment']='CLEAR__CONTEXT'
        assert list(Draft202012Validator(m.schema(r,m.registry(case['data'],iid))).iter_errors(proposed))


def test_provenance_unknown_ids_and_source_changes_are_not_repaired():
    case=CASES[m.IDS[0]];iid=case['indicator_id'];reg=m.registry(case['data'],iid);raw=answer(case);rubric=MANIFEST['rubrics'][iid]
    raw['criteria']['C01']['evidence_ids']=['E_DOES_NOT_EXIST']
    assert list(Draft202012Validator(m.schema(rubric,reg)).iter_errors(raw))
    with pytest.raises(ScopeError,match='EVIDENCE_ID_NOT_FOUND'):m.assemble(case['data']['project'],iid,rubric,reg,raw)
    project=deepcopy(case['data']['project']);project['project_id']='WRONG_PROJECT'
    with pytest.raises(ScopeError,match='SOURCE_CHANGED'):m.assemble(project,iid,rubric,reg,answer(case))


@pytest.mark.parametrize('original',[
    '  Cafe\u0301\u00a0conservado.\r\nSegundo  resultado.  ',
    'Primero\tconservado.\n\n\nSegundo\u200b resultado.',
    'Repetido.\u00a0Repetido.\u00a0Repetido.',
])
def test_normalized_discovery_intervals_keep_exact_original_quotes(corpus,original):
    from layer2_processing.knowledge.text_normalization import normalize
    from autonomous_execution.packing import pack
    normalized=normalize(original,{'unicode':'NFC'})
    data=dict(project=deepcopy(corpus.project),sections=deepcopy(corpus.sections),
        chunks=deepcopy(corpus.chunks),candidates=[deepcopy(corpus.hits[0])])
    data['project']['fields']['methodology']=original
    data['sections'][0].update(text_original=original,text_normalized=normalized)
    # Include an overlapping second interval of the same field, as Discovery does.
    end=len(normalized);start=normalized.rfind(' ')+1
    data['chunks'][0].update(text=normalized,char_start=0,char_end=end)
    data['chunks'].append(data['chunks'][0]|dict(chunk_id='SECOND',text=normalized[start:],char_start=start))
    data['candidates'][0]['discovery_chunks'].append(data['candidates'][0]['discovery_chunks'][0]|dict(chunk_id='SECOND'))
    before=deepcopy(data);iid=corpus.hits[0]['indicator_id'];rubric=corpus.rubrics[iid]
    reg=m.registry(data,iid)
    assert len(reg)==2 and data==before
    assert all(e['text']==original[e['start']:e['end']] for e in reg.values())
    assert all(e['normalized_interval']['offset_basis']=='text_normalized' for e in reg.values())
    raw=dict(criteria={c['criterion_id']:dict(judgment='PARTIAL__CONTEXT',evidence_ids=list(reg),why='Controlled quote')
        for c in rubric['criteria']},conclusion='INSUFFICIENT_EVIDENCE__1',why='Controlled transport')
    wrapper=m.assemble(data['project'],iid,rubric,reg,raw)
    assert all(e['text'] in original for e in wrapper['assessments'][0]['evidence'])
    settings=deepcopy(corpus.settings);settings.update(num_ctx=32768)
    request=pack(data,corpus.profiles[iid],rubric,settings,m.schema(rubric,reg),preserve=True)
    ref=request['context_selection']['selected'][0]
    assert request['payload']['project']['fields']['methodology']==original[ref['char_start']:ref['char_end']]
    assert ref['included_chunk_ids']==['CHUNK','SECOND']
    assert data==before


@pytest.mark.parametrize('mutation',['project','hit_field','section_source','original','normalized','offset','missing_chunk'])
def test_registry_rejects_unauthorized_or_inconsistent_discovery_sources(corpus,mutation):
    data=dict(project=deepcopy(corpus.project),sections=deepcopy(corpus.sections),
        chunks=deepcopy(corpus.chunks),candidates=[deepcopy(corpus.hits[0])])
    if mutation=='project':data['chunks'][0]['source_id']='FOREIGN'
    if mutation=='hit_field':data['candidates'][0]['discovery_chunks'][0]['field_name']='other'
    if mutation=='section_source':data['sections'][0]['source_id']='FOREIGN'
    if mutation=='original':data['project']['fields']['methodology']='Unauthorized replacement'
    if mutation=='normalized':data['sections'][0]['text_normalized']='Unrelated passage'
    if mutation=='offset':data['chunks'][0]['char_end']+=1
    if mutation=='missing_chunk':data['chunks']=[]
    with pytest.raises(ScopeError) as caught:m.registry(data,corpus.hits[0]['indicator_id'])
    assert caught.value.code=='EVIDENCE_SOURCE_MISMATCH'
    assert 'indicator='+corpus.hits[0]['indicator_id'] in str(caught.value)
    assert 'Unauthorized replacement' not in str(caught.value)


def test_ambiguous_normalized_boundary_is_rejected():
    from autonomous_execution.packing import original_chunk
    project=dict(project_id='P',fields={'summary':'\ufb03'})
    section=dict(section_id='S',source_id='P',field_name='summary',text_original='\ufb03',text_normalized='ffi')
    chunk=dict(chunk_id='C',section_id='S',source_id='P',field_name='summary',char_start=1,char_end=3,text='fi')
    with pytest.raises(ValueError,match='boundary cannot map exactly'):
        original_chunk(project,{'S':section},chunk,dict(field_name='summary'))


def test_only_three_authorized_cases_no_copied_historical_outputs(experiment):
    directory,prepared=experiment;outer=comparison.verify(ROOT,directory,authorized=False)
    assert outer['case_ids']==m.IDS and outer['cases']==3
    assert set(outer['historical'])=={'V2','V3','V4'}
    assert not (directory/'assets').exists() and not (directory/'authorization.json').exists()
    assert [c['case_id'] for c in comparison.case_inputs(ROOT,directory,outer)]==m.IDS
    with pytest.raises(ValueError,match='autorizacion'):execute(Factory())
    comparison.authorize(ROOT,'three',prepared['manifest_sha256'])
    with pytest.raises(ValueError,match='no autorizado'):comparison.execute(ROOT,'three','baseline')


def test_one_call_each_and_resume_without_repeating_pass(experiment):
    directory,prepared=experiment;comparison.authorize(ROOT,'three',prepared['manifest_sha256']);factory=Factory()
    report=execute(factory);totals=report['arms']['corrected']['totals']
    assert report['arms']['corrected']['status_counts']=={'PASS':3} and totals['calls']==3 and totals['clarification_calls']==0
    assert report['arms']['corrected']['accuracy_by_category']=={}
    assert not any('previous' in d for d in factory.calls)
    assert all('SYNTH_' not in json.dumps(d) for d in factory.calls)  # No control-name/expected-label leakage.
    assert execute(factory)['arms']['corrected']['totals']['calls']==3 and len(factory.calls)==3
    assert len(list((directory/'corrected/results').rglob('*.json')))==3


def test_global_contradiction_gets_only_one_targeted_clarification(experiment):
    directory,prepared=experiment;comparison.authorize(ROOT,'three',prepared['manifest_sha256'])
    def contradiction(data,value,n):
        if n==1:value['conclusion']='NOT_SUPPORTED__0'
    factory=Factory(contradiction);report=execute(factory)
    assert report['arms']['corrected']['status_counts']=={'PASS':3}
    assert len(factory.calls)==4 and factory.calls[1]['requested_criteria']==['C01','C02','C03','C04','C05']
    assert factory.calls[1]['previous']['conclusion']=='NOT_SUPPORTED__0'
    assert factory.calls[1]['question']['issues']
    assert report['arms']['corrected']['totals']['clarification_calls']==1


def test_missing_criterion_decision_can_be_clarified_without_replacing_others(experiment):
    directory,prepared=experiment;comparison.authorize(ROOT,'three',prepared['manifest_sha256'])
    def missing(data,value,n):
        if n==1:del value['criteria']['C05']
    factory=Factory(missing);report=execute(factory)
    assert report['arms']['corrected']['status_counts']=={'PASS':3}
    assert factory.calls[1]['requested_criteria']==['C05'] and len(factory.calls)==4


def test_missing_conclusion_only_asks_for_that_decision(experiment):
    directory,prepared=experiment;comparison.authorize(ROOT,'three',prepared['manifest_sha256'])
    def missing(data,value,n):
        if n==1:del value['conclusion']
    factory=Factory(missing);report=execute(factory)
    assert report['arms']['corrected']['status_counts']=={'PASS':3} and len(factory.calls)==4
    assert factory.calls[1]['requested_criteria']==[]


def test_clarification_cannot_regenerate_unrelated_criteria(experiment):
    directory,prepared=experiment;comparison.authorize(ROOT,'three',prepared['manifest_sha256'])
    def unrelated(data,value,n):
        if n==1:value['conclusion']='NOT_SUPPORTED__0'
        if n==2:value['criteria']['C99']=deepcopy(data['previous']['criteria']['C01'])
    factory=Factory(unrelated);report=execute(factory)
    assert report['arms']['corrected']['status_counts']=={'BLOCKED':1,'PASS':2} and len(factory.calls)==4


def test_local_context_failure_is_recorded_without_any_inference(experiment,monkeypatch):
    directory,prepared=experiment;comparison.authorize(ROOT,'three',prepared['manifest_sha256'])
    monkeypatch.setattr(m,'INSTRUCTIONS','X'*50000)
    factory=Factory();report=execute(factory)
    assert not factory.calls and report['arms']['corrected']['status_counts']=={'BLOCKED':3}
    assert report['arms']['corrected']['totals']['context_errors']==3
    assert len(list((directory/'corrected/attempts').rglob('budget.failure.json')))==3
    for path in (directory/'corrected/diagnostics').rglob('*.budget.json'):
        diagnostic=s.read(path)
        assert diagnostic['code']=='CONTEXT_TOO_LONG'
        assert diagnostic['this_attempt_dispatched'] is False and not diagnostic['information_removed']
        assert diagnostic['project_count']==1 and diagnostic['model']==MANIFEST['llm']['model']
        assert diagnostic['checks'] and all(not check['fits'] for check in diagnostic['checks'])
        assert all(check['estimated_input_tokens']>check['input_budget'] for check in diagnostic['checks'])
        assert 'prompt' not in diagnostic and 'evidence' not in diagnostic


@pytest.mark.parametrize('project_count',[1,8])
@pytest.mark.parametrize('characters',[200,54000,120000])
def test_context_tiers_preserve_sources_independent_of_project_count(corpus,tmp_path,project_count,characters):
    """Real packing/guards/transport validation, simulated local answers and usage."""
    from autonomous_execution import policy as p
    from autonomous_execution.engine import JobError
    from layer4_evaluation.indicators import context_budget as cb, ollama_provider as transport
    from tests.test_ollama_provider import runtime
    policy=p.validate(s.read(ROOT/'config/autonomous.json'))
    policy['cooldown_seconds']=0
    profiles={iid:profile for iid,profile in list(corpus.profiles.items())[:2]}
    manifest=dict(llm=corpus.settings,policy=policy,profiles=profiles,
        rubrics={iid:corpus.rubrics[iid] for iid in profiles},runtime=runtime(corpus.settings),execution_id='context_test')
    s.write(tmp_path/'manifest.json',manifest)
    calls=[]
    def factory(settings):
        class Client:
            def inspect(self):return runtime(settings)
            def request(self,method,path,payload):
                assert (method,path)==('POST','/api/chat')
                calls.append(payload)
                criteria=payload['format']['properties']['criteria']['properties']
                value=dict(criteria={cid:dict(judgment='NOT_DEMONSTRATED',evidence_ids=[],why='Juicio simulado sin soporte.')
                    for cid in criteria},conclusion='NOT_SUPPORTED__0',why='Respuesta de prueba, no evaluación real.')
                return dict(model=settings['model'],done=True,done_reason='stop',prompt_eval_count=200,eval_count=100,
                    message=dict(content=json.dumps(value)))
        return Client()
    worker=m.MinimalWorker(tmp_path,manifest,client_factory=factory,ram=lambda:100000,sleep=lambda _:None)
    text=('Fuente de prueba con trazabilidad. '*((characters//35)+1))[:characters]
    try:
        for number in range(project_count):
            pid=f'PROJECT_{number}'
            data=dict(project=deepcopy(corpus.project),chunks=deepcopy(corpus.chunks),
                sections=deepcopy(corpus.sections),candidates=[deepcopy(c) for c in corpus.hits if c['indicator_id'] in profiles])
            data['project']['project_id']=pid
            data['project']['fields']['methodology']=text
            data['chunks'][0].update(source_id=pid,text=text,char_end=len(text))
            data['sections'][0].update(source_id=pid,text_original=text)
            for candidate in data['candidates']:candidate['source_id']=pid
            for iid in profiles:
                if characters==120000:
                    with pytest.raises(JobError,match='CONTEXT_TOO_LONG'):worker.evaluate(data,iid,0)
                    diagnostic=s.read(tmp_path/'diagnostics'/pid/iid/'minimal.budget.json')
                    assert len(diagnostic['checks'])==len(policy['tiers'])
                    assert not diagnostic['this_attempt_dispatched'] and not diagnostic['information_removed']
                    assert not (tmp_path/'attempts'/pid/iid/'minimal/1/dispatch.claim.json').exists()
                    continue
                result=worker.evaluate(data,iid,0)
                request=result['request'];registry=result['evidence_registry']
                assert request['prompt'].count(text)==1
                assert len(registry)==1 and next(iter(registry.values()))['project_id']==pid
                assert next(iter(registry.values()))['text']==text
                selected=request['context_selection']['selected'][0]
                assert selected['source_id']==pid and selected['field']=='methodology'
                assert (selected['char_start'],selected['char_end'])==(0,len(text))
                assert not request['context_selection']['omitted']
                assert result['row']['confidence_raw_score']==0
                resources=s.read(tmp_path/'attempts'/pid/iid/'minimal/1/resources.json')
                assert resources['project_count']==resources['fragment_count']==1
                assert resources['context']==(32768 if characters==54000 else 4096)
                assert resources['context_budget_checks'][-1]['fits']
                # The guard accepts equality and rejects one token less, without dispatch.
                schema=m.schema(manifest['rubrics'][iid],registry)
                settings=p.settings(corpus.settings,policy,0)
                tokens=cb.estimate(request['prompt'],schema,settings)['estimated_input_tokens']
                settings['num_ctx']=tokens+settings['num_predict']+settings['context_margin_tokens']
                budget=cb.estimate(request['prompt'],schema,settings)
                assert budget['fits']
                transport.context_guard(request['prompt'],schema,settings,budget=budget)
                settings['num_ctx']-=1
                with pytest.raises(transport.OllamaError,match='CONTEXT_TOO_LONG'):
                    transport.context_guard(request['prompt'],schema,settings,budget=cb.estimate(request['prompt'],schema,settings))
        assert len(calls)==(0 if characters==120000 else project_count*len(profiles))
    finally:worker.close()


def test_uncertain_transport_is_not_repeated_on_resume(experiment):
    from layer4_evaluation.indicators.ollama_provider import OllamaError
    directory,prepared=experiment;comparison.authorize(ROOT,'three',prepared['manifest_sha256'])
    def timeout(data,value,n):
        if n==1:raise OllamaError('TIMEOUT','Interrupcion de transporte simulada.')
    factory=Factory(timeout);report=execute(factory)
    assert report['arms']['corrected']['status_counts']=={'UNCERTAIN':1,'PASS':2} and len(factory.calls)==3
    execute(factory);assert len(factory.calls)==3


@pytest.mark.parametrize('kind',['contradiction','ambiguity'])
def test_unresolved_clarification_blocks_no_third_call_or_false_negative(experiment,kind):
    directory,prepared=experiment;comparison.authorize(ROOT,'three',prepared['manifest_sha256'])
    def bad(data,value,n):
        if n<=2:value['conclusion']='NOT_SUPPORTED__0' if kind=='contradiction' else 'REVIEW_REQUIRED'
    factory=Factory(bad);report=execute(factory)
    assert report['arms']['corrected']['status_counts']=={'BLOCKED':1,'PASS':2}
    assert len(factory.calls)==4 and report['arms']['corrected']['totals']['clarification_calls']==1
    assert not (directory/'corrected/results/SYNTH_DIALOGUE_POSITIVE/ASC-01.json').exists()
    execute(factory);assert len(factory.calls)==4


def test_format_reference_errors_do_not_start_a_repair_chain(experiment):
    directory,prepared=experiment;comparison.authorize(ROOT,'three',prepared['manifest_sha256'])
    def bad(data,value,n):
        if n==1:value['criteria']['C01']['evidence_ids']=['E_INVALID']
    factory=Factory(bad);report=execute(factory)
    assert len(factory.calls)==3 and report['arms']['corrected']['status_counts']=={'BLOCKED':1,'PASS':2}
    assert report['arms']['corrected']['totals']['clarification_calls']==0


def test_completed_transport_recovers_after_result_write_interruption(experiment,monkeypatch):
    directory,prepared=experiment;comparison.authorize(ROOT,'three',prepared['manifest_sha256']);factory=Factory();original=s.write;once=True
    def interrupt(path,value):
        nonlocal once
        if 'results' in Path(path).parts and once:once=False;raise KeyboardInterrupt()
        original(path,value)
    monkeypatch.setattr(s,'write',interrupt)
    with pytest.raises(KeyboardInterrupt):execute(factory)
    assert len(factory.calls)==1
    assert execute(factory)['arms']['corrected']['status_counts']=={'PASS':3} and len(factory.calls)==3


def test_authorized_manifest_changes_are_detected(experiment):
    directory,prepared=experiment;comparison.authorize(ROOT,'three',prepared['manifest_sha256'])
    arm=s.read(directory/'corrected/manifest.json');arm['protocol']['max_calls_per_evaluation']=3;s.write(directory/'corrected/manifest.json',arm)
    with pytest.raises(ValueError,match='INTEGRITY_MISMATCH'):execute(Factory())


@pytest.mark.parametrize('affected',[{'criterion_id':'C01'}, {'criterion_ids':['C01']},
                                   {'criterion_id':'C01','criterion_ids':['C01']}])
def test_question_accepts_existing_diagnostic_identifiers(affected):
    issue=dict(category='DECISION_CRITERIA_INCONSISTENCY',rule='V3_NOT_SUPPORTED:CANNOT_CLAIM_POSITIVE_CONCEPTUAL_SUPPORT',
               path='$.decision',**affected)
    assert m.question(MANIFEST['rubrics']['ECO-01'],{},[issue])==['C01']


@pytest.mark.parametrize('affected',[{'criterion_id':'C99'}, {'criterion_ids':['C01','C99']},
                                   {'criterion_ids':'C01'}, {'criterion_ids':[None]}])
def test_question_rejects_unknown_or_malformed_scope(affected):
    issue=dict(category='DECISION_CRITERIA_INCONSISTENCY',rule='V3_NOT_SUPPORTED:CANNOT_CLAIM_POSITIVE_CONCEPTUAL_SUPPORT',
               path='$.decision',**affected)
    assert m.question(MANIFEST['rubrics']['ECO-01'],{},[issue]) is None


@pytest.mark.parametrize('outcome',['resolved','unrelated','unresolved'])
def test_historical_negative_clarification_scope_end_to_end(tmp_path,monkeypatch,outcome):
    """Replay the actual rejected answer; follow-up answers are offline fixtures, not human labels."""
    monkeypatch.setattr(comparison,'location',lambda root,name:tmp_path/name)
    cid='SYNTH_INCOME_NEGATIVE__ECO-01';pid,iid=cid.split('__')
    prepared=m.prepare(ROOT,'three',case_ids=[cid]);directory=tmp_path/'three'
    outer=comparison.verify(ROOT,directory,authorized=False)
    assert outer['cases']==1 and outer['case_ids']==[cid]
    assert comparison.case_inputs(ROOT,directory,outer)==[CASES[cid]]
    previous=historical.require(MINIMAL_V1)/'corrected/attempts'/pid/iid/'minimal/1'
    raw=s.read(previous/'transport'/pid/'attempt_1/response.raw.txt')
    issues=s.read(previous/'diagnosis.json')['issues']
    assert issues[0]['criterion_ids']==['C01'] and m.question(MANIFEST['rubrics'][iid],raw,issues)==['C01']
    comparison.authorize(ROOT,'three',prepared['manifest_sha256'])
    def replay(data,value,n):
        if n==1:value.clear();value.update(deepcopy(raw))
        elif outcome=='unresolved':
            value['criteria']['C01']=deepcopy(raw['criteria']['C01'])
        elif outcome=='unrelated':
            value['criteria']['C02']=deepcopy(raw['criteria']['C02'])
    factory=Factory(replay);report=execute(factory)
    assert len(factory.calls)==2
    clarification=factory.calls[1]
    assert clarification['requested_criteria']==['C01']
    assert clarification['question']['issues']==issues and clarification['previous']==raw
    assert clarification['evidence']==factory.calls[0]['evidence']
    assert len(clarification['evidence'][0]['text'])==279
    attempt=directory/'corrected/attempts'/pid/iid/'clarification/1'
    transport=s.read(attempt/'schema.json')
    assert list(transport['properties']['criteria']['properties'])==['C01']
    assert transport['properties']['criteria']['additionalProperties'] is False
    assert 'NOT_SUPPORTED__0' in transport['properties']['conclusion']['enum']
    assert 'SUPPORTED__3' in transport['properties']['conclusion']['enum']
    assert '"requested_criteria":["C01"]' in s.read(attempt/'step.json')['request']['prompt']
    result=directory/'corrected/results'/pid/(iid+'.json')
    if outcome=='resolved':
        assert report['arms']['corrected']['status_counts']=={'PASS':1}
        bundle=s.read(result);merged=bundle['semantic_answer']
        assert merged['conclusion']=='NOT_SUPPORTED__0'
        assert all(merged['criteria'][c]==raw['criteria'][c] for c in ['C02','C03','C04','C05'])
        assert bundle['evidence_registry']==m.registry(CASES[cid]['data'],iid)
        assert bundle['row']['confidence_raw_score']==0
    else:
        assert report['arms']['corrected']['status_counts']=={'BLOCKED':1} and not result.exists()
        assert s.read(attempt/'diagnosis.json')['issues']
    execute(factory);assert len(factory.calls)==2  # Never a third inference on resume.


@pytest.mark.parametrize('scenario',['validated','review','ambiguity','resources','partial','normalized'])
def test_autonomous_minimal_queue_export_resume(environment,scenario):
    """Real lifecycle/queue/export, fake local model; no experimental executor."""
    import openpyxl
    from autonomous_execution import lifecycle as l
    from tests.test_ollama_provider import runtime
    e=environment
    if scenario=='normalized':
        import hashlib
        import pyarrow as pa
        import pyarrow.parquet as pq
        path=e.run/'workspace/outputs/layer2/knowledge/source_sections.parquet'
        rows=pq.read_table(path).to_pylist();section=rows[0]
        normalized=section['text_original'];original=normalized.replace(' ','\u00a0',1)
        section.update(text_original=original,text_normalized=normalized,
            text_hash_original=hashlib.sha256(original.encode()).hexdigest())
        pq.write_table(pa.Table.from_pylist(rows),path)
    prepared=l.prepare(e.root,e.run,e.policy,evaluator=m.VERSION)
    manifest=s.read(e.directory/'manifest.json')
    if scenario=='resources' and 'resource_wait' not in manifest:
        from autonomous_execution.resource_wait import defaults
        manifest['resource_wait']=defaults();s.write(e.directory/'manifest.json',manifest)
        prepared['manifest_sha256']=s.sha(e.directory/'manifest.json')
    assert manifest['protocol']['max_calls_per_evaluation']==2
    assert not hasattr(l.evaluation_worker(manifest),'repair')
    calls=[]
    def factory(settings):
        class Client:
            def inspect(self):return runtime(settings)
            def request(self,method,path,payload):
                data=json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n',1)[1]);calls.append(data)
                iid=data['indicator']['indicator_id'];rubric=manifest['rubrics'][iid]
                negative=iid==sorted(manifest['profiles'])[0]
                criteria={c['criterion_id']:dict(judgment='NOT_DEMONSTRATED' if negative else
                    'CLEAR__'+sorted(v3.TEMPORAL[c['temporal_requirement']])[0],
                    evidence_ids=[data['evidence'][0]['id']],why='Juicio simulado con referencia a la fuente original.') for c in rubric['criteria']}
                value=dict(criteria=criteria,conclusion='NOT_SUPPORTED__0' if negative else 'SUPPORTED__3',why='Conclusion simulada; no referencia humana.')
                if negative and scenario in ('review','partial'):value['criteria']['C01']['judgment']='PARTIAL__ACTIVITY_EXECUTED'
                if negative and scenario=='partial' and 'previous' in data:value['conclusion']='INSUFFICIENT_EVIDENCE__2'
                if negative and scenario=='ambiguity' and 'previous' not in data:value['conclusion']='REVIEW_REQUIRED'
                if 'previous' in data:value['criteria']={cid:criteria[cid] for cid in data['requested_criteria']}
                return dict(model=settings['model'],done=True,done_reason='stop',prompt_eval_count=200,eval_count=100,message=dict(content=json.dumps(value)))
        return Client()
    l.authorize(e.root,e.run,prepared['manifest_sha256'])
    ram_values=iter([500,2000,2000]) if scenario=='resources' else iter([]);waits=[]
    result=l.execute(e.root,e.run,client_factory=factory,ram=lambda:next(ram_values,100000),sleep=waits.append)
    assert len(calls)==(3 if scenario in ('ambiguity','review','partial') else 2)
    assert result['counts']==({'BLOCKED':1,'PASS':1} if scenario=='review' else {'PASS':2})
    if scenario=='resources':assert waits
    if scenario=='review':
        assert sum('previous' in d for d in calls)==1
        assert l.retry_pending(e.root,e.run)['requeued']==0
    report=l.export(e.root,e.run,partial=scenario=='review')
    book=openpyxl.load_workbook(report['path'],read_only=True)
    assert book.sheetnames==['INDICADORES','TERRITORIOS']
    rows=list(book['INDICADORES'].values);header=rows[0];rows=[dict(zip(header,r)) for r in rows[1:]]
    decision='INSUFFICIENT_EVIDENCE' if scenario=='partial' else 'NOT_SUPPORTED'
    if scenario=='review':decision='REVIEW_REQUIRED'
    assert len(rows)==2 and {r['estado_cumplimiento'] for r in rows}=={'SUPPORTED',decision}
    negative=next(r for r in rows if r['estado_cumplimiento']==decision)
    if scenario=='partial':
        assert negative['confianza']>0
    else:assert negative['confianza']==(None if scenario=='review' else 0)
    assert negative['ubicacion_evidencia']
    if scenario=='normalized':
        positive=next(r for r in rows if r['estado_cumplimiento']=='SUPPORTED')
        assert 'methods' in positive['fuente_evidencia']
        result=s.read(e.directory/'results/TEST_PROJECT'/('I01.json'))
        assert '\u00a0' in result['wrapper']['assessments'][0]['evidence'][0]['text']
    book.close()
    l.execute(e.root,e.run,client_factory=factory,ram=lambda:100000,sleep=lambda _:None)
    assert len(calls)==(3 if scenario in ('ambiguity','review','partial') else 2)


def test_autonomous_indicator_subset_is_frozen(environment):
    from autonomous_execution import lifecycle as l
    e=environment;ids=[sorted(e.corpus.profiles)[0]]
    prepared=l.prepare(e.root,e.run,e.policy,evaluator=m.VERSION,indicator_ids=ids)
    manifest=s.read(e.directory/'manifest.json')
    assert list(manifest['profiles'])==ids and list(manifest['rubrics'])==ids
    db=s.connect(e.directory)
    try:assert [r[0] for r in db.execute('SELECT iid FROM jobs')]==ids
    finally:db.close()
    l.authorize(e.root,e.run,prepared['manifest_sha256'])
    with pytest.raises(ValueError):l.prepare(e.root,e.run,e.policy,evaluator=m.VERSION,indicator_ids=['UNKNOWN'])


def test_exact_project_indicator_scope_and_readable_export(environment):
    from autonomous_execution import lifecycle as l
    import openpyxl
    e=environment;pairs={'TEST_PROJECT':['I00']}
    prepared=l.prepare(e.root,e.run,e.policy,evaluator=m.VERSION,project_indicators=pairs)
    manifest=l.verify(e.root,e.run,require_authorization=False)
    assert manifest['project_indicators']==pairs and prepared['indicators']==1
    l.authorize(e.root,e.run,prepared['manifest_sha256'])
    report=l.export(e.root,e.run,partial=True)
    assert Path(report['path']).name=='resultado_final.xlsx'
    book=openpyxl.load_workbook(report['path'],read_only=True)
    rows=list(book['INDICADORES'].values)
    assert len(rows)==2 and list(rows[0])==__import__('autonomous_execution.final_output',fromlist=['SHEETS']).SHEETS['INDICADORES']
    record=dict(zip(rows[0],rows[1]));assert record['estado_cumplimiento']=='REVIEW_REQUIRED' and record['confianza'] is None
    book.close()
    db=s.connect(e.directory)
    try:db.execute("UPDATE jobs SET iid='I01'")
    finally:db.close()
    with pytest.raises(ValueError,match='alcance'):l.verify(e.root,e.run,require_authorization=False)


@pytest.mark.parametrize('pid',['PROJ_4636','PROJ_4836','PROJ_5501'])
@pytest.mark.parametrize('iid',['ASC-01','ECO-01','TEC-03'])
def test_institutional_historical_answers_and_mixed_diagnostic_routing(tmp_path,monkeypatch,pid,iid):
    """Read-only historical replay: no accepted result is manufactured from a rejection."""
    import sqlite3
    from autonomous_execution.engine import JobError
    from layer4_evaluation.indicators.validation_diagnostics import semantic_issues
    history=historical.require(COMPACTED_MINIMAL,compacted=True)/'autonomous/main'
    manifest=s.read(history/'manifest.json');source=history/'attempts'/pid/iid/'minimal/1'
    step=s.read(source/'step.json');request=step['request']
    answer=s.read(source/'transport'/pid/'attempt_1/response.raw.txt')
    issues=s.read(source/'diagnosis.json')['issues']
    assert not list(Draft202012Validator(step['schema']).iter_errors(answer))
    sent=s.read(source/'transport'/pid/'attempt_1/request.json')
    assert sent['messages'][0]['content']==request['prompt'] and sent['format']==step['schema']
    assert manifest['prompts']['semantic']==s.read(historical.require(MINIMAL_V1)/'corrected/manifest.json')['prompts']['semantic']
    data=s.read(history/manifest['projects'][pid]['path'])
    connection=sqlite3.connect((history/'candidate_index.sqlite').as_uri()+'?mode=ro',uri=True)
    try:data['candidates']=[json.loads(r[0]) for r in connection.execute("SELECT value FROM rows WHERE kind='candidates' AND pid=?",(pid,))]
    finally:connection.close()
    registry=m.registry(data,iid)
    assert registry==request['evidence_registry']
    new_errors=list(Draft202012Validator(m.schema(manifest['rubrics'][iid],registry)).iter_errors(answer))
    assert not new_errors
    wrapper=m.assemble(data['project'],iid,manifest['rubrics'][iid],registry,answer)
    assessment={k:v for k,v in wrapper['assessments'][0].items() if k!='indicator_id'}
    errors=v3.validate(data['project']['fields'],manifest['profiles'][iid],assessment,manifest['rubrics'][iid])
    assert semantic_issues(errors,assessment,iid,manifest['rubrics'][iid],data['project']['fields'])==issues
    assert {c['criterion_id']:c['support'] for c in assessment['criterion_assessments']}=={
        cid:c['judgment'].split('__')[0] for cid,c in answer['criteria'].items()}
    mixed=(pid,iid)==('PROJ_4636','TEC-03')
    assert len(issues)==(3 if mixed else 1)
    worker=m.MinimalWorker(tmp_path,manifest);calls=[]
    def rejected(project,profile,rubric,name,build,**kwargs):
        # Historical settings are not a new authorization. Exercise packaging
        # within the existing finite tiers, without dispatching an inference.
        settings=m.p.settings(manifest['llm'],manifest['policy'],len(manifest['policy']['tiers'])-1)
        packed,transport=build(settings,1);calls.append(name)
        if name=='clarification':
            selected=sorted({cid for issue in issues for cid in issue.get('criterion_ids',[])} |
                            {issue['criterion_id'] for issue in issues if 'criterion_id' in issue})
            assert packed['semantic_input']['requested_criteria']==selected
            assert set(transport['properties']['criteria']['properties'])==set(selected)
            assert packed['semantic_input']['question']['issues']==issues
            assert 'INSUFFICIENT_EVIDENCE__1/2' in packed['semantic_input']['question']['task']
        folder=tmp_path/'attempts'/pid/iid/name/'1'
        s.write(folder/'step.json',dict(request=packed))
        native=folder/'transport'/pid/'attempt_1'
        s.write(native/'call.json',dict(validation_issues=issues))
        s.write(native/'response.raw.txt',answer)
        raise JobError('INVALID_ASSESSMENT')
    monkeypatch.setattr(worker,'_step',rejected)
    try:
        with pytest.raises(JobError) as exc:worker.evaluate(data,iid,0)
        assert exc.value.code=='CLARIFICATION_UNRESOLVED'
        assert calls==['minimal','clarification']
        assert not (tmp_path/'results').exists()
    finally:worker.close()
