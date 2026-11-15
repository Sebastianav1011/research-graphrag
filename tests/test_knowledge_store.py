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
    def load_artifacts(ws, *a):
        deep.append(Path(ws))
        return read(Path(ws) / 'outputs/layer3/publication/_manifest.json'), {}, None
    monkeypatch.setattr('layer3_graphrag.pipeline.load_artifacts', load_artifacts)
    return root, deep


def config(root, **changes):
    return dict(dict(knowledge_scope='BASE_GLOBAL_V1', reference_catalog='data/catalog.xlsx', raw_base='data',
                     text_columns=['resumen']), **changes)


def builder(root, name, *, label='v1', shared=False):
    """A sealed PREPARED checkpoint with a published (synthetic) GraphRAG."""
    run = root / ('outputs/shared/base/staging' if shared else 'outputs/runs/local') / name
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


@pytest.mark.parametrize('shared', [False, True])
def test_sampling_selection_validates_without_persistent_knowledge_copy(repo, shared):
    root, _ = repo
    source = builder(root, 'run_builder', shared=shared)
    import pyarrow as pa
    import pyarrow.parquet as pq
    from layer2_processing.preprocessing.contracts import KEYS
    from layer2_processing.preprocessing.project_selection import digest
    folder = source / 'workspace/outputs/layer2/canonical'
    for name, keys in KEYS.items():
        row = {key: '1' for key in keys}
        if name == 'proyectos':
            row['source_project_id'] = '1'
        pq.write_table(pa.Table.from_pylist([row]), folder / (name + '.parquet'))
    processing.seal(source)
    manifest = store.register(root, source, activate=True)
    source = store.location(root, manifest)
    before = tree_hash(source)
    cfg = config(root, base_knowledge_action='reuse', project_selection={
        'project_ids': ['1'], 'selection_sha256': digest(['1']), 'sources': {'data/raw/a.csv': sha(root / 'data/raw/a.csv')}})
    run = new_run(root, 'run_sample', cfg)
    assert processing.reuse_global_base(root, run, root / 'data/raw', cfg, 'raw', require_graph=True) is True
    state = read(run_file(run, 'run.json'))
    assert 'knowledge_ref' in state and 'global_reuse' not in state
    assert not (run / 'workspace').exists()
    report = read(run / 'preprocess/selection_manifest.json')
    assert report['status'] == 'VALIDATED_SELECTION' and report['evaluation_project_ids'] == ['1']
    assert not list((store.shared_root(root) / 'validation').iterdir())
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


def test_shared_publication_renames_and_keeps_legacy_pin(repo):
    root, _ = repo
    old = builder(root, 'old')
    previous = store.register(root, old, activate=True)
    old_bytes = tree_hash(old)
    old_manifest = store.manifest_path(root, previous['version_id']).read_bytes()
    pointer = (store.shared_root(root) / 'active.json').read_bytes()
    stage = builder(root, 'build-new', label='new', shared=True)
    stage_bytes = tree_hash(stage)
    expected = store.describe(root, stage)
    new = store.register(root, stage)
    final = store.location(root, new)
    assert final == store.shared_root(root) / 'versions' / new['version_id'] / 'artifacts'
    assert new['storage'] == 'SHARED_SEALED_CHECKPOINT' and new['artifact_inventory_sha256']
    assert new['version_id'] == expected['version_id'] != previous['version_id']
    assert tree_hash(final) == stage_bytes and not stage.exists()
    assert new['location'] == final.relative_to(root).as_posix()
    assert (store.shared_root(root) / 'active.json').read_bytes() == pointer
    store.activate_version(root, new['version_id'])
    assert store.read_active(root)['previous']['version_id'] == previous['version_id']
    assert tree_hash(old) == old_bytes and store.manifest_path(root, previous['version_id']).read_bytes() == old_manifest
    cfg = config(root, base_knowledge_action='reuse')
    run = new_run(root, 'new-evaluation', cfg)
    assert processing.reuse_global_base(root, run, root / 'data/raw', cfg, 'raw')
    assert store.knowledge_root(run) == final
    assert not (run / 'workspace').exists()
    assert REAL_CHECK(root, run)['knowledge_ref']['version_id'] == new['version_id']


@pytest.mark.parametrize('cut', ['rename', 'manifest'])
def test_shared_publication_recovers_interruption_without_touching_previous(repo, monkeypatch, cut):
    root, _ = repo
    old = store.register(root, builder(root, 'old'), activate=True)
    previous = (store.shared_root(root) / 'active.json').read_bytes()
    stage = builder(root, 'build-new', label='new', shared=True)
    described = store.describe(root, stage)
    path = store.manifest_path(root, described['version_id'])
    replace = os.replace
    failed = []
    def interrupt(src, dst):
        dst = Path(dst)
        if not failed and ((cut == 'rename' and dst.name == 'artifacts') or (cut == 'manifest' and dst == path)):
            failed.append(True)
            raise OSError('simulated interruption')
        return replace(src, dst)
    monkeypatch.setattr(store.os, 'replace', interrupt)
    with pytest.raises(OSError, match='simulated'):
        store.register(root, stage, activate=True)
    assert (store.shared_root(root) / 'active.json').read_bytes() == previous
    assert not path.exists()
    # Retry the original durable builder locator, including when rename succeeded.
    new = store.register(root, stage, activate=True)
    assert not stage.exists() and store.location(root, new).is_dir()
    assert store.read_active(root)['previous']['version_id'] == old['version_id']
    assert new['location'].endswith('/artifacts')


def test_new_version_inventory_changes_for_actual_artifact_changes(repo):
    root, _ = repo
    stage = builder(root, 'build-new', shared=True)
    first = store.describe(root, stage)
    write(stage / 'workspace/outputs/layer3/query_cache/q.json', {'key': 'changed'})
    second = store.describe(root, stage)
    assert first['fingerprint'] == second['fingerprint']
    assert first['version_id'] != second['version_id']
    assert first['artifact_inventory_sha256'] != second['artifact_inventory_sha256']


def test_existing_version_is_never_relocated_or_overwritten(repo):
    root, _ = repo
    stage = builder(root, 'build-new', shared=True)
    new = store.register(root, stage)
    before = tree_hash(store.shared_root(root))
    assert store.register(root, stage) == new  # Durable journal makes retry idempotent.
    assert tree_hash(store.shared_root(root)) == before
    # A different builder with identical output bytes cannot replace final artifacts.
    import shutil
    other = store.shared_root(root) / 'staging' / 'another'
    shutil.copytree(store.location(root, new), other)
    with pytest.raises(ValueError, match='ya existe'):
        store.register(root, other)
    assert tree_hash(store.location(root, new)) == tree_hash(other)


def test_prepare_new_base_is_shared_from_first_checkpoint_and_resume_is_pinned(repo, monkeypatch):
    root, _ = repo
    from scripts import pipeline_coordinator as coordinator
    monkeypatch.setattr(coordinator, 'check', REAL_CHECK)
    calls = []
    def prepare_checkpoint(root_, run_, raw, dataset, cfg, through):
        calls.append(run_)
        assert run_.parent == store.shared_root(root) / 'staging'
        assert 'project_selection' not in cfg
        if not run_.exists():
            builder(root, run_.name, label='new', shared=True)
        return dict(status='PREPARED', run=str(run_))
    monkeypatch.setattr(processing, '_prepare_checkpoint', prepare_checkpoint)
    cfg = config(root, base_knowledge_action='rebuild')
    run = new_run(root, 'new-evaluation', cfg)
    result = processing.prepare(root, run, root / 'data/raw', 'raw', cfg)
    assert result['status'] == 'PREPARED' and not (run / 'workspace').exists()
    stage = store.knowledge_root(run)
    assert stage.parent == store.shared_root(root) / 'staging'
    assert REAL_CHECK(root, run)['status'] == 'PREPARED'
    processing.prepare(root, run, root / 'data/raw', 'raw', cfg)
    assert calls == [stage, stage]  # Resume uses the same durable checkpoint.
    request = {}
    manifest = coordinator.register_built_knowledge(root, run, request)
    state = read(run_file(run, 'run.json'))
    assert not stage.exists() and 'knowledge_build' not in state
    assert state['knowledge_ref']['version_id'] == manifest['version_id']
    assert request['knowledge_version']['location'] == manifest['location']
    assert store.knowledge_workspace(run) == store.location(root, manifest) / 'workspace'
    assert store.evaluation_dir(run) == run / 'evaluation'
    assert REAL_CHECK(root, run)['status'] == 'PREPARED'
    assert processing.prepare(root, run, root / 'data/raw', 'raw', cfg)['status'] == 'ALREADY_PREPARED'


def test_activation_recovery_preserves_previous_and_execution_receipt(repo, monkeypatch):
    root, _ = repo
    from scripts import pipeline_coordinator as coordinator
    old = store.register(root, builder(root, 'old'), activate=True)
    stage = builder(root, 'build-new', label='new', shared=True)
    cfg = config(root, base_knowledge_action='rebuild')
    run = new_run(root, 'new-evaluation', cfg)
    state = read(run_file(run, 'run.json'))
    state.update(status='PREPARED', knowledge_build=stage.relative_to(root).as_posix(), storage_layout=store.RUN_LAYOUT)
    write(run_file(run, 'run.json'), state)
    processing._sync_shared_build(root, run, stage)
    original = coordinator.write
    failed = []
    def interrupt(path, value):
        if Path(path) == run_file(run, 'run.json') and 'knowledge_ref' in value and 'knowledge_activation_pending' not in value and not failed:
            failed.append(True)
            raise OSError('interrupted after activation')
        return original(path, value)
    monkeypatch.setattr(coordinator, 'write', interrupt)
    with pytest.raises(OSError, match='interrupted'):
        coordinator.register_built_knowledge(root, run, {})
    pointer = (store.shared_root(root) / 'active.json').read_bytes()
    assert store.read_active(root)['previous']['version_id'] == old['version_id']
    request = {}
    manifest = coordinator.register_built_knowledge(root, run, request)
    assert (store.shared_root(root) / 'active.json').read_bytes() == pointer
    assert not read(run_file(run, 'run.json')).get('knowledge_activation_pending')
    assert read(run_file(run, 'execution.json'))['knowledge_version']['version_id'] == manifest['version_id']
    assert request['knowledge_version']['location'] == manifest['location']


def test_partial_export_reads_evaluation_directory(repo, monkeypatch):
    root, _ = repo
    from scripts import export_verified_partial as recovery
    cfg = config(root, base_knowledge_action='reuse')
    store.register(root, builder(root, 'old'), activate=True)
    run = new_run(root, 'new-evaluation', cfg)
    assert processing.reuse_global_base(root, run, root / 'data/raw', cfg, 'raw')
    directory = run / 'evaluation/batch_one'
    directory.mkdir(parents=True)
    monkeypatch.setattr(recovery.coordinator, 'check', REAL_CHECK)
    monkeypatch.setattr(recovery.live, 'verify_run', lambda folder: {'verified': str(folder)})
    assert recovery.collect(root, run) == [dict(directory=str(directory), state={'verified': str(directory)})]


def test_shared_graph_reader_and_autonomous_pending_guard(repo, monkeypatch):
    root, deep = repo
    from scripts import pipeline_coordinator as coordinator
    from autonomous_execution import lifecycle
    stage = builder(root, 'build-new', shared=True)
    run = new_run(root, 'new-evaluation', config(root, base_knowledge_action='rebuild'))
    state = read(run_file(run, 'run.json'))
    state.update(knowledge_build=stage.relative_to(root).as_posix(), storage_layout=store.RUN_LAYOUT)
    write(run_file(run, 'run.json'), state)
    coordinator.validated_graph(root, run)
    assert deep[-1] == stage / 'workspace'
    (stage / 'workspace/outputs/layer3/publication/_manifest.json').unlink()
    monkeypatch.setattr(lifecycle.p, 'validate', lambda value: value)
    with pytest.raises(ValueError, match='through graphrag'):
        lifecycle.prepare(root, run, {'workers': 1})
    assert not lifecycle.folder(run).exists()


def test_publication_receipt_corruption_fails_closed(repo, monkeypatch):
    root, _ = repo
    stage = builder(root, 'build-new', shared=True)
    replace = os.replace
    def stop_rename(src, dst):
        if Path(dst).name == 'artifacts':
            raise OSError('simulated cut')
        return replace(src, dst)
    monkeypatch.setattr(store.os, 'replace', stop_rename)
    with pytest.raises(OSError):
        store.register(root, stage)
    journal = store._promotion(root, stage)
    data = read(journal)
    data['schema'] = 'unexpected'
    write(journal, data)
    with pytest.raises(store.KnowledgeUnavailable, match='Recibo'):
        store.register(root, stage)
    assert stage.exists() and not store.manifest_path(root, data['manifest']['version_id']).exists()


def test_shared_researchers_never_fall_back_to_global_snapshot(repo):
    root, _ = repo
    import pyarrow as pa
    import pyarrow.parquet as pq
    from autonomous_execution.final_output import researchers
    stage = builder(root, 'build-new', shared=True)
    for base, institutional in [(stage / 'workspace/outputs/layer2/canonical', None),
                                 (root / 'outputs/layer2/canonical', 'WRONG-GLOBAL')]:
        base.mkdir(parents=True, exist_ok=True)
        for name, rows in {
            'proyectos': [dict(project_id='p', source_project_id='siap')],
            'investigadores': [dict(researcher_id='r', institutional_id=institutional)],
            'proyecto_investigador': [dict(project_id='p', researcher_id='r')]
        }.items():
            pq.write_table(pa.Table.from_pylist(rows), base / (name + '.parquet'))
    run = new_run(root, 'new-evaluation', config(root))
    state = read(run_file(run, 'run.json'))
    state['knowledge_build'] = stage.relative_to(root).as_posix()
    write(run_file(run, 'run.json'), state)
    assert researchers(root, run, {'siap_id': 'siap'}) == [None]


def test_autonomous_completes_pending_activation_before_sealing(repo, monkeypatch):
    root, _ = repo
    from autonomous_execution import lifecycle
    from scripts import pipeline_coordinator as coordinator
    stage = builder(root, 'build-new', shared=True)
    manifest = store.register(root, stage)
    _, checksum = store.load_version(root, manifest['version_id'])
    run = new_run(root, 'new-evaluation', config(root))
    state = read(run_file(run, 'run.json'))
    state.update(knowledge_ref=store.reference(manifest, checksum), knowledge_activation_pending=True)
    write(run_file(run, 'run.json'), state)
    write(run_file(run, 'execution.json'), {})
    monkeypatch.setattr(lifecycle.p, 'validate', lambda value: value)
    original = coordinator.register_built_knowledge
    calls = []
    def publish(*args):
        original(*args)
        calls.append(True)
        raise RuntimeError('stopped before autonomous seal')
    monkeypatch.setattr(coordinator, 'register_built_knowledge', publish)
    with pytest.raises(RuntimeError, match='before autonomous seal'):
        lifecycle.prepare(root, run, {'workers': 1})
    assert calls == [True] and not read(run_file(run, 'run.json')).get('knowledge_activation_pending')
    assert not (lifecycle.folder(run) / 'manifest.json').exists()
