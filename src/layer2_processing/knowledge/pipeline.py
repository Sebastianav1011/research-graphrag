"""Explicitly gated orchestration with complete candidates and rollback publication."""
from run_paths import file_path as run_file
import importlib.metadata
import json
import logging
import shutil
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from jsonschema import Draft202012Validator
from . import PIPELINE_VERSION
from .contracts import SCHEMAS, arrow_schema, logical_schema, manifest_schema
from .validate_inputs import load_config, require_approval, validate_inputs, assert_unchanged, WaitingForLayer1, ConfigurationPending
from .documents import build_documents
from .documents import build_sections, normalize_sections
from .chunking import build_chunks
from .documents import build_reference
from .graph_data import build_entities
from .graph_data import build_relations
from .quality import evaluate, write_reports, profile_sections, write_text_profile
from .provenance import file_hash, now, payload_hash, serialize

LOG = logging.getLogger('layer2')


def build_package(snapshot, config, context):
    datasets = snapshot['datasets']
    LOG.info('[2/9] BUILD DOCUMENTS')
    documents = build_documents(datasets, config, context)
    LOG.info('[3/9] BUILD SECTIONS')
    sections = build_sections(documents, datasets, config, context)
    LOG.info('[4/9] NORMALIZE TEXT')
    normalize_sections(sections, config)
    LOG.info('[5/9] CHUNK SOURCES')
    chunks = build_chunks(sections, config, context)
    LOG.info('[6/9] BUILD REFERENCE KNOWLEDGE')
    rd, rs, rc = build_reference(datasets, config, context)
    LOG.info('[7/9] BUILD ENTITIES')
    entities = build_entities(datasets, config, context)
    LOG.info('[8/9] BUILD STRUCTURED RELATIONS')
    relations = build_relations(datasets, config, context)
    return dict(zip(SCHEMAS, [documents, sections, chunks, rd, rs, rc, entities, relations]))


def context_for(snapshot, config, digest, run_id):
    return {'layer1_run_id': snapshot['layer1_run_id'], 'layer2_run_id': run_id,
            'config_version': config['config_version'], 'config_hash': digest,
            'email_policy': config.get('privacy', {}).get('email_policy', 'reject')}


def publish_directory(candidate, destination, archive, finalize):
    """Same-volume directory swap. Rollback on exception; crash journal blocks readers."""
    archive.mkdir(parents=True, exist_ok=True)
    previous = archive / 'previous_knowledge'
    journal = archive.parents[1] / 'publication_pending.json'
    if journal.exists():
        raise RuntimeError('LAYER_2_RECOVERY_REQUIRED: unresolved publication journal')
    destination.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(serialize({'candidate': str(candidate), 'destination': str(destination),
                                 'previous': str(previous)}), encoding='utf-8')
    moved_previous = installed = False
    try:
        if destination.exists():
            destination.rename(previous)
            moved_previous = True
        candidate.rename(destination)
        installed = True
        finalize()
        journal.unlink()
    except Exception:
        if installed:
            destination.rename(archive / 'failed_knowledge')
        if moved_previous:
            previous.rename(destination)
        journal.unlink()
        raise


def run(root, config_path='config/layer2.yaml', mode='publish'):
    root = Path(root).resolve()
    config, digest, config_bytes = load_config(root, config_path, include_bytes=True)
    # Readiness is checked before opening canonical content or creating execution outputs.
    require_approval(root, config, publishing=mode == 'publish')
    LOG.info('[1/9] VALIDATE CANONICAL INPUT')
    snapshot = validate_inputs(root, config)
    if (root / 'outputs/layer2/knowledge_artifacts/publication_pending.json').exists():
        raise RuntimeError('LAYER_2_RECOVERY_REQUIRED: unresolved publication journal')
    if mode == 'profile':
        context = context_for(snapshot, config, digest, 'PROFILE_ONLY')
        docs = build_documents(snapshot['datasets'], config, context)
        sections = normalize_sections(build_sections(docs, snapshot['datasets'], config, context), config)
        rd, rs, _ = build_reference(snapshot['datasets'], config, context)
        result = {'layer1_run_id': snapshot['layer1_run_id'], 'layer1_manifest_hash': snapshot['manifest_hash'],
            'layer2_config_hash': digest, 'publication_kind': 'real', 'inspection': snapshot['inspection'],
            'source_lengths': profile_sections(sections), 'reference_lengths': profile_sections(rs),
            'parameters_provisional': not config['readiness']['chunking_calibrated']}
        assert_unchanged(root, snapshot['hashes'], snapshot['manifest_hash'])
        folder = root / config['outputs']['reports']
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'input_profile.json').write_text(serialize(result), encoding='utf-8')
        write_text_profile(folder, sections, rs)
        return result
    if mode not in {'validate', 'publish'}:
        raise ValueError('Unknown execution mode')
    run_id = 'run_' + now().replace('-', '').replace(':', '').replace('.', '_').replace('+0000', 'Z')
    started = now()
    context = context_for(snapshot, config, digest, run_id)
    package = build_package(snapshot, config, context)
    LOG.info('[9/9] QUALITY + MANIFEST + PUBLISH')
    for name, rows in package.items():
        validator = Draft202012Validator(logical_schema(name))
        id_field = next(iter(SCHEMAS[name]))
        if len({r[id_field] for r in rows}) != len(rows):
            raise ValueError('Duplicate deterministic ID: ' + name)
        for row in rows:
            validator.validate(row)
    summary, reports = evaluate(package, snapshot['datasets'], config, context)
    assert_unchanged(root, snapshot['hashes'], snapshot['manifest_hash'])
    if mode == 'validate':
        return {'status': summary['status'], 'quality': summary,
                'payload_hashes': {name: payload_hash(rows) for name, rows in package.items()}}
    base = root / 'outputs/layer2/knowledge_artifacts'
    base.mkdir(parents=True, exist_ok=True)
    lock = base / '.publish.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(run_id)
    from layer2_processing.checkpoints import run_directory
    archive = run_directory(root,run_id)
    try:
        if (base / 'publication_pending.json').exists():
            raise RuntimeError('LAYER_2_RECOVERY_REQUIRED: unresolved publication journal')
        archive.mkdir(parents=True)
        (archive / 'layer2_config.yaml').write_bytes(config_bytes)
        write_reports(archive / 'quality', summary, reports)
        if summary['failures']:
            raise ValueError('Quality failed: ' + ','.join(summary['failures']))
        candidate = archive / 'knowledge'
        candidate.mkdir()
        for name, rows in package.items():
            table = pa.Table.from_pylist(rows, schema=arrow_schema(name))
            pq.write_table(table, candidate / (name + '.parquet'))
            reread = pq.read_table(candidate / (name + '.parquet'))
            if reread.to_pylist() != rows or reread.schema != arrow_schema(name):
                raise ValueError('Parquet roundtrip failed: ' + name)
        destination = root / config['outputs']['knowledge']
        manifest = {'layer2_run_id': run_id, 'pipeline_version': PIPELINE_VERSION,
            'started_at': started, 'finished_at': now(), 'status': 'SUCCESS', 'publication_kind': 'real',
            'layer1_manifest_path': 'outputs/layer2/canonical/_manifest.json', 'layer1_run_id': snapshot['layer1_run_id'],
            'layer1_manifest_hash': snapshot['manifest_hash'], 'layer2_config_hash': digest,
            'config_snapshot_path': str((archive / 'layer2_config.yaml').relative_to(root)),
            'input_datasets': list(snapshot['datasets']),
            'input_row_counts': {n: len(r) for n, r in snapshot['datasets'].items()}, 'input_hashes': snapshot['hashes'],
            'quality_summary': summary, 'output_files': {n: str((destination / (n + '.parquet')).relative_to(root)) for n in package},
            'output_hashes': {n: file_hash(candidate / (n + '.parquet')) for n in package},
            'payload_hashes': {n: payload_hash(r) for n, r in package.items()},
            'code_hashes': {str(p.relative_to(root)): file_hash(p) for p in sorted((root / 'src/layer2_processing/knowledge').glob('*.py'))},
            'runtime': {p: importlib.metadata.version(p) for p in ('pyarrow', 'PyYAML', 'jsonschema')},
            'previous_publication_compatible': None}
        manifest.update({n + '_created': len(r) for n, r in package.items()})
        if (destination / '_manifest.json').exists():
            previous = json.loads((destination / '_manifest.json').read_text(encoding='utf-8'))
            manifest['previous_publication_compatible'] = (previous.get('layer1_manifest_hash') == snapshot['manifest_hash']
                and previous.get('layer2_config_hash') == digest)
        Draft202012Validator(manifest_schema()).validate(manifest)
        serialized = serialize(manifest)
        (candidate / '_manifest.json').write_text(serialized, encoding='utf-8')
        (archive / 'manifest.json').write_text(serialized, encoding='utf-8')
        assert_unchanged(root, snapshot['hashes'], snapshot['manifest_hash'])
        def finalize():
            assert_unchanged(root, snapshot['hashes'], snapshot['manifest_hash'])
            manifests = root / config['outputs']['manifests']
            manifests.mkdir(parents=True, exist_ok=True)
            (manifests / (run_id + '.json')).write_text(serialized, encoding='utf-8')
        publish_directory(candidate, destination, archive, finalize)
        # Latest quality is a convenience view, archive + published manifest remain authoritative.
        try:
            shutil.copytree(archive / 'quality', root / config['outputs']['quality'], dirs_exist_ok=True)
        except OSError:
            LOG.warning('Latest quality view unavailable; use archived report for this run')
        return manifest
    except Exception as exc:
        archive.mkdir(parents=True, exist_ok=True)
        failure = {'layer2_run_id': run_id, 'started_at': started, 'finished_at': now(),
            'status': 'FAILED', 'error_type': type(exc).__name__, 'reason': str(exc),
            'pipeline_version': PIPELINE_VERSION, 'layer2_config_hash': digest,
            'layer1_run_id': snapshot['layer1_run_id'], 'layer1_manifest_hash': snapshot['manifest_hash']}
        (run_file(archive, 'failure.json')).write_text(serialize(failure), encoding='utf-8')
        manifests = root / config['outputs']['manifests']
        manifests.mkdir(parents=True, exist_ok=True)
        (manifests / (run_id + '.json')).write_text(serialize(failure), encoding='utf-8')
        raise
    finally:
        lock.unlink(missing_ok=True)
