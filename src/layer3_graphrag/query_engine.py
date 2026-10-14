"""Retrieval orchestration only: vector, graph or hybrid; no generation."""
from time import perf_counter

from .context_builder import build_context
from .graph_retriever import GraphRetriever
from .hybrid_retriever import HybridRetriever
from .provenance import stable_id
from .ranking import rank_hits
from .vector_retriever import VectorRetriever


class QueryEngine:
    def __init__(self, snapshot, provider, source_index, reference_index, graph, config, run_id='QUERY', config_hash=None):
        self.snapshot, self.config, self.run_id, self.config_hash = snapshot, config, run_id, config_hash
        self.vector = VectorRetriever(source_index, provider, snapshot, space='SOURCE')
        self.reference = VectorRetriever(reference_index, provider, snapshot, space='REFERENCE')
        self.graph = GraphRetriever(graph, snapshot, config['graph'])
        self.hybrid = HybridRetriever(self.vector, self.graph, snapshot, config['hybrid'])
        self.entities = {(row['entity_type'], row['canonical_id']): row for row in snapshot.tables['entities']}
        self.real_retriever = None
        if config.get('retrieval', {}).get('enabled'):
            from .indicator_retrieval import IndicatorRetriever
            self.real_retriever = IndicatorRetriever(snapshot, source_index, provider, graph, config, run_id)

    def query(self, query_text, query_id=None, mode='hybrid', seed_entity_ids=None):
        if mode not in {'vector', 'graph', 'hybrid'} or not isinstance(query_text, str) or not query_text.strip():
            raise ValueError('Valid retrieval mode and nonempty query are required')
        query_id = query_id or stable_id('Q', query_text, mode, sorted(seed_entity_ids or []), self.snapshot.manifest_hash)
        started = perf_counter()
        source_candidates,source_contexts=None,None
        if self.real_retriever is not None:
            source_candidates,source_contexts,expansion,measured=self.real_retriever.retrieve_sources([query_text],[],None,seed_entity_ids,mode)
            rows=[self.real_retriever._row(d['chunk_id']) | d | {'hybrid_rank':c['source_rank'],
                'hybrid_score':c['hybrid_retrieval_score'],'graph_hops':c['graph_hops'],'graph_score':c['graph_score']}
                for c in source_candidates for d in c['discovery_chunks']]
            hits = []
            for row in rows:
                chunk = self.real_retriever.chunks[row['chunk_id']]
                hits.append(chunk | row | {'provenance_json': chunk['provenance_json'], 'source_space': 'SOURCE',
                    'rank': row['hybrid_rank'], 'retrieval_score': row['hybrid_score'], 'graph_distance': row['graph_hops'],
                    'is_discovery_chunk': True})
            entities = expansion['entities'] or [self.entities[key] for key in sorted({(h['source_type'], h['source_id']) for h in hits})]
            result = {'hits': hits, 'entities': entities, 'relations': expansion['relations'],
                'metrics': {'graph': measured['graph'], 'latency': {k:v for k,v in measured.items() if k.endswith('_ms')}}}
        elif mode == 'hybrid':
            result = self.hybrid.retrieve(query_text, seed_entity_ids)
        elif mode == 'vector':
            hits = self.vector.retrieve(query_text, self.config['vector_index']['top_k'])
            result = {'hits': rank_hits(hits, self.config['hybrid']),
                      'entities': [self.entities[key] for key in sorted({(h['source_type'], h['source_id']) for h in hits})],
                      'relations': [], 'metrics': {'latency': dict(self.vector.last_metrics)}}
        else:
            if not seed_entity_ids:
                raise ValueError('Graph-only mode needs explicit entity seeds, never relevance labels')
            t = perf_counter()
            expanded = self.graph.retrieve(seed_entity_ids)
            result = expanded | {'hits': rank_hits(expanded['hits'], self.config['hybrid']),
                                 'metrics': {'graph': expanded['metrics'], 'latency': {'graph_expansion_latency_ms': (perf_counter() - t) * 1000}}}
        references = []
        if mode != 'graph':
            references = self.reference.retrieve(query_text, self.config['context']['max_reference_chunks'])
            for key in ('embedding_latency_ms', 'vector_search_latency_ms'):
                result['metrics']['latency'][key] = result['metrics']['latency'].get(key, 0) + self.reference.last_metrics[key]
        package = build_context(self.snapshot, query_id, query_text, result['hits'], result['entities'], result['relations'],
                                references, self.config['context'], mode, result['metrics'], self.run_id, self.config_hash,
                                source_candidates,source_contexts,self.config)
        package['metrics']['latency']['total_query_latency_ms'] = (perf_counter() - started) * 1000
        return package

    def query_reference(self, reference_chunk_id, query_id=None, mode='hybrid'):
        row = next((r for r in self.snapshot.tables['reference_chunks'] if r['chunk_id'] == reference_chunk_id), None)
        if row is None:
            raise ValueError('Unknown reference chunk')
        package = self.query(row['text'], query_id=query_id or stable_id('QREF', reference_chunk_id), mode=mode)
        package['provenance']['query_reference_chunk_id'] = reference_chunk_id
        return package
