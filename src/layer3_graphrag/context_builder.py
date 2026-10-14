"""Bounded private packages retaining original chunk text and inherited lineage."""
from copy import deepcopy
from .provenance import digest, lineage, serialize
from .source_context import SourceContextResolver


def build_context(snapshot, query_id, query_text, ranked_hits, entities, relations, reference_hits, settings,
                  mode='hybrid', metrics=None, run_id='QUERY', config_hash=None, source_candidates=None, source_contexts=None, config=None):
    chunks, references, document_ids, seen = [], [], set(), set()
    used_chars = 0
    for hit in ranked_hits:
        if hit.get('source_space') != 'SOURCE':
            raise ValueError('Reference chunk in source context')
        if hit['chunk_id'] in seen:
            continue
        if len(chunks) >= settings['max_chunks']:
            break
        if hit['document_id'] not in document_ids and len(document_ids) >= settings['max_documents']:
            continue
        if used_chars + len(hit['text']) > settings['max_characters']:
            continue
        seen.add(hit['chunk_id'])
        document_ids.add(hit['document_id'])
        chunks.append(deepcopy(hit))
        used_chars += len(hit['text'])
    for hit in reference_hits:
        if hit.get('source_space') != 'REFERENCE':
            raise ValueError('Source chunk in reference context')
        if len(references) >= settings['max_reference_chunks']:
            break
        if used_chars + len(hit['text']) > settings['max_characters']:
            continue
        references.append(deepcopy(hit) | {'is_discovery_chunk': False})
        used_chars += len(hit['text'])
    documents = [deepcopy(row) for row in snapshot.tables['source_documents'] if row['document_id'] in document_ids]
    documents.sort(key=lambda row: row['document_id'])
    kept_entities = deepcopy(entities[:settings['max_entities']])
    entity_ids = {e['entity_id'] for e in kept_entities}
    kept_relations = [deepcopy(r) for r in relations if r['source_entity_id'] in entity_ids and r['target_entity_id'] in entity_ids][:settings['max_relations']]
    provenance = {'query_id': query_id, 'query_hash': digest(query_text), 'layer3_run_id': run_id,
                  'layer3_config_hash': config_hash, 'layer2_run_id': snapshot.manifest['layer2_run_id'],
                  'layer2_manifest_hash': snapshot.manifest_hash, 'layer1_run_id': snapshot.manifest['layer1_run_id'],
                  'layer1_manifest_hash': snapshot.manifest['layer1_manifest_hash'],
                  'source_chunks': [lineage(snapshot, hit) for hit in chunks],
                  'reference_chunks': [lineage(snapshot, hit) for hit in references]}
    package = {'query_id': query_id, 'query_text': query_text, 'mode': mode, 'retrieved_chunks': chunks,
               'retrieved_documents': documents, 'retrieved_entities': kept_entities, 'retrieved_relations': kept_relations,
               'reference_context': references, 'provenance': provenance,
               'retrieval_scores': [{k: hit.get(k) for k in ('chunk_id', 'rank', 'vector_score', 'graph_distance', 'retrieval_score', 'structured_relation_strength')} for hit in chunks],
               'metrics': deepcopy(metrics or {})}
    if source_candidates is None:
        if config is None:
            raise ValueError('SOURCE context requires explicit ranking configuration')
        resolver=SourceContextResolver(snapshot)
        discovery=[dict(hit,vector_score=hit.get('vector_score') or 0.,vector_rank=hit.get('rank'),
            graph_score=hit.get('graph_score') or 0.,graph_hops=hit.get('graph_distance'),graph_path_json='[]',
            reference_chunk_ids=[],retrieval_origin='VECTOR' if mode=='vector' else 'GRAPH_SEMANTIC_RECHECK') for hit in chunks]
        source_candidates,source_contexts=resolver.group_candidates(discovery,None,config,digest(query_text),run_id,mode)
    package['source_candidates']=source_candidates
    package['source_contexts']=source_contexts
    package['metrics']['context'] = {'source_chunks': len(chunks), 'reference_chunks': len(references),
                                      'text_characters': used_chars, 'text_budget': settings['max_characters'],
                                      'source_candidates_omitted': len(ranked_hits) - len(chunks)}
    # The text budget excludes audit metadata; a separate envelope cap prevents unbounded provenance.
    if len(serialize(package)) > settings.get('max_package_characters', 1_000_000):
        raise ValueError('Context package exceeds metadata/provenance envelope budget')
    return package
