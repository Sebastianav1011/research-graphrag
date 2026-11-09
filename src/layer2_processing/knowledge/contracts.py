"""Single output schema authority, including typed empty tables and JSON Schemas."""
import pyarrow as pa

DOCUMENT = dict.fromkeys(['document_id', 'source_id', 'source_type', 'title',
    'canonical_dataset', 'canonical_run_id', 'metadata_json', 'provenance_json', 'layer2_run_id'], 'string')
SECTION = dict.fromkeys(['section_id', 'document_id', 'source_id', 'source_type', 'field_name',
    'text_original', 'text_normalized', 'text_hash', 'text_hash_original',
    'text_hash_normalized', 'provenance_json', 'layer2_run_id'], 'string') | dict.fromkeys(
    ['field_order', 'char_count', 'word_count'], 'integer')
CHUNK = dict.fromkeys(['chunk_id', 'section_id', 'document_id', 'source_id', 'source_type',
    'field_name', 'text', 'chunk_hash', 'provenance_json', 'layer2_run_id'], 'string') | dict.fromkeys(
    ['chunk_index', 'char_start', 'char_end', 'word_count', 'overlap_word_count'], 'integer')
ENTITY = dict.fromkeys(['entity_id', 'entity_type', 'canonical_id', 'label',
    'metadata_json', 'provenance_json', 'layer2_run_id'], 'string')
RELATION = dict.fromkeys(['relation_id', 'source_entity_id', 'relation_type', 'target_entity_id',
    'attributes_json', 'evidence_type', 'provenance_json', 'layer2_run_id'], 'string')
SCHEMAS = {'source_documents': DOCUMENT, 'source_sections': SECTION, 'source_chunks': CHUNK,
    'reference_documents': DOCUMENT, 'reference_sections': SECTION, 'reference_chunks': CHUNK,
    'entities': ENTITY, 'relations': RELATION}
# These schema contracts are also the public record contracts.
SourceDocument = ReferenceDocument = DOCUMENT
SourceSection = ReferenceSection = SECTION
SourceChunk = ReferenceChunk = CHUNK
KnowledgeEntity = ENTITY
KnowledgeRelation = RELATION


def arrow_schema(name):
    return pa.schema([pa.field(k, pa.string() if v == 'string' else pa.int64(),
        nullable=k in {'title', 'label', 'text_original'}) for k, v in SCHEMAS[name].items()])


def logical_schema(name):
    properties = {k: {'type': [v, 'null'] if k in {'title', 'label', 'text_original'} else v}
                  for k, v in SCHEMAS[name].items()}
    if 'source_type' in properties:
        properties['source_type']['enum'] = ['INDICATOR_REFERENCE'] if name.startswith('reference') else ['PROJECT', 'ARTICLE']
    if name == 'entities':
        properties['entity_type']['enum'] = ['PROJECT', 'ARTICLE', 'RESEARCHER', 'ORGANIZATION', 'INDICATOR']
    if name == 'relations':
        properties['evidence_type']['const'] = 'STRUCTURED_CANONICAL'
        properties['relation_type']['enum'] = ['PROJECT_HAS_RESEARCHER', 'ARTICLE_HAS_RESEARCHER']
    for k, prop in properties.items():
        if prop['type'] == 'integer':
            prop['minimum'] = 0
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'title': name,
            'type': 'object', 'additionalProperties': False, 'required': list(properties), 'properties': properties}


def manifest_schema():
    string_fields = ['layer2_run_id', 'pipeline_version', 'started_at', 'finished_at', 'status',
        'layer1_manifest_path', 'layer1_run_id', 'layer1_manifest_hash', 'layer2_config_hash', 'publication_kind']
    object_fields = ['input_row_counts', 'input_hashes', 'output_files', 'output_hashes',
        'payload_hashes', 'quality_summary', 'code_hashes', 'runtime']
    count_fields = [name + '_created' for name in SCHEMAS]
    props = {k: {'type': 'string'} for k in string_fields} | {k: {'type': 'object'} for k in object_fields}
    props |= {k: {'type': 'integer', 'minimum': 0} for k in count_fields}
    props['input_datasets'] = {'type': 'array', 'items': {'type': 'string'}}
    props['status']['const'] = 'SUCCESS'
    props['publication_kind']['const'] = 'real'
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object',
            'required': list(props), 'properties': props, 'additionalProperties': True}
