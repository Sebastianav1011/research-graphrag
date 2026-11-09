"""Unit orchestration with tiny ephemeral fixtures, never the institutional corpus."""
import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from layer3_graphrag.configuration import load_config
from layer3_graphrag.contracts import context_schema, layer3_manifest_schema
from layer3_graphrag.source_context import build_context
from layer3_graphrag.manifest import validate_publication
from layer3_graphrag.pipeline import run, publish_directory
from layer3_graphrag.provenance import file_hash
from layer3_graphrag.retrieval import base_score, combine_hits, rank_hits


def hit(chunk='x', source='P1', vector=1., distance=None, strength=0.):
    return {'chunk_id': chunk, 'source_id': source, 'source_type': 'PROJECT', 'document_id': 'd-' + source,
            'section_id': 's-' + source, 'field_name': 'title', 'source_space': 'SOURCE',
            'vector_score': vector, 'graph_distance': distance, 'structured_relation_strength': strength}


def test_ranking_exact_formula_and_diversity(layer3_config):
    weights = layer3_config['hybrid'] | {'vector_weight': 2., 'graph_weight': 1., 'structured_relation_weight': 1., 'diversity_weight': 0.}
    assert base_score(hit(vector=.6, distance=1, strength=1.), weights)[0] == pytest.approx((2*.8 + .5 + 1)/4)
    weights['diversity_weight'] = 1.
    rows = [hit('a'), hit('b'), hit('c', 'P2', vector=.9)]
    assert [r['chunk_id'] for r in rank_hits(rows, weights)] == ['a', 'c', 'b']


@pytest.mark.parametrize('change', [{'vector_score': float('nan')}, {'graph_distance': -1},
                                  {'vector_score': 2.}, {'structured_relation_strength': 1.1}])
def test_invalid_signals_rejected(change, layer3_config):
    with pytest.raises(ValueError):
        base_score(hit() | change, layer3_config['hybrid'])


def test_combination_keeps_best_signals_and_support(layer3_config):
    merged = combine_hits([hit(vector=.8)], [hit(vector=None, distance=2, strength=1.) | {'relation_ids': ['r']}])
    assert len(merged) == 1 and merged[0]['vector_score'] == .8 and merged[0]['graph_distance'] == 2
    assert merged[0]['relation_ids'] == ['r']
    assert 'confidence_score' not in rank_hits(merged, layer3_config['hybrid'])[0]


def test_cross_space_and_conflicting_links_rejected():
    with pytest.raises(ValueError):
        combine_hits([hit() | {'source_space': 'REFERENCE'}], [])
    with pytest.raises(ValueError):
        combine_hits([hit()], [hit(source='different')])


def test_context_limits_whole_chunks_and_no_reference_evidence(snapshot, layer3_config):
    hits = [row | {'source_space': 'SOURCE', 'vector_score': 1., 'graph_distance': None, 'rank': i + 1} for i, row in enumerate(snapshot.tables['source_chunks'])]
    refs = [row | {'source_space': 'REFERENCE'} for row in snapshot.tables['reference_chunks']]
    settings = layer3_config['context'] | {'max_chunks': 1, 'max_documents': 1}
    package = build_context(snapshot, 'q', 'forest', hits, snapshot.tables['entities'], snapshot.tables['relations'], refs, settings, config=layer3_config)
    assert len(package['retrieved_chunks']) == len(package['retrieved_documents']) == 1
    assert package['reference_context'][0]['is_discovery_chunk'] is False
    Draft202012Validator(context_schema()).validate(package)
    limited = build_context(snapshot, 'q', 'forest', hits, [], [], refs, settings | {'max_characters': 1}, config=layer3_config)
    assert limited['retrieved_chunks'] == limited['reference_context'] == []


def test_context_envelope_limit(snapshot, layer3_config):
    with pytest.raises(ValueError, match='envelope'):
        build_context(snapshot, 'q', 'forest', [], [], [], [], layer3_config['context'] | {'max_package_characters': 1}, config=layer3_config)


def test_plan_and_gate_never_open_knowledge(tmp_path, layer3_config, monkeypatch):
    import yaml
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/layer3.yaml').write_text(yaml.safe_dump(layer3_config), encoding='utf-8')
    def forbidden(*args, **kwargs):
        raise AssertionError('Knowledge was opened before approval')
    monkeypatch.setattr('layer3_graphrag.pipeline.validate_inputs', forbidden)
    plan = run(tmp_path)
    assert not plan['knowledge_read'] and not plan['published']
    for mode in ('validate', 'build', 'query', 'evaluate'):
        with pytest.raises(RuntimeError, match='WAITING'):
            run(tmp_path, mode=mode)
    assert not (tmp_path / 'outputs').exists()


def test_ephemeral_end_to_end_three_modes_and_reference(approved_workspace, fake_provider):
    root, config = approved_workspace
    before = {str(p): file_hash(p) for p in (root / 'outputs/layer2/knowledge').iterdir()}
    manifest = run(root, mode='build', provider=fake_provider)
    Draft202012Validator(layer3_manifest_schema()).validate(manifest)
    for mode in ('vector', 'graph', 'hybrid'):
        package = run(root, mode='query', provider=fake_provider, query_text='forest', retrieval_mode=mode, seed_entity_ids=['PROJECT:P1'])
        Draft202012Validator(context_schema()).validate(package)
        assert package['retrieved_chunks']
        assert all(r['source_space'] == 'SOURCE' for r in package['retrieved_chunks'])
        assert package['provenance']['layer2_manifest_hash'] == manifest['layer2_manifest_hash']
        assert package['provenance']['layer1_run_id'] == 'unit-layer1'
    assert all(file_hash(__import__('pathlib').Path(p)) == sha for p, sha in before.items())
    assert not (root / 'outputs/layer2/canonical').exists()


def test_graph_mode_requires_non_ground_truth_seeds(approved_workspace, fake_provider):
    root, _ = approved_workspace
    run(root, mode='build', provider=fake_provider)
    with pytest.raises(ValueError, match='explicit entity seeds'):
        run(root, mode='query', provider=fake_provider, query_text='forest', retrieval_mode='graph')


def test_vector_top_k_separate_from_hybrid_candidate_pool(approved_workspace, fake_provider):
    import yaml
    root, config = approved_workspace
    config['vector_index']['top_k'] = 1
    (root / 'config/layer3.yaml').write_text(yaml.safe_dump(config), encoding='utf-8')
    run(root, mode='build', provider=fake_provider)
    vector = run(root, mode='query', provider=fake_provider, query_text='forest', retrieval_mode='vector')
    hybrid = run(root, mode='query', provider=fake_provider, query_text='forest', retrieval_mode='hybrid')
    assert len(vector['retrieved_chunks']) == 1
    assert len(hybrid['retrieved_chunks']) == 2


def test_idempotence_cache_and_snapshot_rebuild(approved_workspace, fake_provider):
    root, config = approved_workspace
    first = run(root, mode='build', provider=fake_provider)
    files = root / 'outputs/layer3/publication/embeddings/source/records.json'
    old = json.loads(files.read_text(encoding='utf-8'))
    call_count = len(fake_provider.document_calls)
    second = run(root, mode='build', provider=fake_provider)
    new = json.loads(files.read_text(encoding='utf-8'))
    assert len(fake_provider.document_calls) == call_count
    assert first['layer3_run_id'] != second['layer3_run_id']
    assert [{k: v for k, v in r.items() if k != 'layer3_run_id'} for r in old] == [{k: v for k, v in r.items() if k != 'layer3_run_id'} for r in new]
    assert validate_publication(root / 'outputs/layer3/publication')['layer3_run_id'] == second['layer3_run_id']


def test_changed_source_prevents_query_and_publication(approved_workspace, fake_provider, monkeypatch):
    root, _ = approved_workspace
    run(root, mode='build', provider=fake_provider)
    path = root / 'outputs/layer2/knowledge/source_chunks.parquet'
    path.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='hash mismatch'):
        run(root, mode='query', provider=fake_provider, query_text='forest')


def test_publication_rollback_restores_old_directory(tmp_path):
    archive = tmp_path / 'outputs/runs/one'
    candidate = archive / 'graphrag'
    candidate.mkdir(parents=True)
    (candidate / 'new').write_text('new', encoding='utf-8')
    destination = tmp_path / 'outputs/layer3/publication'
    destination.mkdir(parents=True)
    (destination / 'old').write_text('old', encoding='utf-8')
    def failure():
        raise RuntimeError('simulated finalization failure')
    with pytest.raises(RuntimeError):
        publish_directory(candidate, destination, archive, failure)
    assert (destination / 'old').read_text(encoding='utf-8') == 'old'
    assert (archive / 'failed_graphrag/new').exists()
    assert not (archive.parent.parent / 'publication_pending.json').exists()


def test_evaluation_uses_same_set_without_reference_ground_truth(approved_workspace, fake_provider):
    root, _ = approved_workspace
    run(root, mode='build', provider=fake_provider)
    reports = root / 'outputs/layer3/reports'
    reports.mkdir(exist_ok=True)
    queries = [{'query_id': 'q', 'query_text': 'forest', 'query_type': 'unit', 'expected_source_ids': ['P1'],
                'expected_entity_ids': [], 'expected_relation_types': [], 'notes': 'Ephemeral unit labels only',
                'seed_entity_ids': ['PROJECT:P1']}]
    (reports / 'unit-queries.json').write_text(json.dumps(queries), encoding='utf-8')
    result = run(root, mode='evaluate', provider=fake_provider, queries_path='outputs/layer3/reports/unit-queries.json')
    assert set(result['modes']) == {'vector', 'graph', 'hybrid'}
    assert result['query_ids'] == ['q']
