"""Unattended lifecycle and failure simulations. No real models or embeddings."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace

import openpyxl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import run as console
from tests.test_ollama_provider import sample, runtime
from tests.test_context_budget import corpus
from autonomous_execution import lifecycle as l, policy as p, store as s
from autonomous_execution.engine import Worker, JobError
from layer4_evaluation.indicators.ollama_provider import OllamaError

VERIFY_GRAPH=l.verify_graph


@pytest.fixture
def environment(tmp_path,monkeypatch,corpus,sample):
    from scripts import pipeline_coordinator as coordinator
    root=tmp_path;run=root/'outputs/runs/test';run.mkdir(parents=True)
    (root/'run.py').write_text('# synthetic console',encoding='utf-8')
    from autonomous_execution.final_output import template_path
    import shutil
    target=template_path(root);target.parent.mkdir(parents=True)
    shutil.copyfile(template_path(),target)
    # The normal preparation seals its existing authoritative DANE resource.
    real=Path(p.__file__).resolve().parents[2]
    reference=real/'outputs/layer2/reference'
    shutil.copytree(reference,root/'outputs/layer2/reference',ignore=shutil.ignore_patterns('versions'))
    from layer2_processing.checkpoints import locate
    reference_manifest=s.read(reference/'dane_reference_manifest.json')
    original=locate(real/reference_manifest['source_file'])
    target=root/reference_manifest['source_file'];target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(original,target)
    policy=s.read(Path(p.__file__).resolve().parents[2]/'config/autonomous.json')
    policy['cooldown_seconds']=0
    profiles={k:v for k,v in list(corpus.profiles.items())[:2]}
    catalog=dict(profiles=profiles,rubrics={k:corpus.rubrics[k] for k in profiles})
    (root/'data/layer1_sources/base').mkdir(parents=True)
    (root/'data/layer1_sources/incoming').mkdir()
    state=dict(status='PREPARED',raw_path='data/layer1_sources',configuration=dict(llm=corpus.settings),scope_quarantine={})
    s.write(run/'run.json',state)
    s.write(run/'execution.json',dict(selection=dict(mode='projects',files=[]),project_ids=['TEST']))
    s.write(run/'raw_manifest.json',dict(raw='synthetic',files={}))
    s.write(run/'prepared_hashes.json',{})
    monkeypatch.setattr(coordinator,'check',lambda root,run:s.read(run/'run.json'))
    monkeypatch.setattr(coordinator,'scope_projects',lambda *a:['TEST'])
    monkeypatch.setattr(l,'historical',lambda *a:({}, {},runtime(corpus.settings),catalog))
    knowledge=run/'workspace/outputs/layer2/knowledge';knowledge.mkdir(parents=True)
    sections=[dict(row,source_type='PROJECT',document_id='TEST_DOCUMENT') for row in corpus.sections]
    pq.write_table(pa.Table.from_pylist(sections),knowledge/'source_sections.parquet')
    pq.write_table(pa.Table.from_pylist(corpus.chunks),knowledge/'source_chunks.parquet')
    s.write(knowledge/'_manifest.json',dict(synthetic=True))
    canonical=knowledge.parent/'canonical';canonical.mkdir()
    pq.write_table(pa.Table.from_pylist([dict(project_id='TEST_PROJECT',source_project_id='TEST')]),canonical/'proyectos.parquet')
    publication=run/'workspace/outputs/layer3/publication';(publication/'retrieval').mkdir(parents=True)
    s.write(publication/'_manifest.json',dict(synthetic=True))
    pq.write_table(pa.Table.from_pylist(corpus.hits),publication/'retrieval/source_indicator_candidates.parquet')
    import layer3_graphrag.manifest as graph
    monkeypatch.setattr(graph,'validate_publication',lambda *a:None)
    monkeypatch.setattr(l,'verify_graph',lambda *a:dict(synthetic=True))
    monkeypatch.setattr(l,'graph_policy',lambda *a:dict(model='BGE-M3',allow_model_download=False))
    result=l.prepare(root,run,policy)
    return SimpleNamespace(root=root,run=run,directory=l.folder(run),policy=policy,prepared=result,
        sample=sample,corpus=corpus,coordinator=coordinator)


class ClientFactory:
    def __init__(self,sample,behavior=None):
        self.sample=sample;self.behavior=behavior;self.calls=[];self.lock=threading.Lock();self.active=0;self.maximum=0

    def __call__(self,settings):
        factory=self
        class Client:
            def inspect(self):return runtime(settings)
            def request(self,method,path,payload):
                with factory.lock:
                    factory.active+=1;factory.maximum=max(factory.maximum,factory.active)
                    factory.calls.append(payload)
                try:
                    raw=payload['messages'][0]['content'].split('INPUT_JSON:\n',1)[1]
                    data,_=json.JSONDecoder().raw_decode(raw)
                    iid=data['indicators'][0]['indicator_id']
                    a=deepcopy(factory.sample['assessment']);a['indicator_id']=iid
                    if 'requested_criterion_ids' in data:
                        a['criterion_assessments']=[c for c in a['criterion_assessments'] if c['criterion_id'] in data['requested_criterion_ids']]
                    keys=payload['format']['properties']['assessments']['items']['properties']
                    a={k:v for k,v in a.items() if k in keys}
                    result=dict(model=settings['model'],done=True,done_reason='stop',prompt_eval_count=300,eval_count=150,
                        message=dict(content=json.dumps(dict(project_id=data['project']['project_id'],assessments=[a]))))
                    if factory.behavior:factory.behavior(data,payload,result,len(factory.calls))
                    return result
                finally:
                    with factory.lock:factory.active-=1
        return Client()


def authorize(e):
    return l.authorize(e.root,e.run,e.prepared['manifest_sha256'])


def stub_discovery(e,run):
    """Only the local BGE child is replaced; lifecycle scope/binding stay real."""
    old=s.read(e.directory/'manifest.json')
    pairs={'TEST_PROJECT':list(old['profiles'])}
    target=run/'discovery_candidates.parquet'
    pq.write_table(pa.Table.from_pylist([r for r in e.corpus.hits if r['indicator_id'] in old['profiles']]),target)
    audit=dict(project_indicators=pairs,catalog_ids=sorted(old['profiles']),
        comparisons=[dict(project_id=pid,indicator_id=iid,selected=True) for pid,ids in pairs.items() for iid in ids],
        settings=dict(calibration_status='PROVISIONAL_PENDING_HUMAN_REVIEW'),graph_relations=0,
        graph_manifest_sha256=s.sha(run/'workspace/outputs/layer3/publication/_manifest.json'),
        knowledge_manifest_sha256=s.sha(run/'workspace/outputs/layer2/knowledge/_manifest.json'),
        catalog_sha256=l.canonical_hash(dict(profiles=old['profiles'],rubrics=old['rubrics'])),
        candidates_sha256=s.sha(target))
    s.write(run/'discovery.json',audit)
    return audit


def execute(e,factory,**kw):
    return l.execute(e.root,e.run,client_factory=factory,ram=lambda:100000,sleep=lambda _:None,**kw)


def test_manifest_requires_exact_explicit_authorization_once(environment):
    e=environment;factory=ClientFactory(e.sample)
    with pytest.raises(ValueError,match='autorizacion'):execute(e,factory)
    with pytest.raises(ValueError,match='SHA-256'):l.authorize(e.root,e.run,'wrong')
    assert not factory.calls
    authorize(e)
    original=(e.directory/'authorization.json').read_bytes()
    assert execute(e,factory)['status']=='COMPLETE'
    assert len(factory.calls)==2
    assert execute(e,factory)['status']=='COMPLETE' and len(factory.calls)==2
    authorize(e)
    assert (e.directory/'authorization.json').read_bytes()==original


@pytest.mark.parametrize('resource',['territories','template','reference'])
def test_projection_resources_are_pinned_before_authorization(environment,resource):
    e=environment
    from autonomous_execution.final_output import template_path
    manifest=l.verify(e.root,e.run,require_authorization=False)
    assert manifest['final_projection']['filename']=='resultado_final.xlsx'
    assert not (e.directory/'authorization.json').exists()
    paths=dict(territories=e.directory/'territories.json',
        template=template_path(e.root),
        reference=e.root/'outputs/layer2/reference/dane_territories.parquet')
    path=paths[resource]
    assert path.relative_to(e.root).as_posix() in manifest['files']
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='autorizado cambiado'):
        l.authorize(e.root,e.run,e.prepared['manifest_sha256'])
    assert not (e.directory/'authorization.json').exists()


def test_automatic_scope_drives_queue_evidence_and_resume_without_cartesian_product(environment):
    e=environment;audit=stub_discovery(e,e.run)
    audit['project_indicators']={'TEST_PROJECT':['I00']}
    for row in audit['comparisons']:row['selected']=row['indicator_id']=='I00'
    target=e.run/'discovery_candidates.parquet'
    pq.write_table(pa.Table.from_pylist([r for r in e.corpus.hits if r['indicator_id']=='I00']),target)
    audit['candidates_sha256']=s.sha(target);s.write(e.run/'discovery.json',audit)
    e.prepared=l.prepare(e.root,e.run,e.policy,discovery=audit)
    manifest=l.verify(e.root,e.run,require_authorization=False)
    assert len(manifest['profiles'])==2 and manifest['project_indicators']=={'TEST_PROJECT':['I00']}
    assert e.prepared['indicators']==1 and not (e.directory/'authorization.json').exists()
    factory=ClientFactory(e.sample);authorize(e)
    assert execute(e,factory)['evaluated']==1 and len(factory.calls)==1
    assert execute(e,factory)['evaluated']==1 and len(factory.calls)==1
    worker=Worker(e.directory,manifest)
    try:assert {r['indicator_id'] for r in worker.load_project('TEST_PROJECT')['candidates']}=={'I00'}
    finally:worker.close()
    assert Path(l.export(e.root,e.run)['path']).name=='resultado_final.xlsx'


def test_automatic_zero_candidates_preserves_project_without_negative_assessments(environment):
    e=environment;audit=stub_discovery(e,e.run)
    audit['project_indicators']={'TEST_PROJECT':[]}
    for row in audit['comparisons']:row['selected']=False
    target=e.run/'discovery_candidates.parquet'
    pq.write_table(pa.Table.from_pylist([],schema=pa.schema([('source_id',pa.string())])),target)
    audit['candidates_sha256']=s.sha(target);s.write(e.run/'discovery.json',audit)
    e.prepared=l.prepare(e.root,e.run,e.policy,discovery=audit)
    assert e.prepared['indicators']==0
    factory=ClientFactory(e.sample);authorize(e)
    result=execute(e,factory)
    assert result['status']=='COMPLETE' and result['projects_completed']==1
    assert result['indicators_total']==0 and not factory.calls
    report=l.export(e.root,e.run)
    assert report['evaluations']==0 and report['status']=='COMPLETE'


def test_normative_changes_only_evaluator_responsibilities(environment):
    import hashlib
    from layer4_evaluation.indicators import assessment_v3 as v3
    historical = 'Codex es el único intérprete; Python comprobará citas y calculará confianza.'
    local = ('Qwen, mediante Ollama local, realiza la evaluación semántica; '
             'Python valida el contrato y las evidencias y calcula la confianza.')
    assert v3.INSTRUCTIONS.count(historical)==1
    assert p.NORMATIVE.count(local)==1
    assert p.NORMATIVE.replace(local,historical,1)==v3.INSTRUCTIONS
    manifest=s.read(environment.directory/'manifest.json')
    assert manifest['prompts']['normative']==p.NORMATIVE
    assert manifest['prompts']['normative_sha256']==hashlib.sha256(p.NORMATIVE.encode('utf-8')).hexdigest()


def test_incomplete_response_increases_bounded_output_and_keeps_valid_result(environment):
    e=environment
    def length_first(data,payload,result,n):
        if n==1:result.update(done_reason='length',eval_count=payload['options']['num_predict'])
    factory=ClientFactory(e.sample,length_first);authorize(e)
    result=execute(e,factory)
    assert result['status']=='COMPLETE' and result['recovered']==1 and result['calls']==3
    assert factory.calls[1]['options']['num_predict']>factory.calls[0]['options']['num_predict']
    assert all(c['options']['num_ctx']<=e.policy['max_context'] for c in factory.calls)
    assert result['total_tokens']>0


def test_complex_output_shards_all_criteria_then_llm_decides(environment):
    e=environment
    def force_split(data,payload,result,n):
        keys=payload['format']['properties']['assessments']['items']['properties']
        if 'decision' in keys and 'criterion_assessments' in keys:
            result.update(done_reason='length',eval_count=payload['options']['num_predict'])
    factory=ClientFactory(e.sample,force_split);authorize(e)
    result=execute(e,factory)
    assert result['status']=='COMPLETE'
    for path in (e.directory/'results').rglob('*.json'):
        item=s.read(path)['wrapper']['assessments'][0]
        assert sorted(c['criterion_id'] for c in item['criterion_assessments'])==['C01','C02','C03','C04']
        assert item['decision']=='SUPPORTED'
    assert len(factory.calls)<=2*(2+2*2+2)


def test_invalid_evidence_remains_blocked_and_other_indicator_continues(environment):
    e=environment
    def fabricated(data,payload,result,n):
        if data['indicators'][0]['indicator_id']=='I00':
            wrapper=json.loads(result['message']['content'])
            if 'evidence' in wrapper['assessments'][0]:
                wrapper['assessments'][0]['evidence'][0]['text']='Fabricated source'
            result['message']['content']=json.dumps(wrapper)
    factory=ClientFactory(e.sample,fabricated);authorize(e)
    result=execute(e,factory)
    assert result['blocked']==1 and result['evaluated']==1
    assert not (e.directory/'results/TEST_PROJECT/I00.json').exists()
    assert result['counts']['PASS']==1
    first=len(factory.calls);execute(e,factory);assert len(factory.calls)==first
    assert l.retry_pending(e.root,e.run)['requeued']==1
    execute(e,factory)
    assert l.retry_pending(e.root,e.run)['requeued']==0


@pytest.mark.parametrize('kind',['schema','semantic'])
def test_local_validation_exception_does_not_stop_other_indicators(environment,monkeypatch,kind):
    from jsonschema import ValidationError
    from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError
    e=environment;authorize(e);evaluate=Worker.evaluate
    def isolated(self,data,iid,round_number):
        if iid=='I00':
            if kind=='schema':raise ValidationError('Synthetic invalid assessment')
            raise AssessmentValidationError([dict(category='INVALID_FIELD_VALUE',rule='SYNTHETIC',path='$')])
        return evaluate(self,data,iid,round_number)
    monkeypatch.setattr(Worker,'evaluate',isolated)
    factory=ClientFactory(e.sample);result=execute(e,factory)
    assert result['status']=='PARTIAL' and result['evaluated']==1 and result['blocked']==1
    assert result['projects_processed']==1 and result['projects_completed']==0
    assert result['processing_complete'] and result['results_available'] and len(factory.calls)==1
    original={f:f.read_bytes() for f in (e.directory/'results').rglob('*.json')}
    exported=l.export(e.root,e.run)
    assert exported['exported_rows']==1 and exported['supported']==1 and exported['blocked_assessments']==1
    assert exported['pending_assessments']==0 and exported['status']=='PARTIAL'
    assert all(f.read_bytes()==value for f,value in original.items())
    audit=s.read(Path(exported['path']).with_suffix('.receipt.json'))['evaluations']
    assert next(r for r in audit if r['status']=='BLOCKED')['confidence'] is None


def test_timeout_never_blindly_repeats_and_requires_explicit_uncertain_ack(environment):
    e=environment
    def timeout(data,payload,result,n):
        if n==1:raise OllamaError('TIMEOUT','Synthetic timeout')
    factory=ClientFactory(e.sample,timeout);authorize(e)
    result=execute(e,factory)
    assert result['uncertain']==1 and result['evaluated']==1
    assert len(factory.calls)==2
    assert l.retry_pending(e.root,e.run)['requeued']==0
    assert l.retry_pending(e.root,e.run,acknowledge_uncertain=True)['requeued']==1
    assert execute(e,factory)['status']=='COMPLETE'


def test_crash_after_receipt_recovers_without_repeating_approved_call(environment,monkeypatch):
    e=environment;factory=ClientFactory(e.sample);authorize(e)
    original=Worker.adopt
    flag={'crash':True}
    def crash(self,job,data,**kw):
        if flag['crash'] and (self.directory/'results'/job['pid']/(job['iid']+'.json')).exists():
            flag['crash']=False
            raise KeyboardInterrupt()
        return original(self,job,data,**kw)
    monkeypatch.setattr(Worker,'adopt',crash)
    assert execute(e,factory)['status']=='INTERRUPTED'
    assert len(factory.calls)==1
    assert execute(e,factory)['status']=='COMPLETE'
    assert len(factory.calls)==2


def test_persisted_pass_must_match_manifest_confidence_contract(environment):
    e=environment;factory=ClientFactory(e.sample);authorize(e)
    assert execute(e,factory)['status']=='COMPLETE'
    path=e.directory/'manifest.json';manifest=s.read(path)
    # A synthetic checkpoint cannot reinterpret a V3 PASS as the newer SK contract.
    from layer4_evaluation.indicators import assessment_v3 as v3
    manifest.update(schema_version=v3.SK_VERSION,confidence_version=v3.SK_CONFIDENCE_VERSION)
    s.write(path,manifest)
    with pytest.raises((ValueError,JobError),match='CONTRACT'):
        l.verify(e.root,e.run,require_authorization=False)
    assert len(factory.calls)==2


@pytest.mark.parametrize('field,value',[
    ('assessment_version','ASSESSMENT_V2'),('confidence_version','RAW_CONFIDENCE_V1'),
    ('confidence_version','EVIDENCE_CONFIDENCE_SK_V1'),('conceptual_coverage_version','OTHER_K')])
def test_result_contract_rejects_old_score_or_components_without_recalculation(sample,field,value):
    from autonomous_execution.engine import check_result_contract
    from layer4_evaluation.indicators import assessment_v3 as v3
    project=dict(project_id='SYNTH',fields=sample['fields'])
    row=v3.indicator_row(project,sample['profile'],sample['assessment'],sample['rubric'])
    bundle=dict(row=row,wrapper=dict(assessments=[deepcopy(sample['assessment'])]))
    check_result_contract(dict(schema_version=v3.VERSION),bundle)
    bundle['row'][field]=value;original=deepcopy(bundle)
    with pytest.raises(JobError,match='RESULT_CONTRACT_INCOMPATIBLE'):
        check_result_contract(dict(schema_version=v3.VERSION),bundle)
    assert bundle==original


def test_repeated_resume_preserves_pass_bytes_and_counts_progress_separately(environment):
    e=environment;factory=ClientFactory(e.sample);authorize(e)
    assert execute(e,factory)['status']=='COMPLETE'
    protected={p:p.read_bytes() for folder in ('results','attempts') for p in (e.directory/folder).rglob('*') if p.is_file()}
    def forbidden(*args):pytest.fail('Completed PASS must not contact a model')
    for _ in range(2):
        state=execute(e,forbidden)
        assert state['status']=='COMPLETE' and state['evaluated']==2 and state['calls']==2
    assert len(factory.calls)==2
    assert all(path.read_bytes()==content for path,content in protected.items())
    db=s.connect(e.directory)
    try:
        assert db.execute("SELECT COUNT(*) FROM jobs WHERE status='PASS'").fetchone()[0]==2
        assert db.execute("SELECT COUNT(*) FROM events WHERE code='RESUMED'").fetchone()[0]==3
        assert db.execute("SELECT COUNT(*) FROM events WHERE code='PASS'").fetchone()[0]==2
    finally:db.close()


def test_restart_with_inflight_claim_blocks_uncertain_and_continues(environment,monkeypatch):
    e=environment;factory=ClientFactory(e.sample);authorize(e)
    original=s.write
    def crash(path,value):
        original(path,value)
        if Path(path).name=='dispatch.claim.json':raise KeyboardInterrupt()
    monkeypatch.setattr(s,'write',crash)
    assert execute(e,factory)['status']=='INTERRUPTED'
    assert not factory.calls
    monkeypatch.setattr(s,'write',original)
    result=execute(e,factory)
    assert result['uncertain']==1 and result['evaluated']==1 and len(factory.calls)==1


def test_memory_floor_pauses_without_inference(environment,monkeypatch):
    from autonomous_execution import resource_wait
    e=environment;manifest=s.read(e.directory/'manifest.json')
    manifest['resource_wait']['max_wait_seconds']=60;s.write(e.directory/'manifest.json',manifest)
    e.prepared['manifest_sha256']=s.sha(e.directory/'manifest.json')
    authorize(e);factory=ClientFactory(e.sample);clock=[0]
    monkeypatch.setattr(resource_wait,'time',SimpleNamespace(time=lambda:clock[0]))
    result=l.execute(e.root,e.run,client_factory=factory,ram=lambda:0,sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    assert result['blocked']==0 and result['pending']==2 and not factory.calls
    assert result['status']=='WAITING_RESOURCES' and result['waiting_resources']==1


def test_partial_export_separates_verified_pass_and_unvalidated_pending(environment):
    e=environment;authorize(e)
    from layer4_evaluation.thesis_output import COLUMNS,SHEETS
    def fail(data,payload,result,n):
        if n==1:raise OllamaError('TIMEOUT','Synthetic timeout')
    execute(e,ClientFactory(e.sample,fail))
    saved={p:p.read_bytes() for p in (e.directory/'results').rglob('*.json')}
    before=s.status(e.directory)
    assert l.export(e.root,e.run)['status']=='PARTIAL'
    result=l.export(e.root,e.run,partial=True)
    book=openpyxl.load_workbook(result['path'],read_only=True)
    try:
        assert book.sheetnames==SHEETS
        rows=list(book['Proyectos'].values)
        assert list(rows[0])==COLUMNS and len(rows)==2
        record=dict(zip(rows[0],rows[1]))
        assert record['estado_cumplimiento']=='SUPPORTED'
        assert isinstance(record['confianza'],(float,int))
        assert list(book[SHEETS[1]].values)==[tuple(COLUMNS)]
    finally:book.close()
    audit=s.read(Path(result['path']).with_suffix('.receipt.json'))['evaluations']
    assert sum(r['status']=='PASS' for r in audit)==1
    pending=next(r for r in audit if r['status']!='PASS')
    assert pending['status']=='UNCERTAIN' and pending['confidence'] is None
    after=s.status(e.directory)
    assert before['calls']==after['calls'] and before['counts']==after['counts']
    assert all(p.read_bytes()==data for p,data in saved.items())
    assert not (e.run/'resultado_indicadores.autonomous.final.xlsx').exists()


@pytest.mark.parametrize('target',['manifest','source','code','pass'])
def test_changed_approved_scope_or_result_fails_closed(environment,target):
    e=environment;authorize(e);factory=ClientFactory(e.sample)
    if target=='manifest':
        value=s.read(e.directory/'manifest.json');value['llm']['endpoint']='http://external.invalid'
        s.write(e.directory/'manifest.json',value)
    elif target=='source':s.write(e.run/'raw_manifest.json',{'changed':True})
    elif target=='code':(e.root/'run.py').write_text('changed')
    else:
        execute(e,factory);next((e.directory/'results').rglob('*.json')).write_text('{}')
    before=len(factory.calls)
    with pytest.raises(ValueError):execute(e,factory)
    assert len(factory.calls)==before


@pytest.mark.parametrize('changes',[{'workers':3},{'max_context':2048},{'attempts_per_step':100},{'min_free_ram_mb':0}])
def test_resource_policy_is_finite_and_conservative(environment,changes):
    with pytest.raises(ValueError):p.validate(environment.policy|changes)


@pytest.mark.parametrize('selector',[
    ['--projects','A,B'],['--file','incoming/demo.xlsx'],
    ['--file','incoming/demo.xlsx','--projects','A'],['--delivery','demo']])
def test_four_prepare_modes_keep_existing_selection_engine(tmp_path,monkeypatch,selector):
    from autonomous_execution.cli import dispatch
    args=console.parser().parse_args(['prepare','--run-id','new',*selector])
    calls=[]
    coordinator=SimpleNamespace(configuration=lambda *a:({},None,tmp_path/'outputs/runs'),
        find_run=lambda root,runs,name:runs/name,execute_pipeline=lambda *a,**kw:calls.append(kw),
        within=lambda root,name:Path(p.__file__).resolve().parents[2]/name)
    from contextlib import nullcontext
    coordinator.lock=lambda *a:nullcontext()
    monkeypatch.setattr(l,'prepare',lambda *a,**kw:{'status':'REVIEW_REQUIRED'})
    monkeypatch.setattr('autonomous_execution.discovery.prepare',lambda *a:None)
    assert dispatch(tmp_path,args,coordinator)['status']=='REVIEW_REQUIRED'
    assert calls[0]['through']=='knowledge' and calls[0]['confirm'] is None
    assert calls[0]['input_file']==args.input_file and calls[0]['delivery']==args.delivery


def test_authorization_cannot_be_replaced_by_legacy_yes_flag(environment):
    from autonomous_execution.cli import dispatch
    args=console.parser().parse_args(['start','--run-id','test','--authorize-llm'])
    with pytest.raises(ValueError,match='exclusivamente'):dispatch(environment.root,args,environment.coordinator)


def amend_policy(e,**changes):
    manifest=s.read(e.directory/'manifest.json');manifest['policy'].update(changes)
    s.write(e.directory/'manifest.json',manifest)
    e.prepared['manifest_sha256']=s.sha(e.directory/'manifest.json')


def test_two_workers_are_bounded_and_never_claim_same_indicator(environment):
    e=environment
    # Historical two-worker policy remains supported without the new single-
    # worker wait scheduler; the normal autonomous default stays at one worker.
    manifest=s.read(e.directory/'manifest.json');manifest.pop('resource_wait')
    s.write(e.directory/'manifest.json',manifest)
    amend_policy(e,workers=2);authorize(e)
    ready=threading.Barrier(2)
    factory=ClientFactory(e.sample,lambda *a:ready.wait(timeout=10))
    result=execute(e,factory)
    assert result['status']=='COMPLETE' and result['evaluated']==2
    assert factory.maximum==2 and len(factory.calls)==2


def test_oom_pauses_without_increasing_context_or_hiding_failure(environment):
    e=environment;authorize(e)
    def oom(*a):raise OllamaError('OUT_OF_MEMORY','Synthetic OOM')
    factory=ClientFactory(e.sample,oom)
    result=execute(e,factory)
    assert result['status']=='PAUSED' and result['pending']==1 and result['blocked']==1
    assert len(factory.calls)==1 and result['errors']==[{'error':'OUT_OF_MEMORY','evaluations':1}]


def test_known_server_error_retries_with_finite_budget(environment):
    e=environment;authorize(e)
    def temporary(data,payload,result,n):
        if n==1:raise OllamaError('SERVER_ERROR','Synthetic HTTP failure')
    factory=ClientFactory(e.sample,temporary)
    result=execute(e,factory)
    assert result['status']=='COMPLETE' and result['recovered']==1 and len(factory.calls)==3


def test_server_unavailable_before_dispatch_resumes_without_spending_attempt(environment):
    e=environment;authorize(e)
    class Offline:
        def inspect(self):raise OllamaError('SERVER_UNAVAILABLE','Synthetic offline')
    result=execute(e,lambda settings:Offline())
    assert result['status']=='PAUSED' and result['pending']==2 and result['calls']==0
    factory=ClientFactory(e.sample)
    assert execute(e,factory)['status']=='COMPLETE' and len(factory.calls)==2


def test_historical_pass_is_imported_without_repeating_inference(environment,monkeypatch):
    from autonomous_execution.engine import result_row
    e=environment
    manifest=s.read(e.directory/'manifest.json')
    data=s.read(e.directory/'inputs/TEST_PROJECT.json')
    wrapper=dict(project_id='TEST_PROJECT',assessments=[dict(indicator_id='I00',**deepcopy(e.sample['assessment']))])
    row=result_row(data['project'],manifest['profiles']['I00'],manifest['rubrics']['I00'],wrapper)
    from layer4_evaluation.indicators import context_budget as cb
    request=cb.make_request(data['project'],manifest['profiles']['I00'],manifest['rubrics']['I00'],data['project']['fields'])
    accepted={('TEST_PROJECT','I00'):dict(wrapper=wrapper,row=row,request=request,historical=True)}
    monkeypatch.setattr(l,'historical',lambda *a:(accepted,{},runtime(e.corpus.settings),manifest))
    # Simulate a shutdown before manifest publication, without any authorization.
    (e.directory/'manifest.json').rename(e.directory/'manifest.preparing.json')
    e.prepared=l.prepare(e.root,e.run,e.policy)
    assert e.prepared['imported_pass']==1
    assert list((e.run/'autonomous/preparation_history').glob('*/manifest.preparing.json'))
    assert s.status(e.directory)['evaluated']==1
    authorize(e);factory=ClientFactory(e.sample)
    result=execute(e,factory)
    assert result['status']=='COMPLETE' and len(factory.calls)==1


def test_orphan_graph_index_is_archived_and_rebuilt_before_any_dispatch(environment):
    e=environment
    (e.directory/'candidate_staging').mkdir()
    (e.directory/'candidate_staging/source_index.sqlite').write_text('incomplete')
    authorize(e);factory=ClientFactory(e.sample)
    assert execute(e,factory)['status']=='COMPLETE'
    assert list((e.directory/'index_history').glob('*/candidate_staging/source_index.sqlite'))


def test_long_queue_survives_restart_without_a_global_token_or_call_quota(tmp_path):
    directory=tmp_path/'queue';directory.mkdir();db=s.connect(directory)
    with s.transaction(db):
        for project in range(12):
            pid=f'P{project:03}'
            db.execute('INSERT INTO projects VALUES(?,?,?,?)',(pid,pid,'synthetic','hash'))
            for indicator in range(30):
                db.execute("INSERT INTO jobs(pid,iid,status,updated) VALUES(?,?,'PENDING',?)",(pid,f'I{indicator:02}',s.now()))
    def process(limit):
        for _ in range(limit):
            job=s.claim(db)
            if job is None:break
            with s.transaction(db):
                db.execute("UPDATE jobs SET status='PASS' WHERE pid=? AND iid=?",(job['pid'],job['iid']))
                db.execute('INSERT INTO usage VALUES(?,?,?,?,?,?,?,?)',(job['pid'],job['iid'],'synthetic',1,1000,2000,3600,None))
                s.event(db,'evaluation','PASS',job['pid'],job['iid'])
    process(137);db.close()
    checkpoint=s.status(directory)
    assert checkpoint['evaluated']==137 and checkpoint['pending']==223
    db=s.connect(directory);process(1000);db.close()
    final=s.status(directory)
    assert final['status']=='COMPLETE' and final['calls']==360 and final['total_tokens']==1080000
    assert final['wall_seconds']==360*3600 and final['projects_completed']==12


def test_background_launch_is_explicit_authorized_and_has_no_stdin(environment,monkeypatch):
    import subprocess
    e=environment;calls=[]
    def spawn(command,**kwargs):
        calls.append((command,kwargs));return SimpleNamespace(pid=12345)
    monkeypatch.setattr(subprocess,'Popen',spawn)
    with pytest.raises(ValueError,match='autorizacion'):l.background(e.root,e.run)
    authorize(e)
    result=l.background(e.root,e.run)
    assert result['pid']==12345 and calls[0][1]['stdin']==subprocess.DEVNULL
    assert '--non-interactive' in calls[0][0] and '--authorize-llm' not in calls[0][0]


def test_split_synthesis_receives_complete_original_rubric(environment):
    e=environment
    phases=set()
    approved=s.read(e.directory/'manifest.json')['prompts']
    def split(data,payload,result,n):
        keys=payload['format']['properties']['assessments']['items']['properties']
        phase=('shard' if 'requested_criterion_ids' in data else
               'synthesis' if 'criterion_assessments' not in keys else 'normal')
        phases.add(phase)
        suffix=(approved.get('structured_synthesis',approved['synthesis']) if phase=='synthesis' else
                approved.get('concise','')+(approved['shard'] if phase=='shard' else ''))
        assert payload['messages'][0]['content'].split('\nINPUT_JSON:\n',1)[0]==approved['normative']+approved['repair']+suffix
        if 'decision' in keys and 'criterion_assessments' in keys:result['done_reason']='length'
        if 'decision' in keys and 'criterion_assessments' not in keys:
            assert len(data['indicators'][0]['rubric']['criteria'])==4
            assert {c['criterion_id'] for c in data['verified_criterion_assessments']}=={'C01','C02','C03','C04'}
    authorize(e)
    assert execute(e,ClientFactory(e.sample,split))['status']=='COMPLETE'
    assert phases=={'normal','shard','synthesis'}


def test_transport_completed_before_crash_is_recovered_offline(environment,monkeypatch):
    e=environment;authorize(e);factory=ClientFactory(e.sample)
    original=Worker.evaluate;flag={'crash':True}
    def interrupted(self,*args):
        result=original(self,*args)
        if flag['crash']:
            flag['crash']=False;raise KeyboardInterrupt()
        return result
    monkeypatch.setattr(Worker,'evaluate',interrupted)
    assert execute(e,factory)['status']=='INTERRUPTED'
    assert len(factory.calls)==1
    assert execute(e,factory)['status']=='COMPLETE' and len(factory.calls)==2


def test_new_source_inside_approved_directory_stops_without_inference(environment):
    e=environment;authorize(e);factory=ClientFactory(e.sample)
    (e.root/'data/layer1_sources/base/new.json').write_text('{}')
    with pytest.raises(ValueError,match='Fuentes agregadas'):execute(e,factory)
    assert not factory.calls


def test_status_reports_integrity_error_and_retains_coverage(environment):
    from autonomous_execution.cli import dispatch
    e=environment
    (e.root/'data/layer1_sources/base/new.json').write_text('{}')
    args=console.parser().parse_args(['status','--autonomous','--run-id','test'])
    monkey_config=lambda *a:({},None,e.run.parent)
    stub=SimpleNamespace(configuration=monkey_config,find_run=lambda *a:e.run)
    result=dispatch(e.root,args,stub)
    assert result['status']=='BLOCKED_INTEGRITY' and result['pending']==2


def test_process_identity_marks_abandoned_running_checkpoint_interrupted(tmp_path):
    directory=tmp_path/'queue';directory.mkdir();db=s.connect(directory)
    db.execute("INSERT INTO projects VALUES('P','P','p','h')")
    db.execute("INSERT INTO jobs(pid,iid,status) VALUES('P','I','RUNNING')");db.close()
    s.write(directory/'worker.json',dict(pid=4294967294,creation='dead',state='RUNNING'))
    assert s.status(directory)['status']=='INTERRUPTED'


def test_metadata_transient_errors_retry_without_dispatch_duplication(environment):
    e=environment;authorize(e);factory=ClientFactory(e.sample);failures={'remaining':2}
    def flaky(settings):
        client=factory(settings);original=client.inspect
        def inspect():
            if failures['remaining']:
                failures['remaining']-=1;raise OllamaError('SERVER_UNAVAILABLE','Synthetic metadata outage')
            return original()
        client.inspect=inspect;return client
    assert execute(e,flaky)['status']=='COMPLETE' and len(factory.calls)==2


@pytest.mark.parametrize('message',[
    'model requires more system memory (7 GiB) than is available (4 GiB)',
    'insufficient VRAM','failed to allocate a tensor','out of memory'])
def test_ollama_memory_messages_are_never_retried_as_generic_server_errors(message):
    from autonomous_execution.transport import classify
    assert classify(500,message).code=='OUT_OF_MEMORY'


def test_synthesis_cannot_accept_a_decision_inconsistent_with_verified_criteria(environment):
    e=environment;authorize(e)
    def wrong(data,payload,result,n):
        if data['indicators'][0]['indicator_id']!='I00':return
        keys=payload['format']['properties']['assessments']['items']['properties']
        if 'decision' in keys and 'criterion_assessments' in keys:
            result['done_reason']='length'
        elif 'decision' in keys:
            wrapper=json.loads(result['message']['content'])
            wrapper['assessments'][0].update(decision='NOT_SUPPORTED',support_strength=0)
            result['message']['content']=json.dumps(wrapper)
    result=execute(e,ClientFactory(e.sample,wrong))
    assert result['blocked']==1 and result['evaluated']==1
    assert not (e.directory/'results/TEST_PROJECT/I00.json').exists()


def test_file_inventory_stays_isolated_while_delivery_watches_new_files(tmp_path):
    from autonomous_execution import scope
    root=tmp_path;delivery=root/'data/layer1_sources/incoming/demo';delivery.mkdir(parents=True)
    (delivery/'one.json').write_text('{}')
    state=dict(raw_path='data/layer1_sources',configuration=dict(source_paths=['incoming/demo/one.json']))
    file_scope=scope.inventory(root,state,dict(mode='file'))
    delivery_scope=scope.inventory(root,state,dict(mode='delivery'))
    (delivery/'two.json').write_text('{}')
    scope.check(root,file_scope)
    with pytest.raises(ValueError,match='Fuentes agregadas'):scope.check(root,delivery_scope)


def test_existing_graph_is_bound_to_knowledge_and_bge_without_encoding(environment,monkeypatch):
    import layer3_graphrag.configuration as config
    import layer3_graphrag.embeddings as embeddings
    import layer3_graphrag.manifest as graph
    e=environment
    s.write(e.run/'workspace/outputs/layer2/knowledge/_manifest.json',{'synthetic':True})
    lazy=SimpleNamespace(_model=None)
    monkeypatch.setattr(config,'load_config',lambda *a:({'embeddings':{}},'config'))
    monkeypatch.setattr(embeddings,'create_provider',lambda *a:lazy)
    monkeypatch.setattr(embeddings,'embedding_config_hash',lambda *a:'BGE')
    monkeypatch.setattr(graph,'validate_publication',lambda path,expected:dict(embedding_config_hash='BGE',candidate_architecture='SOURCE_INDICATOR_V1'))
    assert VERIFY_GRAPH(e.run)['embedding_config_hash']=='BGE' and lazy._model is None
    monkeypatch.setattr(embeddings,'embedding_config_hash',lambda *a:'OTHER')
    with pytest.raises(ValueError,match='BGE-M3'):VERIFY_GRAPH(e.run)


def test_new_graph_build_uses_authorized_short_lived_process(environment,monkeypatch):
    import subprocess
    e=environment;calls=[]
    monkeypatch.setattr(subprocess,'run',lambda command,**kw:calls.append((command,kw)) or SimpleNamespace(returncode=0))
    with pytest.raises(ValueError,match='autorizacion'):l.build_graph(e.root,e.run)
    authorize(e);l.build_graph(e.root,e.run)
    assert len(calls)==1 and 'graph_worker.py' in calls[0][0][1]
    assert '--manifest-sha256' in calls[0][0] and calls[0][1]['stdin']==subprocess.DEVNULL


def test_unsigned_review_refresh_preserves_old_bytes_and_needs_new_hash(environment):
    e=environment;before=(e.directory/'manifest.json').read_bytes()
    changed=e.policy|dict(workers=2)
    result=l.prepare(e.root,e.run,changed)
    archived=list((e.run/'autonomous/preparation_history').glob('*/manifest.json'))
    assert archived and archived[0].read_bytes()==before
    assert result['manifest_sha256']!=e.prepared['manifest_sha256']
    assert not (e.directory/'authorization.json').exists()
    l.authorize(e.root,e.run,result['manifest_sha256'])
    with pytest.raises(ValueError,match='ya autorizada'):l.prepare(e.root,e.run,e.policy)
