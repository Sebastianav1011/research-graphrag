"""Resolve complete SOURCE section references, aggregate SOURCE+INDICATOR and assemble bounded discovery diagnostics."""

from collections import defaultdict
import json
from .provenance import digest, serialize, stable_id
from copy import deepcopy
from .provenance import digest, lineage, serialize



# Reconstruct SOURCE context through published section references, never concatenated text.
FIELD_ROLES = {
    'PROJECT': {'orientation': ('title', 'keywords'), 'substantive': ('summary', 'methodology', 'objectives', 'expected_results')},
    'ARTICLE': {'orientation': ('title', 'keywords'), 'substantive': ('abstract',)},
}


class SourceContextResolver:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.documents = {r['document_id']: r for r in snapshot.tables['source_documents']}
        sources={(r['source_type'],r['source_id']) for r in self.documents.values()}
        if len(sources)!=len(self.documents):
            raise ValueError('SOURCE maps to multiple documents')
        self.sections = {r['section_id']: r for r in snapshot.tables['source_sections']}
        self.chunks = {r['chunk_id']: r for r in snapshot.tables['source_chunks']}
        self.by_document, self.by_section = defaultdict(list), defaultdict(list)
        for section in self.sections.values():
            self.by_document[section['document_id']].append(section)
        for chunk in self.chunks.values():
            self.by_section[chunk['section_id']].append(chunk)
        self.cache = {}

    def reconstruct(self, source_type, source_id, document_id, run_id='QUERY'):
        key = (source_type, source_id, document_id)
        if key not in self.cache:
            doc = self.documents.get(document_id)
            if doc is None or any(doc[k] != v for k,v in zip(('source_type','source_id','document_id'),key)):
                raise ValueError('Invalid SOURCE document mapping')
            if source_type not in FIELD_ROLES:
                raise ValueError('REFERENCE cannot be a candidate SOURCE')
            groups = {'orientation': [], 'substantive': []}
            for section in sorted(self.by_document[document_id], key=lambda r: (r.get('field_order',0),r['field_name'],r['section_id'])):
                if section['source_type'] != source_type or section['source_id'] != source_id:
                    raise ValueError('Section SOURCE mapping mismatch')
                if not section['text_normalized'].strip():
                    continue
                role = 'substantive' if section['field_name'] in FIELD_ROLES[source_type]['substantive'] else 'orientation'
                groups[role].append({'field_name':section['field_name'], 'section_id':section['section_id'],
                    'text_hash':section.get('text_hash_normalized', section.get('text_hash',digest(section['text_normalized']))),
                    'chunk_ids': [r['chunk_id'] for r in sorted(self.by_section[section['section_id']],key=lambda r:(r.get('chunk_index',0),r['chunk_id']))]})
            context = {'source_type':source_type,'source_id':source_id,'document_id':document_id,
                'title_section_id':next((s['section_id'] for s in groups['orientation'] if s['field_name']=='title'),None),
                'orientation_sections':groups['orientation'], 'substantive_sections':groups['substantive'],
                'available_field_names':sorted({s['field_name'] for rows in groups.values() for s in rows}),
                'context_status':'ASSESSMENT_READY' if groups['substantive'] else 'DISCOVERY_ONLY'}
            context['source_context_hash'] = digest(context)
            context['context_package_id'] = stable_id('SOURCE_CONTEXT',context['source_context_hash'],self.snapshot.manifest_hash)
            context['provenance_json'] = self.provenance(context,[])
            self.cache[key] = context
        return dict(self.cache[key],layer3_run_id=run_id)

    def provenance(self, context, discovery_ids):
        doc = self.documents[context['document_id']]
        sections = context['orientation_sections'] + context['substantive_sections']
        result = {'source_id':context['source_id'],'source_type':context['source_type'],'document_id':context['document_id'],
            'layer2_run_id':self.snapshot.manifest['layer2_run_id'], 'layer2_manifest_hash':self.snapshot.manifest_hash,
            'layer1_run_id':self.snapshot.manifest['layer1_run_id'],'layer1_manifest_hash':self.snapshot.manifest['layer1_manifest_hash'],
            'document_provenance_hash':digest(json.loads(doc['provenance_json'])),
            'sections':[{'section_id':s['section_id'],'field_name':s['field_name'],'text_hash':s['text_hash'],
                'provenance_hash':digest(json.loads(self.sections[s['section_id']]['provenance_json']))} for s in sections],
            'discovery_chunks':[{'chunk_id':k,'section_id':self.chunks[k]['section_id'],'field_name':self.chunks[k]['field_name'],
                'chunk_hash':self.chunks[k]['chunk_hash'],'provenance_hash':digest(json.loads(self.chunks[k]['provenance_json']))} for k in discovery_ids]}
        # Full inherited provenance is resolved from the immutable Layer 2 publication.
        # Texts, original_values and personal metadata are not duplicated here.
        return serialize(result)

    def group_candidates(self, rows, indicator_id, config, fingerprint, run_id, mode='hybrid'):
        groups = defaultdict(list)
        for row in rows:
            if row['source_type'] not in FIELD_ROLES or row['chunk_id'] not in self.chunks:
                raise ValueError('Non-SOURCE discovery chunk')
            groups[(row['source_type'],row['source_id'],row['document_id'])].append(row)
        candidates, contexts = [], {}
        for key, hits in groups.items():
            hits = sorted(hits,key=lambda r:(-r['vector_score'],r['chunk_id']))
            if len({r['chunk_id'] for r in hits}) != len(hits):
                raise ValueError('Duplicate discovery chunk in SOURCE')
            chosen = hits[:config['retrieval']['max_chunks_per_source']]
            context = self.reconstruct(*key,run_id)
            best_vector = max(r['vector_score'] for r in hits)
            graph_hit = min(hits,key=lambda r:(-r['graph_score'],r['graph_hops'] if r['graph_hops'] is not None else 999,r['chunk_id']))
            graph_score = graph_hit['graph_score']
            score = config['hybrid']['vector_weight']*((best_vector+1)/2) + config['hybrid']['graph_weight']*graph_score
            ranks = [r['vector_rank'] for r in hits if r['vector_rank'] is not None]
            candidate = {'candidate_id':stable_id('SOURCE_INDICATOR',indicator_id,*key,self.snapshot.manifest_hash,fingerprint,'source_candidate_v1'),
                'indicator_id':indicator_id,'source_type':key[0],'source_id':key[1],'document_id':key[2],
                'context_package_id':context['context_package_id'],'context_status':context['context_status'],
                'discovery_chunk_ids':[r['chunk_id'] for r in chosen], 'discovery_field_names':[r['field_name'] for r in chosen],
                'discovery_retrieval_origins':[r.get('retrieval_origin','VECTOR') for r in chosen],
                'discovery_chunks':[{'chunk_id':r['chunk_id'],'field_name':r['field_name'],'vector_score':r['vector_score'],
                    'vector_rank':r['vector_rank'],'retrieval_origin':r.get('retrieval_origin','VECTOR'),
                    'reference_chunk_ids':r['reference_chunk_ids']} for r in chosen],
                'reference_chunk_ids':sorted({k for r in hits for k in r['reference_chunk_ids']}),
                'best_vector_score':best_vector,'top_chunk_scores':[r['vector_score'] for r in chosen],
                'best_vector_rank':min(ranks) if ranks else None, 'graph_score':graph_score,
                'graph_hops':graph_hit['graph_hops'],'graph_path_json':graph_hit['graph_path_json'],
                'hybrid_retrieval_score':score,'source_rank':0,'retrieval_mode':mode.upper(),
                'orientation_section_ids':[s['section_id'] for s in context['orientation_sections']],
                'substantive_section_ids':[s['section_id'] for s in context['substantive_sections']],
                'available_field_names':context['available_field_names'],'source_context_hash':context['source_context_hash'],
                'provenance_json':self.provenance(context,[r['chunk_id'] for r in chosen]),'layer3_run_id':run_id}
            candidates.append(candidate)
            contexts[context['context_package_id']] = context
        metric = 'best_vector_score' if mode=='vector' else 'graph_score' if mode=='graph' else 'hybrid_retrieval_score'
        candidates.sort(key=lambda r:(-r[metric],r['source_type'],r['source_id'],r['document_id']))
        candidates=candidates[:config['retrieval']['final_candidates_per_indicator']]
        for rank,row in enumerate(candidates,1): row['source_rank']=rank
        return candidates,[contexts[k] for k in sorted({r['context_package_id'] for r in candidates})]

# Bounded private packages retaining original chunk text and inherited lineage.
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
