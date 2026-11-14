"""Shared BASE knowledge: verified, versioned and referenced without per-run copies.

A version is a sealed PREPARED checkpoint with a published GraphRAG (the existing
run layout: ``manifiestos/run.json``, ``preprocess/`` and ``workspace/`` with
``outputs/layer2`` and ``outputs/layer3``). The registry only adds small JSON
files under ``outputs/shared/base``:

* ``versions/<version_id>/manifest.json``: identity (inputs that determine the
  artifacts), component digests and the location of the sealed artifacts.
* ``active.json``: atomic pointer to the active version and its manifest SHA-256.
* ``activations.jsonl``: append-only activation history.

Evaluation runs store ``knowledge_ref`` (version id + manifest SHA-256) and read
the artifacts where they are; activating another version later never changes
what an earlier run references. Registration never moves, copies or edits the
artifacts it describes, so historical runs and their hashes stay intact.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

SHARED = 'outputs/shared/base'
VERSION_SCHEMA = 'SHARED_BASE_KNOWLEDGE_V1'
RUN_LAYOUT = 'SHARED_KNOWLEDGE_REFERENCE_V1'
REFERENCE_PREFIX = 'shared:'
# Code/configuration whose bytes shape preprocessing, Knowledge and GraphRAG.
KNOWLEDGE_CODE = ('src/layer2_processing/preprocessing/', 'src/layer2_processing/knowledge/',
                  'src/layer3_graphrag/', 'config/')
# Run options that never alter knowledge artifacts (same set as historical reuse).
NON_KNOWLEDGE_CONFIG = {'llm', 'evaluation', 'evaluation_policy', 'project_selection', 'processing_scope', 'runs_base',
                        'base_knowledge_action', 'base_knowledge_source'}


class KnowledgeUnavailable(ValueError):
    """No registered version is compatible and intact; never silently rebuilt."""


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _sha(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            hasher.update(block)
    return hasher.hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _atomic_write(path, value):
    """Write a complete file next to its target, then replace it in one step."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    os.replace(temporary, path)


def shared_root(root):
    return Path(root) / SHARED


def data_config(config):
    return {k: v for k, v in config.items() if k not in NON_KNOWLEDGE_CONFIG}


def identity(state, raw_manifest):
    """Inputs that determine the artifacts; prompts, policies, contracts and selection excluded."""
    config = state['configuration']
    return dict(schema=VERSION_SCHEMA, dataset=state['dataset'], raw_path=state['raw_path'],
        raw_files=raw_manifest['files'], catalog_sha256=state.get('global_catalog_sha256'),
        knowledge_scope=config.get('knowledge_scope'), data_config=data_config(config),
        knowledge_code={k: v for k, v in sorted(state['code_hashes'].items()) if k.startswith(KNOWLEDGE_CODE)})


def _query_cache(directory):
    files = sorted(p for p in Path(directory).glob('*') if p.is_file()) if Path(directory).is_dir() else []
    return dict(files=len(files), sha256=digest([[p.name, _sha(p)] for p in files]))


def components(builder):
    """Digests of every reusable component; recomputed on each verification."""
    from run_paths import file_path as run_file
    workspace = builder / 'workspace'
    publication = workspace / 'outputs/layer3/publication'
    published = _read(publication / '_manifest.json')
    return dict(
        preprocessing=dict(canonical_manifest_sha256=_sha(workspace / 'outputs/layer2/canonical/_manifest.json'),
                           prepared_hashes_sha256=_sha(run_file(builder, 'prepared_hashes.json'))),
        knowledge=dict(manifest_sha256=_sha(workspace / 'outputs/layer2/knowledge/_manifest.json')),
        embeddings=dict(embedding_config_hash=published.get('embedding_config_hash'), model=published.get('embedding_model'),
                        model_revision=published.get('model_revision'), source_count=published.get('source_embedding_count'),
                        reference_count=published.get('reference_embedding_count')),
        vector_indexes=published.get('vector_indexes'),
        graph=dict(node_count=published.get('node_count'), edge_count=published.get('edge_count')),
        publication=dict(manifest_sha256=_sha(publication / '_manifest.json'), layer3_run_id=published.get('layer3_run_id')),
        query_cache=_query_cache(workspace / 'outputs/layer3/query_cache'))


def describe(root, builder):
    """Version manifest of a sealed builder checkpoint (no writes)."""
    from run_paths import file_path as run_file
    root, builder = Path(root).resolve(), Path(builder).resolve()
    if not builder.is_relative_to(root / 'outputs'):
        raise ValueError('La version debe residir dentro de outputs')
    state = _read(run_file(builder, 'run.json'))
    if state.get('status') != 'PREPARED' or state.get('configuration', {}).get('knowledge_scope') != 'BASE_GLOBAL_V1':
        raise ValueError('Solo un checkpoint BASE_GLOBAL_V1 PREPARED puede registrarse')
    if state.get('knowledge_ref') or state.get('global_reuse'):
        raise ValueError('Registrar el checkpoint que construyo el conocimiento, no un run que lo referencia o copio')
    if not (builder / 'workspace/outputs/layer3/publication/_manifest.json').is_file():
        raise ValueError('Checkpoint sin GraphRAG publicado')
    ident = identity(state, _read(run_file(builder, 'raw_manifest.json')))
    parts = components(builder)
    fingerprint = digest(ident)
    return dict(schema=VERSION_SCHEMA, version_id=fingerprint[:16] + '-' + parts['publication']['manifest_sha256'][:8],
        fingerprint=fingerprint, identity=ident, components=parts, location=builder.relative_to(root).as_posix(),
        storage='IN_PLACE_SEALED_CHECKPOINT', builder_run_id=state['run_id'])


def _valid_id(version_id):
    if not isinstance(version_id, str) or not re.fullmatch(r'[0-9a-f]{16}-[0-9a-f]{8}', version_id):
        raise ValueError('Identificador de version de conocimiento invalido')
    return version_id


def manifest_path(root, version_id):
    return shared_root(root) / 'versions' / _valid_id(version_id) / 'manifest.json'


def load_version(root, version_id):
    path = manifest_path(root, version_id)
    if not path.is_file():
        raise KnowledgeUnavailable('Version de conocimiento no registrada: ' + version_id)
    manifest = _read(path)
    if manifest.get('schema') != VERSION_SCHEMA or manifest.get('version_id') != version_id:
        raise ValueError('Manifiesto de version incompatible: ' + version_id)
    return manifest, _sha(path)


def location(root, manifest):
    root = Path(root).resolve()
    path = (root / manifest['location']).resolve()
    if not path.is_relative_to(root / 'outputs'):
        raise ValueError('Ubicacion de version fuera de outputs')
    return path


def verify(root, manifest, *, deep=True):
    """Integrity of a registered version; raises on any missing/changed component."""
    from layer2_processing.pipeline import check
    builder = location(root, manifest)
    if not builder.is_dir():
        raise KnowledgeUnavailable('Artefactos de la version ausentes: ' + manifest['location'])
    try:
        check(root, builder, knowledge_only=True)  # RAW, knowledge code/config and every sealed file.
        current = describe(root, builder)
    except (OSError, KeyError) as exc:
        raise KnowledgeUnavailable(f'Version {manifest["version_id"]} ilegible: {exc}') from exc
    for key in ('fingerprint', 'identity', 'components', 'version_id', 'location'):
        if current[key] != manifest[key]:
            raise KnowledgeUnavailable(f'Version {manifest["version_id"]} alterada: {key}')
    from layer3_graphrag.manifest import validate_publication
    workspace = builder / 'workspace'
    validate_publication(workspace / 'outputs/layer3/publication', manifest['components']['knowledge']['manifest_sha256'])
    if deep:
        # Same deep validation as historical reuse: vectors, indexes and graph
        # against the approved snapshot. Lazy provider: no model is loaded.
        from layer3_graphrag.configuration import load_config
        from layer3_graphrag.validate_inputs import validate_inputs
        from layer3_graphrag.pipeline import load_artifacts
        from layer3_graphrag.embeddings import create_provider
        config, _ = load_config(workspace)
        snapshot = validate_inputs(workspace, config)
        load_artifacts(workspace, snapshot, config, create_provider(config['embeddings']))
    return manifest


def register(root, builder, *, activate=False, when=None):
    """Register (idempotently) a verified checkpoint in place; never copies or edits it."""
    manifest = describe(root, builder)
    target = manifest_path(root, manifest['version_id'])
    if target.is_file():
        existing, _ = load_version(root, manifest['version_id'])
        if {k: v for k, v in existing.items() if k != 'registered_at'} != manifest:
            raise ValueError('Ya existe otra version con el mismo identificador')
        manifest = existing
    else:
        manifest = dict(manifest, registered_at=when or datetime.now(timezone.utc).isoformat())
        verify(root, manifest, deep=True)
        _atomic_write(target, manifest)
    if activate:
        activate_version(root, manifest['version_id'], when=when)
    return manifest


def read_active(root):
    path = shared_root(root) / 'active.json'
    return _read(path) if path.is_file() else None


def activate_version(root, version_id, *, when=None):
    """Point active.json at a complete, verified version (atomic replace)."""
    manifest, manifest_sha = load_version(root, version_id)
    verify(root, manifest, deep=True)
    previous = read_active(root)
    pointer = dict(schema=VERSION_SCHEMA, version_id=version_id, manifest_sha256=manifest_sha,
        fingerprint=manifest['fingerprint'], activated_at=when or datetime.now(timezone.utc).isoformat(),
        previous=None if previous is None else {k: previous[k] for k in ('version_id', 'manifest_sha256')})
    _atomic_write(shared_root(root) / 'active.json', pointer)
    with (shared_root(root) / 'activations.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(_canonical(pointer) + '\n')
    return pointer


def compatible(root, raw, config, dataset, *, version_id=None):
    """Return the active (or explicitly pinned) version usable for this request.

    Compatibility = same dataset, RAW files, catalog and knowledge-shaping
    configuration, plus intact artifacts and unchanged knowledge code. Prompts,
    confidence policy, export contract and project selection are irrelevant.
    """
    from layer2_processing.preprocessing.adapters import verify_raw
    root = Path(root).resolve()
    if version_id is None:
        active = read_active(root)
        if active is None:
            raise KnowledgeUnavailable('No hay version de conocimiento BASE activa en ' + SHARED)
        version_id = active['version_id']
    manifest, manifest_sha = load_version(root, version_id)
    if version_id == (read_active(root) or {}).get('version_id') and read_active(root)['manifest_sha256'] != manifest_sha:
        raise KnowledgeUnavailable('Puntero activo y manifiesto de version difieren')
    ident = manifest['identity']
    reasons = []
    if ident['dataset'] != dataset: reasons.append('dataset')
    if (root / ident['raw_path']).resolve() != Path(raw).resolve(): reasons.append('raw_path')
    if ident['knowledge_scope'] != config.get('knowledge_scope'): reasons.append('knowledge_scope')
    if ident['data_config'] != data_config(config): reasons.append('configuracion de datos')
    from layer2_processing.checkpoints import resolve
    if ident['catalog_sha256'] != _sha(resolve(root, config['reference_catalog'])): reasons.append('catalogo')
    try:
        verify_raw(Path(raw), ident['raw_files'], config.get('source_paths'))
    except (OSError, ValueError):
        reasons.append('fuentes RAW')
    if reasons:
        raise KnowledgeUnavailable(f'Version {version_id} incompatible: ' + ', '.join(reasons))
    verify(root, manifest, deep=True)
    return manifest, manifest_sha


def reference(manifest, manifest_sha):
    """Stable reference stored in a run; never just 'the current base'."""
    return dict(version_id=manifest['version_id'], manifest_sha256=manifest_sha, fingerprint=manifest['fingerprint'],
        location=manifest['location'], knowledge_manifest_sha256=manifest['components']['knowledge']['manifest_sha256'],
        publication_manifest_sha256=manifest['components']['publication']['manifest_sha256'])


def resolve_reference(root, ref, *, deep=False):
    """Artifacts of the exact version a run used, even if another one is active now."""
    manifest, manifest_sha = load_version(root, ref['version_id'])
    if manifest_sha != ref['manifest_sha256'] or reference(manifest, manifest_sha) != ref:
        raise KnowledgeUnavailable('La version referenciada por el run cambio: ' + ref['version_id'])
    verify(root, manifest, deep=deep)
    return location(root, manifest)


def run_state(run):
    from run_paths import file_path as run_file
    path = run_file(run, 'run.json')
    return _read(path) if Path(path).is_file() else {}


def knowledge_root(run):
    """Directory holding the knowledge checkpoint a run uses (cheap: manifest pin only)."""
    from run_paths import repo_of
    run = Path(run)
    ref = run_state(run).get('knowledge_ref')
    if not ref:
        return run  # Legacy runs own (or hold a copy of) their knowledge.
    root = repo_of(run)
    manifest, manifest_sha = load_version(root, ref['version_id'])
    if manifest_sha != ref['manifest_sha256']:
        raise KnowledgeUnavailable('La version referenciada por el run cambio: ' + ref['version_id'])
    return location(root, manifest)


def knowledge_workspace(run):
    return knowledge_root(run) / 'workspace'


def evaluation_dir(run):
    """Evaluation checkpoints: historical layouts first, then the shared-knowledge layout."""
    run = Path(run)
    if (run / 'layer5_results').exists():
        return run / 'layer5_results'
    if run_state(run).get('storage_layout') == RUN_LAYOUT:
        return run / 'evaluation'
    return run / 'workspace/outputs/layer4'


def registered_locations(root):
    """Checkpoints that back registered versions; retention must keep them."""
    found = set()
    versions = shared_root(root) / 'versions'
    if versions.is_dir():
        for path in versions.glob('*/manifest.json'):
            try:
                found.add(location(root, _read(path)))
            except (OSError, ValueError, KeyError):
                continue
    return found


def status(root):
    active = read_active(root)
    versions = []
    folder = shared_root(root) / 'versions'
    for path in sorted(folder.glob('*/manifest.json')) if folder.is_dir() else []:
        manifest = _read(path)
        versions.append(dict(version_id=manifest['version_id'], location=manifest['location'],
            builder_run_id=manifest.get('builder_run_id'), registered_at=manifest.get('registered_at'),
            active=bool(active) and active['version_id'] == manifest['version_id']))
    return dict(shared_root=SHARED, active=active, versions=versions)
