"""Knowledge contract tests use temporary Parquet files, never real Layer 2."""
import copy
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from layer3_graphrag.contracts import KNOWLEDGE_TABLES
from layer3_graphrag.provenance import file_hash, serialize, text_hash
from layer3_graphrag.validate_inputs import assert_unchanged, validate_inputs, validate_tables


def publish_fixture(root, snapshot, config):
    """Local contract fixture marked real for gate tests, not institutional data."""
    folder = root / 'data' / 'knowledge'
    folder.mkdir(parents=True)
    manifest = copy.deepcopy(snapshot.manifest)
    manifest.update(status='SUCCESS', publication_kind='real', output_hashes={})
    for table in KNOWLEDGE_TABLES:
        path = folder / (table + '.parquet')
        pq.write_table(pa.Table.from_pylist(snapshot.tables[table]), path)
        manifest['output_hashes'][table] = file_hash(path)
        manifest[table + '_created'] = len(snapshot.tables[table])
    path = folder / '_manifest.json'
    path.write_text(serialize(manifest), encoding='utf-8')
    approved = copy.deepcopy(config)
    approved['readiness'].update(layer2_status='FINAL_PROJECT_LAYER_2_READY',
                                 approved_layer2_manifest_sha256=file_hash(path))
    return folder, manifest, approved


def update_manifest(folder, manifest, config):
    path = folder / '_manifest.json'
    path.write_text(serialize(manifest), encoding='utf-8')
    config['readiness']['approved_layer2_manifest_sha256'] = file_hash(path)


def test_all_eight_tables_validate_and_exact_approved_hash_is_preserved(snapshot, layer3_config, tmp_path):
    folder, manifest, config = publish_fixture(tmp_path, snapshot, layer3_config)
    result = validate_inputs(tmp_path, config)
    assert set(result.tables) == set(KNOWLEDGE_TABLES)
    assert result.manifest_hash == config['readiness']['approved_layer2_manifest_sha256']
    assert result.root == tmp_path.resolve()
    assert result.hashes == manifest['output_hashes']
    assert_unchanged(result)


def test_unapproved_snapshot_fails_before_parquet_reads(snapshot, layer3_config, tmp_path, monkeypatch):
    folder, manifest, config = publish_fixture(tmp_path, snapshot, layer3_config)
    config['readiness']['approved_layer2_manifest_sha256'] = '0' * 64
    def forbidden(*args, **kwargs):
        raise AssertionError('Cannot read unapproved dataset')
    monkeypatch.setattr(pq, 'read_table', forbidden)
    with pytest.raises(RuntimeError, match='explicitly approved'):
        validate_inputs(tmp_path, config)


@pytest.mark.parametrize('field,value', [('status', 'FAILED'), ('publication_kind', 'synthetic')])
def test_nonfinal_publication_rejected(snapshot, layer3_config, tmp_path, field, value):
    folder, manifest, config = publish_fixture(tmp_path, snapshot, layer3_config)
    manifest[field] = value
    update_manifest(folder, manifest, config)
    with pytest.raises(ValueError, match='successful and real'):
        validate_inputs(tmp_path, config)


def test_missing_knowledge_file_is_not_substituted(snapshot, layer3_config, tmp_path):
    folder, manifest, config = publish_fixture(tmp_path, snapshot, layer3_config)
    (folder / 'source_chunks.parquet').unlink()
    with pytest.raises(FileNotFoundError):
        validate_inputs(tmp_path, config)


def test_empty_parquet_still_requires_contract_columns(snapshot, layer3_config, tmp_path):
    folder, manifest, config = publish_fixture(tmp_path, snapshot, layer3_config)
    path = folder / 'relations.parquet'
    pq.write_table(pa.table({'relation_id': pa.array([], type=pa.string())}), path)
    manifest['relations_created'] = 0
    manifest['output_hashes']['relations'] = file_hash(path)
    update_manifest(folder, manifest, config)
    with pytest.raises(ValueError, match='schema'):
        validate_inputs(tmp_path, config)


def test_typed_empty_relations_are_valid_without_invented_edges(snapshot, layer3_config, tmp_path):
    folder, manifest, config = publish_fixture(tmp_path, snapshot, layer3_config)
    path = folder / 'relations.parquet'
    schema = pq.read_schema(path)
    pq.write_table(pa.Table.from_pylist([], schema=schema), path)
    manifest['relations_created'] = 0
    manifest['output_hashes']['relations'] = file_hash(path)
    update_manifest(folder, manifest, config)
    result = validate_inputs(tmp_path, config)
    assert result.tables['relations'] == []


def test_parquet_hash_and_row_counts_are_checked(snapshot, layer3_config, tmp_path):
    folder, manifest, config = publish_fixture(tmp_path, snapshot, layer3_config)
    with (folder / 'source_chunks.parquet').open('ab') as stream:
        stream.write(b'altered')
    with pytest.raises(ValueError, match='hash mismatch'):
        validate_inputs(tmp_path, config)
    manifest['output_hashes']['source_chunks'] = file_hash(folder / 'source_chunks.parquet')
    manifest['source_chunks_created'] += 1
    update_manifest(folder, manifest, config)
    # Rewrite the fixture as valid Parquet before testing row counts independently.
    pq.write_table(pa.Table.from_pylist(snapshot.tables['source_chunks']), folder / 'source_chunks.parquet')
    manifest['output_hashes']['source_chunks'] = file_hash(folder / 'source_chunks.parquet')
    update_manifest(folder, manifest, config)
    with pytest.raises(ValueError, match='row count'):
        validate_inputs(tmp_path, config)


@pytest.mark.parametrize('relative', ['data/knowledge/.publish.lock', 'outputs/layer2/.publish.lock',
                                    'outputs/layer2/publication_pending.json'])
def test_inflight_layer2_publication_rejected(snapshot, layer3_config, tmp_path, relative):
    folder, manifest, config = publish_fixture(tmp_path, snapshot, layer3_config)
    lock = tmp_path / relative
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text('pending', encoding='utf-8')
    with pytest.raises(RuntimeError, match='publication|recovery'):
        validate_inputs(tmp_path, config)


@pytest.mark.parametrize('target', ['_manifest.json', 'source_chunks.parquet'])
def test_snapshot_mutation_invalidates_operation(snapshot, layer3_config, tmp_path, target):
    folder, manifest, config = publish_fixture(tmp_path, snapshot, layer3_config)
    result = validate_inputs(tmp_path, config)
    with (folder / target).open('ab') as stream:
        stream.write(b' changed')
    with pytest.raises(RuntimeError, match='changed'):
        assert_unchanged(result)


@pytest.mark.parametrize('table,key,value,error', [
    ('source_chunks', 'section_id', 'nonexistent', 'chunk'),
    ('source_sections', 'document_id', 'nonexistent', 'section'),
    ('source_documents', 'source_type', 'INDICATOR_REFERENCE', 'space'),
    ('reference_documents', 'source_type', 'ARTICLE', 'space'),
    ('source_documents', 'source_id', 'unknown', 'entity'),
    ('source_documents', 'canonical_run_id', 'wrong-run', 'lineage'),
    ('source_chunks', 'layer2_run_id', 'wrong-run', 'run IDs'),
    ('source_chunks', 'char_start', -1, 'offsets'),
    ('source_chunks', 'char_end', 999999, 'offsets'),
    ('source_chunks', 'char_start', True, 'offsets'),
    ('source_chunks', 'text', 'fabricated', 'slice'),
    ('source_chunks', 'chunk_hash', '0' * 64, 'hash'),
    ('source_sections', 'text_normalized', None, 'text'),
    ('source_chunks', 'field_name', 'incorrect', 'chunk'),
])
def test_invalid_contract_values_rejected(snapshot, table, key, value, error):
    tables = copy.deepcopy(snapshot.tables)
    tables[table][0][key] = value
    with pytest.raises(ValueError, match=error):
        validate_tables(tables, snapshot.manifest)


def test_missing_fields_and_duplicate_ids_rejected(snapshot):
    tables = copy.deepcopy(snapshot.tables)
    del tables['source_chunks'][0]['text']
    with pytest.raises(ValueError, match='fields'):
        validate_tables(tables, snapshot.manifest)
    tables = copy.deepcopy(snapshot.tables)
    tables['source_chunks'].append(copy.deepcopy(tables['source_chunks'][0]))
    with pytest.raises(ValueError, match='duplicate'):
        validate_tables(tables, snapshot.manifest)


@pytest.mark.parametrize('key,value', [('layer1_run_id', 'wrong'), ('layer2_run_id', 'wrong'),
                                    ('layer1', []), ('chunk_id', 'wrong'),
                                    ('section_id', 'wrong'), ('document_id', 'wrong'),
                                    ('source_field', 'wrong')])
def test_provenance_contract_rejects_disconnected_chain(snapshot, key, value):
    tables = copy.deepcopy(snapshot.tables)
    chunk = tables['source_chunks'][0]
    provenance = json.loads(chunk['provenance_json'])
    provenance[key] = value
    chunk['provenance_json'] = json.dumps(provenance)
    with pytest.raises(ValueError, match='lineage|provenance'):
        validate_tables(tables, snapshot.manifest)


def test_no_parallel_entity_identity_and_exact_tables_required(snapshot):
    tables = copy.deepcopy(snapshot.tables)
    entity = copy.deepcopy(tables['entities'][0])
    entity['entity_id'] = 'duplicate-identity-new-node'
    tables['entities'].append(entity)
    with pytest.raises(ValueError, match='same Layer 2 identity'):
        validate_tables(tables, snapshot.manifest)
    tables = copy.deepcopy(snapshot.tables)
    del tables['reference_chunks']
    with pytest.raises(ValueError, match='eight'):
        validate_tables(tables, snapshot.manifest)


def test_source_reference_chunk_ids_do_not_overlap(snapshot):
    tables = copy.deepcopy(snapshot.tables)
    reference = tables['reference_chunks'][0]
    reference['chunk_id'] = tables['source_chunks'][0]['chunk_id']
    provenance = json.loads(reference['provenance_json'])
    provenance['chunk_id'] = reference['chunk_id']
    reference['provenance_json'] = json.dumps(provenance)
    with pytest.raises(ValueError, match='both spaces'):
        validate_tables(tables, snapshot.manifest)
