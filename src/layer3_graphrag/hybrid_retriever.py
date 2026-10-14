"""Vector seeds expand through existing structured graph relations."""
from time import perf_counter
from .ranking import combine_hits, rank_hits


class HybridRetriever:
    def __init__(self, vector_retriever, graph_retriever, snapshot, settings):
        self.vector = vector_retriever
        self.graph = graph_retriever
        self.snapshot = snapshot
        self.settings = settings
        self.entities = {(r['entity_type'], r['canonical_id']): r['entity_id'] for r in snapshot.tables['entities']}

    def retrieve(self, query_text, seed_entity_ids=None):
        hits = self.vector.retrieve(query_text, self.settings['candidate_pool'])
        seeds = set(seed_entity_ids or [])
        seeds.update(self.entities[(h['source_type'], h['source_id'])] for h in hits)
        started = perf_counter()
        expanded = self.graph.retrieve(sorted(seeds), space='SOURCE')
        elapsed = (perf_counter() - started) * 1000
        ranked = rank_hits(combine_hits(hits, expanded['hits']), self.settings, self.settings['candidate_pool'])
        return {'hits': ranked, 'entities': expanded['entities'], 'relations': expanded['relations'],
                'support_paths': expanded['support_paths'],
                'metrics': {'graph': expanded['metrics'], 'latency': self.vector.last_metrics | {'graph_expansion_latency_ms': elapsed}}}
