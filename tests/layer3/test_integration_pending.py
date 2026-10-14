"""Real tests opt in only after final Layer 2 approval; never forced PASS."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from layer3_graphrag.configuration import load_config, require_approval
from layer3_graphrag.embedding_provider import create_provider
from layer3_graphrag.evaluation import compare_engines, load_evaluation_queries
from layer3_graphrag.pipeline import build_candidate
from layer3_graphrag.query_engine import QueryEngine
from layer3_graphrag.validate_inputs import assert_unchanged, validate_inputs

pytestmark = pytest.mark.skipif(os.getenv('LAYER3_RUN_REAL_INTEGRATION') != '1',
    reason='WAITING FOR FINAL_PROJECT_LAYER_2_READY, approved manifest and explicit real-integration opt-in')
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def real_snapshot():
    config, config_hash = load_config(ROOT)
    try:
        require_approval(config, building=True)
    except RuntimeError as exc:
        pytest.skip(str(exc))
    return validate_inputs(ROOT, config), config, config_hash


@pytest.fixture(scope='module')
def real_artifacts(real_snapshot):
    snapshot, config, config_hash = real_snapshot
    provider = create_provider(config['embeddings'])
    temp_root = ROOT / 'outputs/layer3/integration-temp'
    temp_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='layer3-real-integration-', dir=temp_root) as directory:
        # Real data remains private and temporary, never published by these tests.
        # Use exactly the approved settings/fingerprint for rebuild and query checks.
        # The configured cache remains private; candidate artifacts are temporary.
        artifacts = build_candidate(ROOT, snapshot, config, config_hash, 'REAL_INTEGRATION', Path(directory), provider)
        engine = QueryEngine(snapshot, provider, artifacts.indexes['SOURCE'], artifacts.indexes['REFERENCE'], artifacts.graph, config)
        yield snapshot, config, artifacts, engine


@pytest.fixture
def real_queries(real_artifacts):
    _, config, _, _ = real_artifacts
    location = config['evaluation'].get('queries')
    if not location:
        pytest.skip('WAITING FOR institutional evaluation set; no ground truth invented')
    from layer3_graphrag.configuration import inside
    queries = load_evaluation_queries(inside(ROOT, location, ('data/knowledge', 'outputs/layer3')))
    if not queries:
        pytest.skip('WAITING FOR nonempty institutional evaluation set')
    return queries


def test_read_layer2_manifest(real_snapshot):
    snapshot, _, _ = real_snapshot
    assert snapshot.manifest['status'] == 'SUCCESS'


def test_embeddings_source(real_artifacts):
    snapshot, _, a, _ = real_artifacts
    assert len(a.bundles['SOURCE'].records) == len(snapshot.tables['source_chunks'])


def test_embeddings_reference(real_artifacts):
    snapshot, _, a, _ = real_artifacts
    assert len(a.bundles['REFERENCE'].records) == len(snapshot.tables['reference_chunks'])


def test_vector_index(real_artifacts):
    assert all(index.validate()['valid'] for index in real_artifacts[2].indexes.values())


def test_graph_build(real_artifacts):
    assert set(real_artifacts[2].graph.nodes) == {r['entity_id'] for r in real_artifacts[0].tables['entities']}


def test_graph_integrity(real_artifacts):
    assert real_artifacts[2].graph.validate()['valid']


@pytest.mark.parametrize('mode', ['vector', 'graph', 'hybrid'])
def test_retrieval_modes(real_artifacts, real_queries, mode):
    engine = real_artifacts[3]
    for q in real_queries:
        if mode == 'graph' and not q.get('seed_entity_ids'):
            pytest.skip('WAITING FOR explicit graph seeds, never expected_source/entity_ids')
        assert engine.query(q['query_text'], q['query_id'], mode, q.get('seed_entity_ids'))['query_id'] == q['query_id']


def test_context_package(real_artifacts, real_queries):
    q = real_queries[0]
    assert real_artifacts[3].query(q['query_text'])['provenance']['layer2_manifest_hash'] == real_artifacts[0].manifest_hash


def test_provenance(real_artifacts, real_queries):
    package = real_artifacts[3].query(real_queries[0]['query_text'])
    assert all(r['layer1_run_id'] == real_artifacts[0].manifest['layer1_run_id'] for r in package['provenance']['source_chunks'])


def test_idempotence(real_artifacts):
    from layer3_graphrag.embedding_pipeline import reuse_bundle
    snapshot, config, artifacts, engine = real_artifacts
    # Reload the compatible real bundle, as production does; never force corpus inference.
    other = reuse_bundle(artifacts.candidate / 'embeddings/source', snapshot, 'SOURCE',
                         engine.vector.provider, config['embeddings'], 'SECOND_REAL_TEST')
    assert other is not None
    assert other.metadata['computed_unique_texts'] == 0
    assert other.metadata['reuse_origin'] == 'VERIFIED_PUBLICATION'
    assert other.metadata['cache_hits'] == len(snapshot.tables['source_chunks'])
    assert [r['embedding_id'] for r in other.records] == [r['embedding_id'] for r in artifacts.bundles['SOURCE'].records]
    import numpy as np
    np.testing.assert_allclose(other.vectors, artifacts.bundles['SOURCE'].vectors, atol=1e-6, rtol=0)


def test_evaluation(real_artifacts, real_queries):
    _, config, _, engine = real_artifacts
    if any(not q.get('seed_entity_ids') for q in real_queries):
        pytest.skip('WAITING FOR graph seeds for comparable modes')
    result = compare_engines({m: engine for m in config['evaluation']['compare_modes']}, real_queries, config['evaluation']['k_values'])
    assert result['query_ids'] == [q['query_id'] for q in real_queries]


def test_end_to_end_graphrag_retrieval(real_artifacts, real_queries):
    assert real_artifacts[3].query(real_queries[0]['query_text'], mode='hybrid')['mode'] == 'hybrid'


def test_snapshot_stability(real_snapshot):
    assert_unchanged(real_snapshot[0])


@pytest.mark.parametrize('space', ['SOURCE', 'REFERENCE'])
def test_real_index_reload_and_exact_alignment(real_artifacts, space):
    from layer3_graphrag.vector_index import NumpyVectorIndex
    import numpy as np
    artifacts = real_artifacts[2]
    restored = NumpyVectorIndex.load(artifacts.candidate / 'indexes' / space.lower())
    assert restored.records == artifacts.indexes[space].records
    np.testing.assert_array_equal(restored.vectors, artifacts.indexes[space].vectors)


@pytest.mark.parametrize('space', ['SOURCE', 'REFERENCE'])
def test_real_numeric_embedding_integrity(real_artifacts, space):
    import numpy as np
    bundle = real_artifacts[2].bundles[space]
    assert np.isfinite(bundle.vectors).all()
    assert (np.linalg.norm(bundle.vectors, axis=1) > 0).all()
    np.testing.assert_allclose(np.linalg.norm(bundle.vectors, axis=1), 1., atol=1e-6, rtol=0)
    assert len(bundle.records) == len({r['chunk_id'] for r in bundle.records})


def test_real_graph_reload(real_artifacts):
    from layer3_graphrag.graph_store import LocalGraphStore
    artifacts = real_artifacts[2]
    graph = LocalGraphStore.load(artifacts.candidate / 'graph')
    assert graph.nodes == artifacts.graph.nodes
    assert graph.relations == artifacts.graph.relations


def test_real_resolved_bridge_paths(real_artifacts):
    import json
    import pyarrow.parquet as pq
    snapshot, config, artifacts, _ = real_artifacts
    from layer3_graphrag.indicator_retrieval import IndicatorRetriever
    retriever = IndicatorRetriever(snapshot, artifacts.indexes['SOURCE'], real_artifacts[3].vector.provider,
        artifacts.graph, config, 'BRIDGE_CHECK')
    for row in pq.read_table(artifacts.candidate / 'retrieval/source_indicator_candidates.parquet').to_pylist():
        if row['graph_path_json'] != '[]':
            path = json.loads(row['graph_path_json'])
            end = path['entity_ids'][-1]
            retriever.check_path(end, path['relation_ids'], [path['seed_entity_id']])


def test_real_all_indicators_candidates_context_provenance_privacy(real_artifacts):
    import pyarrow.parquet as pq
    from layer3_graphrag.source_quality import validate_retrieval
    snapshot, config, artifacts, _ = real_artifacts
    candidates = pq.read_table(artifacts.candidate / 'retrieval/source_indicator_candidates.parquet').to_pylist()
    packages = pq.read_table(artifacts.candidate / 'retrieval/source_context_packages.parquet').to_pylist()
    assert len(packages) == len({r['context_package_id'] for r in candidates})
    assert {r['indicator_id'] for r in candidates} == {r['source_id'] for r in snapshot.tables['reference_documents']}
    result, issues, anomalies, privacy = validate_retrieval(snapshot, artifacts.graph, candidates, packages, config)
    assert result['status'] == 'PASS' and not issues and not anomalies and not privacy
    assert result['provenance_coverage'] == 1


def test_real_quality_and_safe_candidate_manifest(real_artifacts):
    from layer3_graphrag.manifest import validate_publication
    artifacts = real_artifacts[2]
    assert artifacts.quality['status'] == 'PASS'
    assert artifacts.quality['retrieval']['status'] == 'PASS'
    assert validate_publication(artifacts.candidate, real_artifacts[0].manifest_hash)['status'] == 'SUCCESS'


def test_real_no_truncation(real_artifacts):
    import json
    token_profile = json.loads((ROOT / 'outputs/layer3/reports/token_profile.json').read_text(encoding='utf-8'))
    for space in ('SOURCE', 'REFERENCE'):
        assert token_profile[space]['chunks_above_model_limit'] == 0
        assert token_profile[space]['count'] == len(real_artifacts[0].tables[space.lower() + '_chunks'])


def test_real_two_published_builds_idempotent(real_artifacts):
    import json
    result = json.loads((ROOT / 'outputs/layer3/reports/idempotence.json').read_text(encoding='utf-8'))
    assert result['status'] == 'PASS'
    assert len(set(result['builds'])) == 2


def test_real_unlabeled_evaluation_remains_unavailable(real_artifacts, real_queries):
    from layer3_graphrag.evaluation import compare_engines
    assert not any(q['expected_source_ids'] for q in real_queries)
    result = compare_engines({m: real_artifacts[3] for m in ('vector', 'graph', 'hybrid')}, real_queries[:1], [1,5,10])
    assert result['query_ids'] == [real_queries[0]['query_id']]


def test_real_graph_source_seed_and_free_text_engine(real_artifacts):
    import json
    snapshot, config, artifacts, engine = real_artifacts
    from layer3_graphrag.provenance import serialize
    chunks_by_source = {}
    for row in snapshot.tables['source_chunks']:
        chunks_by_source.setdefault((row['source_type'], row['source_id']), []).append(row)
    eligible = []
    for relation in snapshot.tables['relations']:
        researcher = artifacts.graph.nodes[relation['target_entity_id']]
        source = artifacts.graph.nodes[relation['source_entity_id']]
        if source['entity_type'] == 'PROJECT' and json.loads(researcher['metadata_json']).get('identity_status', '').upper() == 'RESOLVED' and (source['entity_type'], source['canonical_id']) in chunks_by_source:
            eligible.append(source)
    assert eligible
    seed = min(eligible, key=lambda r: r['entity_id'])
    chunk = min(chunks_by_source[(seed['entity_type'], seed['canonical_id'])], key=lambda r: r['chunk_id'])
    results = {}
    for mode in ('vector', 'graph', 'hybrid'):
        package = engine.query(chunk['text'], query_id='REAL_FREE_QUERY_' + mode, mode=mode, seed_entity_ids=[seed['entity_id']])
        assert package['retrieved_chunks']
        assert all(r['source_space'] == 'SOURCE' for r in package['retrieved_chunks'])
        assert all(not r['is_discovery_chunk'] for r in package['reference_context'])
        results[mode] = {'explicit_seed_entity_ids': [seed['entity_id']], 'query_chunk_id': chunk['chunk_id'],
            'retrieved_chunk_ids': [r['chunk_id'] for r in package['retrieved_chunks']], 'metrics': package['metrics']}
    (ROOT / 'outputs/layer3/reports/free_query_validation.json').write_text(serialize(results), encoding='utf-8')


def test_real_source_index_search_api(real_artifacts):
    import pytest
    artifacts = real_artifacts[2]
    hits = artifacts.indexes['SOURCE'].search(artifacts.bundles['SOURCE'].vectors[0], 30)
    assert len(hits) == 30
    assert hits[0]['score'] == pytest.approx(1., abs=1e-6)
    assert all(r['source_space'] == 'SOURCE' for r in hits)
    assert len({r['chunk_id'] for r in hits}) == 30
