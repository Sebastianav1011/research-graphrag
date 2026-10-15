"""Behavioral tests for factual expansion with measured semantic support."""
import copy
import json
import pytest
from layer3_graphrag.embeddings import build_embeddings
from layer3_graphrag.graph import build_graph
from layer3_graphrag.indicator_retrieval import IndicatorRetriever, diverse
from layer3_graphrag.vector_index import NumpyVectorIndex
from layer3_graphrag.quality import validate_retrieval


def service(snapshot, fake_provider, layer3_config):
    cfg = copy.deepcopy(layer3_config)
    cfg['embeddings'].update(model=fake_provider.model_name, model_version=fake_provider.model_version,
        dimensions=fake_provider.dimensions, batch_size=fake_provider.batch_size)
    cfg['retrieval'].update(enabled=True, vector_top_k_per_reference_chunk=1)
    bundle = build_embeddings(snapshot, 'SOURCE', fake_provider, cfg['embeddings'], 'unit')
    index = NumpyVectorIndex('SOURCE')
    index.build(bundle)
    graph = build_graph(snapshot)
    return IndicatorRetriever(snapshot, index, fake_provider, graph, cfg, 'unit'), cfg


def test_graph_cannot_promote_zero_semantic_support(snapshot, fake_provider, layer3_config):
    retriever, cfg = service(snapshot, fake_provider, layer3_config)
    rows, expanded, metrics = retriever.score_rows(['forest'], ['c-reference'])
    assert {r['source_id'] for r in rows} == {'P1'}
    assert any(r['canonical_id'] == 'A1' for r in expanded['entities'])
    assert metrics['ambiguous_bridge_uses'] == 0
    assert rows[0]['hybrid_score'] == pytest.approx(.8)


def test_reference_batch_preserves_source_and_provenance(snapshot, fake_provider, layer3_config):
    retriever, cfg = service(snapshot, fake_provider, layer3_config)
    candidates, packages, comparison, metrics = retriever.process()
    assert len(packages) == 1
    assert all('c-reference' not in r['discovery_chunk_ids'] for r in candidates)
    assert candidates[0]['reference_chunk_ids'] == ['c-reference']
    result, issues, anomalies, privacy = validate_retrieval(snapshot, retriever.graph, candidates, packages, cfg)
    assert result['status'] == 'PASS' and not issues and not anomalies and not privacy
    assert comparison[0]['graph_candidates'] == 0


def test_ambiguous_bridge_is_blocked_and_invalid_path_rejected(snapshot, fake_provider, layer3_config):
    snapshot.tables['entities'][2]['metadata_json'] = json.dumps({'identity_status': 'ambiguous'})
    retriever, cfg = service(snapshot, fake_provider, layer3_config)
    _, expanded, _ = retriever.score_rows(['forest'], ['c-reference'])
    assert not any(r['canonical_id'] == 'A1' for r in expanded['entities'])
    with pytest.raises(ValueError, match='bridge'):
        retriever.check_path('ARTICLE:A1', ['rel-PROJECT:P1', 'rel-ARTICLE:A1'], ['PROJECT:P1'])


def test_diversity_retains_best_chunks_and_deterministic_ties():
    rows = [{'chunk_id': str(n), 'source_type': 'PROJECT', 'source_id': 'p' if n < 5 else 'q', 'score': 1-n*.01} for n in range(8)]
    chosen = diverse(rows, 'score', 6, 3)
    assert [r['chunk_id'] for r in chosen] == ['0','1','2','5','6','7']
