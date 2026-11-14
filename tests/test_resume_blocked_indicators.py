"""Small offline regressions: mocked transport, disposable checkpoints only."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tests.test_ollama_provider import sample, live_run, response, runtime
from tests.test_context_budget import corpus, packed, install_plan
from layer2_processing.preprocessing.adapters import read, write, sha
from layer4_evaluation import live_execution as live
from layer4_evaluation.indicators import ollama_provider as transport
from tests.layer5_experiment.test_assessment_v3 import case,sk_case
from tests.test_manual_pipeline import sandbox,project


@pytest.mark.parametrize('positives',[3,0],ids=['three_verified_positives','no_verified_positives'])
def test_47_persisted_valid_results_survive_one_error_export_and_resume(
        live_run,corpus,sk_case,sandbox,monkeypatch,positives):
    """Real scheduler, receipts, semantic/evidence gates, export and resume; mocked HTTP only."""
    import shutil
    from collections import Counter
    import openpyxl
    from scripts import pipeline_coordinator as runner
    from layer4_evaluation.indicators import context_budget as cb,assessment_v3 as v3
    from layer4_evaluation.thesis_output import TEMPLATE
    from tests.test_evidence_references import selection
    directory,client=live_run;root,raw,config=sandbox
    corpus.settings=transport.configuration(corpus.settings|{'num_ctx':16384})
    source=raw/'synthetic.json'
    write(source,project('TEST')|{'methodology':corpus.project['fields']['methodology']})
    run=root/'outputs/runs/acceptance';runner.prepare(root,run,raw,'prueba_en_vivo',config)
    corpus.project['field_provenance']={'methodology':dict(section_id='SECTION',raw_sources=[dict(
        record_source=str(source),source_row=1,field_mapping={'methodology':'methodology'},
        original_values={'methodology':corpus.project['fields']['methodology']})])}
    requests,_=cb.prepare_contexts([corpus.project],corpus.profiles,corpus.rubrics,corpus.settings,
        corpus.hits,corpus.chunks,corpus.sections,evidence_references=True,assessment_version=v3.SK_VERSION)
    install_plan(directory,corpus,requests)
    plan=read(directory/'plan.json');plan.update(isolate_indicator_errors=True,token_limit_retries=2,
        corrective_retries=2,maximum_calls=144,total_token_reservation_cap=144*corpus.settings['num_ctx'],
        assessment_version=v3.SK_VERSION,confidence_version=v3.SK_CONFIDENCE_VERSION)
    write(directory/'plan.json',plan)
    manifest=read(directory/'manifest.json');manifest['plan_sha256']=sha(directory/'plan.json');write(directory/'manifest.json',manifest)
    target=run/'layer5_results/batch_test';shutil.copytree(directory,target)
    monkeypatch.setattr(live,'BASE',target.parent)
    monkeypatch.setattr(runner,'engine',lambda *a:live)
    monkeypatch.setattr(runner,'validated_graph',lambda *a:{})
    template=root/TEMPLATE;template.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(runner.ROOT/TEMPLATE,template)
    client.inspect.return_value=runtime(corpus.settings);sent=[]
    def reply(method,path,payload):
        body=json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n')[1])
        iid=body['indicators'][0]['indicator_id'];sent.append(iid)
        sample=deepcopy(sk_case)
        if int(iid[1:])>=positives:
            a=sample['assessment'];a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=0,evidence=[])
            for c in a['criterion_assessments']:c.update(support='NOT_DEMONSTRATED',coverage=0,evidence_indices=[])
            a['strength_rubric']={k:([] if k=='evidence_indices' else 'Sin respaldo suficiente.' if k=='explanation' else 0) for k in a['strength_rubric']}
        answer=selection(sample,corpus.project['project_id'],iid)
        if iid=='I47':del answer['assessments'][0]['criterion_assessments']
        return response(answer)
    client.request.side_effect=reply
    result=live.execute(SimpleNamespace(run='batch_test',authorize=True))
    assert result['status']=='PARTIAL' and result['valid_assessments']==47
    assert result['processed_projects']==1 and result['completed_projects']==0
    assert result['supported']==positives and result['insufficient_evidence']==47-positives
    assert result['blocked_assessments']==1 and result['pending_assessments']==0
    state=live.verify_run(target)['projects'][0]
    assert state['blocked_indicators']=={'I47':'BLOCKED_ERROR'} and state['retryable_indicators']==[]
    protected={p:p.read_bytes() for p in target.rglob('*') if p.is_file()}
    exported=runner.export(root,run)
    assert exported['status']=='PARTIAL' and exported['valid_assessments']==47
    assert exported['exported_rows']==48 and exported['supported']==positives and exported['export_exclusions']==[]
    saved=read(runner.run_file(run,'export.json'))
    assert saved['processed_projects']==1 and saved['completed_projects']==0
    assert saved['blocked_assessments']==1 and saved['pending_assessments']==0
    persisted=read(runner.run_file(run,'resultados/evaluaciones_validas.json'))
    assert len(persisted['assessments'])==47 and not any(r['indicator_id']=='I47' for r in persisted['assessments'])
    book=openpyxl.load_workbook(exported['excel'],read_only=True)
    try:
        rows=list(book['Proyectos'].values)[1:]
        assert len(rows)==48 and {r[1] for r in rows}=={f'I{n:02d}' for n in range(48)}
        assert sum(r[2]=='SUPPORTED' for r in rows)==positives
        assert all('Evidencia literal:' in r[3] and 'section_id=' in r[5] for r in rows if r[2]=='SUPPORTED')
        assert rows[-1][2]=='BLOCKED_ERROR' and rows[-1][7] is None
        assert all(r[7]==0 for r in rows if r[2]=='INSUFFICIENT_EVIDENCE')
    finally:book.close()
    if not positives:assert 'todos los indicadores' in saved['note']
    client.inspect.side_effect=AssertionError('Resume must not initialize a model for exhausted work')
    calls=len(sent)
    for _ in range(2):
        resumed=live.execute(SimpleNamespace(run='batch_test',authorize=False))
        assert resumed['status']=='PARTIAL' and resumed['valid_assessments']==47
        assert resumed['blocked_assessments']==1 and resumed['supported']==positives
    assert len(sent)==calls and all(Counter(sent)[f'I{n:02d}']==1 for n in range(47))
    assert 1<=Counter(sent)['I47']<=3 and all(p.read_bytes()==value for p,value in protected.items())


def configured(directory, corpus):
    corpus.settings=transport.configuration(corpus.settings|{'num_ctx':16384})
    corpus.hits = corpus.hits[:2]
    requests, _ = packed(corpus)
    install_plan(directory, corpus, requests)
    plan = read(directory/'plan.json')
    plan.update(isolate_indicator_errors=True, token_limit_retries=2, maximum_calls=144,
        total_token_reservation_cap=144*corpus.settings['num_ctx'],
        budgets=dict(assessment_reservation=3*corpus.settings['num_ctx'],
            assessment_postcall_review_threshold=3*corpus.settings['num_ctx']))
    write(directory/'plan.json', plan)
    manifest = read(directory/'manifest.json')
    manifest['plan_sha256'] = sha(directory/'plan.json')
    write(directory/'manifest.json', manifest)


def wrapper(payload, sample, invalid=None):
    body = json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n')[1])
    iid = body['indicators'][0]['indicator_id']
    assessment = dict(indicator_id=iid, **deepcopy(sample['assessment']))
    if invalid == 'quote':
        assessment['evidence'][0]['text'] = 'Invented quote absent from the sent fragments.'
    elif invalid == 'index':
        assessment['criterion_assessments'][0]['evidence_indices'] = [999]
    elif invalid == 'criteria':
        assessment.update(decision='NOT_SUPPORTED', support_strength=0)
    return response(dict(project_id=body['project']['project_id'], assessments=[assessment]))


@pytest.mark.parametrize('invalid', ['quote', 'index', 'criteria'])
def test_invalid_output_gets_corrective_feedback_and_validates(live_run, corpus, sample, invalid):
    directory, client = live_run
    configured(directory, corpus)
    client.inspect.return_value = runtime(corpus.settings)
    prompts = []
    def reply(method, path, payload):
        prompts.append(payload['messages'][0]['content'])
        return wrapper(payload, sample, invalid if len(prompts) == 1 else None)
    client.request.side_effect = reply
    result = live.execute(SimpleNamespace(run='batch_test', authorize=True))
    assert result['valid_assessments'] == 2 and client.request.call_count == 3
    assert 'ERRORES:' in prompts[1]
    assert not live.verify_run(directory)['errors']


@pytest.mark.parametrize('still_invalid', [False, True])
def test_resume_preserves_valid_and_does_not_reset_exhausted_corrections(live_run, corpus, sample, still_invalid):
    directory, client = live_run
    configured(directory, corpus)
    client.inspect.return_value = runtime(corpus.settings)
    bad = True
    def reply(method, path, payload):
        body = json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n')[1])
        return wrapper(payload, sample, 'index' if bad and body['indicators'][0]['indicator_id']=='I00' else None)
    client.request.side_effect = reply
    first = live.execute(SimpleNamespace(run='batch_test', authorize=True))
    assert first['valid_assessments']==1 and client.request.call_count==3
    assert first['status']=='PARTIAL' and first['processed_projects']==1 and first['completed_projects']==0
    assert first['processing_complete'] and first['results_available']
    # The fixture also has 46 contexts that cannot be dispatched.
    assert first['blocked_assessments']==47 and first['pending_assessments']==0
    assert first['expected_assessments']==48
    protected = {p:p.read_bytes() for p in (directory/'calls').rglob('*') if p.is_file()}
    bad = still_invalid
    resumed = live.execute(SimpleNamespace(run='batch_test', authorize=False))
    assert client.request.call_count == 3
    assert resumed['valid_assessments'] == 1
    assert all(p.read_bytes()==value for p,value in protected.items())
    state=live.verify_run(directory)
    assert state['projects'][0]['blocked_indicators']
    assert state['new_calls']==client.request.call_count
    live.execute(SimpleNamespace(run='batch_test', authorize=False))
    assert client.request.call_count==3


@pytest.mark.parametrize('boundary',['record','rows','verification'])
@pytest.mark.parametrize('contract',['legacy','sk_refs'])
def test_resume_finishes_durable_manual_receipt_without_repeating_inference(live_run,corpus,sample,sk_case,monkeypatch,boundary,contract):
    directory,client=live_run
    configured(directory,corpus);client.inspect.return_value=runtime(corpus.settings)
    if contract=='sk_refs':
        from layer4_evaluation.indicators import context_budget as cb,assessment_v3 as v3
        from tests.test_evidence_references import selection
        requests,_=cb.prepare_contexts([corpus.project],corpus.profiles,corpus.rubrics,corpus.settings,
            corpus.hits,corpus.chunks,corpus.sections,evidence_references=True,assessment_version=v3.SK_VERSION)
        plan=read(directory/'plan.json');plan.update(context_requests=requests,
            assessment_version=v3.SK_VERSION,confidence_version=v3.SK_CONFIDENCE_VERSION)
        write(directory/'plan.json',plan)
        manifest=read(directory/'manifest.json');manifest['plan_sha256']=sha(directory/'plan.json');write(directory/'manifest.json',manifest)
        def reply(method,path,payload):
            body=json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n')[1])
            return response(selection(sk_case,body['project']['project_id'],body['indicators'][0]['indicator_id']))
        client.request.side_effect=reply
    else:client.request.side_effect=lambda method,path,payload:wrapper(payload,sample)
    original=live.write;interrupted=False
    def crash(path,value):
        nonlocal interrupted
        match=(path.parent.name=='assessment' and path.parent.parent.name=='records' if boundary=='record' else
            path.name==('assessment.rows.json' if boundary=='rows' else 'verification.json'))
        if match and not interrupted:
            interrupted=True;raise KeyboardInterrupt()
        return original(path,value)
    monkeypatch.setattr(live,'write',crash)
    with pytest.raises(KeyboardInterrupt):live.execute(SimpleNamespace(run='batch_test',authorize=True))
    assert interrupted and client.request.call_count==1
    protected={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    # A read-only verification may reconstruct a view, but never writes receipts.
    interrupted_state=live.verify_run(directory)
    assert interrupted_state['projects'][0]['pending_indicators']==['I01']
    assert not interrupted_state['projects'][0]['processed']
    assert {p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}==protected
    monkeypatch.setattr(live,'write',original)
    resumed=live.execute(SimpleNamespace(run='batch_test',authorize=False))
    assert resumed['valid_assessments']==2 and client.request.call_count==2
    assert all(p.read_bytes()==content for p,content in protected.items() if p.name!='status.json')
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    client.inspect.side_effect=AssertionError('No model metadata needed for completed work')
    live.execute(SimpleNamespace(run='batch_test',authorize=False))
    assert client.request.call_count==2
    assert all(p.read_bytes()==content for p,content in saved.items())


@pytest.mark.parametrize('mutation',['completion','raw_response','metrics','authorization'])
def test_recovery_revalidates_original_transport_and_never_overwrites_invalid_checkpoint(
        live_run,corpus,sample,monkeypatch,mutation):
    directory,client=live_run
    configured(directory,corpus);client.inspect.return_value=runtime(corpus.settings)
    client.request.side_effect=lambda method,path,payload:wrapper(payload,sample)
    original=live.write
    def crash(path,value):
        if path.parent.name=='assessment' and path.parent.parent.name=='records':raise KeyboardInterrupt()
        return original(path,value)
    monkeypatch.setattr(live,'write',crash)
    with pytest.raises(KeyboardInterrupt):live.execute(SimpleNamespace(run='batch_test',authorize=True))
    monkeypatch.setattr(live,'write',original)
    if mutation=='raw_response':
        next(directory.rglob('response.raw.txt')).write_text('{}',encoding='utf-8')
    elif mutation=='authorization':
        path=next(directory.rglob('authorization.used.json'));write(path,read(path)|dict(authorized=False))
    else:
        path=next(directory.rglob('native_response.json'));body=read(path)
        body.update(done_reason='length') if mutation=='completion' else body.update(eval_count=body['eval_count']+1)
        write(path,body)
    protected={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):live.execute(SimpleNamespace(run='batch_test',authorize=False))
    assert client.request.call_count==1
    assert {p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}==protected


def test_response_without_finished_call_receipt_remains_uncertain(live_run,corpus,sample,monkeypatch):
    from pathlib import Path
    directory,client=live_run
    configured(directory,corpus);client.inspect.return_value=runtime(corpus.settings)
    client.request.side_effect=lambda method,path,payload:wrapper(payload,sample)
    original=Path.write_text
    def crash(path,*args,**kwargs):
        if path.name=='call.json' and 'ollama_runs' in path.parts:raise KeyboardInterrupt()
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'write_text',crash)
    with pytest.raises(KeyboardInterrupt):live.execute(SimpleNamespace(run='batch_test',authorize=True))
    monkeypatch.setattr(Path,'write_text',original)
    assert list(directory.rglob('response.json')) and not list(directory.rglob('call.json'))
    protected={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    with pytest.raises(ValueError,match='UNCERTAIN_OUTCOME'):
        live.execute(SimpleNamespace(run='batch_test',authorize=False))
    assert client.request.call_count==1
    assert {p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}==protected


def test_atomic_checkpoint_write_leaves_previous_bytes_on_serialization_failure(tmp_path):
    path=tmp_path/'checkpoint.json';live.write(path,dict(valid=True))
    original=path.read_bytes()
    with pytest.raises(ValueError):live.write(path,dict(invalid=float('nan')))
    assert path.read_bytes()==original and not list(tmp_path.glob('*.pending'))


def test_progress_cannot_count_more_calls_than_the_persisted_receipts(live_run,corpus,sample):
    directory,client=live_run
    configured(directory,corpus);client.inspect.return_value=runtime(corpus.settings)
    client.request.side_effect=lambda method,path,payload:wrapper(payload,sample)
    live.execute(SimpleNamespace(run='batch_test',authorize=True))
    path=next(directory.rglob('verification.json'));verification=read(path)
    write(path,verification|dict(calls=verification['calls']+1))
    protected={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    with pytest.raises(ValueError,match='Conteo/metricas'):
        live.execute(SimpleNamespace(run='batch_test',authorize=False))
    assert client.request.call_count==2
    assert {p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}==protected
