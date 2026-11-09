"""Phase-one contracts and historical replay. No Ollama or embeddings."""
from copy import deepcopy
import json
from pathlib import Path
import csv

import pytest
from autonomous_execution import policy as p, phase1, comparison, store as s
from autonomous_execution.engine import gate
from layer4_evaluation.indicators import assessment_v3 as v3, context_budget as cb
from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError
from layer4_evaluation.indicators.selection import canonical_hash
from tests.test_autonomous_execution import environment, ClientFactory, authorize, execute
from tests.test_ollama_provider import sample
from tests.test_context_budget import corpus

ROOT=Path(__file__).resolve().parents[1]
HIST=ROOT/'outputs/runs'/comparison.HISTORY/'autonomous/main'


def history_shards(pid,iid):
    m=s.read(HIST/'manifest.json');data=s.read(HIST/m['projects'][pid]['path'])
    judgments=[];evidence=[];requests=[]
    for offset in range(0,len(m['rubrics'][iid]['criteria']),3):
        folder=HIST/'attempts'/pid/iid/('r0_shard_'+str(offset))
        accepted=[]
        for path in folder.glob('*/transport/*/attempt_1/call.json'):
            if s.read(path)['exit_status']==0:accepted.append(path)
        call=sorted(accepted)[-1];step=call.parents[3]/'step.json'
        request=s.read(step)['request'];item=s.read(call.parent/'response.json')['assessments'][0]
        base=len(evidence);evidence+=item['evidence']
        judgments += [{**c,'evidence_indices':[i+base for i in c['evidence_indices']]} for c in item['criterion_assessments']]
        requests.append(request)
    return m,data,judgments,evidence,requests


@pytest.mark.parametrize('mutation',['stage','orientation','quote','index','missing','duplicate','unsupported_quote'])
def test_criterion_contract_rejects_same_invalid_support_in_shard_and_final(sample,mutation):
    f=deepcopy(sample['fields']);a=deepcopy(sample['assessment']);r=sample['rubric'];profile=sample['profile']
    if mutation=='stage':a['evidence'][0]['stage']='RESULT_EXPECTED'
    if mutation=='orientation':f['title']=a['evidence'][0]['text'];a['evidence'][0]['field']='title'
    if mutation=='quote':a['evidence'][0]['text']='No existe esta evidencia.'
    if mutation=='index':a['criterion_assessments'][0]['evidence_indices']=[99]
    if mutation=='missing':a['criterion_assessments'].pop()
    if mutation=='duplicate':a['criterion_assessments'][1]=deepcopy(a['criterion_assessments'][0])
    if mutation=='unsupported_quote':a['criterion_assessments'][0]['support']='NOT_DEMONSTRATED'
    ids=[c['criterion_id'] for c in r['criteria']]
    assert v3.validate_criteria(f,profile,a,r,ids)
    assert v3.validate(f,profile,a,r)


def test_valid_positive_partial_and_negative_contracts(sample):
    a=deepcopy(sample['assessment']);ids=[c['criterion_id'] for c in sample['rubric']['criteria']]
    for support in ('CLEAR','PARTIAL','NOT_DEMONSTRATED'):
        b=deepcopy(a)
        for c in b['criterion_assessments']:
            if c['support']=='CLEAR':c.update(support=support,evidence_indices=[] if support=='NOT_DEMONSTRATED' else [0])
        assert not v3.validate_criteria(sample['fields'],sample['profile'],b,sample['rubric'],ids)


def test_historical_tec03_shards_are_rejected_before_synthesis():
    m,data,j,e,requests=history_shards('PROJ_5501','TEC-03')
    ids=[c['criterion_id'] for c in j]
    issues=v3.validate_criteria(data['project']['fields'],m['profiles']['TEC-03'],dict(criterion_assessments=j,evidence=e),m['rubrics']['TEC-03'],ids)
    assert issues.count('V3_CRITERION:CLEAR_REQUIRES_COMPATIBLE_SUBSTANTIVE_EVIDENCE')==4
    from layer4_evaluation.indicators.validation_diagnostics import semantic_issues
    details=semantic_issues(issues,dict(criterion_assessments=j,evidence=e),'TEC-03',m['rubrics']['TEC-03'],data['project']['fields'])
    assert {i['criterion_id'] for i in details}=={'C01','C02','C03','C04'}
    assert all('.support' in i['path'] for i in details)


@pytest.mark.parametrize('pid,iid',comparison.REAL[:8])
def test_all_eight_historical_synthesis_ledgers_fit_and_preserve_sources(pid,iid):
    m,data,j,e,requests=history_shards(pid,iid)
    evidence,judgments=phase1.merge(e,j)
    request=phase1.synthesis(data['project'],m['profiles'][iid],m['rubrics'][iid],requests,judgments,evidence)
    policy=s.read(ROOT/'config/autonomous.json');schema=p.schema(data['project']['fields'],policy,decision_only=True)
    settings=p.settings(m['llm'],policy,2,decision_only=True)
    assert cb.estimate(request['prompt'],schema,settings)['fits']
    assert settings['num_predict']==512
    payload=request['payload'];spans={span['id']:span for span in payload['source_spans']}
    assert [c['criterion_id'] for c in payload['verified_criterion_assessments']]==[c['criterion_id'] for c in judgments]
    assert all('explanation' not in c for c in payload['verified_criterion_assessments'])
    for original,ref in zip(evidence,payload['verified_evidence']):
        assert spans[ref['source_span']]['text'][ref['start']:ref['end']]==original['text']
        assert ref['stage']==original['stage']
    for original in requests:
        for field,text in original['payload']['project']['fields'].items():
            if text:assert any(text in span['text'] for span in spans.values() if span['field']==field)


def test_exact_evidence_deduplication_keeps_distinct_stages():
    e=[dict(field='summary',text='Literal.',stage=stage) for stage in ('CONTEXT','CONTEXT','RESULT_EXPECTED')]
    j=[dict(criterion_id='C01',support='PARTIAL',explanation='Motivo.',evidence_indices=[0,1,2])]
    unique,items=phase1.merge(e,j)
    assert len(unique)==2 and items[0]['evidence_indices']==[0,1]
    assert e[1]==e[0] and j[0]['evidence_indices']==[0,1,2]


def test_budget_inputs_grow_and_synthesis_has_separate_output():
    policy=p.validate(s.read(ROOT/'config/autonomous.json'))
    inputs=[p.settings({},policy,i)['num_ctx']-p.settings({},policy,i)['num_predict']-policy['context_margin_tokens'] for i in range(3)]
    assert inputs==[2304,3840,5376]
    assert [cb.estimate('',{},p.settings({},policy,i,decision_only=True))['input_budget'] for i in range(3)]==[2816,4864,6912]
    invalid=deepcopy(policy);invalid['tiers']=invalid['tiers'][:3];invalid['tiers'][2]['num_predict']=4096
    with pytest.raises(ValueError,match='efectivo'):p.validate(invalid)
    old=s.read(HIST/'manifest.json')['policy'];assert p.validate(old)==old


def test_targeted_repair_preserves_evidence_and_avoids_context_escalation(environment):
    e=environment
    def bad_first(data,payload,result,n):
        if n==1:
            raw=json.loads(result['message']['content']);raw['assessments'][0]['evidence'][0]['stage']='RESULT_EXPECTED'
            result['message']['content']=json.dumps(raw)
    factory=ClientFactory(e.sample,bad_first);authorize(e)
    assert execute(e,factory)['status']=='COMPLETE'
    assert 'REPARACION DEL CONTRATO' in factory.calls[1]['messages'][0]['content']
    assert factory.calls[0]['options']['num_ctx']==factory.calls[1]['options']['num_ctx']
    assert 'Juicio sintético' not in factory.calls[1]['messages'][0]['content']


def test_no_invalid_shard_reaches_decision_synthesis(environment):
    e=environment;seen=[]
    def bad_shard(data,payload,result,n):
        keys=payload['format']['properties']['assessments']['items']['properties']
        if 'criterion_assessments' in keys and 'decision' in keys:result['done_reason']='length'
        if 'requested_criterion_ids' in data:
            raw=json.loads(result['message']['content']);raw['assessments'][0]['evidence'][0]['stage']='RESULT_EXPECTED'
            result['message']['content']=json.dumps(raw)
        if 'criterion_assessments' not in keys:seen.append('synthesis')
    authorize(e);result=execute(e,ClientFactory(e.sample,bad_shard))
    assert result['blocked']==2 and not seen


def test_sharded_export_keeps_brief_explanation_and_archives_literal_evidence(environment):
    from autonomous_execution import lifecycle as l
    from openpyxl import load_workbook
    e=environment
    def split(data,payload,result,n):
        keys=payload['format']['properties']['assessments']['items']['properties']
        if 'decision' in keys and 'criterion_assessments' in keys:result['done_reason']='length'
    authorize(e);assert execute(e,ClientFactory(e.sample,split))['status']=='COMPLETE'
    exported=l.export(e.root,e.run)
    book=load_workbook(exported['path'],read_only=True)
    rows=list(book['INDICADORES'].values)[1:];book.close()
    assert len(rows)==2 and all(row[6] for row in rows)
    results=list((e.directory/'results').glob('*/*.json'))
    assert len(results)==2
    for path in results:
        assessment=s.read(path)['wrapper']['assessments'][0]
        assert e.sample['assessment']['evidence'][0]['text'] in [item['text'] for item in assessment['evidence']]


def test_irreducible_synthesis_budget_fails_closed_with_receipt(environment):
    from autonomous_execution.engine import Worker, JobError
    e=environment;manifest=s.read(e.directory/'manifest.json');data=s.read(e.directory/'inputs/TEST_PROJECT.json')
    factory=ClientFactory(e.sample);worker=Worker(e.directory,manifest,client_factory=factory,ram=lambda:100000,sleep=lambda _:None)
    try:
        def build(settings,attempt):return dict(prompt='X'*(e.policy['max_context']*3)),{}
        with pytest.raises(JobError,match='SYNTHESIS_CONTEXT_TOO_LONG'):
            worker._step(data['project'],manifest['profiles']['I00'],manifest['rubrics']['I00'],
                         'oversized_synthesis',build,decision_only=True)
        receipt=s.read(e.directory/'diagnostics/TEST_PROJECT/I00/oversized_synthesis.budget.json')
        assert receipt['information_dropped'] is False and receipt['this_attempt_dispatched'] is False
        assert len(receipt['checks'])==len(e.policy['tiers']) and not factory.calls
    finally:worker.close()


def test_historical_pass_scores_and_all_original_run_bytes_are_preserved():
    from autonomous_execution.engine import result_row
    m=s.read(HIST/'manifest.json');count=0
    for path in (HIST/'results').glob('*/*.json'):
        pid=path.parent.name;iid=path.stem;bundle=s.read(path);project=s.read(HIST/m['projects'][pid]['path'])['project']
        assert result_row(project,m['profiles'][iid],m['rubrics'][iid],bundle['wrapper'])==bundle['row']
        count+=1
    assert count==136
    protected=s.read(ROOT/'outputs/runs'/comparison.HISTORY/'protected_before.json')
    assert all(s.sha(ROOT/name)==digest for name,digest in protected.items())


@pytest.fixture
def experiment(tmp_path,monkeypatch):
    monkeypatch.setattr(comparison,'location',lambda root,name:tmp_path/name)
    result=comparison.prepare(ROOT,'panel')
    return tmp_path/'panel',result


def test_panel_exact_scope_labels_and_authorization_integrity(experiment):
    directory,result=experiment;cases=s.read(directory/'assets/cases.json')
    assert len(cases)==20 and sum(c['origin']=='SYNTHETIC_CONTROL' for c in cases)==4
    assert all(c['reference']==dict(status='PENDING_HUMAN_REVIEW',decision=None) for c in cases)
    with pytest.raises(ValueError,match='autorizacion'):comparison.verify(ROOT,directory)
    with pytest.raises(ValueError,match='SHA-256'):comparison.authorize(ROOT,'panel','wrong')
    comparison.authorize(ROOT,'panel',result['manifest_sha256'])
    receipt=(directory/'authorization.json').read_bytes()
    comparison.authorize(ROOT,'panel',result['manifest_sha256']);assert (directory/'authorization.json').read_bytes()==receipt
    s.write(directory/'assets/cases.json',[])
    with pytest.raises(ValueError,match='INTEGRITY_MISMATCH'):comparison.verify(ROOT,directory)


def test_comparison_simulated_integration_resume_and_pending_labels(experiment):
    directory,result=experiment
    # Mock payloads exercise the complete 20-case scheduler, not semantic accuracy.
    runtime=s.read(directory/'corrected/manifest.json')['runtime'];calls=[]
    class Client:
        def __init__(self,settings):self.settings=settings
        def inspect(self):return runtime|dict(configuration=self.settings,configuration_sha256=canonical_hash(self.settings))
        def request(self,method,path,payload):
            calls.append(payload);text=payload['messages'][0]['content'].split('INPUT_JSON:\n',1)[1]
            data,_=json.JSONDecoder().raw_decode(text)
            item=dict(indicator_id=data['indicators'][0]['indicator_id'],assessment_version=v3.VERSION,
                decision='NOT_SUPPORTED',support_strength=0,explanation='Respuesta negativa del cliente simulado.',evidence=[],
                criterion_assessments=[dict(criterion_id=c['criterion_id'],support='NOT_DEMONSTRATED',evidence_indices=[],explanation='Sin soporte en esta simulacion.') for c in data['indicators'][0]['rubric']['criteria']])
            keys=payload['format']['properties']['assessments']['items']['properties'];item={k:v for k,v in item.items() if k in keys}
            return dict(model=self.settings['model'],done=True,done_reason='stop',prompt_eval_count=100,eval_count=100,
                message=dict(content=json.dumps(dict(project_id=data['project']['project_id'],assessments=[item]))))
    comparison.authorize(ROOT,'panel',result['manifest_sha256'])
    result=comparison.execute(ROOT,'panel','corrected',client_factory=Client,ram=lambda:100000,sleep=lambda _:None)
    assert result['arms']['corrected']['totals']['calls']==20
    assert result['arms']['corrected']['accuracy_by_category']=={}
    assert result['arms']['corrected']['totals']['accepted_shard_contract_violations']==0
    count=len(calls);comparison.execute(ROOT,'panel','corrected',client_factory=Client,ram=lambda:100000,sleep=lambda _:None)
    assert len(calls)==count
    with (directory/'human.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['case_id','status','decision','reviewer','reviewed_at']);writer.writeheader()
        writer.writerow(dict(case_id=comparison.REAL[0][0]+'__'+comparison.REAL[0][1],status='APPROVED_HUMAN_REVIEW',decision='SUPPORTED',reviewer='Synthetic test reviewer',reviewed_at=s.now()))
    result=comparison.metrics(ROOT,'panel',directory/'human.csv')
    assert result['arms']['corrected']['accuracy_by_category']['SUPPORTED']['accuracy']==0
