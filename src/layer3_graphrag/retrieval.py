"""Compose vector and hybrid query discovery with ranking and SOURCE context assembly; no assessment."""
from __future__ import annotations

from time import perf_counter
from typing import Any
import numpy as np
import math
from copy import deepcopy
from .source_context import build_context
from .graph_retriever import GraphRetriever
from .provenance import stable_id



# Retrieve within a single knowledge space, retaining Layer 2 provenance.
class VectorRetriever:
    def __init__(self, index: Any, provider: Any, snapshot: Any, space: str = "SOURCE"):
        if space not in {"SOURCE", "REFERENCE"} or index.space != space:
            raise ValueError("Retriever/index source space mismatch")
        self.index, self.provider, self.snapshot, self.space = index, provider, snapshot, space
        self.last_metrics: dict = {}
        prefix = "source" if space == "SOURCE" else "reference"
        self.chunks = {r["chunk_id"]: r for r in snapshot.tables[f"{prefix}_chunks"]}
        if len(self.chunks) != len(snapshot.tables[f"{prefix}_chunks"]):
            raise ValueError("Duplicate chunk IDs in knowledge snapshot")
        self.sections = {r["section_id"]: r for r in snapshot.tables[f"{prefix}_sections"]}
        self.documents = {r["document_id"]: r for r in snapshot.tables[f"{prefix}_documents"]}
        self._validate_compatibility()

    def _validate_compatibility(self) -> None:
        self.index.validate()
        for field, attr in (("model", "model_name"), ("model_version", "model_version"),
                            ("dimensions", "dimensions")):
            if self.index.metadata.get(field) != getattr(self.provider, attr):
                raise ValueError(f"Provider/index incompatibility: {field}")
        expected_hash = self.index.metadata.get("layer2_manifest_hash")
        if expected_hash is not None and expected_hash != self.snapshot.manifest_hash:
            raise ValueError("Index belongs to a different Layer 2 snapshot")
        for record in self.index.records:
            chunk = self.chunks.get(record["chunk_id"])
            if chunk is None:
                raise ValueError("Index references missing chunk")
            if record.get("chunk_hash") is not None and record["chunk_hash"] != chunk.get("chunk_hash"):
                raise ValueError("Index references changed chunk")

    def retrieve(self, query_text: str, top_k: int) -> list[dict]:
        if not isinstance(query_text, str) or not query_text.strip():
            raise ValueError("Nonempty query text required")
        self._validate_compatibility()
        start = perf_counter()
        vectors = np.asarray(self.provider.embed_queries([query_text]))
        if vectors.shape != (1, self.provider.dimensions):
            raise ValueError("Query provider returned an invalid matrix")
        embedded = perf_counter()
        hits = self.index.search(vectors[0], top_k)
        searched = perf_counter()
        results = []
        for hit in hits:
            chunk = self.chunks[hit["chunk_id"]]
            section = self.sections.get(chunk.get("section_id"))
            document = self.documents.get(chunk.get("document_id"))
            if section is None or document is None or section.get("document_id") != chunk.get("document_id"):
                raise ValueError("Broken chunk → section → document provenance")
            if not chunk.get("provenance_json"):
                raise ValueError("Missing retrieval provenance")
            results.append({**{key: chunk.get(key) for key in (
                "chunk_id", "source_id", "source_type", "field_name", "document_id", "section_id", "text",
                "provenance_json")}, **hit, "vector_score": hit["score"], "graph_distance": None,
                "structured_relation_strength": 0.0, "layer2_manifest_hash": self.snapshot.manifest_hash,
                "layer2_run_id": self.snapshot.manifest.get("layer2_run_id"),
                "layer1_run_id": self.snapshot.manifest.get("layer1_run_id"),
                "layer1_manifest_hash": self.snapshot.manifest.get("layer1_manifest_hash"),
                "is_discovery_chunk": self.space == "SOURCE"})
        self.last_metrics = {"embedding_latency_ms": (embedded-start)*1000,
                             "vector_search_latency_ms": (searched-embedded)*1000,
                             "total_retrieval_latency_ms": (perf_counter()-start)*1000}
        return results

# Configurable retrieval signals; no confidence or indicator decisions.
def combine_hits(vector_hits, graph_hits):
    combined = {}
    for hit in [*vector_hits, *graph_hits]:
        key = hit['chunk_id']
        if hit.get('source_space') != 'SOURCE':
            raise ValueError('Hybrid candidate pool must contain SOURCE chunks only')
        if key not in combined:
            combined[key] = deepcopy(hit)
            continue
        current = combined[key]
        for field in ('document_id', 'source_id', 'source_type', 'field_name', 'section_id'):
            if current[field] != hit[field]:
                raise ValueError('Conflicting retrieval metadata for one chunk')
        if hit.get('vector_score') is not None:
            current['vector_score'] = max(v for v in (current.get('vector_score'), hit['vector_score']) if v is not None)
        if hit.get('graph_distance') is not None:
            current['graph_distance'] = min(v for v in (current.get('graph_distance'), hit['graph_distance']) if v is not None)
        current['structured_relation_strength'] = max(current.get('structured_relation_strength', 0), hit.get('structured_relation_strength', 0))
        current['relation_ids'] = sorted(set(current.get('relation_ids', [])) | set(hit.get('relation_ids', [])))
    return list(combined.values())


def base_score(hit, settings):
    vector = hit.get('vector_score')
    if vector is not None and (not isinstance(vector, (int, float)) or not math.isfinite(vector) or not -1.000001 <= vector <= 1.000001):
        raise ValueError('Invalid cosine retrieval signal')
    distance = hit.get('graph_distance')
    if distance is not None and (type(distance) is not int or distance < 0):
        raise ValueError('Invalid graph distance')
    strength = hit.get('structured_relation_strength', 0.0)
    if not isinstance(strength, (int, float)) or not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('Invalid structured relation signal')
    signals = {'vector': (max(-1., min(1., vector)) + 1) / 2 if vector is not None else 0.,
               'graph': 1. / (1 + distance) if distance is not None else 0., 'structured_relation': strength}
    weights = {key: settings[key + '_weight'] for key in signals}
    if any(not math.isfinite(v) or v < 0 for v in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError('Invalid ranking weights')
    score = sum(weights[key] * signals[key] for key in signals) / sum(weights.values())
    return score, signals


def rank_hits(hits, settings, limit=None):
    remaining = []
    seen = set()
    for hit in hits:
        if hit['chunk_id'] in seen:
            raise ValueError('Duplicate ranking chunk ID')
        seen.add(hit['chunk_id'])
        value, signals = base_score(hit, settings)
        remaining.append(deepcopy(hit) | {'base_retrieval_score': value, 'ranking_signals': signals})
    diversity = settings.get('diversity_weight', 0.)
    if not math.isfinite(diversity) or diversity < 0:
        raise ValueError('Invalid diversity weight')
    selected, source_counts = [], {}
    while remaining and (limit is None or len(selected) < limit):
        def score(row):
            source = (row['source_type'], row['source_id'])
            return row['base_retrieval_score'] + diversity / (1 + source_counts.get(source, 0))
        remaining.sort(key=lambda row: (-score(row), row['chunk_id']))
        best = remaining.pop(0)
        best['retrieval_score'] = score(best)
        best['rank'] = len(selected) + 1
        selected.append(best)
        source = (best['source_type'], best['source_id'])
        source_counts[source] = source_counts.get(source, 0) + 1
    return selected

# Vector seeds expand through existing structured graph relations.
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

# Retrieval orchestration only: vector, graph or hybrid; no generation.
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
