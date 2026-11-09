"""Focused complete cycles in temporary roots; no models, embeddings or network."""
import csv
import json
from pathlib import Path
import shutil

import pytest
import run as console
import evaluation_contracts as contracts
from scripts import pipeline_coordinator as runner
from layer2_processing.preprocessing.adapters import read,write,sha
from layer2_processing.checkpoints import verify_expected
from run_paths import file_path,list_runs
from tests.test_unified_runner import system
from tests.test_manual_pipeline import sandbox

SOURCE=Path(__file__).resolve().parents[1]

@pytest.fixture
def stable(system,monkeypatch):
    e=system;root=e.root
    shutil.copytree(SOURCE/'src',root/'src',ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('pipeline_coordinator.py','run_pipeline_manual.py'):
        target=root/'scripts'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(SOURCE/'scripts'/name,target)
    for name in ('layer1.yaml','layer2.yaml','layer3.yaml','openai.json'):
        shutil.copyfile(SOURCE/'config'/name,root/'config'/name)
    catalog=root/'data/layer1_sources/reference/indicadores/catalog.xlsx'
    catalog.parent.mkdir(parents=True,exist_ok=True);catalog.write_bytes(b'synthetic catalog')
    base=root/'data/layer1_sources/base/descriptores-limpio.json'
    write(base,[dict(id=f'{i:03}',title='Synthetic',summary='Synthetic evidence') for i in range(1,31)])
    e.projects[:]=[dict(project_id=f'PROJ_{i:03}',source_project_id=f'{i:03}',
        provenance_json=json.dumps([dict(record_source=str(base))])) for i in range(1,31)]
    monkeypatch.setattr(console,'ROOT',root)
    monkeypatch.setattr(console.sys.stdin,'isatty',lambda:True)
    monkeypatch.setattr(contracts,'catalog_hash',lambda root:'synthetic-catalog')
    monkeypatch.setattr('model_access.api_key',lambda root:'synthetic-no-network')
    e.contract=contracts.create(root,'tesis_comparacion_30',30,42,contracts.inventory(root,runner),'synthetic-catalog')
    original_plan=runner.prepare_evaluation
    def plan(root,run,ids):
        batch=original_plan(root,run,ids)
        target=e.engine(root,run).BASE/batch/'plan.json'
        value=read(target)
        value.update(profiles={f'I{i:02}':{} for i in range(48)},rubrics={f'I{i:02}':{} for i in range(48)},maximum_calls=48*len(ids),
            runtime=read(file_path(run,'execution.json'))['llm'])
        write(target,value)
        return batch
    monkeypatch.setattr(runner,'prepare_evaluation',plan)
    original_engine=e.engine
    def engine(root,run):
        module=original_engine(root,run);verify=module.verify_run
        def verified(directory):
            result=verify(directory)
            for project in result['projects']:
                project['rows']=[dict(project['rows'][0],indicator_id=f'I{i:02}',
                    decision='SUPPORTED' if i else 'UNSUPPORTED') for i in range(48)] if project['rows'] else []
            return result
        module.verify_run=verified
        module.summary=lambda state:dict(status=state['status'],projects_evaluated=len(state['projects']),
            indicators_completed=sum(len(p['rows']) for p in state['projects']))
        return module
    monkeypatch.setattr(runner,'engine',engine)
    e.runpath=root/'outputs/runs/local/fresh30'
    return e

def command(e,provider='ollama'):
    return ['run','--provider',provider,'--contract',e.contract.relative_to(e.root).as_posix(),
        '--run-id','fresh30','--through','export']

@pytest.mark.parametrize('provider',['ollama','openai'])
@pytest.mark.parametrize('entry',['menu','cli'])
def test_complete_thirty_project_cycle_one_approval(stable,monkeypatch,capsys,provider,entry):
    e=stable;confirmed=False;invocations=[];registrations=[];events=[]
    e.runpath=e.root/('outputs/runs/api/fresh30' if provider=='openai' else 'outputs/runs/local/fresh30')
    original=runner.execute_pipeline
    original_approval=runner.execution_approval
    def approval(root,run,*args,**kwargs):
        e.runpath=run
        return original_approval(root,run,*args,**kwargs)
    monkeypatch.setattr(runner,'execution_approval',approval)
    def execute(*args,**kwargs):
        invocations.append(kwargs)
        notify=kwargs['notify']
        def progress(event):
            events.append(event)
            notify(event)
        kwargs['notify']=progress
        return original(*args,**kwargs)
    monkeypatch.setattr(runner,'execute_pipeline',execute)
    verify=runner.verify_sources
    def registered(*args,**kwargs):
        assert confirmed
        assert read(file_path(e.runpath,'run.json'))['status']=='REGISTERED'
        assert read(e.runpath/'estado/run.authorization.json')['authorized'] is True
        assert console.main(['status','--run-id',e.runpath.name])==3
        registrations.append(True)
        return verify(*args,**kwargs)
    monkeypatch.setattr(runner,'verify_sources',registered)
    answers=['1','3','1'] if entry=='menu' else []
    if provider=='openai':answers+=['15']
    answers+=['S']
    if entry=='menu':answers+=['0']
    iterator=iter(answers);prompts=[]
    def answer(prompt):
        nonlocal confirmed
        prompts.append(prompt)
        assert '[EN CURSO]' not in capsys.readouterr().out
        if prompt=='¿Iniciar ejecución? (S/N): ':
            from layer4_evaluation.indicators import performance
            assert performance._active_run.sensor is None
            assert not e.runpath.exists() and not e.calls
            confirmed=True
        return next(iterator)
    monkeypatch.setattr('builtins.input',answer)
    assert console.main(['--provider',provider] if entry=='menu' else command(e,provider))==0
    assert len(invocations)==1 and registrations==[True]
    assert invocations[0]['single_authorization'] is True
    if entry=='menu':assert e.runpath.name.startswith('run_')
    assert prompts.count('¿Iniciar ejecución? (S/N): ')==1
    run=e.runpath
    progress=read(file_path(run,'progress.json'))
    assert progress['status']=='COMPLETE',progress.get('error')
    assert read(file_path(run,'execution.json'))['project_ids']==contracts.load(e.contract)['project_ids']
    with (run/'resultados/indicadores.csv').open(encoding='utf-8-sig',newline='') as stream:
        rows=list(csv.DictReader(stream,delimiter=';'))
    assert len({r['siap_id'] for r in rows})==30
    assert all(r['parrafo_evidencia'] and r['confianza'] for r in rows)
    assert (run/'resultados/indicadores_territorios.csv').is_file()
    assert (run/'resultados/performance/resumen.csv').is_file()
    assert list((e.root/'outputs/historico').rglob('indicadores.csv'))
    assert list((e.root/'outputs/historico').rglob('run.authorization.json'))
    assert console.main(['status','--run-id',e.runpath.name])==0
    assert len([c for c in e.calls if isinstance(c,tuple)])==15
    assert len(list(run.rglob('run_authorization.reference.json')))==15
    last=next(event for event in reversed(events) if event['status']=='EVALUATION_PROGRESS')
    assert last['projects_evaluated']==30 and last['indicators_completed']==1440
    monkeypatch.setattr('builtins.input',lambda *a:pytest.fail('No repeated approval'))
    before=list(e.calls)
    assert console.main(['resume','--run-id',e.runpath.name])==0
    assert e.calls==before

@pytest.mark.parametrize('answer',['N',''])
@pytest.mark.parametrize('provider',['ollama','openai'])
def test_cancellation_before_registration(stable,monkeypatch,answer,provider):
    e=stable;values=['1','3','1']
    if provider=='openai':values+=['15']
    answers=iter(values+[answer,'0'])
    monkeypatch.setattr('builtins.input',lambda prompt:next(answers))
    assert console.main(['--provider',provider])==0
    assert not list_runs(e.root) and not e.calls

def test_invalid_answers_and_eof_are_visible(stable,monkeypatch,capsys):
    answers=iter(['bad','1','bad-submenu','1','-1','2.3','3','maybe','N','0'])
    monkeypatch.setattr('builtins.input',lambda prompt:next(answers))
    assert console.main([])==0
    output=capsys.readouterr().out
    assert 'entera positiva' in output and 'Respuesta invalida' in output
    def eof(prompt):raise EOFError()
    monkeypatch.setattr('builtins.input',eof)
    assert console.main([])==2
    assert 'EOF' in capsys.readouterr().out

def test_fingerprint_change_never_silently_reuses_approval(stable,monkeypatch,capsys):
    e=stable;monkeypatch.setattr('builtins.input',lambda prompt:'S')
    assert console.main(command(e))==0
    original=e.root/'src/evaluation_contracts.py';old=sha(original)
    original.write_bytes(original.read_bytes()+b'\n# simulated changed code\n')
    with pytest.raises(ValueError,match='Fingerprint mismatch'):
        verify_expected(e.root,'src/evaluation_contracts.py',old)
    before=list(e.calls)
    previous_check=runner.check
    def sealed_check(root,run):
        verify_expected(root,'src/evaluation_contracts.py',old)
        return previous_check(root,run)
    monkeypatch.setattr(runner,'check',sealed_check)
    monkeypatch.setattr('builtins.input',lambda prompt:'N')
    assert console.main(['resume','--run-id','fresh30'])==2
    assert e.calls==before
    assert 'Fingerprint mismatch: src/evaluation_contracts.py' in capsys.readouterr().out

def test_duplicate_id_never_overwrites(stable,monkeypatch,capsys):
    e=stable;monkeypatch.setattr('builtins.input',lambda prompt:'S')
    assert console.main(command(e))==0
    before={p.relative_to(e.runpath):p.read_bytes() for p in e.runpath.rglob('*') if p.is_file()}
    assert console.main(command(e))==2
    assert 'ya existe' in capsys.readouterr().out
    assert before=={p.relative_to(e.runpath):p.read_bytes() for p in e.runpath.rglob('*') if p.is_file()}

@pytest.mark.parametrize('change',['model','destination','configuration'])
def test_changed_scope_requires_new_approval(stable,change):
    from layer4_evaluation.indicators.ollama_provider import configuration
    e=stable
    config,raw,_=runner.selected_configuration(e.root,'config/pipeline_manual.json',source='base')
    config['llm']=configuration()
    metadata=contracts.inventory(e.root,runner)
    binding=dict(llm=config['llm'],contract=None)
    approval=runner.execution_approval(e.root,e.runpath,config,metadata,binding,'export',lambda *a:True)
    write(e.runpath/'estado/run.authorization.json',approval)
    assert runner.execution_approval(e.root,e.runpath,config,metadata,binding,'export',
        lambda *a:pytest.fail('Identical scope must reuse approval'))==approval
    if change=='model':binding['llm']=dict(binding['llm'],model='changed-model')
    elif change=='destination':binding['llm']=dict(binding['llm'],endpoint='http://127.0.0.1:11435')
    else:config=dict(config,new_relevant_condition=True)
    requested=[]
    assert runner.execution_approval(e.root,e.runpath,config,metadata,binding,'export',
        lambda *a:requested.append(a) or False) is None
    assert len(requested)==1

def test_changed_data_and_corrupt_approval_are_rejected(stable):
    from layer4_evaluation.indicators.ollama_provider import configuration
    e=stable;config,_,_=runner.selected_configuration(e.root,'config/pipeline_manual.json',source='base')
    approval=runner.execution_approval(e.root,e.runpath,config,contracts.inventory(e.root,runner),
        dict(llm=configuration(),contract=None),'export',lambda *a:True)
    path=e.root/next(iter(approval['scope']['sources']))
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='Alcance autorizado modificado'):
        runner.verify_execution_approval(e.root,approval)
    approval['scope']['run_id']='tampered'
    with pytest.raises(ValueError,match='corrupta'):
        runner.verify_execution_approval(e.root,approval)

def test_safe_individual_input_block_keeps_other_projects_running(stable,monkeypatch):
    e=stable;monkeypatch.setattr('builtins.input',lambda prompt:'S')
    monkeypatch.setattr(runner,'projects_without_evidence',lambda run,ids:['001'])
    assert console.main(command(e))==3
    execution=read(file_path(e.runpath,'execution.json'))
    assert execution['blocked_projects']=={'001':['NO_AUTHORIZED_SUBSTANTIVE_TEXT']}
    evaluated=[pid for call in e.calls if isinstance(call,tuple) for pid in call[1]]
    assert len(evaluated)==29 and '001' not in evaluated
    assert read(file_path(e.runpath,'export.json'))['processed_projects']==29

def test_stop_resume_reuses_approval_checkpoints_and_valid_batches(stable,monkeypatch):
    e=stable;monkeypatch.setattr('builtins.input',lambda prompt:'S')
    evaluate=runner.evaluate
    def stop_after_first(*args,**kwargs):
        result=evaluate(*args,**kwargs)
        if kwargs.get('execute'):
            assert console.main(['stop','--run-id',e.runpath.name])==0
        return result
    monkeypatch.setattr(runner,'evaluate',stop_after_first)
    assert console.main(command(e))==3
    assert read(file_path(e.runpath,'progress.json'))['status']=='INTERRUPTED'
    assert len([c for c in e.calls if isinstance(c,tuple)])==1
    approval=(e.runpath/'estado/run.authorization.json').read_bytes()
    monkeypatch.setattr(runner,'evaluate',evaluate)
    monkeypatch.setattr('builtins.input',lambda prompt:pytest.fail('Approval must persist'))
    assert console.main(['resume','--run-id','fresh30'])==0
    assert (e.runpath/'estado/run.authorization.json').read_bytes()==approval
    assert len([c for c in e.calls if isinstance(c,tuple)])==15
    assert e.calls.count('preprocessing')==e.calls.count('knowledge')==e.calls.count('graphrag')==1

def test_native_preprocessing_knowledge_seals_current_code_without_models(sandbox,monkeypatch):
    from tests.test_scoped_identity import setup_sources,paper
    from experiment_runtime import options
    from layer2_processing.pipeline import check
    root,_,config=sandbox
    setup_sources(root,[paper()])
    write(root/'config/pipeline_manual.json',config)
    monkeypatch.setattr(contracts,'catalog_hash',lambda root:'synthetic-catalog')
    population=contracts.inventory(root,runner)
    path=contracts.create(root,'synthetic',2,42,population,'synthetic-catalog')
    selected=contracts.resolve(contracts.load(path),population,'synthetic-catalog')
    token=options.set(dict(provider='ollama',contract=selected))
    approvals=[]
    try:
        result=runner.execute_pipeline(root,source='base',run_id='native-new',project_ids=selected['project_ids'],
            through='knowledge',single_authorization=True,confirm=lambda kind,scope:approvals.append(kind) or True)
        assert result['status']=='COMPLETE' and approvals==['run']
        run=root/'outputs/runs/local/native-new'
        assert check(root,run)['status']=='PREPARED'
        assert runner.execution_status(root,run_id='native-new')['status']=='VERIFIED'
        result=runner.execute_pipeline(root,run_id='native-new',resume=True,single_authorization=True,
            confirm=lambda *a:pytest.fail('No repeated authorization'))
        assert result['status']=='COMPLETE'
        changed=root/'src/evaluation_contracts.py'
        changed.write_bytes(changed.read_bytes()+b'\n# simulated external edit\n')
        with pytest.raises(ValueError,match='Fingerprint mismatch: src/evaluation_contracts.py'):
            check(root,run)
    finally:options.reset(token)

@pytest.mark.parametrize('selection,expected',[(['1','3'],3),(['2'],30),(['3','1'],30)])
def test_minimal_menu_selectors_run_to_export_without_more_questions(stable,monkeypatch,capsys,selection,expected):
    e=stable;prompts=[];calls=[]
    original=runner.execute_pipeline
    def execute(*args,**kwargs):
        calls.append(kwargs)
        return original(*args,**kwargs)
    monkeypatch.setattr(runner,'execute_pipeline',execute)
    answers=iter(['1']+selection+['S','0'])
    def answer(prompt):
        prompts.append(prompt)
        return next(answers)
    monkeypatch.setattr('builtins.input',answer)
    assert console.main([])==0
    assert len(calls)==1 and calls[0]['source']=='base' and calls[0]['run_id'] is None
    assert prompts.count('¿Iniciar ejecución? (S/N): ')==1
    runs=list_runs(e.root)
    assert len(runs)==1 and runs[0].name.startswith('run_')
    progress=read(file_path(runs[0],'progress.json'))
    assert progress['status']=='COMPLETE',progress.get('error')
    assert len(read(file_path(runs[0],'execution.json'))['project_ids'])==expected
    assert read(file_path(runs[0],'export.json'))['processed_projects']==expected
    output=capsys.readouterr().out
    assert '1. Ejecutar sistema\n2. Cambiar modelo\n0. Salir' in output
    assert '3. Reanudar' not in output and '11.' not in output
    assert '[EN CURSO]' not in output and '"scope_sha256"' not in output and '{\n' not in output
    assert 'Etapa: preprocessing' in output and 'Etapa: export' in output and 'Resultados: ' in output
    assert not any('Run ID' in p or 'Detenerse' in p or 'Fuentes' in p or 'manifiesto' in p for p in prompts)

@pytest.mark.parametrize('provider,answers',[('openai',['2','2','1','0']),('ollama',['2','1','0'])])
def test_model_change_is_the_only_other_main_action(stable,monkeypatch,capsys,provider,answers):
    from model_access import preferences,save_preferences
    e=stable;save_preferences(e.root,'ollama' if provider=='openai' else 'openai')
    iterator=iter(answers)
    monkeypatch.setattr('builtins.input',lambda prompt:next(iterator))
    assert console.main([])==0
    assert preferences(e.root)['provider']==provider
    assert not e.calls and not list_runs(e.root)
    assert 'Modelo actual: '+('OPENAI API' if provider=='openai' else 'LOCAL') in capsys.readouterr().out

def test_back_and_contract_cancellation_do_not_start_work(stable,monkeypatch):
    e=stable
    iterator=iter(['1','0','1','3','0','0','0'])
    monkeypatch.setattr('builtins.input',lambda prompt:next(iterator))
    assert console.main([])==0
    assert not e.calls and not list_runs(e.root)

def test_cli_autonomous_flag_uses_same_complete_executor(stable,monkeypatch):
    e=stable;asked=[]
    def answer(prompt):
        asked.append(prompt)
        return 'S'
    monkeypatch.setattr('builtins.input',answer)
    assert console.main(command(e)+['--autonomous'])==0
    assert asked==['¿Iniciar ejecución? (S/N): ']
    assert read(file_path(e.runpath,'progress.json'))['status']=='COMPLETE'

def test_preparation_error_preserves_registration_and_recovers_without_prompt(stable,monkeypatch,capsys):
    e=stable;original=runner.verify_sources
    def failed(*args,**kwargs):raise RuntimeError('SIMULATED_PREPARATION_ERROR')
    monkeypatch.setattr(runner,'verify_sources',failed)
    monkeypatch.setattr('builtins.input',lambda prompt:'S')
    assert console.main(command(e))==2
    assert not e.calls
    assert console.main(['status','--run-id','fresh30'])==3
    assert 'SIMULATED_PREPARATION_ERROR' in capsys.readouterr().out
    approval=(e.runpath/'estado/run.authorization.json').read_bytes()
    monkeypatch.setattr(runner,'verify_sources',original)
    monkeypatch.setattr('builtins.input',lambda prompt:pytest.fail('No new questions after consent'))
    resumed=console.main(['resume','--run-id','fresh30','--autonomous'])
    assert resumed==0,capsys.readouterr().out
    assert read(file_path(e.runpath,'progress.json'))['status']=='COMPLETE'
    assert (e.runpath/'estado/run.authorization.json').read_bytes()==approval
