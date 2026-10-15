"""Approved local builds and retrieval; plan mode never opens knowledge data."""
import json
import logging
import os
import shutil
import csv
import time
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from . import IMPLEMENTATION_STATUS
from .configuration import inside, load_config, require_approval
from .embeddings import EmbeddingCache, build_embeddings, embedding_config_hash, load_bundle, save_bundle, reuse_bundle
from .embeddings import create_provider
from .evaluation import compare_engines, load_evaluation_queries
from .graph import build_graph
from .graph import LocalGraphStore
from .manifest import create_manifest, now, validate_publication
from .provenance import serialize, stable_id
from .provenance import file_hash
from .graph import profile_graph
from .quality import evaluate, write_reports
from .retrieval import QueryEngine
from .validate_inputs import assert_unchanged, validate_inputs
from .vector_index import NumpyVectorIndex, create_vector_index

LOG = logging.getLogger(__name__)


@dataclass
class BuildArtifacts:
    bundles: dict
    indexes: dict
    graph: LocalGraphStore
    quality: dict
    reports: dict
    candidate: Path
    manifest: dict


def preparation_plan(config, config_hash):
    pending = []
    if config['readiness'].get('layer2_status') != 'FINAL_PROJECT_LAYER_2_READY' or not config['readiness'].get('approved_layer2_manifest_sha256'):
        pending.append('final approved Layer 2 snapshot')
    if config['embeddings'].get('provider') == 'unconfigured' or not config['embeddings'].get('model_version'):
        pending.append('model and pinned revision selection')
    if not config['execution']['allow_real_build']:
        pending.append('real build authorization')
    return {'status': IMPLEMENTATION_STATUS if pending else 'LAYER_3_REAL_EXECUTION_CONFIGURED', 'layer3_config_hash': config_hash,
            'knowledge_read': False, 'embeddings_executed': False, 'published': False,
            'backends': {'vector': config['vector_index']['backend'], 'graph': config['graph']['backend']},
            'modes': ['vector', 'graph', 'hybrid'],
            'pending': pending, 'acceptance_report': 'outputs/layer3/reports/source_level_final_acceptance.json'}


def build_candidate(root, snapshot, config, config_hash, run_id, archive, provider):
    """Internal build; callers supply an approved snapshot or ephemeral test fixture."""
    started = now()
    if hasattr(provider, 'validate_model_files'):
        provider.validate_model_files()
    timer = time.perf_counter()
    graph = build_graph(snapshot, config['quality'])
    graph_seconds = time.perf_counter() - timer
    timer = time.perf_counter()
    cache = EmbeddingCache(inside(root, config['embeddings']['cache'], ('outputs/layer3',)))
    publication=inside(root,config['outputs']['publication'],('data/graphrag',))
    bundles={}
    if (publication/'_manifest.json').exists():
        validate_publication(publication,snapshot.manifest_hash)
        for space in ('SOURCE','REFERENCE'):
            bundle=reuse_bundle(publication/'embeddings'/space.lower(),snapshot,space,provider,config['embeddings'],run_id)
            if bundle is not None: bundles[space]=bundle
    for space in ('SOURCE','REFERENCE'):
        if space not in bundles: bundles[space]=build_embeddings(snapshot,space,provider,config['embeddings'],run_id,cache)
    embedding_seconds = time.perf_counter() - timer
    timer = time.perf_counter()
    indexes = {space: create_vector_index(config['vector_index']['backend'], space) for space in bundles}
    for space in indexes:
        indexes[space].build(bundles[space])
    index_seconds = time.perf_counter() - timer
    summary, reports = evaluate(snapshot, bundles, indexes, graph, config)
    archive = Path(archive)
    archive.mkdir(parents=True, exist_ok=True)
    candidates, packages, comparisons, metrics = [], [], [], []
    if config.get('retrieval', {}).get('enabled'):
        from .indicator_retrieval import IndicatorRetriever
        from .quality import validate_retrieval
        candidates, packages, comparisons, metrics = IndicatorRetriever(snapshot, indexes['SOURCE'], provider,
            graph, config, run_id).process()
        result, issues, anomalies, privacy = validate_retrieval(snapshot, graph, candidates, packages, config)
        summary['retrieval'] = result
        reports['retrieval_provenance_issues'].extend(issues)
        reports['retrieval_anomalies'].extend(anomalies)
        reports['privacy_issues'].extend(privacy)
        if result['status'] != 'PASS':
            summary['failures'].append('retrieval')
            summary['status'] = 'FAIL'
    summary['build_seconds'] = {'embeddings': embedding_seconds, 'indexes': index_seconds, 'graph': graph_seconds}
    write_reports(archive / 'quality', summary, reports)
    if summary['status'] != 'PASS':
        raise ValueError('Layer 3 candidate quality failed: ' + ', '.join(summary['failures']))
    candidate = archive / 'graphrag'
    candidate.mkdir(parents=True)
    for space in bundles:
        save_bundle(bundles[space], candidate / 'embeddings' / space.lower())
        # Flat required delivery names; existing reloadable bundle contract is retained.
        np.save(candidate / 'embeddings' / (space.lower() + '_embeddings.npy'), bundles[space].vectors, allow_pickle=False)
        pq.write_table(pa.Table.from_pylist(bundles[space].records), candidate / 'embeddings' /
            (space.lower() + '_embedding_metadata.parquet'), compression='zstd')
        if pq.read_table(candidate / 'embeddings' / (space.lower() + '_embedding_metadata.parquet')).to_pylist() != bundles[space].records:
            raise ValueError('Flat embedding metadata roundtrip differs')
        flat_vectors = np.load(candidate / 'embeddings' / (space.lower() + '_embeddings.npy'), mmap_mode='r', allow_pickle=False)
        if not np.array_equal(flat_vectors, bundles[space].vectors):
            raise ValueError('Flat embedding matrix roundtrip differs')
        del flat_vectors
        indexes[space].save(candidate / 'indexes' / space.lower())
        # Reopen saved artifacts now, before any publication.
        restored = load_bundle(candidate / 'embeddings' / space.lower())
        if restored.records != bundles[space].records:
            raise ValueError('Embedding roundtrip differs')
        NumpyVectorIndex.load(candidate / 'indexes' / space.lower(), {'config_hash': bundles[space].metadata['config_hash']})
    graph.save(candidate / 'graph')
    LocalGraphStore.load(candidate / 'graph')
    (candidate / 'retrieval').mkdir()
    graph_profile = profile_graph(graph)
    (candidate / 'graph/graph_summary.json').write_text(serialize(graph_profile), encoding='utf-8')
    if config.get('retrieval', {}).get('enabled'):
        from .indicator_retrieval import write_outputs
        write_outputs(candidate / 'retrieval', candidates, packages)
        pq.write_table(pa.Table.from_pylist(comparisons), candidate / 'retrieval/technical_comparison.parquet', compression='zstd')
        reports_dir = archive / 'reports'
        reports_dir.mkdir()
        (reports_dir / 'graph_profile.json').write_text(serialize(graph_profile), encoding='utf-8')
        (reports_dir / 'graph_profile.md').write_text('# Grafo real de Capa 3\n\n```json\n' + json.dumps(graph_profile, indent=2) + '\n```\n', encoding='utf-8')
        (reports_dir / 'retrieval_metrics.json').write_text(serialize(metrics), encoding='utf-8')
        with (reports_dir / 'vector_vs_hybrid.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(comparisons[0]))
            writer.writeheader()
            writer.writerows(comparisons)
        (reports_dir / 'retrieval_comparison.md').write_text('# Comparación técnica real\n\n'
            'Mismas queries REFERENCE para VECTOR, GRAPH y HYBRID. GRAPH recibe explícitamente el nodo '
            'INDICATOR correspondiente; esos nodos están aislados y no introducen fuentes. HYBRID usa '
            'semillas vectoriales visibles en retrieval_metrics.json. Son condiciones distintas de acceso a '
            'semillas, sin ground truth ni afirmación de superioridad. GROUND_TRUTH_NOT_AVAILABLE: '
            'Precision@K, Recall@K, HitRate@K y MRR = N/A. Los cambios y latencias están en vector_vs_hybrid.csv.\n', encoding='utf-8')
    (archive / 'config.json').write_text(serialize(config), encoding='utf-8')
    import yaml
    (archive / 'layer3_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf-8')
    manifest = create_manifest(root, snapshot, config_hash, run_id, started, bundles, indexes, graph, candidate)
    manifest.update(embedding_provider=config['embeddings']['provider'], model_revision=provider.model_version,
        dimensions=provider.dimensions, device=config['embeddings']['device'], dtype=config['embeddings'].get('dtype', 'float32'),
        max_seq_length=config['embeddings'].get('max_seq_length'), batch_size=provider.batch_size,
        normalization=config['embeddings']['normalize_embeddings'], source_embedding_count=len(bundles['SOURCE'].records),
        reference_embedding_count=len(bundles['REFERENCE'].records), vector_index_backend='numpy_exact', vector_metric='cosine',
        graph_backend='local_json', node_count=len(graph.nodes), edge_count=len(graph.relations),
        researcher_bridge_policy='resolved_only', retrieval_parameters=config.get('retrieval', {}),
        graph_parameters=config['graph'], hybrid_weights={k: config['hybrid'][k] for k in ('vector_weight', 'graph_weight')},
        indicator_count=len(snapshot.tables['reference_documents']), candidate_count=len(candidates), context_package_count=len(packages),
        quality_summary=summary, input_hashes=snapshot.hashes,
        candidate_architecture='SOURCE_INDICATOR_V1', discovery_unit='CHUNK', candidate_unit='SOURCE_INDICATOR',
        source_context_storage='NORMALIZED_SECTION_REFERENCES', indicator_profiles_status='PENDING_GROUP_REVIEW',
        config_snapshot_sha256=file_hash(archive / 'layer3_config.yaml'))
    manifest['runtime'].update(getattr(provider, 'runtime_fingerprint', {}))
    hardware_path = Path(root) / 'outputs/layer3/reports/hardware.json'
    tokens_path = Path(root) / 'outputs/layer3/reports/token_profile.json'
    if hardware_path.exists():
        manifest['hardware'] = json.loads(hardware_path.read_text(encoding='utf-8'))
    if tokens_path.exists():
        manifest['token_profile'] = json.loads(tokens_path.read_text(encoding='utf-8'))
    if config.get('retrieval', {}).get('enabled'):
        manifest['evaluation'] = {'status': 'GROUND_TRUTH_NOT_AVAILABLE', 'Precision@K': None, 'Recall@K': None,
            'HitRate@K': None, 'MRR': None, 'technical_comparison': 'retrieval/technical_comparison.parquet'}
    (candidate / '_manifest.json').write_text(serialize(manifest), encoding='utf-8')
    validate_publication(candidate, snapshot.manifest_hash)
    assert_unchanged(snapshot)
    return BuildArtifacts(bundles, indexes, graph, summary, reports, candidate, manifest)


def publish_directory(candidate, destination, archive, finalize):
    """Directory swap with rollback and a journal retained on incomplete rollback."""
    candidate, destination, archive = Path(candidate), Path(destination), Path(archive)
    archive.mkdir(parents=True, exist_ok=True)
    previous = archive / 'previous_graphrag'
    failed = archive / 'failed_graphrag'
    journal = archive.parent.parent / 'publication_pending.json'
    if journal.exists() or previous.exists() or failed.exists():
        raise RuntimeError('Publication recovery is pending or archive is not fresh')
    journal.write_text(serialize({'candidate': str(candidate), 'destination': str(destination),
                                  'previous': str(previous)}), encoding='utf-8')
    moved, installed = False, False
    try:
        if destination.exists():
            destination.rename(previous)
            moved = True
        destination.parent.mkdir(parents=True, exist_ok=True)
        candidate.rename(destination)
        installed = True
        finalize()
        journal.unlink()
    except Exception:
        if installed:
            destination.rename(failed)
        if moved:
            previous.rename(destination)
        journal.unlink()
        raise


def load_artifacts(root, snapshot, config, provider):
    directory = inside(root, config['outputs']['publication'], ('data/graphrag',))
    base = inside(root, config['outputs']['base'], ('outputs/layer3',))
    if (base / 'publication_pending.json').exists() or (base / '.publish.lock').exists():
        raise RuntimeError('Layer 3 publication/recovery in progress')
    manifest = validate_publication(directory, snapshot.manifest_hash)
    fingerprint = embedding_config_hash(config['embeddings'], provider)
    if manifest['embedding_config_hash'] != fingerprint:
        raise ValueError('Published embeddings incompatible with current provider/configuration')
    indexes = {space: NumpyVectorIndex.load(directory / 'indexes' / space.lower(),
                {'source_space': space, 'layer2_manifest_hash': snapshot.manifest_hash, 'config_hash': fingerprint})
               for space in ('SOURCE', 'REFERENCE')}
    graph = LocalGraphStore.load(directory / 'graph')
    if set(graph.nodes) != {r['entity_id'] for r in snapshot.tables['entities']} or set(graph.relations) != {r['relation_id'] for r in snapshot.tables['relations']}:
        raise ValueError('Graph does not cover the approved snapshot')
    return manifest, indexes, graph


def run(root, config_path='config/layer3.yaml', mode='plan', provider=None, query_text=None,
        query_id=None, retrieval_mode='hybrid', seed_entity_ids=None, queries_path=None):
    root = Path(root).resolve()
    config, config_hash = load_config(root, config_path)
    if mode == 'plan':
        return preparation_plan(config, config_hash)
    if mode not in {'validate', 'build', 'query', 'evaluate'}:
        raise ValueError('Unknown Layer 3 execution mode')
    require_approval(config, building=mode == 'build')
    snapshot = validate_inputs(root, config)
    if mode == 'validate':
        graph = build_graph(snapshot, config['quality'])
        result={'status': 'VALIDATED_APPROVED_LAYER_2_INPUT', 'layer2_manifest_hash': snapshot.manifest_hash,
                'knowledge_rows': {name: len(rows) for name, rows in snapshot.tables.items()}, 'graph_integrity': graph.validate()}
        reports=inside(root,config['outputs']['reports'],('outputs/layer3',)); reports.mkdir(parents=True,exist_ok=True)
        (reports/'input_validation.json').write_text(serialize(result|{'status':'PASS','layer2_run_id':snapshot.manifest['layer2_run_id'],'input_hashes':snapshot.hashes}),encoding='utf-8')
        return result
    provider = provider or create_provider(config['embeddings'])
    base = inside(root, config['outputs']['base'], ('outputs/layer3',))
    if mode == 'build':
        base.mkdir(parents=True, exist_ok=True)
        if (base / 'publication_pending.json').exists():
            raise RuntimeError('Layer 3 recovery is required')
        lock = base / '.publish.lock'
        run_id = 'layer3_' + now().replace(':', '').replace('.', '_') + '_' + uuid4().hex[:8]
        archive = base / 'runs' / run_id
        # The x mode acquires the lock; a failure must not unlink another writer's lock.
        with lock.open('x', encoding='utf-8') as stream:
            stream.write(run_id)
        try:
            artifacts = build_candidate(root, snapshot, config, config_hash, run_id, archive, provider)
            destination = inside(root, config['outputs']['publication'], ('data/graphrag',))
            manifests = inside(root, config['outputs']['manifests'], ('outputs/layer3',))
            def finalize():
                assert_unchanged(snapshot)
                validate_publication(destination, snapshot.manifest_hash)
                manifests.mkdir(parents=True, exist_ok=True)
                (manifests / (run_id + '.json')).write_text(serialize(artifacts.manifest), encoding='utf-8')
            assert_unchanged(snapshot)
            publish_directory(artifacts.candidate, destination, archive, finalize)
            try:
                shutil.copytree(archive / 'quality', inside(root, config['outputs']['quality'], ('outputs/layer3',)), dirs_exist_ok=True)
                if (archive / 'reports').exists():
                    shutil.copytree(archive / 'reports', inside(root, config['outputs']['reports'], ('outputs/layer3',)), dirs_exist_ok=True)
            except OSError:
                LOG.warning('Use archived quality report; latest view could not be updated')
            return artifacts.manifest
        except Exception as exc:
            archive.mkdir(parents=True, exist_ok=True)
            failure = {'status': 'FAILED', 'layer3_run_id': run_id, 'layer2_manifest_hash': snapshot.manifest_hash,
                       'error_type': type(exc).__name__, 'reason': str(exc)}
            (archive / 'failure.json').write_text(serialize(failure), encoding='utf-8')
            raise
        finally:
            lock.unlink(missing_ok=True)
    manifest, indexes, graph = load_artifacts(root, snapshot, config, provider)
    engine = QueryEngine(snapshot, provider, indexes['SOURCE'], indexes['REFERENCE'], graph, config,
                         manifest['layer3_run_id'], config_hash)
    if mode == 'query':
        result = engine.query(query_text, query_id, retrieval_mode, seed_entity_ids)
        assert_unchanged(snapshot)
        reports = inside(root, config['outputs']['reports'], ('outputs/layer3',))
        reports.mkdir(parents=True, exist_ok=True)
        filename = stable_id('CONTEXT', result['query_id'], config_hash, snapshot.manifest_hash) + '.json'
        (reports / filename).write_text(serialize(result), encoding='utf-8')
        return result
    location = queries_path or config['evaluation'].get('queries')
    if not location:
        raise ValueError('An explicitly labeled evaluation set is required')
    path = inside(root, location, ('data/knowledge', 'outputs/layer3',))
    queries = load_evaluation_queries(path)
    result = compare_engines({m: engine for m in config['evaluation']['compare_modes']}, queries, config['evaluation']['k_values'])
    assert_unchanged(snapshot)
    result['provenance'] = {'layer2_manifest_hash': snapshot.manifest_hash, 'layer3_run_id': manifest['layer3_run_id'],
                            'layer3_config_hash': config_hash}
    reports = inside(root, config['outputs']['reports'], ('outputs/layer3',))
    reports.mkdir(parents=True, exist_ok=True)
    (reports / (stable_id('EVALUATION', queries, config_hash, snapshot.manifest_hash) + '.json')).write_text(serialize(result), encoding='utf-8')
    return result
