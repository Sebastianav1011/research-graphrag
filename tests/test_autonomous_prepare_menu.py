"""Interactive console simulations; no model, embedding or real pipeline calls."""
from argparse import Namespace
from copy import deepcopy
from pathlib import Path
import shutil

import pytest

import run as console
from autonomous_execution import cli,lifecycle as l,prepare_menu as menu,store as s
from tests.test_autonomous_execution import environment,stub_discovery
from tests.test_context_budget import corpus
from tests.test_ollama_provider import sample
from tests.test_unified_runner import system
from scripts import pipeline_coordinator as coordinator


def answers(monkeypatch,values):
    iterator=iter(values)
    def read(prompt):
        print(prompt,end='')
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError() from None
    monkeypatch.setattr('builtins.input',read)


@pytest.fixture
def incoming(tmp_path):
    directory=tmp_path/'data/layer1_sources/incoming'
    for name in ['alpha/nested/project.JSON','alpha/root.csv','beta/report.docx','loose.txt',
                 'README.md','ignored.exe','.private/hidden.json','~$locked.xlsx']:
        file=directory/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('synthetic')
    return tmp_path


def test_numeric_browser_reaches_nested_file_without_path_entry(incoming,monkeypatch):
    answers(monkeypatch,['1','2','2'])
    assert menu.browse_file(incoming)=='data/layer1_sources/incoming/alpha/nested/project.JSON'


@pytest.mark.parametrize('choice,expected',[('1',None),('2','ASC-01,ECO-01,TEC-03')])
def test_indicator_coverage_menu(monkeypatch,choice,expected):
    answers(monkeypatch,[choice]);assert menu.select_indicators()==expected


def test_menu_indicator_subset_reaches_authorized_manifest(wizard,monkeypatch):
    e=wizard;e.menu_args.indicators='I00'
    monkeypatch.setattr(menu,'select_indicators',lambda:pytest.fail('Normal menu must not ask for indicators'))
    answers(monkeypatch,['1','1','1',''])
    menu.prepare(e.root,e.menu_args,e.coordinator,e.original)
    manifest=s.read(l.folder(e.root/'outputs/runs/menu_new')/'manifest.json')
    assert list(manifest['profiles'])==['I00'] and list(manifest['rubrics'])==['I00']
    assert manifest['protocol']['max_calls_per_evaluation']==2


def test_browser_can_go_back_to_incoming_and_select_another_folder(incoming,monkeypatch):
    answers(monkeypatch,['1','1','2','2'])
    assert menu.browse_file(incoming)=='data/layer1_sources/incoming/beta/report.docx'


def test_listing_uses_compatible_formats_and_skips_links(incoming,monkeypatch):
    original=Path.is_symlink
    monkeypatch.setattr(Path,'is_symlink',lambda path:path.name=='beta' or original(path))
    base,files,folders=menu.incoming_entries(incoming)
    assert {p.relative_to(base).as_posix() for p in files}=={'alpha/root.csv','alpha/nested/project.JSON','loose.txt'}
    assert {p.relative_to(base).as_posix() for p in folders}=={'alpha','alpha/nested'}


@pytest.mark.parametrize('choices,expected',[
    (['1'],dict(source='base',input_file=None,delivery=None)),
    (['2','1','2','2'],dict(source=None,input_file='data/layer1_sources/incoming/alpha/nested/project.JSON',delivery=None)),
    (['3','1'],dict(source=None,input_file=None,delivery='alpha'))])
def test_three_source_modes(incoming,monkeypatch,choices,expected):
    answers(monkeypatch,choices)
    assert menu.select_source(incoming)==expected


def test_invalid_numeric_choice_and_missing_projects_are_reported(monkeypatch,capsys):
    answers(monkeypatch,['bogus','7','1','-1','bad','3'])
    assert menu.select_projects()==dict(limit=3,all_projects=False,seed=42)
    output=capsys.readouterr().out
    assert 'entera positiva' in output and 'Opcion invalida' in output
    assert 'IDs' not in output and 'Proyectos disponibles:' not in output


def test_empty_incoming_and_cancel_do_not_choose_a_default(tmp_path,monkeypatch):
    (tmp_path/'data/layer1_sources/incoming').mkdir(parents=True)
    with pytest.raises(ValueError,match='No hay archivos compatibles'):menu.browse_file(tmp_path)
    answers(monkeypatch,['0'])
    with pytest.raises(menu.Cancelled):menu.select_source(tmp_path)


@pytest.fixture
def wizard(environment,monkeypatch):
    e=environment
    monkeypatch.setattr(menu,'select_indicators',lambda:pytest.fail('Normal menu must not ask for indicators'))
    monkeypatch.setattr('autonomous_execution.discovery.prepare',lambda root,run:stub_discovery(e,run))
    calls=[];requests=[]
    s.write(e.root/'config/autonomous.json',e.policy)
    monkeypatch.setattr(e.coordinator,'configuration',lambda root,path:
        ({},root/'data/layer1_sources',root/'outputs/runs'))
    def pipeline(root,*,run_id,through,confirm,config_path,limit=None,all_projects=False,seed=42,**source):
        assert through=='knowledge' and confirm is None
        requests.append(dict(limit=limit,all_projects=all_projects,seed=seed))
        calls.append(source)
        target=root/'outputs/runs'/run_id;target.mkdir(parents=True)
        for name in ('run.json','execution.json','raw_manifest.json','prepared_hashes.json'):
            shutil.copyfile(e.run/name,target/name)
        shutil.copytree(e.run/'workspace',target/'workspace')
        request=s.read(target/'execution.json')
        request['project_ids']=['TEST']
        files=[]
        if source['delivery'] or source['input_file']:
            relative=source['input_file'] or ('incoming/'+source['delivery']+'/projects.json')
            s.write(root/'data/layer1_sources'/relative,[])
            files=[relative]
            state=s.read(target/'run.json');state['configuration']['source_paths']=files
            s.write(target/'run.json',state)
        request['selection']=dict(mode='delivery' if source['delivery'] else 'file' if source['input_file'] else 'source',files=files)
        s.write(target/'execution.json',request)
    monkeypatch.setattr(e.coordinator,'execute_pipeline',pipeline)
    monkeypatch.setattr(menu,'available_projects',lambda *a:['TEST'])
    monkeypatch.setattr(l,'OllamaClient',lambda *a:pytest.fail('Ollama must not be used'))
    monkeypatch.setattr('layer3_graphrag.embeddings.SentenceTransformersProvider._load',lambda *a:pytest.fail('Embedding weights must not load'))
    e.menu_args=console.parser().parse_args(['prepare','--autonomous','--run-id','menu_new'])
    e.menu_calls=calls
    e.menu_requests=requests
    # Invoke the original dispatcher after selection; this is the real prepare
    # implementation exercised with synthetic ETL/knowledge artifacts.
    e.original=cli.dispatch.__wrapped__
    return e


def test_menu_generates_real_manifest_and_requires_explicit_authorization(wizard,monkeypatch,capsys):
    e=wizard;answers(monkeypatch,['1','1','1',''])
    result=menu.prepare(e.root,e.menu_args,e.coordinator,e.original)
    directory=l.folder(e.root/'outputs/runs/menu_new');manifest=s.read(directory/'manifest.json')
    assert result['status']=='REVIEW_REQUIRED'
    assert manifest['selection']['project_ids']==['TEST']
    assert manifest['policy']==e.policy and manifest['profiles']==s.read(e.directory/'manifest.json')['profiles']
    assert not (directory/'authorization.json').exists()
    summary=(directory/'review_summary.txt').read_text(encoding='utf-8')
    assert 'Evaluaciones previstas: 2' in summary and result['manifest_sha256'] in summary
    assert manifest['discovery']['considered_per_project']==2
    assert manifest['project_indicators']=={'TEST_PROJECT':['I00','I01']}
    assert manifest['llm']['model'] in summary
    assert e.menu_calls==[dict(source='base',input_file=None,delivery=None)]
    assert 'AUTORIZAR' in capsys.readouterr().out


@pytest.mark.parametrize('source,selection',[(dict(source=None,input_file='incoming/test.json',delivery=None),'file'),
    (dict(source=None,input_file=None,delivery='delivery_a'),'delivery')])
def test_source_subset_validated_before_manifest_including_deliveries(wizard,monkeypatch,capsys,source,selection):
    e=wizard
    monkeypatch.setattr(menu,'select_source',lambda root:source)
    def scope(root,run,selected,requested=None):
        assert selected['mode']==selection
        assert requested is None or requested==['TEST']
        return requested or ['TEST']
    monkeypatch.setattr(e.coordinator,'scope_projects',scope)
    answers(monkeypatch,['1','bad','1',''])
    result=menu.prepare(e.root,e.menu_args,e.coordinator,e.original)
    assert result['status']=='REVIEW_REQUIRED' and e.menu_calls==[source]
    assert 'entera positiva' in capsys.readouterr().out
    manifest=s.read(l.folder(e.root/'outputs/runs/menu_new')/'manifest.json')
    assert manifest['selection']['mode']==selection and manifest['selection']['project_ids']==['TEST']
    assert len(manifest['source_inventory']['files'])==1
    assert all('/incoming/' in name for name in manifest['source_inventory']['files'])


def test_single_manifest_approval_starts_existing_background_worker(wizard,monkeypatch):
    e=wizard;answers(monkeypatch,['1','1','1','AUTORIZAR']);launched=[]
    def background(root,run,**kwargs):
        l.verify(root,run)
        assert kwargs==dict(through='export',config_path=e.menu_args.config)
        launched.append(run)
        return dict(status='STARTED',pid=1234)
    monkeypatch.setattr(l,'background',background)
    assert menu.prepare(e.root,e.menu_args,e.coordinator,e.original)['status']=='STARTED'
    assert len(launched)==1


@pytest.mark.parametrize('response',['si','yes',''])
def test_other_confirmation_words_never_authorize(wizard,monkeypatch,response):
    e=wizard;answers(monkeypatch,['1','1','1',response])
    monkeypatch.setattr(l,'background',lambda *a,**kw:pytest.fail('Unapproved launch'))
    assert menu.prepare(e.root,e.menu_args,e.coordinator,e.original)['status']=='REVIEW_REQUIRED'
    assert not (l.folder(e.root/'outputs/runs/menu_new')/'authorization.json').exists()


def test_eof_at_review_preserves_unsigned_preparation(wizard,monkeypatch):
    e=wizard;answers(monkeypatch,['1','1','1'])
    assert menu.prepare(e.root,e.menu_args,e.coordinator,e.original)['status']=='REVIEW_REQUIRED'


def test_changing_manifest_after_review_prevents_authorization_and_launch(wizard,monkeypatch):
    e=wizard;values=iter(['1','1','1'])
    def read(prompt):
        if 'AUTORIZAR' not in prompt:return next(values)
        path=l.folder(e.root/'outputs/runs/menu_new')/'manifest.json'
        manifest=s.read(path);manifest['created_at']='modified-after-review';s.write(path,manifest)
        return 'AUTORIZAR'
    monkeypatch.setattr('builtins.input',read)
    monkeypatch.setattr(l,'background',lambda *a,**kw:pytest.fail('Changed manifest launched'))
    with pytest.raises(ValueError,match='SHA-256'):
        menu.prepare(e.root,e.menu_args,e.coordinator,e.original)
    assert not (l.folder(e.root/'outputs/runs/menu_new')/'authorization.json').exists()


@pytest.mark.parametrize('flags,tty,interactive',[
    (['prepare','--autonomous'],True,True),
    (['prepare','--autonomous'],False,False),
    (['prepare'],True,False),
    (['prepare','--autonomous','--non-interactive'],True,False),
    (['prepare','--autonomous','--run-id','historical'],True,False),
    (['prepare','--autonomous','--projects','001,002'],True,False),
    (['prepare','--autonomous','--file','incoming/a.json'],True,False),
    (['prepare','--autonomous','--file','incoming/a.json','--projects','001'],True,False),
    (['prepare','--autonomous','--delivery','a'],True,False),
    (['resume','--autonomous','--run-id','historical'],True,False),
    (['start','--autonomous','--run-id','historical','--background'],True,False)])
def test_adapter_preserves_explicit_commands(monkeypatch,flags,tty,interactive,tmp_path):
    monkeypatch.setattr(cli,'dispatch',lambda *a:dict(status='ORIGINAL'))
    monkeypatch.setattr(menu.sys.stdin,'isatty',lambda:tty)
    monkeypatch.setattr(menu,'prepare',lambda *a:dict(status='MENU'))
    menu.install()
    assert cli.dispatch(tmp_path,console.parser().parse_args(flags),Namespace())['status']==('MENU' if interactive else 'ORIGINAL')


def test_summary_reports_all_48_indicators_without_documentary_text(environment):
    manifest=s.read(environment.directory/'manifest.json')
    manifest=deepcopy(manifest)
    manifest['profiles']={f'I{i:02}':{} for i in range(48)}
    summary=menu.review(manifest,'a'*64,environment.run)
    assert '1 x 48 = 48' in summary
    assert 'Catalogo: 48 indicadores' in summary
    assert not any(iid in summary for iid in manifest['profiles'])
    assert manifest['llm']['model'] in summary
    original_text=max((value for value in environment.corpus.project['fields'].values() if value),key=len)
    assert original_text not in summary


def test_available_projects_uses_native_mapping_without_pipeline_or_base_leak(system):
    args=console.parser().parse_args(['prepare','--autonomous'])
    from tests.test_layer1_intake import official_project_file
    official_project_file(system.root, records=[dict(id_actividad='LOCAL', resumen='Synthetic source')],
                          relative='incoming/delivery/nested/projects.xlsx')
    base=dict(source='base',input_file=None,delivery=None)
    assert menu.available_projects(system.root,args,base,coordinator)==[f'{i:03}' for i in range(1,11)]
    for source in [dict(source=None,input_file='incoming/delivery/nested/projects.xlsx',delivery=None),
                   dict(source=None,input_file=None,delivery='delivery')]:
        assert menu.available_projects(system.root,args,source,coordinator)==['LOCAL']
    assert system.calls==[]


@pytest.mark.parametrize('source',[
    dict(source='base',input_file=None,delivery=None),
    dict(source=None,input_file='incoming/projects.json',delivery=None),
    dict(source=None,input_file=None,delivery='delivery_a')])
def test_project_subset_reuses_native_etl_scoping_where_supported(wizard,monkeypatch,source):
    e=wizard
    monkeypatch.setattr(menu,'select_source',lambda root:source)
    monkeypatch.setattr(menu,'available_projects',lambda *a:['TEST','OTHER'])
    answers(monkeypatch,['1','1',''])
    assert menu.prepare(e.root,e.menu_args,e.coordinator,e.original)['status']=='REVIEW_REQUIRED'
    assert e.menu_requests==[dict(limit=1,all_projects=False,seed=42)]
    manifest=s.read(l.folder(e.root/'outputs/runs/menu_new')/'manifest.json')
    assert manifest['selection']['project_ids']==['TEST']


def test_canonical_scope_rejects_project_before_manifest_even_if_preview_had_it(wizard,monkeypatch):
    e=wizard;answers(monkeypatch,['1','1','1'])
    def rejected(root,run,selection,requested=None):
        raise ValueError('Proyectos no presentes en las fuentes seleccionadas: TEST')
    monkeypatch.setattr(e.coordinator,'scope_projects',rejected)
    with pytest.raises(ValueError,match='no presentes'):
        menu.prepare(e.root,e.menu_args,e.coordinator,e.original)
    assert not (l.folder(e.root/'outputs/runs/menu_new')/'manifest.json').exists()


def test_exact_console_command_opens_menu_and_generates_unsigned_manifest(wizard,monkeypatch,capsys):
    e=wizard
    monkeypatch.setattr(console,'ROOT',e.root)
    monkeypatch.setattr(menu.sys.stdin,'isatty',lambda:True)
    answers(monkeypatch,['1','1','1',''])
    assert console.main(['prepare','--autonomous'])==3
    manifests=list((e.root/'outputs/runs').glob('run_*/autonomous/main/manifest.json'))
    assert len(manifests)==1 and not (manifests[0].parent/'authorization.json').exists()
    assert s.read(manifests[0])['selection']['project_ids']==['TEST']
    assert 'Resumen de ejecucion autonoma' in capsys.readouterr().out
