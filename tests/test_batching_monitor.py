"""No inference: batching, independent evidence, recovery, costs and read-only status."""
from copy import deepcopy
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest
from autonomous_execution import batching as b, minimal as m, store as s, monitor
from layer4_evaluation.indicators.selection import canonical_hash
from tests.test_minimal_evaluation import CASES,MANIFEST,answer as positive_answer


@pytest.fixture
def batch(tmp_path):
    case=deepcopy(CASES['SYNTH_INCOME_POSITIVE__ECO-01']);data=case['data'];iid=case['indicator_id']
    other='ECO-99';profile=deepcopy(MANIFEST['profiles'][iid]);rubric=deepcopy(MANIFEST['rubrics'][iid])
    profile['indicator_id']=other;rubric['indicator_id']=other
    rubric['profile_sha256']=canonical_hash(profile)
    rubric.pop('rubric_sha256');rubric['rubric_sha256']=canonical_hash(rubric)
    data['candidates']+=[dict(c,indicator_id=other) for c in data['candidates'] if c['indicator_id']==iid]
    policy=s.read(Path(__file__).resolve().parents[1]/'config/autonomous.json');policy['cooldown_seconds']=0
    manifest=dict(execution_id='synthetic',repository_root=str(tmp_path),policy=policy,llm=MANIFEST['llm'],
        runtime=MANIFEST['runtime'],profiles={iid:MANIFEST['profiles'][iid],other:profile},
        rubrics={iid:MANIFEST['rubrics'][iid],other:rubric},batching=dict(size=2),projects={})
    from tokenizers import Tokenizer,models,pre_tokenizers
    tokenizer=Tokenizer(models.WordLevel({'[UNK]':0},unk_token='[UNK]'));tokenizer.pre_tokenizer=pre_tokenizers.Whitespace()
    tokenizer_path=tmp_path/'synthetic-tokenizer.json';tokenizer.save(str(tokenizer_path))
    manifest['batching'].update(context_margin_tokens=300,tokenizer=dict(path=str(tokenizer_path),sha256=s.sha(tokenizer_path),
        template_tokens=12,model_digest=manifest['runtime']['digest'],model_metadata_sha256=manifest['runtime']['model_metadata_sha256']))
    s.write(tmp_path/'manifest.json',manifest)
    db=s.connect(tmp_path);pid=data['project']['project_id']
    db.execute('INSERT INTO projects VALUES(?,?,?,?)',(pid,'synthetic','',''))
    for member in (iid,other):db.execute('INSERT INTO jobs(pid,iid,status,updated) VALUES(?,?,?,?)',(pid,member,'PENDING',s.now()))
    db.close();calls=[];control={}
    class Factory:
        def __call__(self,settings):
            class Client:
                def inspect(self):return manifest['runtime']|dict(configuration=settings,configuration_sha256=canonical_hash(settings))
                def request(self,method,path,payload):
                    inputs=json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n')[1]);calls.append(inputs)
                    def negative(member):return dict(criteria={c['criterion_id']:dict(judgment='NOT_DEMONSTRATED',evidence_ids=[],why='No demostrado por las fuentes.') for c in manifest['rubrics'][member]['criteria']},conclusion='NOT_SUPPORTED__0',why='No demostrado.')
                    if 'indicators' in inputs:answer={i['indicator_id']:negative(i['indicator_id']) for i in inputs['indicators']}
                    else:
                        member=inputs['indicator']['indicator_id'];answer=negative(member)
                        if 'requested_criteria' in inputs:answer['criteria']={cid:value for cid,value in answer['criteria'].items() if cid in inputs['requested_criteria']}
                        if member in payload['format']['properties']:answer={member:answer}
                    if control.get('interrupt'):raise KeyboardInterrupt()
                    if control.get('bad_member') and len(calls)==1:
                        answer[other]['criteria']['C01']['judgment']='CLEAR__ACTIVITY_EXECUTED'
                    if control.get('malformed_member') and len(calls)==1:
                        answer[other].pop('criteria')
                    if control.get('missing_member') and len(calls)==1:
                        answer.pop(other)
                    return dict(model=settings['model'],done=True,done_reason='stop',prompt_eval_count=300,eval_count=250,message=dict(content=json.dumps(answer)))
            return Client()
    worker=b.BatchWorker(tmp_path,manifest,client_factory=Factory(),ram=lambda:99999,sleep=lambda _:None)
    worker.load_project=lambda pid:data
    return SimpleNamespace(worker=worker,data=data,manifest=manifest,directory=tmp_path,calls=calls,iid=iid,other=other,pid=pid,control=control)


def test_shared_batch_has_full_coverage_one_usage_and_resume_no_call(batch):
    e=batch;e.worker.loop()
    db=s.connect(e.directory)
    assert db.execute("SELECT COUNT(*) FROM jobs WHERE status='PASS'").fetchone()[0]==2
    assert len(e.calls)==1
    assert db.execute('SELECT COUNT(*),SUM(input_tokens),SUM(output_tokens) FROM usage').fetchone()[:]==(1,300,250)
    db.execute("UPDATE jobs SET status='PENDING'");db.close()
    # Crash after durable results but before scheduling commit: adopt without inference.
    w=b.BatchWorker(e.directory,e.manifest,client_factory=lambda _:pytest.fail('No repeat'),ram=lambda:99999)
    w.load_project=lambda pid:e.data;w.loop()
    assert monitor.snapshot(e.directory)['evaluated']==2


def test_budget_does_not_shorten_evidence(batch):
    e=batch;settings=b.p.settings(e.manifest['llm'],e.worker.policy,0)
    items=[b.item_for(e.data,e.manifest,i,settings) for i in (e.iid,e.other)]
    request,schema=b.request_for(items,settings)
    assert request['context_budget']['fits']
    for item in items:
        assert item['evidence']==m.registry(e.data,item['iid'])
        assert item['request']['coverage_receipt']
    assert len(request['semantic_input']['evidence'])==len(items[0]['evidence'])
    assert request['context_budget']['num_ctx']==6144
    e.worker.close()


def test_foreign_evidence_and_missing_indicator_are_rejected(batch):
    e=batch;settings=b.p.settings(e.manifest['llm'],e.worker.policy,0)
    item=b.item_for(e.data,e.manifest,e.iid,settings)
    answer=dict(criteria={c['criterion_id']:dict(judgment='NOT_DEMONSTRATED',evidence_ids=['FOREIGN'],why='No.') for c in item['rubric']['criteria']},conclusion='NOT_SUPPORTED__0',why='No.')
    with pytest.raises(Exception):b.validate_item(e.data,item,answer)
    request,schema=b.request_for([item],settings)
    assert not b.Draft202012Validator(schema).is_valid({})
    e.worker.close()


def test_positive_decisions_keep_independent_evidence_and_confidence(batch):
    e=batch;settings=b.p.settings(e.manifest['llm'],e.worker.policy,0)
    answer=positive_answer(CASES['SYNTH_INCOME_POSITIVE__ECO-01'])
    for member in (e.iid,e.other):
        item=b.item_for(e.data,e.manifest,member,settings)
        result=b.validate_item(e.data,item,deepcopy(answer))
        assert result['row']['confidence_raw_score']==86.25
        assert result['wrapper']['assessments'][0]['indicator_id']==member
        assert all(quote['text'] in e.data['project']['fields'][quote['field']] for quote in result['wrapper']['assessments'][0]['evidence'])
    e.worker.close()


def test_one_invalid_member_preserves_valid_member_and_evaluates_only_remaining(batch):
    e=batch;e.control['bad_member']=True;e.worker.loop()
    result=monitor.snapshot(e.directory)
    assert result['evaluated']==2 and len(e.calls)==2
    assert len(e.calls[0]['indicators'])==2 and 'indicator' in e.calls[1]
    receipt=s.read(next((e.directory/'batch_receipts').rglob('*.json')))
    assert receipt['accepted']==[e.iid] and receipt['fallback']==[e.other]


@pytest.mark.parametrize('failure',['malformed_member','missing_member'])
def test_structural_member_failure_does_not_discard_valid_sibling(batch,failure):
    e=batch;e.control[failure]=True;e.worker.loop()
    result=monitor.snapshot(e.directory)
    assert result['evaluated']==2 and len(e.calls)==2
    assert e.calls[1]['indicator']['indicator_id']==e.other
    receipt=s.read(next((e.directory/'batch_receipts').rglob('*.json')))
    assert receipt['accepted']==[e.iid] and receipt['fallback']==[e.other]
    protected={f:f.read_bytes() for f in (e.directory/'results').rglob('*.json')}
    worker=b.BatchWorker(e.directory,e.manifest,client_factory=lambda _:pytest.fail('No repeat'))
    worker.load_project=lambda pid:e.data;worker.loop()
    assert all(f.read_bytes()==value for f,value in protected.items())


def test_valid_batch_member_can_be_reused_despite_structural_sibling_error(batch):
    import shutil
    from autonomous_execution.preparation_integrity import reusable_result
    e=batch;e.control['malformed_member']=True;e.worker.loop()
    source=e.directory.parent/(e.directory.name+'_reuse')
    shutil.copytree(e.directory,source/'autonomous/main')
    db=s.connect(source/'autonomous/main')
    job=dict(db.execute('SELECT * FROM jobs WHERE iid=?',(e.iid,)).fetchone());db.close()
    bundle,files=reusable_result(source.parent,source,e.manifest,job,e.data)
    assert bundle['row']['assessment_validation_status']=='VALID' and files


def test_shared_clarification_receipt_is_reusable_without_inference(batch):
    import shutil
    from autonomous_execution.preparation_integrity import reusable_result
    e=batch;e.control['bad_member']=True;e.worker.loop()
    source=e.directory.parent/(e.directory.name+'_copied_source')
    directory=source/'autonomous/main';shutil.copytree(e.directory,directory)
    db=s.connect(directory);job=dict(db.execute('SELECT * FROM jobs WHERE iid=?',(e.other,)).fetchone());db.close()
    bundle,files=reusable_result(source.parent,source,e.manifest,job,e.data)
    assert bundle['shared_initial']['owner_indicator']==e.iid and files
    assert len(e.calls)==2


def test_interrupted_shared_transport_never_redispatches_uncertain_members(batch):
    e=batch;e.control['interrupt']=True
    with pytest.raises(KeyboardInterrupt):e.worker.loop()
    db=s.connect(e.directory);db.execute("UPDATE jobs SET status='PENDING' WHERE status='RUNNING'");db.close()
    w=b.BatchWorker(e.directory,e.manifest,client_factory=lambda _:pytest.fail('No duplicate shared call'),ram=lambda:99999)
    w.load_project=lambda pid:e.data;w.loop()
    result=monitor.snapshot(e.directory)
    assert result['uncertain']==2 and len(e.calls)==1 and result['evaluated']==0


def test_monitor_does_not_create_or_mutate_queue_and_does_not_assume_active(batch,monkeypatch):
    e=batch;e.worker.close();db=s.connect(e.directory)
    db.execute("UPDATE jobs SET status='PASS' WHERE iid=?",(e.iid,))
    db.execute("UPDATE jobs SET status='RUNNING',attempts=1 WHERE iid=?",(e.other,))
    s.event(db,'evaluation','STARTED',e.pid,e.other);db.close()
    s.write(e.directory/'worker.json',dict(pid=123,creation=1,state='RUNNING',started_at=s.now()))
    monkeypatch.setattr(s,'process_info',lambda pid:dict(alive=True,creation=2))
    before=s.sha(e.directory/'queue.sqlite');result=monitor.snapshot(e.directory)
    assert before==s.sha(e.directory/'queue.sqlite')
    assert result['status']=='INTERRUPTED' and result['projects_completed']==0
    assert result['projects_partial']==1 and result['progress_percent']==50
    assert result['eta_seconds'] is None and not result['worker']['alive']
    with pytest.raises(sqlite3.OperationalError):monitor.snapshot(e.directory/'absent')


def test_monitor_explains_blocked_indicators_without_counting_them_complete(batch):
    e=batch;e.worker.close();db=s.connect(e.directory)
    db.execute("UPDATE jobs SET status='BLOCKED',error='CLARIFICATION_UNRESOLVED' WHERE iid=?",(e.other,))
    db.close();result=monitor.snapshot(e.directory)
    assert result['blocked_details']==[dict(project=e.pid,indicator=e.other,error='CLARIFICATION_UNRESOLVED')]
    assert result['evaluated']==0 and result['projects_completed']==0
    assert 'CLARIFICATION_UNRESOLVED: 1' in monitor.render(result|dict(run_id='synthetic'))


def test_pinned_token_budget_counts_prompt_not_external_grammar_and_checks_model(monkeypatch):
    from layer4_evaluation.indicators import token_budget,context_budget as cb
    from layer4_evaluation.indicators.ollama_provider import context_guard,OllamaError
    monkeypatch.setattr(token_budget,'count',lambda prompt,descriptor:len(prompt.split()))
    descriptor=dict(path='synthetic',sha256='synthetic',template_tokens=12,model_digest='D',model_metadata_sha256='M')
    settings=dict(num_ctx=6144,num_predict=1024,context_margin_tokens=300)
    schema={'description':'large external decoding grammar '*2000}
    budget=cb.estimate('Uno dos tres',schema,settings,tokenizer=descriptor)
    assert budget['estimated_input_tokens']==15 and budget['schema_tokens']==0 and budget['fits']
    runtime=dict(template_bytes=13,digest='D',model_metadata_sha256='M')
    assert context_guard('Uno dos tres',schema,settings,runtime,budget)<6144
    with pytest.raises(OllamaError,match='RUNTIME_DRIFT'):
        context_guard('Uno dos tres',schema,settings,runtime|dict(digest='OTHER'),budget)
    with pytest.raises(OllamaError,match='MISMATCH'):
        context_guard('Un texto diferente y mayor',schema,settings,runtime,budget)
