"""Ephemeral examples only; no institutional input and no persistent corpus."""
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
import yaml
import pyarrow as pa
import pyarrow.parquet as pq

from layer3_graphrag.contracts import KNOWLEDGE_TABLES, KnowledgeSnapshot
from layer3_graphrag.embedding_provider import EmbeddingProvider
from layer3_graphrag.provenance import file_hash, serialize, text_hash

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def layer3_config():
    config = deepcopy(yaml.safe_load((ROOT / 'config/layer3.yaml').read_text(encoding='utf-8')))
    # Gate unit tests require a closed fixture regardless of official runtime readiness.
    config['readiness'] = {'layer2_status': 'WAITING_FOR_FINAL_PROJECT_LAYER_2_READY', 'approved_layer2_manifest_sha256': None}
    config['execution']['allow_real_build'] = False
    config.get('retrieval', {})['enabled'] = False
    return config


def make_snapshot(root):
    manifest = {'layer2_run_id': 'unit-layer2', 'layer1_run_id': 'unit-layer1',
                'layer1_manifest_hash': 'a' * 64, 'status': 'SUCCESS', 'publication_kind': 'real'}
    tables = {name: [] for name in KNOWLEDGE_TABLES}
    for prefix, source_id, source_type, doc_id, chunk_id, words in (
            ('source', 'P1', 'PROJECT', 'doc-project', 'c-project', 'forest restoration'),
            ('source', 'A1', 'ARTICLE', 'doc-article', 'c-article', 'sea conservation'),
            ('reference', 'I1', 'INDICATOR_REFERENCE', 'doc-reference', 'c-reference', 'indicator forest')):
        section_id = doc_id + '-section'
        prov = {'layer1_run_id': 'unit-layer1', 'layer2_run_id': 'unit-layer2', 'canonical_id': source_id,
                'layer1': [{'record_source': 'unit-memory', 'source_row': 2, 'field_mapping': {'title': 'title'}, 'original_values': {'title': words}}],
                'document_id': doc_id, 'section_id': section_id, 'chunk_id': chunk_id, 'source_field': 'title'}
        tables[prefix + '_documents'].append({'document_id': doc_id, 'source_id': source_id, 'source_type': source_type,
            'title': words, 'canonical_dataset': 'indicadores' if prefix == 'reference' else 'proyectos' if source_type == 'PROJECT' else 'articulos',
            'canonical_run_id': 'unit-layer1', 'metadata_json': '{}', 'provenance_json': serialize(prov), 'layer2_run_id': 'unit-layer2'})
        tables[prefix + '_sections'].append({'section_id': section_id, 'document_id': doc_id, 'source_id': source_id,
            'source_type': source_type, 'field_name': 'title', 'text_original': words, 'text_normalized': words,
            'text_hash': text_hash(words), 'text_hash_original': text_hash(words), 'text_hash_normalized': text_hash(words),
            'field_order': 0, 'char_count': len(words), 'word_count': 2, 'provenance_json': serialize(prov), 'layer2_run_id': 'unit-layer2'})
        tables[prefix + '_chunks'].append({'chunk_id': chunk_id, 'section_id': section_id, 'document_id': doc_id,
            'source_id': source_id, 'source_type': source_type, 'field_name': 'title', 'text': words, 'chunk_hash': text_hash(words),
            'char_start': 0, 'char_end': len(words), 'chunk_index': 0, 'word_count': 2, 'overlap_word_count': 0,
            'provenance_json': serialize(prov), 'layer2_run_id': 'unit-layer2'})
    prov = serialize({'layer1_run_id': 'unit-layer1', 'layer2_run_id': 'unit-layer2', 'layer1': [{'record_source': 'unit-memory', 'source_row': 2}]})
    for kind, cid in (('PROJECT', 'P1'), ('ARTICLE', 'A1'), ('RESEARCHER', 'R1'), ('INDICATOR', 'I1')):
        tables['entities'].append({'entity_id': kind + ':' + cid, 'entity_type': kind, 'canonical_id': cid,
            'label': kind, 'metadata_json': serialize({'identity_status': 'resolved'}) if kind == 'RESEARCHER' else '{}',
            'provenance_json': prov, 'layer2_run_id': 'unit-layer2'})
    for source, kind in (('PROJECT:P1', 'PROJECT_HAS_RESEARCHER'), ('ARTICLE:A1', 'ARTICLE_HAS_RESEARCHER')):
        tables['relations'].append({'relation_id': 'rel-' + source, 'source_entity_id': source,
            'target_entity_id': 'RESEARCHER:R1', 'relation_type': kind, 'attributes_json': '{}',
            'evidence_type': 'STRUCTURED_CANONICAL', 'provenance_json': prov, 'layer2_run_id': 'unit-layer2'})
    return KnowledgeSnapshot(Path(root).resolve(), manifest, 'b' * 64, tables, {})


@pytest.fixture
def snapshot(tmp_path):
    return make_snapshot(tmp_path)


class FakeProvider(EmbeddingProvider):
    model_name = 'unit-test-model'
    model_version = 'unit-test-v1'
    dimensions = 3
    batch_size = 2

    def __init__(self):
        self.document_calls, self.query_calls = [], []

    def _embed(self, texts):
        return np.asarray([[1., 0., 0.] if 'forest' in text else [0., 1., 0.] if 'sea' in text else [0., 0., 1.] for text in texts], dtype=np.float32).reshape(-1, 3)

    def embed_documents(self, texts):
        self.document_calls.append(list(texts))
        return self._embed(texts)

    def embed_queries(self, texts):
        self.query_calls.append(list(texts))
        return self._embed(texts)


@pytest.fixture
def fake_provider():
    return FakeProvider()


@pytest.fixture
def approved_workspace(tmp_path, snapshot, layer3_config):
    folder = tmp_path / 'data/knowledge'
    folder.mkdir(parents=True)
    snapshot.manifest['output_hashes'] = {}
    snapshot.manifest['layer1_manifest_path'] = 'data/canonical/_manifest.json'
    for table, rows in snapshot.tables.items():
        path = folder / (table + '.parquet')
        pq.write_table(pa.Table.from_pylist(rows), path)
        snapshot.manifest['output_hashes'][table] = file_hash(path)
        snapshot.manifest[table + '_created'] = len(rows)
    path = folder / '_manifest.json'
    path.write_text(serialize(snapshot.manifest), encoding='utf-8')
    config = deepcopy(layer3_config)
    config['readiness'] = {'layer2_status': 'FINAL_PROJECT_LAYER_2_READY', 'approved_layer2_manifest_sha256': file_hash(path)}
    config['execution']['allow_real_build'] = True
    config['embeddings'].update({'provider': 'unit-test-injected', 'model': FakeProvider.model_name,
                                 'model_version': FakeProvider.model_version, 'dimensions': FakeProvider.dimensions})
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/layer3.yaml').write_text(yaml.safe_dump(config), encoding='utf-8')
    return tmp_path, config
