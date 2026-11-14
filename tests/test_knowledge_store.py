"""Shared BASE knowledge registry: synthetic checkpoints, no models, embeddings or rebuilds.

Heavy GraphRAG validators (publication hashes, vector/graph loading) are replaced
by recording fakes; the registry logic, RAW/catalog checks, atomic pointers,
run references and checkpoint integrity of the real ``check()`` are exercised.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

import knowledge_store as store
from layer2_processing import pipeline as processing
from layer2_processing.preprocessing.adapters import read, sha, write
from run_paths import file_path as run_file

KNOWLEDGE_CODE = 'src/layer3_graphrag/synthetic.py'
REAL_CHECK = processing.check  # Captured before the fixture replaces the builder check.


def tree_hash(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(Path(folder).rglob('*')) if p.is_file()}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / 'repo with spaces'
    (root / 'data/raw').mkdir(parents=True)
    (root / 'data/raw/a.csv').write_text('id,resumen\n1,texto\n', encoding='utf-8')
    (root / 'data/catalog.xlsx').write_bytes(b'catalog-v1')
    (root / 'src/layer3_graphrag').mkdir(parents=True)
    (root / KNOWLEDGE_CODE).write_text('VERSION = 1\n', encoding='utf-8')
    for name in ('scripts/run_pipeline_manual.py', 'scripts/pipeline_coordinator.py', 'config/sources.example.yaml',
                 'config/layer1.yaml', 'config/layer2.yaml', 'config/layer3.yaml'):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text('# synthetic\n', encoding='utf-8')
    deep = []

    def fake_check(root_, run, *, knowledge_only=False):
        state = read(run_file(run, 'run.json'))
        if state['status'] != 'PREPARED':
            raise ValueError('Preparacion incompleta')
        for name, digest in state['code_hashes'].items():
            if sha(Path(root_) / name) != digest:
                raise ValueError('Codigo de conocimiento modificado')
        for name, digest in read(run_file(run, 'prepared_hashes.json')).items():
            if sha(run / name) != digest:
                raise ValueError('Producto de preprocesamiento modificado: ' + name)
        if state.get('knowledge_ref'):
            store.resolve_reference(root_, state['knowledge_ref'])
        return state

    def fake_publication(folder, knowledge_hash):
        if read(Path(folder) / '_manifest.json')['knowledge_manifest_sha256'] != knowledge_hash:
            raise ValueError('Publicacion de otro conocimiento')

    # Import first: modules that bind these names at import time must capture the
    # real functions, so reverting the patches cannot leak fakes into later tests.
    import layer3_graphrag.pipeline, layer3_graphrag.configuration, layer3_graphrag.validate_inputs  # noqa: F401
    import layer3_graphrag.embeddings, layer3_graphrag.manifest  # noqa: F401
    monkeypatch.setattr(processing, 'check', fake_check)
    monkeypatch.setattr('layer3_graphrag.manifest.validate_publication', fake_publication)
    monkeypatch.setattr('layer3_graphrag.configuration.load_config', lambda ws: ({'embeddings': {}}, None))
    monkeypatch.setattr('layer3_graphrag.validate_inputs.validate_inputs', lambda ws, cfg: None)
    monkeypatch.setattr('layer3_graphrag.embeddings.create_provider', lambda settings: None)
    monkeypatch.setattr('layer3_graphrag.pipeline.load_artifacts', lambda ws, *a: deep.append(Path(ws)))
    return root, deep


def config(root, **changes):
    return dict(dict(knowledge_scope='BASE_GLOBAL_V1', reference_catalog='data/catalog.xlsx', raw_base='data',
                     text_columns=['resumen']), **changes)


def builder(root, name, *, label='v1'):
    """A sealed PREPARED checkpoint with a published (synthetic) GraphRAG."""
    run = root / 'outputs/runs/local' / name
    ws = run / 'workspace/outputs'
    write(ws / 'layer2/canonical/_manifest.json', {'canonical': label})
    write(ws / 'layer2/knowledge/_manifest.json', {'knowledge': label})
    (ws / 'layer2/knowledge/source_chunks.parquet').write_bytes(b'large-chunks-' + label.encode() * 1000)
    write(ws / 'layer3/publication/_manifest.json', dict(knowledge_manifest_sha256=sha(ws / 'layer2/knowledge/_manifest.json'),
        embedding_config_hash='emb', embedding_model='BAAI/bge-m3', model_revision='rev', source_embedding_count=3,
        reference_embedding_count=2, vector_indexes={'source': {'count': 3}}, node_count=5, edge_count=4, layer3_run_id=name))
    (ws / 'layer3/publication/indexes').mkdir(parents=True)
    (ws / 'layer3/publication/indexes/vectors.npy').write_bytes(b'vectors-' + label.encode() * 1000)
    write(ws / 'layer3/query_cache/q.json', {'key': 'q'})
    write(run_file(run, 'raw_manifest.json'), {'raw': str(root / 'data/raw'), 'files': {'a.csv': sha(root / 'data/raw/a.csv')}})
    write(run_file(run, 'run.json'), dict(run_id=name, dataset='raw', raw_path='data/raw', status='PREPARED',
        configuration=config(root, llm={'provider': 'ollama'}, base_knowledge_action='rebuild'),
        code_hashes={KNOWLEDGE_CODE: sha(root / KNOWLEDGE_CODE)}, global_catalog_sha256=sha(root / 'data/catalog.xlsx'),
        counts={'proyectos': 2}, knowledge_counts={'source_chunks': 3}))
    sealed = {p.relative_to(run).as_posix(): sha(p) for p in (run / 'workspace/outputs/layer2').rglob('*') if p.is_file()}
    write(run_file(run, 'prepared_hashes.json'), sealed)
    return run


def new_run(root, name, cfg):
    run = root / 'outputs/runs/local' / name
    write(run_file(run, 'run.json'), dict(status='REGISTERED', dataset='raw', raw_path='data/raw', configuration=cfg))
    return run


def test_register_creates_manifest_without_touching_checkpoint(repo):
    root, deep = repo
    old = builder(root, 'run_builder')
    before = tree_hash(old)
    manifest = store.register(root, old, activate=True)
    assert tree_hash(old) == before  # In place: nothing copied, moved or edited.
    saved, manifest_sha = store.load_version(root, manifest['version_id'])
    assert saved['location'] == 'outputs/runs/local/run_builder' and saved['storage'] == 'IN_PLACE_SEALED_CHECKPOINT'
    assert set(saved['components']) == {'preprocessing', 'knowledge', 'embeddings', 'vector_indexes', 'graph', 'publication', 'query_cache'}
    active = store.read_active(root)
    assert active['version_id'] == manifest['version_id'] and active['manifest_sha256'] == manifest_sha and deep
    assert store.register(root, old)['version_id'] == manifest['version_id']  # Idempotent.


def test_fingerprint_ignores_prompt_policy_contract_and_selection(repo):
    root, _ = repo
    state = read(run_file(builder(root, 'run_builder'), 'run.json'))
    raw = read(run_file(root / 'outputs/runs/local/run_builder', 'raw_manifest.json'))
    base = store.identity(state, raw)
    for change in (dict(llm={'model': 'other'}), dict(evaluation_policy={'mode': 'x'}), dict(project_selection={'ids': ['1']}),
                   dict(evaluation={'contract': 'THESIS_VALID_ASSESSMENTS_V2'}), dict(base_knowledge_source='shared:x')):
        assert store.identity(dict(state, configuration=state['configuration'] | change), raw) == base
    assert store.identity(dict(state, configuration=state['configuration'] | dict(text_columns=['x'])), raw) != base
    assert store.identity(dict(state, code_hashes={KNOWLEDGE_CODE: 'other'}), raw) != base
    assert store.identity(dict(state, code_hashes=state['code_hashes'] | {'src/layer4_evaluation/prompt.py': 'p'}), raw) == base


def test_compatible_selects_active_and_rejects_incompatible_requests(repo):
    root, _ = repo
    manifest = store.register(root, builder(root, 'run_builder'), activate=True)
    found, _ = store.compatible(root, root / 'data/raw', config(root, llm={'provider': 'openai'}), 'raw')
    assert found['version_id'] == manifest['version_id']
    with pytest.raises(store.KnowledgeUnavailable, match='configuracion de datos'):
        store.compatible(root, root / 'data/raw', config(root, text_columns=['otra']), 'raw')
    with pytest.raises(store.KnowledgeUnavailable, match='dataset'):
        store.compatible(root, root / 'data/raw', config(root), 'other')
    (root / 'data/catalog.xlsx').write_bytes(b'catalog-v2')
    with pytest.raises(store.KnowledgeUnavailable, match='catalogo'):
        store.compatible(root, root / 'data/raw', config(root), 'raw')
    (root / 'data/catalog.xlsx').write_bytes(b'catalog-v1')
    (root / 'data/raw/a.csv').write_text('changed', encoding='utf-8')
    with pytest.raises(store.KnowledgeUnavailable, match='fuentes RAW'):
        store.compatible(root, root / 'data/raw', config(root), 'raw')


def test_no_active_version_is_reported_not_rebuilt(repo):
    root, _ = repo
    with pytest.raises(store.KnowledgeUnavailable, match='No hay version'):
        store.compatible(root, root / 'data/raw', config(root), 'raw')
    run = new_run(root, 'run_eval', config(root, base_knowledge_action='reuse'))
    assert processing.reuse_global_base(root, run, root / 'data/raw', config(root), 'raw', probe=True) is False
    assert 'No hay version' in processing.reuse_global_base.last_reason


@pytest.mark.parametrize('damage', ['missing', 'corrupt_sealed', 'corrupt_publication', 'corrupt_cache', 'code'])
def test_missing_or_corrupt_components_are_detected(repo, damage):
    root, _ = repo
    run = builder(root, 'run_builder')
    manifest = store.register(root, run, activate=True)
    ws = run / 'workspace/outputs'
    if damage == 'missing':
        (ws / 'layer3/publication/_manifest.json').unlink()
    elif damage == 'corrupt_sealed':
        (ws / 'layer2/knowledge/source_chunks.parquet').write_bytes(b'tampered')
    elif damage == 'corrupt_publication':
        published = read(ws / 'layer3/publication/_manifest.json'); published['node_count'] = 6
        write(ws / 'layer3/publication/_manifest.json', published)
    elif damage == 'corrupt_cache':
        write(ws / 'layer3/query_cache/q.json', {'key': 'tampered'})
    else:
        (root / KNOWLEDGE_CODE).write_text('VERSION = 2\n', encoding='utf-8')
    with pytest.raises(ValueError):
        store.verify(root, manifest, deep=False)
    with pytest.raises(ValueError):
        store.compatible(root, root / 'data/raw', config(root), 'raw')


def test_tampered_registry_manifest_or_pointer_is_rejected(repo):
    root, _ = repo
    manifest = store.register(root, builder(root, 'run_builder'), activate=True)
    path = store.manifest_path(root, manifest['version_id'])
    value = read(path); value['location'] = 'outputs/runs/local/other'
    write(path, value)
    with pytest.raises(ValueError):
        store.compatible(root, root / 'data/raw', config(root), 'raw')
    with pytest.raises(ValueError, match='invalido'):
        store.load_version(root, '../escape')


def test_activation_is_atomic_and_previous_survives_a_failed_candidate(repo, monkeypatch):
    root, _ = repo
    first = store.register(root, builder(root, 'run_v1'), activate=True)
    pointer = store.read_active(root)
    # A second (complete) version registered but with a failure during activation.
    second_run = builder(root, 'run_v2', label='v2')
    second = store.register(root, second_run)
    assert store.read_active(root) == pointer  # Registration alone never activates.
    def broken(*a, **kw):
        raise ValueError('fallo simulado durante la verificacion profunda')
    monkeypatch.setattr('layer3_graphrag.pipeline.load_artifacts', broken)
    with pytest.raises(ValueError, match='fallo simulado'):
        store.activate_version(root, second['version_id'])
    assert store.read_active(root) == pointer and not (store.shared_root(root) / 'active.json.tmp').exists()
    # An incomplete build (no publication) can never be registered or activated.
    incomplete = builder(root, 'run_partial', label='v3')
    (incomplete / 'workspace/outputs/layer3/publication/_manifest.json').unlink()
    with pytest.raises(ValueError, match='GraphRAG publicado'):
        store.register(root, incomplete, activate=True)
    assert store.read_active(root)['version_id'] == first['version_id']


def test_new_active_version_does_not_change_earlier_run_reference(repo):
    root, _ = repo
    first = store.register(root, builder(root, 'run_v1'), activate=True)
    run = new_run(root, 'run_eval', config(root, base_knowledge_action='reuse'))
    assert processing.reuse_global_base(root, run, root / 'data/raw', config(root, base_knowledge_action='reuse'), 'raw', require_graph=True)
    ref = read(run_file(run, 'run.json'))['knowledge_ref']
    second = store.register(root, builder(root, 'run_v2', label='v2'), activate=True)
    assert store.read_active(root)['version_id'] == second['version_id'] != first['version_id']
    assert read(run_file(run, 'run.json'))['knowledge_ref'] == ref
    assert store.knowledge_root(run) == (root / 'outputs/runs/local/run_v1').resolve()
    assert store.resolve_reference(root, ref) == (root / 'outputs/runs/local/run_v1').resolve()


def test_reuse_references_without_copying_and_checks_through_the_version(repo):
    root, deep = repo
    store.register(root, builder(root, 'run_builder'), activate=True)
    cfg = config(root, base_knowledge_action='reuse', llm={'provider': 'ollama'})
    run = new_run(root, 'run_eval', cfg)
    probe = processing.reuse_global_base(root, run, root / 'data/raw', cfg, 'raw', probe=True, require_graph=True)
    assert probe.startswith(store.REFERENCE_PREFIX)
    cfg['base_knowledge_source'] = probe
    assert processing.reuse_global_base(root, run, root / 'data/raw', cfg, 'raw', require_graph=True) is True
    state = read(run_file(run, 'run.json'))
    assert state['status'] == 'PREPARED' and state['storage_layout'] == store.RUN_LAYOUT
    assert state['knowledge_ref']['version_id'] == probe[len(store.REFERENCE_PREFIX):]
    assert not (run / 'workspace').exists() and not (run / 'preprocess').exists()
    size = sum(p.stat().st_size for p in run.rglob('*') if p.is_file())
    assert size < 20_000  # Only small receipts, never the knowledge artifacts.
    assert store.knowledge_workspace(run) == (root / 'outputs/runs/local/run_builder/workspace').resolve()
    assert store.evaluation_dir(run) == run / 'evaluation'
    # The real run check verifies RAW, code and seals of the run and, through its
    # reference, the shared version (builder check replaced by the fixture).
    assert REAL_CHECK(root, run)['knowledge_ref'] == state['knowledge_ref']
    with pytest.raises(ValueError, match='No sobrescribir'):
        processing.reuse_global_base(root, run, root / 'data/raw', cfg, 'raw')


def test_sampling_selection_keeps_documented_copy_from_the_registered_version(repo, monkeypatch):
    root, _ = repo
    source = builder(root, 'run_builder')
    store.register(root, source, activate=True)
    before = tree_hash(source)
    validated = []
    monkeypatch.setattr('layer2_processing.preprocessing.project_selection.validate_selection',
                        lambda root_, run: validated.append(run.name))
    cfg = config(root, base_knowledge_action='reuse', project_selection={'project_ids': ['1']})
    run = new_run(root, 'run_sample', cfg)
    assert processing.reuse_global_base(root, run, root / 'data/raw', cfg, 'raw', require_graph=True) is True
    state = read(run_file(run, 'run.json'))
    assert state['global_reuse']['source_run'] == 'run_builder' and 'knowledge_ref' not in state
    assert (run / 'workspace/outputs/layer3/publication/_manifest.json').is_file() and validated == ['run_sample']
    assert tree_hash(source) == before


def test_reference_check_fails_when_shared_artifacts_change(repo):
    root, _ = repo
    run_builder = builder(root, 'run_builder')
    store.register(root, run_builder, activate=True)
    cfg = config(root, base_knowledge_action='reuse')
    run = new_run(root, 'run_eval', cfg)
    assert processing.reuse_global_base(root, run, root / 'data/raw', cfg, 'raw')
    REAL_CHECK(root, run)
    (run_builder / 'workspace/outputs/layer2/knowledge/source_chunks.parquet').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='modificado'):
        REAL_CHECK(root, run)


def test_legacy_runs_keep_their_own_layout(repo):
    root, _ = repo
    legacy = builder(root, 'run_20261114_053532_061299')
    state = read(run_file(legacy, 'run.json')); state['global_reuse'] = {'source_run': 'run_x', 'graph_reused': True}
    write(run_file(legacy, 'run.json'), state)
    before = tree_hash(legacy)
    assert store.knowledge_workspace(legacy) == legacy / 'workspace'
    assert store.evaluation_dir(legacy) == legacy / 'workspace/outputs/layer4'
    (legacy / 'layer5_results').mkdir()
    assert store.evaluation_dir(legacy) == legacy / 'layer5_results'
    (legacy / 'layer5_results').rmdir()
    with pytest.raises(ValueError, match='no un run que lo referencia o copio'):
        store.register(root, legacy)  # Copies are not registered as originals.
    assert tree_hash(legacy) == before


def test_retention_pins_checkpoints_backing_registered_versions(repo):
    root, _ = repo
    run = builder(root, 'run_builder')
    store.register(root, run, activate=True)
    assert run.resolve() in store.registered_locations(root)
    from run_retention import plan
    rows = {r['key']: r for r in plan(root, dict(version=1, keep_recent=1))}
    assert rows['local/run_builder']['reason'].startswith('Pinned')
