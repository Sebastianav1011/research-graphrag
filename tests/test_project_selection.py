"""Project counts, reproducibility, shared identities and strict scope; no models."""
import pytest
import run as console
from scripts import pipeline_coordinator as runner
from layer2_processing.preprocessing.adapters import read, write
from layer2_processing.preprocessing.project_selection import sample_projects, select, validate_selection
from .test_manual_pipeline import sandbox
from .test_scoped_identity import setup_sources, paper, rows


def test_sampling_is_seeded_order_independent_and_proportional():
    features = {f'{i:04}': ['A' if i < 80 else 'B', '2024', 'open', str(i % 2)] for i in range(100)}
    chosen = sample_projects(features, 10, 42)
    assert chosen == sample_projects(dict(reversed(list(features.items()))), 10, 42)
    assert chosen != sample_projects(features, 10, 43)
    assert len(chosen) == len(set(chosen)) == 10
    assert sum(features[p][0] == 'B' for p in chosen) == 2
    assert chosen != sorted(features)[:10]
    assert sample_projects(features, 100) == sorted(features)


@pytest.mark.parametrize('limit', [0, -1, 101, True])
def test_invalid_counts_fail(limit):
    with pytest.raises(ValueError):
        sample_projects({str(i): ['A'] for i in range(100)}, limit)


def test_shared_identity_does_not_expand_projects_or_claim_project_production(sandbox):
    root, _, config = sandbox
    setup_sources(root, [paper(), paper('A2', 'DOC1', 'Other work')], extra_members=[
        dict(id_actividad='P2', id_empleado='EMP1', documento='DOC1', nombre_completo='Synthetic One')])
    write(root / 'config/pipeline_manual.json', config)
    result = runner.execute_pipeline(root, all_projects=True, dry_run=True, run_id='all')
    assert result['status'] == 'VALIDATED_SELECTION'
    run = runner.find_run(root,root/'outputs/runs','all')
    manifest = read(run / 'preprocess/selection_manifest.json')
    assert manifest['selected_count'] == 2 and manifest['shared_researchers'] == 1
    assert manifest['verified_project_publication_relations'] == 0
    assert len(rows(run, 'articulos')) == 2
    assert not (run / 'workspace/outputs/layer2/knowledge').exists()
    assert not (run / 'workspace/outputs/layer3').exists()
    replay = runner.execute_pipeline(root, selection_manifest='outputs/runs/all/preprocess/selection_manifest.json',
                                     dry_run=True, run_id='replay')
    assert replay['status'] == 'VALIDATED_SELECTION'
    assert read(root / 'outputs/runs/replay/preprocess/selection_manifest.json')['project_ids'] == ['P1', 'P2']
    one = runner.execute_pipeline(root, project_ids=['P1'], dry_run=True, run_id='one')
    assert one['selected_count'] == 1
    one_run=runner.find_run(root,root/'outputs/runs','one')
    assert {r['source_project_id'] for r in rows(one_run, 'proyectos')} == {'P1','P2'}
    assert len(rows(one_run,'articulos'))==2
    assert read(one_run/'execution.json')['project_ids']==['P1']
    # The same strong researcher identity survives independently scoped runs.
    all_ids = {r['researcher_id'] for r in rows(run, 'proyecto_investigador') if r['project_id'] == 'PROJ_P1'}
    assert all_ids == {r['researcher_id'] for r in rows(one_run, 'proyecto_investigador') if r['project_id']=='PROJ_P1'}
    state = read(run / 'run.json')
    state['configuration']['project_selection']['project_ids'] = ['EXTERNAL']
    write(run / 'run.json', state)
    with pytest.raises(ValueError, match='critica'):
        validate_selection(root, run)


def test_sources_changed_refuse_replay(sandbox):
    root, _, config = sandbox
    base = setup_sources(root, [paper()])
    selected = select(root, base, config, all_projects=True)
    write(root / 'sample.json', selected)
    write(base / 'produccion.json', [paper('NEW')])
    with pytest.raises(ValueError, match='Fuentes'):
        select(root, base, config, replay=root / 'sample.json')


def test_strict_reuse_checks_publication_without_building_and_keeps_global_scope(tmp_path,monkeypatch):
    from layer2_processing import pipeline as processing
    from layer2_processing.preprocessing.adapters import sha
    from types import SimpleNamespace
    root=tmp_path;raw=root/'data/base';raw.mkdir(parents=True)
    catalog=root/'catalog.xlsx';catalog.write_bytes(b'synthetic')
    config=dict(knowledge_scope='BASE_GLOBAL_V1',reference_catalog='catalog.xlsx',base_knowledge_action='reuse')
    prior=root/'outputs/runs/old'
    write(runner.run_file(prior,'run.json'),dict(status='PREPARED',dataset='raw',configuration=config,
        raw_path='data/base',global_catalog_sha256=sha(catalog),counts={'proyectos':2}))
    write(runner.run_file(prior,'raw_manifest.json'),{'files':{}})
    write(prior/'workspace/outputs/layer2/knowledge/_manifest.json',{'synthetic':True})
    write(prior/'workspace/outputs/layer3/publication/_manifest.json',{'synthetic':True})
    monkeypatch.setattr(processing,'check',lambda *a,**kw:None)
    monkeypatch.setattr(processing,'code_hashes',lambda *a:{})
    monkeypatch.setattr(processing,'prepare_files',lambda *a:pytest.fail('No ETL in reuse mode'))
    monkeypatch.setattr('layer3_graphrag.manifest.validate_publication',lambda *a:{})
    monkeypatch.setattr('layer3_graphrag.configuration.load_config',lambda *a:({'embeddings':{}},'config'))
    monkeypatch.setattr('layer3_graphrag.validate_inputs.validate_inputs',lambda *a:SimpleNamespace())
    monkeypatch.setattr('layer3_graphrag.embeddings.create_provider',lambda *a:object())
    checked=[]
    monkeypatch.setattr('layer3_graphrag.pipeline.load_artifacts',lambda *a:checked.append(True))
    target=root/'outputs/runs/new'
    assert processing.reuse_global_base(root,target,raw,config,'raw',probe=True,require_graph=True)=='outputs/runs/old'
    assert not target.exists() and checked
    processing.prepare(root,target,raw,'raw',config)
    assert read(runner.run_file(target,'run.json'))['counts']['proyectos']==2
    def incompatible(*a):raise ValueError('embedding fingerprint changed')
    monkeypatch.setattr('layer3_graphrag.pipeline.load_artifacts',incompatible)
    assert not processing.reuse_global_base(root,root/'unused',raw,config,'raw',probe=True,require_graph=True)
    with pytest.raises(ValueError,match='No existe conocimiento'):
        processing.prepare(root,root/'outputs/runs/refused',raw,'raw',config)


def test_rebuild_bypasses_reuse_and_enters_existing_preparation(tmp_path,monkeypatch):
    from layer2_processing import pipeline as processing
    root=tmp_path;raw=root/'raw';raw.mkdir()
    (root/'catalog.xlsx').write_bytes(b'synthetic')
    monkeypatch.setattr(processing,'code_hashes',lambda *a:{})
    monkeypatch.setattr(processing,'reuse_global_base',lambda *a,**kw:pytest.fail('Rebuild must not reuse'))
    def enter(*args):raise ValueError('SYNTHETIC_PREPARATION_REACHED')
    monkeypatch.setattr(processing,'prepare_files',enter)
    with pytest.raises(ValueError,match='SYNTHETIC_PREPARATION_REACHED'):
        processing.prepare(root,root/'outputs/runs/new',raw,'raw',dict(knowledge_scope='BASE_GLOBAL_V1',
            reference_catalog='catalog.xlsx',base_knowledge_action='rebuild'))


@pytest.mark.parametrize('published',[False,True])
def test_global_base_reuses_knowledge_across_selections_and_invalidates_changed_sources(sandbox,monkeypatch,published):
    from layer2_processing.pipeline import reuse_global_base
    from layer2_processing.preprocessing.adapters import sha
    root,_,config=sandbox
    base=setup_sources(root,[paper()])
    write(base/'extra_projects.json',[dict(id_actividad='P3',resumen='Additional valid project narrative')])
    write(root/'config/pipeline_manual.json',config)
    runner.execute_pipeline(root,source='base',project_ids=['P1'],through='knowledge',run_id='global1')
    first=runner.find_run(root,root/'outputs/runs','global1')
    manifest=first/'workspace/outputs/layer2/knowledge/_manifest.json';before=sha(manifest)
    assert {r['source_project_id'] for r in rows(first,'proyectos')}=={'P1','P2','P3'}
    assert len(read(runner.run_file(first,'raw_manifest.json'))['files'])==4
    assert len(rows(first,'articulos'))==1
    if published:
        write(first/'workspace/outputs/layer3/publication/_manifest.json',{'synthetic_only':True})
        write(first/'workspace/outputs/layer3/publication/graph/graph.json',{'synthetic_only':True})
        checks=[]
        monkeypatch.setattr('layer3_graphrag.manifest.validate_publication',lambda path,fingerprint:checks.append(fingerprint))
    runner.execute_pipeline(root,source='base',project_ids=['P2'],through='knowledge',run_id='global2')
    second=runner.find_run(root,root/'outputs/runs','global2')
    state=read(runner.run_file(second,'run.json'))
    assert state['global_reuse']['source_run']=='global1'
    assert state['global_reuse']['graph_reused']==published
    if published:
        assert checks==[before]
        assert sha(first/'workspace/outputs/layer3/publication/graph/graph.json')==sha(second/'workspace/outputs/layer3/publication/graph/graph.json')
    assert sha(second/'workspace/outputs/layer2/knowledge/_manifest.json')==before==sha(manifest)
    assert read(runner.run_file(second,'execution.json'))['project_ids']==['P2']
    assert not (second/'evaluation').exists()
    runner.check(root,second)
    write(base/'produccion.json',[paper('CHANGED')])
    assert not reuse_global_base(root,root/'outputs/runs/unused',base,state['configuration'],'raw')
    with pytest.raises(ValueError,match='RAW cambio'):
        runner.check(root,second)


@pytest.mark.parametrize('selector', ['file', 'delivery'])
def test_count_sampling_respects_selected_input(sandbox, selector):
    from .test_layer1_intake import official_project_file
    root, _, _ = sandbox
    source = official_project_file(root, records=[
        dict(id_actividad=f'{i:05}', resumen='Synthetic project evidence') for i in range(6)])
    kwargs = dict(input_file=source.relative_to(root).as_posix()) if selector == 'file' else dict(delivery='entrega_test')
    result = runner.execute_pipeline(root, limit=3, seed=42, dry_run=True, run_id='sample', **kwargs)
    assert result['status'] == 'VALIDATED_SELECTION'
    run = runner.find_run(root,root/'outputs/runs','sample')
    manifest = read(run / 'preprocess/selection_manifest.json')
    selected = manifest['project_ids']
    assert len(selected) == len(set(selected)) == 3
    assert set(selected) <= {f'{i:05}' for i in range(6)}
    assert {r['source_project_id'] for r in rows(run, 'proyectos')} == set(selected)
    assert not (run / 'workspace/outputs/layer3').exists()


def test_distinct_researcher_namespace_and_repeated_narratives(sandbox):
    root, _, config = sandbox
    first = paper()
    second = paper()
    second['resumen'] = 'Another authorized original narrative'
    setup_sources(root, [first, second], extra_members=[dict(id_actividad='P1', id_empleado='EMP1',
        id_investigador='NOT_AN_EMPLOYEE_ALIAS', documento='DOC1', nombre_completo='Synthetic One')])
    write(root / 'config/pipeline_manual.json', config)
    result = runner.execute_pipeline(root, all_projects=True, dry_run=True, run_id='narratives')
    assert result['status'] == 'VALIDATED_SELECTION'
    run = runner.find_run(root,root/'outputs/runs','narratives')
    assert len(rows(run, 'articulos')) == 1
    assert all(p['identity_status'] == 'resolved' for p in rows(run, 'investigadores'))
    runner.knowledge(root, run)
    import pyarrow.parquet as pq
    sections = pq.read_table(run / 'workspace/outputs/layer2/knowledge/source_sections.parquet').to_pylist()
    assert any(s['text_original'] == second['resumen'] for s in sections)
    assert all(s['source_id'] in {'PROJ_P1','PROJ_P2','ART_SRC_A1'} for s in sections)


def test_console_never_defaults_to_whole_database(monkeypatch):
    monkeypatch.setattr(console, 'coordinator', lambda: object())
    with pytest.raises(ValueError, match='nunca'):
        console.dispatch(console.parser().parse_args(['run']))
    with pytest.raises(SystemExit):
        console.parser().parse_args(['--all', '--limit', '10'])


def test_bare_flags_and_menu_use_same_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(console, 'dispatch', lambda args: calls.append(args) or dict(status='VALIDATED_SELECTION'))
    assert console.main(['--limit', '10', '--seed', '17', '--dry-run']) == 0
    assert calls[-1].command == 'run' and calls[-1].limit == 10 and calls[-1].seed == 17
    answers = iter(['1', '2', '1', '10', '0'])
    monkeypatch.setattr('builtins.input', lambda *a: next(answers))
    assert console.main([]) == 0
    assert calls[-1].limit == 10 and calls[-1].seed == 42


def test_native_incoming_selection_never_reads_base(sandbox,monkeypatch):
    from .test_layer1_intake import official_project_file
    from layer2_processing.preprocessing import adapters
    root,_,_=sandbox
    setup_sources(root,[paper()])
    incoming=official_project_file(root,records=[dict(id_actividad='LOCAL',resumen='Synthetic local narrative')])
    original=adapters.read_source
    def selected_only(path,*args,**kwargs):
        assert 'base' not in path.parts
        return original(path,*args,**kwargs)
    monkeypatch.setattr(adapters,'read_source',selected_only)
    config,raw,_=runner.selected_configuration(root,'config/pipeline_manual.json',input_file=incoming.relative_to(root).as_posix())
    selected=select(root,raw,config,all_projects=True)
    assert selected['project_ids']==['LOCAL']
    assert all('/incoming/' in name or '/reference/' in name for name in selected['sources'])
