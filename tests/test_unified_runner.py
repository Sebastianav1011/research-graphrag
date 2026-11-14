"""Selection and one-command orchestration, with mocked layers and no models."""
import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

import run as console
from scripts import pipeline_coordinator as runner
from layer2_processing.preprocessing.adapters import discover_sources, read, write, sha, verify_raw


def project_file(system, relative, ids):
    """Use the current public intake template for incoming project fixtures."""
    from layer2_processing.preprocessing.adapters import PROJECT_HEADERS
    path=system.intake/relative
    path.parent.mkdir(parents=True,exist_ok=True)
    book=openpyxl.Workbook()
    book.active.title='Proyectos'
    book.active.append(list(PROJECT_HEADERS))
    for pid in ids:
        values=dict(id_actividad=pid,titulo_proyecto='Synthetic project',resumen='Synthetic authorized narrative')
        book.active.append([values.get(name) for name in PROJECT_HEADERS])
    book.save(path)
    book.close()
    config=read(system.root/'config/pipeline_manual.json')
    config['files'][relative]={'domain':'proyectos'}
    write(system.root/'config/pipeline_manual.json',config)
    return path


@pytest.fixture
def system(tmp_path, monkeypatch):
    root = tmp_path/'repo'
    import shutil
    from layer4_evaluation.thesis_output import TEMPLATE
    (root/TEMPLATE).parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[1]/TEMPLATE,root/TEMPLATE)
    intake = root/'data/layer1_sources'
    base = intake/'base/descriptores-limpio.json'
    write(base, [dict(id=f'{i:03d}', title='Synthetic fixture', summary='Original synthetic document') for i in range(1, 11)])
    config = dict(raw_base='data/layer1_sources', runs_base='outputs/runs',
        reference_catalog='data/layer1_sources/reference/indicadores/catalog.xlsx',
        files={'*.json':{'domain':'proyectos'}})
    write(root/'config/pipeline_manual.json', config)
    write(root/'config/sources.example.yaml', {'proyectos':{'mapping':{'source_project_id':['id'], 'title':['title'], 'summary':['summary']}}})
    projects = [dict(project_id=f'PROJ_{i:03d}', source_project_id=f'{i:03d}',
        provenance_json=json.dumps([{'record_source':str(base)}])) for i in range(1, 11)]
    calls, events, permissions = [], [], []
    current_run = {}
    def table(path):
        return SimpleNamespace(to_pylist=lambda:projects if Path(path).name == 'proyectos.parquet' else [])
    monkeypatch.setattr(runner.pq, 'read_table', table)
    monkeypatch.setattr(runner, 'check', lambda root,run:read(runner.run_file(run,'run.json')))
    monkeypatch.setattr(runner, 'projects_without_evidence', lambda run, selected: [])
    def preview(root,path,source=None,input_file=None,delivery=None):
        settings,raw,_=runner.selected_configuration(root,path,source,input_file,delivery)
        found=discover_sources(root,settings,raw)
        return dict(status=found['status'],discovery_status=found['status'],
            files=[{k:v for k,v in item.items() if k!='records'} for item in found['files']])
    monkeypatch.setattr(runner, 'verify_sources', preview)
    def prepare(root,run,raw,dataset,settings,through):
        current_run['path']=run
        calls.append('preprocessing')
        if not runner.run_file(run,'run.json').exists() or read(runner.run_file(run,'run.json'))['status']=='REGISTERED':
            write(runner.run_file(run,'run.json'),dict(status='PREPROCESSED',dataset=dataset,configuration=settings,
                                     raw_path=raw.relative_to(root).as_posix()))
    def knowledge(root,run):
        calls.append('knowledge')
        write(runner.run_file(run,'run.json'),read(runner.run_file(run,'run.json'))|dict(status='PREPARED'))
    def graph(root,run,build=False):
        calls.append('graphrag')
        write(run/'workspace/outputs/layer3/publication/_manifest.json',{'mock':'validated separately'})
    monkeypatch.setattr(runner, 'prepare', prepare)
    monkeypatch.setattr(runner, 'knowledge', knowledge)
    monkeypatch.setattr(runner, 'graph', graph)
    monkeypatch.setattr(runner, 'validated_graph', lambda *a:{})
    registrations=[]
    # Mocked builds have no sealed artifacts; shared registration is tested in test_knowledge_store.
    monkeypatch.setattr(runner, 'register_built_knowledge', lambda root,run,request:registrations.append(run.name))
    completed=set()
    def engine(root,run):
        folder=run/'workspace/outputs/layer4'
        def check(directory):return read(directory/'plan.json')
        def verify(directory):
            done=directory.name in completed
            return dict(status='COMPLETE' if done else 'PARTIAL',errors=[],projects=[
                dict(project_id=p['project_id'],complete=done,blocked_indicators={},rows=[dict(indicator_id='TEST',confidence_raw_score=50,decision='SUPPORTED',assessment_validation_status='VALID',confidence_status='COMPUTED',evidence_explanation='Synthetic explanation')] if done else [])
                for p in check(directory)['projects']])
        def execute(args):
            directory=folder/args.run
            assert args.authorize or (directory/'authorization.json').exists()
            calls.append(('ollama', [p['siap_id'] for p in check(directory)['projects']]))
            completed.add(args.run)
            write(directory/'authorization.json',{'mock':'explicit authorization'})
            return verify(directory)
        return SimpleNamespace(BASE=folder,check=check,verify_run=verify,execute=execute,
            assessment_from_row=lambda row:dict(criterion_assessments=[dict(support='CLEAR',evidence_indices=[0])],evidence=[dict(field='summary',text='Synthetic evidence')]),
            v3=SimpleNamespace(validate=lambda *a:[]),
            evidence_locations=lambda p,a:[dict(field='summary',text='Synthetic evidence',match_valid=True,
                section_id='SECTION',start=0,end=18,coordinate_system='original')])
    monkeypatch.setattr(runner, 'engine', engine)
    def plan(root,run,selected):
        folder=engine(root,run).BASE/runner.batch_name(selected)
        if not (folder/'plan.json').exists():
            docs=[dict(project_id='PROJ_'+identity,siap_id=identity,fields={'summary':'Synthetic evidence'},
                field_provenance={'summary':{'raw_sources':[dict(record_source=str(base),source_row=1,field_mapping={'summary':'summary'})]}})
                for identity in selected]
            write(folder/'plan.json',dict(projects=docs,profiles={'TEST':{}},rubrics={'TEST':{}},
                maximum_calls=3*len(selected),runtime={'provider':'ollama','model':'mock'},
                evaluation_policy=read(runner.run_file(run,'execution.json')).get('evaluation_policy',{})))
            (folder/'review.txt').write_text(json.dumps(selected),encoding='utf-8')
        return folder.name
    monkeypatch.setattr(runner, 'prepare_evaluation', plan)
    def confirm(kind,summary):
        permissions.append((kind,summary))
        return True
    return SimpleNamespace(root=root,intake=intake,projects=projects,calls=calls,events=events,permissions=permissions,
        confirm=confirm,run=lambda:current_run['path'],engine=engine)


def test_one_command_three_projects_exports_only_requested(system):
    result=runner.execute_pipeline(system.root,project_ids=['001','002','003'],through='export',
        confirm=system.confirm,notify=system.events.append)
    assert result['status']=='COMPLETE' and result['run_id'].startswith('run_')
    assert [c for c in system.calls if isinstance(c,tuple)]==[('ollama',['001','002']),('ollama',['003'])]
    assert [kind for kind,_ in system.permissions]==['build','llm','llm']
    book=openpyxl.load_workbook(result['excel'],read_only=True)
    from layer4_evaluation.thesis_output import SHEETS
    assert book.sheetnames==SHEETS
    assert {row[0] for row in list(book.worksheets[0].values)[1:]}=={'001','002','003'}
    assert book.worksheets[1].max_row==1
    book.close()
    saved=read(system.run()/'export.json')
    assert saved['csv']['indicator_rows']==3 and saved['csv']['territory_rows']==0
    assert set(saved['csv']['paths'])=={'indicadores.csv','indicadores_territorios.csv'}
    assert saved['preprocessed_projects']==10 and saved['scoped_projects']==3 and saved['pending_projects']==[]
    summary=next(e['summary'] for e in system.events if e['status']=='INPUT_SUMMARY')
    assert summary['input_rows']==10
    assert summary['stages']==list(runner.STAGES)


def test_file_discovers_ids_and_ignores_other_deliveries(system):
    primary=project_file(system,'incoming/selected/projects.xlsx',['002','003'])
    write(system.intake/'incoming/unrelated/bad.json',{'unconfigured':'do not process'})
    for row in system.projects[1:3]:
        row['provenance_json']=json.dumps([dict(record_source=str(primary))])
    result=runner.execute_pipeline(system.root,input_file='incoming/selected/projects.xlsx',through='export',
        confirm=system.confirm,notify=system.events.append)
    assert result['status']=='COMPLETE'
    assert [c for c in system.calls if isinstance(c,tuple)]==[('ollama',['002','003'])]
    summary=next(e['summary'] for e in system.events if e['status']=='INPUT_SUMMARY')
    assert summary['selected_files']==['incoming/selected/projects.xlsx'] and summary['input_rows']==2
    assert summary['supporting_files']==[]  # Independent inputs never add base evidence.
    state=read(system.run()/'run.json')
    assert state['configuration']['source_paths']==['incoming/selected/projects.xlsx']


def test_delivery_contains_multiple_files_and_has_no_total_project_cap(system):
    for part,ids in [('a',range(1,5)),('b',range(5,8))]:
        path=project_file(system,f'incoming/delivery/{part}.xlsx',[f'{i:03d}' for i in ids])
        for i in ids:system.projects[i-1]['provenance_json']=json.dumps([dict(record_source=str(path))])
    result=runner.execute_pipeline(system.root,delivery='delivery',through='export',confirm=system.confirm,notify=system.events.append)
    assert result['status']=='COMPLETE'
    evaluated=[identity for call in system.calls if isinstance(call,tuple) for identity in call[1]]
    assert evaluated==[f'{i:03d}' for i in range(1,8)]
    assert len(next(e['summary'] for e in system.events if e['status']=='INPUT_SUMMARY')['selected_files'])==2


def test_denied_review_can_resume_without_repeating_valid_calls(system):
    deny=lambda kind,summary:kind=='build'
    result=runner.execute_pipeline(system.root,run_id='selection',project_ids=['001'],through='export',confirm=deny)
    assert result['status']=='REVIEW_REQUIRED'
    assert not any(isinstance(call,tuple) for call in system.calls)
    assert 'resume --run-id selection' in result['resume_command']
    result=runner.execute_pipeline(system.root,run_id='selection',resume=True,confirm=system.confirm)
    assert result['status']=='COMPLETE'
    runner.execute_pipeline(system.root,run_id='selection',resume=True,confirm=system.confirm)
    assert len([call for call in system.calls if isinstance(call,tuple)])==1


def test_resume_reuses_completed_stages_and_pass_without_export_side_effects(system):
    first=runner.execute_pipeline(system.root,run_id='checkpoint_only',project_ids=['001','002','003'],
        through='evaluation',confirm=system.confirm,notify=system.events.append)
    assert first['status']=='COMPLETE'
    calls=list(system.calls)
    protected={p:p.read_bytes() for p in (system.run()/'workspace/outputs/layer4').rglob('*') if p.is_file()}
    for _ in range(2):
        result=runner.execute_pipeline(system.root,run_id='checkpoint_only',resume=True,through='evaluation',
            confirm=system.confirm,notify=system.events.append)
        assert result['status']=='COMPLETE' and system.calls==calls
        assert all(p.read_bytes()==content for p,content in protected.items())
    assert sum(event['status']=='STAGE_REUSED' for event in system.events)==6


def test_individual_batch_errors_report_all_processed_projects_and_partial_run(system,monkeypatch):
    engine=system.engine
    def isolated(root,run):
        module=engine(root,run);verify=module.verify_run
        def status(directory):
            state=verify(directory);state['blocking_errors']=[]
            for p in state['projects']:
                p.update(selected=['TEST'],blocked_indicators={},pending_indicators=[])
                if p['complete']:
                    p['processed']=True
                    if p['project_id']!='PROJ_001':
                        p.update(complete=False,selected=['TEST','BAD'],blocked_indicators={'BAD':'BLOCKED_ERROR'})
                        state['errors'].append(p['project_id']+': BLOCKED_ERROR')
            if state['errors']:state['status']='PARTIAL'
            return state
        module.verify_run=status
        return module
    monkeypatch.setattr(runner,'engine',isolated)
    result=runner.execute_pipeline(system.root,project_ids=['001','002','003','004','005'],through='evaluation',
        confirm=system.confirm,notify=system.events.append)
    assert result['status']=='PARTIAL' and result['selected_projects']==5
    assert result['processed_projects']==5 and result['completed_projects']==1
    assert result['valid_assessments']==5 and result['blocked_assessments']==4 and result['pending_assessments']==0
    assert result['processing_complete'] and result['results_available']
    progress=[e for e in system.events if e['status']=='EVALUATION_PROGRESS'][-1]
    assert progress['projects_processed']==5 and progress['projects_completed']==1


def test_scope_rejects_unknown_project_before_graph(system):
    with pytest.raises(ValueError,match='no presentes'):
        runner.execute_pipeline(system.root,project_ids=['999'],through='export',confirm=system.confirm,notify=system.events.append)
    assert 'graphrag' not in system.calls
    assert system.events[-1]['checkpoint_available'] is True
    assert 'resume --run-id' in system.events[-1]['resume_command']


def test_selected_file_must_have_explicit_project_provenance(system):
    selected=project_file(system,'incoming/other.xlsx',['777'])
    with pytest.raises(ValueError,match='Seleccion sin PROJECT'):
        runner.execute_pipeline(system.root,input_file='incoming/other.xlsx',through='evaluation',confirm=system.confirm)
    assert not any(isinstance(call,tuple) for call in system.calls)


def test_explicit_membership_selects_project_without_inferring_person_links(system,monkeypatch):
    primary=system.intake/'incoming/members.json'
    write(primary,[dict(employee='TEST_EMPLOYEE',project='003',name='Fictitious person')])
    cfg=read(system.root/'config/pipeline_manual.json')
    cfg['files']={'base/*.json':{'domain':'proyectos'},'incoming/members.json':{'domain':'investigadores'}}
    write(system.root/'config/pipeline_manual.json',cfg)
    registry=read(system.root/'config/sources.example.yaml')
    registry['investigadores']={'mapping':{'institutional_id':['employee'],'source_project_id':['project'],'full_name':['name']}}
    write(system.root/'config/sources.example.yaml',registry)
    original=runner.pq.read_table
    def table(path):
        if Path(path).name=='proyecto_investigador.parquet':
            return SimpleNamespace(to_pylist=lambda:[dict(project_id='PROJ_003',
                provenance_json=json.dumps([dict(record_source=str(primary))]))])
        return original(path)
    monkeypatch.setattr(runner.pq,'read_table',table)
    prepare=runner.prepare
    def with_membership(*args,**kwargs):
        prepare(*args,**kwargs)
        marker=system.run()/'workspace/outputs/layer2/canonical/proyecto_investigador.parquet'
        marker.parent.mkdir(parents=True,exist_ok=True)
        marker.write_bytes(b'mocked reader, no generated data')
    monkeypatch.setattr(runner,'prepare',with_membership)
    result=runner.execute_pipeline(system.root,input_file='incoming/members.json',through='export',confirm=system.confirm)
    assert result['status']=='COMPLETE'
    assert [c for c in system.calls if isinstance(c,tuple)]==[('ollama',['003'])]


def test_foreign_evaluation_cannot_replace_scoped_excel(system):
    result=runner.execute_pipeline(system.root,project_ids=['001'],through='export',confirm=system.confirm)
    original_hash=sha(Path(result['excel']))
    batch=runner.prepare_evaluation(system.root,system.run(),['004'])
    system.engine(system.root,system.run()).execute(SimpleNamespace(run=batch,authorize=True))
    with pytest.raises(ValueError,match='fuera de la seleccion'):
        runner.export(system.root,system.run())
    assert sha(Path(result['excel']))==original_hash


def test_resume_integrity_hashes_only_selected_original_files(tmp_path):
    raw=tmp_path/'layer1_sources'
    write(raw/'base/a.json',{'fixture':'base'})
    paths=['base/a.json']
    fingerprints={name:sha(raw/name) for name in paths}
    write(raw/'incoming/unrelated/new.json',{'fixture':'unselected'})
    verify_raw(raw,fingerprints,paths)
    write(raw/'base/a.json',{'fixture':'changed'})
    with pytest.raises(ValueError,match='RAW cambio'):
        verify_raw(raw,fingerprints,paths)


@pytest.mark.parametrize('value',['123,,456','123,123',''])
def test_projects_argument_rejects_empty_and_duplicate_ids(value):
    with pytest.raises(ValueError):
        console.selected_projects(console.parser().parse_args(['run','--projects',value]))


def test_cli_projects_keeps_leading_zeroes_and_single_python_call(monkeypatch):
    calls=[]
    monkeypatch.setattr(console,'coordinator',lambda:SimpleNamespace(execute_pipeline=lambda *a,**kw:calls.append(kw) or {'status':'COMPLETE'}))
    assert console.main(['run','--projects','001,002,003','--through','export'])==0
    assert len(calls)==1 and calls[0]['project_ids']==['001','002','003'] and callable(calls[0]['confirm'])


def test_cli_combines_file_and_projects(monkeypatch):
    calls=[]
    monkeypatch.setattr(console,'coordinator',lambda:SimpleNamespace(execute_pipeline=lambda *a,**kw:calls.append(kw) or {'status':'COMPLETE'}))
    path='data/layer1_sources/incoming/synthetic/projects.xlsx'
    assert console.main(['run','--file',path,'--projects','002,005,009','--through','export'])==0
    assert calls[0]['input_file']==path and calls[0]['project_ids']==['002','005','009']


def synthetic_excel(system, count=10):
    path=project_file(system,'incoming/synthetic/projects.xlsx',[f'{i:03d}' for i in range(1,count+1)])
    for i in range(1,count+1):
        system.projects[i-1]['provenance_json']=json.dumps([dict(record_source=str(path))])
    return path


def test_file_with_ten_projects_scopes_three_and_resumes_without_repeating(system):
    primary=synthetic_excel(system)
    original=sha(primary)
    settings,raw,_=runner.selected_configuration(system.root,'config/pipeline_manual.json',input_file=str(primary))
    found=discover_sources(system.root,settings,raw)
    selected=next(item for item in found['files'] if item['file'].endswith('projects.xlsx'))
    assert selected['mapping']['source_project_id']==['id_actividad']
    result=runner.execute_pipeline(system.root,input_file=str(primary),project_ids=['002','005','009'],
        through='export',confirm=system.confirm,notify=system.events.append)
    assert result['status']=='COMPLETE'
    assert next(e['summary'] for e in system.events if e['status']=='INPUT_SUMMARY')['input_rows']==10
    calls=[c for c in system.calls if isinstance(c,tuple)]
    assert calls==[('ollama',['002','005']),('ollama',['009'])]
    result=runner.execute_pipeline(system.root,run_id=result['run_id'],resume=True,confirm=system.confirm)
    assert [c for c in system.calls if isinstance(c,tuple)]==calls
    book=openpyxl.load_workbook(result['excel'],read_only=True)
    assert {row[0] for row in list(book.worksheets[0].values)[1:]}=={'002','005','009'}
    book.close()
    assert sha(primary)==original


def test_file_rejects_project_present_only_in_supporting_base(system):
    primary=synthetic_excel(system,count=2)
    original=sha(primary)
    with pytest.raises(ValueError,match='no presentes.*003'):
        runner.execute_pipeline(system.root,input_file=str(primary),project_ids=['001','003'],
            through='export',confirm=system.confirm)
    assert 'graphrag' not in system.calls
    assert not any(isinstance(c,tuple) for c in system.calls)
    assert sha(primary)==original


def test_projects_without_file_use_only_base_by_default(system):
    write(system.intake/'incoming/invalid.json',{'invalid':'not selected'})
    result=runner.execute_pipeline(system.root,project_ids=['001'],through='export',confirm=system.confirm)
    assert result['status']=='COMPLETE'
    assert read(system.run()/'run.json')['raw_path']=='data/layer1_sources/base'


def test_interactive_authorization_requires_explicit_yes(monkeypatch):
    monkeypatch.setattr(console.sys.stdin,'isatty',lambda:True)
    monkeypatch.setattr('builtins.input',lambda *a:'si')
    assert console.confirm_action('llm',{'review':'private review path'}) is True
    monkeypatch.setattr('builtins.input',lambda *a:'')
    assert console.confirm_action('llm',{}) is False


def test_no_terminal_never_authorizes(monkeypatch):
    monkeypatch.setattr(console.sys.stdin,'isatty',lambda:False)
    monkeypatch.setattr('builtins.input',lambda *a:pytest.fail('No unattended prompt'))
    assert console.confirm_action('llm',{}) is False


def test_truthy_text_is_not_authorization(system):
    result=runner.execute_pipeline(system.root,project_ids=['001'],through='export',confirm=lambda *a:'no')
    assert result['status']=='BUILD_APPROVAL_REQUIRED'
    assert 'graphrag' not in system.calls


def test_reuse_skips_build_stages_and_resume_keeps_original_reference(system,monkeypatch):
    probes=[]
    def reuse(*a,**kw):probes.append(kw);return 'outputs/runs/global-original'
    monkeypatch.setattr(runner.processing,'reuse_global_base',reuse)
    original=runner.prepare
    def prepare(root,run,raw,dataset,config,through):
        original(root,run,raw,dataset,config,through)
        path=runner.run_file(run,'run.json');value=read(path)
        value.update(status='PREPARED',global_reuse={'source_run':'global-original','graph_reused':True})
        write(path,value)
    monkeypatch.setattr(runner,'prepare',prepare)
    result=runner.execute_pipeline(system.root,source='base',project_ids=['001'],through='knowledge',run_id='reuse')
    assert result['status']=='COMPLETE' and system.calls==['preprocessing']
    run=system.run();saved=read(runner.run_file(run,'execution.json'))
    assert saved['base_knowledge_source']=='outputs/runs/global-original' and saved['project_ids']==['001']
    monkeypatch.setattr(runner.processing,'reuse_global_base',lambda *a,**kw:pytest.fail('Resume must not search for another knowledge base'))
    assert runner.execute_pipeline(system.root,run_id='reuse',resume=True,through='knowledge')['status']=='COMPLETE'
    assert read(runner.run_file(run,'execution.json'))['base_knowledge_source']==saved['base_knowledge_source']
    with pytest.raises(ValueError,match='Resume conserva'):
        runner.execute_pipeline(system.root,run_id='reuse',resume=True,knowledge_action='rebuild')


def test_missing_compatible_knowledge_offers_rebuild_without_processing(system,monkeypatch):
    monkeypatch.setattr(runner.processing,'reuse_global_base',lambda *a,**kw:False)
    offered=[]
    result=runner.execute_pipeline(system.root,source='base',project_ids=['001'],through='knowledge',
        confirm=lambda kind,summary:offered.append(kind) or False)
    assert result['status']=='KNOWLEDGE_REBUILD_REQUIRED'
    assert offered==['knowledge_rebuild'] and system.calls==[]


@pytest.mark.parametrize('mode',['prospective','demonstrated'])
@pytest.mark.parametrize('context',['full-descriptor','graphrag'])
def test_execution_freezes_independent_modes_and_refuses_incompatible_resume(system,mode,context):
    from layer4_evaluation.indicators import assessment_v3 as v3
    result=runner.execute_pipeline(system.root,source='base',project_ids=['001'],run_id='modes',through='knowledge',
        evaluation_mode=mode,context_mode=context)
    run=system.run();execution=read(runner.run_file(run,'execution.json'));state=read(runner.run_file(run,'run.json'))
    policy=execution['evaluation_policy'];v3.verify_evaluation_policy(policy)
    assert policy['evaluation_mode']=={'prospective':v3.PROSPECTIVE,'demonstrated':v3.DEMONSTRATED}[mode]
    assert policy['context_mode']=={'full-descriptor':v3.FULL_CONTEXT,'graphrag':v3.GRAPHRAG_CONTEXT}[context]
    assert state['configuration']['evaluation_policy']==policy
    assert read(runner.run_file(run,'model.binding.json'))['evaluation_policy']==policy
    assert execution['llm']['num_ctx']==(24576 if context=='full-descriptor' else 8192)
    before={p.relative_to(run):sha(p) for p in run.rglob('*') if p.is_file()}
    calls=list(system.calls)
    with pytest.raises(ValueError,match='Modos incompatibles'):
        runner.execute_pipeline(system.root,run_id='modes',resume=True,evaluation_mode='demonstrated' if mode=='prospective' else 'prospective')
    assert all(sha(run/p)==value for p,value in before.items()) and system.calls==calls
    runner.execute_pipeline(system.root,run_id='modes',resume=True,through='knowledge')
    assert read(runner.run_file(run,'execution.json'))['evaluation_policy']==policy


def test_base_defaults_to_prospective_full_but_incoming_does_not(system):
    from layer4_evaluation.indicators import assessment_v3 as v3
    runner.execute_pipeline(system.root,source='base',project_ids=['001'],run_id='base-modes',through='knowledge')
    assert read(runner.run_file(system.run(),'execution.json'))['evaluation_policy']['evaluation_mode']==v3.PROSPECTIVE
    policy=v3.evaluation_policy(base=False)
    assert policy['evaluation_mode']==v3.DEMONSTRATED and policy['context_mode']==v3.GRAPHRAG_CONTEXT
    assert v3.evaluation_policy(saved={})=={}  # Historical checkpoints are not migrated.


def test_modes_can_be_selected_in_existing_configuration(system):
    from layer4_evaluation.indicators import assessment_v3 as v3
    path=system.root/'config/pipeline_manual.json';config=read(path)
    config['evaluation']=dict(mode='demonstrated',context_mode='full-descriptor');write(path,config)
    runner.execute_pipeline(system.root,source='base',project_ids=['001'],run_id='configured-modes',through='knowledge')
    policy=read(runner.run_file(system.run(),'execution.json'))['evaluation_policy']
    assert policy['evaluation_mode']==v3.DEMONSTRATED and policy['context_mode']==v3.FULL_CONTEXT
