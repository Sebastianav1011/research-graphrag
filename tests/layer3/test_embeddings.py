"""Embeddings tests use a small in-memory deterministic provider only."""
import copy
import sys

import numpy as np
import pytest

from layer3_graphrag.embedding_pipeline import (
    EmbeddingCache, build_embeddings, cache_key, embedding_config_hash,
    load_bundle, save_bundle, validate_vectors,
)
from layer3_graphrag.embedding_provider import create_provider


def settings(config, provider):
    result = copy.deepcopy(config['embeddings'])
    result.update(provider='unit_test', model=provider.model_name, model_version=provider.model_version,
                  dimensions=provider.dimensions, batch_size=provider.batch_size)
    return result


def test_embedding_metadata_cache_and_run_independence(snapshot, fake_provider, layer3_config, tmp_path):
    config = settings(layer3_config, fake_provider)
    cache = EmbeddingCache(tmp_path / 'cache')
    first = build_embeddings(snapshot, 'SOURCE', fake_provider, config, 'run-a', cache)
    calls = len(fake_provider.document_calls)
    second = build_embeddings(snapshot, 'SOURCE', fake_provider, config, 'run-b', cache)
    assert len(fake_provider.document_calls) == calls
    assert first.metadata['computed_unique_texts'] == 2
    assert second.metadata['computed_unique_texts'] == 0
    assert second.metadata['cache_hits'] == 2
    np.testing.assert_allclose(first.vectors, second.vectors)
    assert [r['embedding_id'] for r in first.records] == [r['embedding_id'] for r in second.records]
    assert all(r['layer3_run_id'] == 'run-b' for r in second.records)
    assert all(r['source_space'] == 'SOURCE' and r['dimensions'] == 3 for r in first.records)
    assert {r['chunk_id'] for r in first.records} == {'c-project', 'c-article'}
    assert all({'model', 'model_version', 'text_hash', 'embedding_hash', 'embedding_config_hash'} <= r.keys()
               for r in first.records)
    assert not fake_provider.query_calls


def test_repeated_text_computed_once_without_cache(snapshot, fake_provider, layer3_config):
    duplicate = copy.deepcopy(snapshot)
    chunk = copy.deepcopy(duplicate.tables['source_chunks'][0])
    chunk['chunk_id'] = 'c-clone'
    duplicate.tables['source_chunks'] = [duplicate.tables['source_chunks'][0], chunk]
    bundle = build_embeddings(duplicate, 'SOURCE', fake_provider, settings(layer3_config, fake_provider), 'run')
    assert bundle.metadata['computed_unique_texts'] == 1
    assert sum(map(len, fake_provider.document_calls)) == 1
    assert bundle.records[0]['embedding_id'] != bundle.records[1]['embedding_id']
    np.testing.assert_array_equal(bundle.vectors[0], bundle.vectors[1])


@pytest.mark.parametrize('key,value', [('dimensions', 4), ('model', 'wrong-model'), ('model_version', 'wrong-revision')])
def test_provider_cannot_silently_override_embedding_configuration(snapshot, fake_provider, layer3_config, key, value):
    config = settings(layer3_config, fake_provider)
    config[key] = value
    with pytest.raises(ValueError):
        build_embeddings(snapshot, 'SOURCE', fake_provider, config, 'run')
    assert fake_provider.document_calls == []


def test_cache_spaces_and_configuration_are_distinct(snapshot, fake_provider, layer3_config):
    config = settings(layer3_config, fake_provider)
    chunk = snapshot.tables['source_chunks'][0]
    base = embedding_config_hash(config, fake_provider)
    assert cache_key(chunk, 'SOURCE', base) != cache_key(chunk, 'REFERENCE', base)
    for key, value in [('normalize_embeddings', False), ('normalization_version', 'v2'),
                       ('model', 'different'), ('model_version', 'different'), ('dimensions', 4)]:
        changed = config | {key: value}
        assert cache_key(chunk, 'SOURCE', base) != cache_key(chunk, 'SOURCE', embedding_config_hash(changed, fake_provider))
    fake_provider.model_version = 'unit-test-v2'
    assert base != embedding_config_hash(config, fake_provider)


def test_cache_rejects_stale_chunk_hash(snapshot):
    chunk = copy.deepcopy(snapshot.tables['source_chunks'][0])
    chunk['text'] += ' changed'
    with pytest.raises(ValueError):
        cache_key(chunk, 'SOURCE', 'hash')


def test_source_and_reference_have_separate_metadata(snapshot, fake_provider, layer3_config):
    config = settings(layer3_config, fake_provider)
    source = build_embeddings(snapshot, 'SOURCE', fake_provider, config, 'run')
    reference = build_embeddings(snapshot, 'REFERENCE', fake_provider, config, 'run')
    assert reference.records[0]['chunk_id'] == 'c-reference'
    assert reference.metadata['source_space'] == 'REFERENCE'
    assert source.metadata['source_space'] == 'SOURCE'


@pytest.mark.parametrize('vectors', [[[0, 0, 0]], [[1, 2]], [[float('nan'), 1, 1]], [[1, float('inf'), 1]]])
def test_invalid_embedding_vectors_rejected(vectors):
    with pytest.raises(ValueError):
        validate_vectors(vectors, 1, 3)


def test_normalization_and_empty_vector_shape():
    normalized = validate_vectors([[3, 4, 0]], 1, 3, normalize=True)
    np.testing.assert_allclose(normalized, [[0.6, 0.8, 0]])
    assert normalized.dtype == np.float32
    assert validate_vectors(np.empty((0, 3)), 0, 3).shape == (0, 3)


def test_bundle_roundtrip_and_corruption(snapshot, fake_provider, layer3_config, tmp_path):
    bundle = build_embeddings(snapshot, 'SOURCE', fake_provider, settings(layer3_config, fake_provider), 'run')
    save_bundle(bundle, tmp_path)
    restored = load_bundle(tmp_path)
    assert restored.records == bundle.records
    np.testing.assert_array_equal(restored.vectors, bundle.vectors)
    with (tmp_path / 'records.json').open('ab') as stream:
        stream.write(b' ')
    with pytest.raises(ValueError, match='checksum'):
        load_bundle(tmp_path)


def test_cache_rejects_corruption_and_dimension_mismatch(tmp_path):
    cache = EmbeddingCache(tmp_path)
    cache.put('key', np.asarray([1, 2, 3], dtype=np.float32))
    with pytest.raises(ValueError):
        cache.get('key', 4)
    with (tmp_path / 'key.npy').open('ab') as stream:
        stream.write(b'corruption')
    with pytest.raises(ValueError, match='corrupt'):
        cache.get('key', 3)


def test_optional_adapter_is_lazy_and_queries_documents_are_separate(monkeypatch, layer3_config):
    config = layer3_config['embeddings'] | {'provider': 'sentence_transformers', 'model': 'local-model',
              'model_version': 'a' * 40, 'dimensions': 3}
    monkeypatch.setitem(sys.modules, 'sentence_transformers', None)
    provider = create_provider(config)
    assert provider._model is None
    assert provider.embed_documents([]).shape == (0, 3)
    assert provider.embed_queries([]).shape == (0, 3)
    with pytest.raises(RuntimeError, match='not installed'):
        provider.embed_documents(['text'])
    class LocalModel:
        max_seq_length = 8192
        def tokenizer(self, texts, **kwargs):
            return {'length': [len(text.split()) for text in texts]}
        def encode_document(self, texts, **kwargs):
            return [[1, 0, 0] for _ in texts]
        def encode_query(self, texts, **kwargs):
            return [[0, 1, 0] for _ in texts]
    provider._model = LocalModel()
    np.testing.assert_array_equal(provider.embed_documents(['text']), [[1, 0, 0]])
    np.testing.assert_array_equal(provider.embed_queries(['text']), [[0, 1, 0]])


@pytest.mark.parametrize('revision', ['main', 'v1.0', 'g' * 40])
def test_real_provider_requires_immutable_revision(layer3_config, revision):
    config = layer3_config['embeddings'] | {'provider': 'sentence_transformers', 'model': 'local-model',
              'model_version': revision, 'dimensions': 3}
    with pytest.raises(ValueError, match='immutable'):
        create_provider(config)
