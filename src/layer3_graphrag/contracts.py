"""Layer 3 contracts, independent of executable upstream modules."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SPACES = ('SOURCE', 'REFERENCE')
KNOWLEDGE_TABLES = ('source_documents', 'source_sections', 'source_chunks',
                    'reference_documents', 'reference_sections', 'reference_chunks', 'entities', 'relations')
ENTITY_TYPES = ('PROJECT', 'ARTICLE', 'RESEARCHER', 'ORGANIZATION', 'INDICATOR')
RELATION_ENDPOINTS = {'PROJECT_HAS_RESEARCHER': ('PROJECT', 'RESEARCHER'),
                      'ARTICLE_HAS_RESEARCHER': ('ARTICLE', 'RESEARCHER')}
KEYS = {table: 'document_id' if table.endswith('documents') else 'section_id' if table.endswith('sections')
        else 'chunk_id' if table.endswith('chunks') else 'entity_id' if table == 'entities' else 'relation_id'
        for table in KNOWLEDGE_TABLES}
REQUIRED = {
    'documents': {'document_id', 'source_id', 'source_type', 'canonical_run_id', 'canonical_dataset', 'provenance_json', 'layer2_run_id'},
    'sections': {'section_id', 'document_id', 'source_id', 'source_type', 'field_name', 'text_normalized', 'provenance_json', 'layer2_run_id'},
    'chunks': {'chunk_id', 'section_id', 'document_id', 'source_id', 'source_type', 'field_name', 'text', 'chunk_hash', 'char_start', 'char_end', 'provenance_json', 'layer2_run_id'},
    'entities': {'entity_id', 'entity_type', 'canonical_id', 'metadata_json', 'provenance_json', 'layer2_run_id'},
    'relations': {'relation_id', 'source_entity_id', 'target_entity_id', 'relation_type', 'attributes_json', 'evidence_type', 'provenance_json', 'layer2_run_id'},
}


@dataclass
class KnowledgeSnapshot:
    root: Path
    manifest: dict
    manifest_hash: str
    tables: dict[str, list[dict]]
    hashes: dict[str, str]


@dataclass
class EmbeddingBundle:
    records: list[dict]
    vectors: np.ndarray
    metadata: dict


def evaluation_query_schema():
    strings = {'type': 'array', 'items': {'type': 'string'}, 'uniqueItems': True}
    props = {k: {'type': 'string', 'minLength': 1} for k in ('query_id', 'query_text', 'query_type')}
    props |= {k: strings for k in ('expected_source_ids', 'expected_entity_ids', 'expected_relation_types', 'seed_entity_ids')}
    props['notes'] = {'type': 'string'}
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object',
            'properties': props, 'required': ['query_id', 'query_text', 'query_type', 'expected_source_ids',
                                             'expected_entity_ids', 'expected_relation_types', 'notes'],
            'additionalProperties': False}


def embedding_schema():
    props = {k: {'type': 'string', 'minLength': 1} for k in ('embedding_id', 'chunk_id', 'source_space',
             'model', 'model_version', 'text_hash', 'embedding_hash', 'layer3_run_id', 'embedding_config_hash')}
    props['source_space']['enum'] = list(SPACES)
    props['dimensions'] = {'type': 'integer', 'minimum': 1}
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object',
            'properties': props, 'required': list(props), 'additionalProperties': True}


def context_schema():
    props = {k: {'type': 'string'} for k in ('query_id', 'query_text', 'mode')}
    props |= {k: {'type': 'array', 'items': {'type': 'object'}} for k in ('retrieved_chunks', 'retrieved_documents',
              'retrieved_entities', 'retrieved_relations', 'reference_context', 'retrieval_scores', 'source_candidates', 'source_contexts')}
    props |= {k: {'type': 'object'} for k in ('provenance', 'metrics')}
    props['mode']['enum'] = ['vector', 'graph', 'hybrid']
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object',
            'properties': props, 'required': list(props), 'additionalProperties': False}


def layer3_manifest_schema():
    props = {k: {'type': 'string', 'minLength': 1} for k in ('layer3_run_id', 'layer3_config_hash',
             'layer2_run_id', 'layer2_manifest_hash', 'layer1_run_id', 'layer1_manifest_hash',
             'embedding_config_hash', 'status', 'pipeline_version', 'started_at', 'finished_at')}
    props['status']['const'] = 'SUCCESS'
    props |= {k: {'type': 'object'} for k in ('embedding_model', 'vector_indexes', 'graph', 'counts',
                                          'evaluation', 'output_hashes', 'code_hashes', 'runtime')}
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object',
            'properties': props, 'required': list(props), 'additionalProperties': True}


def source_candidate_arrow_schema():
    import pyarrow as pa
    fields = []
    for name in ('candidate_id','indicator_id','source_id','source_type','document_id','context_package_id','context_status'):
        fields.append(pa.field(name, pa.string(), nullable=False))
    fields += [pa.field(k,pa.list_(pa.string()),nullable=False) for k in ('discovery_chunk_ids','discovery_field_names','discovery_retrieval_origins','reference_chunk_ids','orientation_section_ids','substantive_section_ids','available_field_names')]
    fields += [pa.field('discovery_chunks',pa.list_(pa.struct([
        pa.field('chunk_id',pa.string(),nullable=False),pa.field('field_name',pa.string(),nullable=False),
        pa.field('vector_score',pa.float64(),nullable=False),pa.field('vector_rank',pa.int64()),
        pa.field('retrieval_origin',pa.string(),nullable=False),pa.field('reference_chunk_ids',pa.list_(pa.string()),nullable=False)])),nullable=False),
        pa.field('retrieval_mode', pa.string(), nullable=False), pa.field('best_vector_score', pa.float64(), nullable=False),
        pa.field('top_chunk_scores',pa.list_(pa.float64()),nullable=False),
        pa.field('best_vector_rank', pa.int64()), pa.field('graph_score', pa.float64(), nullable=False),
        pa.field('graph_hops', pa.int64()), pa.field('graph_path_json', pa.string(), nullable=False),
        pa.field('hybrid_retrieval_score', pa.float64(), nullable=False), pa.field('source_rank', pa.int64(), nullable=False),
        pa.field('source_context_hash', pa.string(), nullable=False), pa.field('provenance_json', pa.string(), nullable=False),
        pa.field('layer3_run_id', pa.string(), nullable=False)]
    return pa.schema(fields)


def source_context_arrow_schema():
    import pyarrow as pa
    fields = [pa.field(k,pa.string(),nullable=False) for k in ('context_package_id','source_id','source_type','document_id','context_status','source_context_hash','provenance_json','layer3_run_id')]
    fields += [pa.field('title_section_id',pa.string()),pa.field('available_field_names',pa.list_(pa.string()),nullable=False)]
    reference = pa.struct([pa.field('field_name',pa.string(),nullable=False),pa.field('section_id',pa.string(),nullable=False),pa.field('text_hash',pa.string(),nullable=False),pa.field('chunk_ids',pa.list_(pa.string()),nullable=False)])
    fields += [pa.field(k,pa.list_(reference),nullable=False) for k in ('orientation_sections','substantive_sections')]
    return pa.schema(fields)


def arrow_json_schema(schema):
    import pyarrow as pa
    def field_schema(field):
        kind=field.type
        if pa.types.is_list(kind): item={'type':'array','items':field_schema(kind.value_field)}
        elif pa.types.is_struct(kind): item={'type':'object','properties':{f.name:field_schema(f) for f in kind},'required':[f.name for f in kind],'additionalProperties':False}
        elif pa.types.is_integer(kind): item={'type':'integer'}
        elif pa.types.is_floating(kind): item={'type':'number'}
        else: item={'type':'string'}
        return {'anyOf':[item,{'type':'null'}]} if field.nullable else item
    result={'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','properties':{f.name:field_schema(f) for f in schema},'required':schema.names,'additionalProperties':False}
    result['properties']['context_status']={'enum':['ASSESSMENT_READY','DISCOVERY_ONLY']}
    return result
