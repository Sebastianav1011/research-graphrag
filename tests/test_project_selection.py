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
    run = root / 'outputs/runs/all'
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
    assert {r['source_project_id'] for r in rows(root / 'outputs/runs/one', 'proyectos')} == {'P1'}
    # The same strong researcher identity survives independently scoped runs.
    all_ids = {r['researcher_id'] for r in rows(run, 'proyecto_investigador') if r['project_id'] == 'PROJ_P1'}
    assert all_ids == {r['researcher_id'] for r in rows(root / 'outputs/runs/one', 'proyecto_investigador')}
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


@pytest.mark.parametrize('selector', ['file', 'delivery'])
def test_count_sampling_respects_selected_input(sandbox, selector):
    from .test_layer1_intake import official_project_file
    root, _, _ = sandbox
    source = official_project_file(root, records=[
        dict(id_actividad=f'{i:05}', resumen='Synthetic project evidence') for i in range(6)])
    kwargs = dict(input_file=source.relative_to(root).as_posix()) if selector == 'file' else dict(delivery='entrega_test')
    result = runner.execute_pipeline(root, limit=3, seed=42, dry_run=True, run_id='sample', **kwargs)
    assert result['status'] == 'VALIDATED_SELECTION'
    run = root / 'outputs/runs/sample'
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
    run = root / 'outputs/runs/narratives'
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
    answers = iter(['1', 'base', '', '1', '10', 'preprocessing', '0'])
    monkeypatch.setattr('builtins.input', lambda *a: next(answers))
    assert console.main([]) == 0
    assert calls[-1].limit == 10 and calls[-1].seed == 42
