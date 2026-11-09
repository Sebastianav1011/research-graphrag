from layer2_processing.checkpoints import resolve
"""Closed boundary: only the eight knowledge files and their approved manifest."""
import json
from pathlib import Path

import pyarrow.parquet as pq
import pyarrow as pa

from .configuration import require_approval
from .contracts import KNOWLEDGE_TABLES, KEYS, REQUIRED, KnowledgeSnapshot
from .provenance import file_hash, text_hash

PHYSICAL_FIELDS = {
    'documents': 'document_id source_id source_type title canonical_dataset canonical_run_id metadata_json provenance_json layer2_run_id',
    'sections': 'section_id document_id source_id source_type field_name field_order text_original text_normalized char_count word_count text_hash text_hash_original text_hash_normalized provenance_json layer2_run_id',
    'chunks': 'chunk_id section_id document_id source_id source_type field_name chunk_index text char_start char_end word_count overlap_word_count chunk_hash provenance_json layer2_run_id',
    'entities': 'entity_id entity_type canonical_id label metadata_json provenance_json layer2_run_id',
    'relations': 'relation_id source_entity_id relation_type target_entity_id attributes_json evidence_type provenance_json layer2_run_id',
}


def validate_physical_schema(table, kind):
    expected = set(PHYSICAL_FIELDS[kind].split())
    if set(table.schema.names) != expected:
        raise ValueError('Knowledge physical schema columns differ: ' + kind)
    integer_fields = {'field_order', 'char_count', 'word_count', 'chunk_index', 'char_start', 'char_end', 'overlap_word_count'}
    for field in table.schema:
        required_type = pa.int64() if field.name in integer_fields else pa.string()
        if field.type != required_type:
            raise ValueError('Knowledge physical schema type differs: ' + field.name)
        if field.name not in {'title', 'label', 'text_original'} and table.column(field.name).null_count:
            raise ValueError('Unexpected knowledge null: ' + field.name)


def assert_unchanged(snapshot):
    folder = resolve(snapshot.root, 'outputs/layer2/knowledge')
    if folder.resolve() != folder or (folder / '_manifest.json').resolve().parent != folder or any((folder / (table + '.parquet')).resolve().parent != folder for table in snapshot.hashes):
        raise RuntimeError('Knowledge snapshot path changed or uses redirected files')
    if file_hash(folder / '_manifest.json') != snapshot.manifest_hash:
        raise RuntimeError('Layer 2 manifest changed during Layer 3 operation')
    for table, sha in snapshot.hashes.items():
        if file_hash(folder / (table + '.parquet')) != sha:
            raise RuntimeError('Layer 2 dataset changed: ' + table)
    if (folder / '.publish.lock').exists() or (snapshot.root / 'outputs/layer2/knowledge_artifacts/.publish.lock').exists():
        raise RuntimeError('Layer 2 publication is in progress')
    if (snapshot.root / 'outputs/layer2/knowledge_artifacts/publication_pending.json').exists():
        raise RuntimeError('Layer 2 publication recovery is pending')


def validate_tables(tables, manifest, fail_on_missing_provenance=True):
    if set(tables) != set(KNOWLEDGE_TABLES):
        raise ValueError('Exactly eight Layer 2 tables are required')
    for table, rows in tables.items():
        kind = table.split('_')[-1] if table.startswith(('source_', 'reference_')) else table
        required = REQUIRED[kind]
        seen = set()
        for row in rows:
            if not required <= set(row):
                raise ValueError('Missing knowledge fields: ' + table)
            if not isinstance(row[KEYS[table]], str) or not row[KEYS[table]] or row[KEYS[table]] in seen:
                raise ValueError('Invalid or duplicate knowledge ID: ' + table)
            seen.add(row[KEYS[table]])
            if row['layer2_run_id'] != manifest['layer2_run_id']:
                raise ValueError('Mixed Layer 2 run IDs')
            if fail_on_missing_provenance:
                upstream = json.loads(row['provenance_json'])
                if not isinstance(upstream, dict) or upstream.get('layer1_run_id') != manifest['layer1_run_id'] or upstream.get('layer2_run_id') != manifest['layer2_run_id']:
                    raise ValueError('Missing/mismatched inherited lineage')
                if not isinstance(upstream.get('layer1'), list) or not upstream['layer1']:
                    raise ValueError('Missing original lineage references')
    entity_links = {(row['entity_type'], row['canonical_id']): row['entity_id'] for row in tables['entities']}
    if len(entity_links) != len(tables['entities']):
        raise ValueError('Multiple entities for the same Layer 2 identity')
    for prefix in ('source', 'reference'):
        documents = {row['document_id']: row for row in tables[prefix + '_documents']}
        sections = {row['section_id']: row for row in tables[prefix + '_sections']}
        expected_types = {'PROJECT', 'ARTICLE'} if prefix == 'source' else {'INDICATOR_REFERENCE'}
        for document in documents.values():
            if document['source_type'] not in expected_types or document['canonical_run_id'] != manifest['layer1_run_id']:
                raise ValueError('Document space or canonical lineage mismatch')
            entity_type = 'INDICATOR' if prefix == 'reference' else document['source_type']
            if (entity_type, document['source_id']) not in entity_links:
                raise ValueError('Document has no existing entity identity')
        for section in sections.values():
            document = documents.get(section['document_id'])
            if not document or any(section[f] != document[f] for f in ('source_id', 'source_type')):
                raise ValueError('Orphan/mismatched section')
            if not isinstance(section['text_normalized'], str):
                raise ValueError('Invalid section text')
            if 'text_hash_normalized' in section and section['text_hash_normalized'] != text_hash(section['text_normalized']):
                raise ValueError('Section text hash mismatch')
        for chunk in tables[prefix + '_chunks']:
            section = sections.get(chunk['section_id'])
            if not section or any(chunk[f] != section[f] for f in ('document_id', 'source_id', 'source_type', 'field_name')):
                raise ValueError('Orphan/mismatched chunk')
            start, end = chunk['char_start'], chunk['char_end']
            if type(start) is not int or type(end) is not int or not (0 <= start < end <= len(section['text_normalized'])):
                raise ValueError('Invalid chunk offsets')
            if not isinstance(chunk['text'], str) or chunk['text'] != section['text_normalized'][start:end]:
                raise ValueError('Chunk text differs from section slice')
            if chunk['chunk_hash'] != text_hash(chunk['text']):
                raise ValueError('Chunk hash mismatch')
            if fail_on_missing_provenance:
                upstream = json.loads(chunk['provenance_json'])
                for key in ('chunk_id', 'section_id', 'document_id'):
                    if upstream.get(key) != chunk[key]:
                        raise ValueError('Chunk provenance ID mismatch')
                if upstream.get('source_field') != chunk['field_name']:
                    raise ValueError('Chunk field provenance mismatch')
    all_chunk_ids = [row['chunk_id'] for p in ('source', 'reference') for row in tables[p + '_chunks']]
    if len(all_chunk_ids) != len(set(all_chunk_ids)):
        raise ValueError('Chunk identity appears in both spaces')


def validate_inputs(root, config):
    # Approval before stat/open of any corpus file.
    require_approval(config)
    root = Path(root).resolve()
    intended = resolve(root, 'outputs/layer2/knowledge')
    folder = intended.resolve()
    if folder != intended:
        raise ValueError('Knowledge directory escapes project root')
    if (folder / '.publish.lock').exists() or (root / 'outputs/layer2/knowledge_artifacts/.publish.lock').exists() or (root / 'outputs/layer2/knowledge_artifacts/publication_pending.json').exists():
        raise RuntimeError('Layer 2 publication/recovery is in progress')
    manifest_path = folder / '_manifest.json'
    if manifest_path.resolve().parent != folder:
        raise ValueError('Knowledge manifest escapes its approved directory')
    raw = manifest_path.read_bytes()
    sha = __import__('hashlib').sha256(raw).hexdigest()
    if sha != config['readiness']['approved_layer2_manifest_sha256']:
        raise RuntimeError('Layer 2 snapshot is not the explicitly approved snapshot')
    manifest = json.loads(raw)
    for key in ('layer2_run_id', 'layer1_run_id', 'layer1_manifest_hash', 'output_hashes'):
        if key not in manifest:
            raise ValueError('Incomplete knowledge manifest: ' + key)
    if manifest.get('status') != 'SUCCESS' or manifest.get('publication_kind') != 'real':
        raise ValueError('Layer 2 publication must be successful and real')
    tables, hashes = {}, {}
    for table in KNOWLEDGE_TABLES:
        path = (folder / (table + '.parquet')).resolve()
        if path.parent != folder:
            raise ValueError('Knowledge file escapes its approved directory')
        expected = manifest['output_hashes'].get(table)
        if not isinstance(expected, str) or file_hash(path) != expected:
            raise ValueError('Knowledge hash mismatch: ' + table)
        arrow_table = pq.read_table(path)
        kind = table.split('_')[-1] if table.startswith(('source_', 'reference_')) else table
        if not REQUIRED[kind] <= set(arrow_table.schema.names):
            raise ValueError('Incomplete knowledge schema, including empty tables: ' + table)
        validate_physical_schema(arrow_table, kind)
        rows = arrow_table.to_pylist()
        if manifest.get(table + '_created') != len(rows):
            raise ValueError('Knowledge row count mismatch: ' + table)
        tables[table], hashes[table] = rows, expected
    snapshot = KnowledgeSnapshot(root, manifest, sha, tables, hashes)
    validate_tables(tables, manifest, config['quality']['fail_on_missing_provenance'])
    assert_unchanged(snapshot)
    return snapshot
