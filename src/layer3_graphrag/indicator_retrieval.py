"""Real reference-driven candidates: dense semantics plus bounded factual context."""
from collections import Counter, defaultdict
from time import perf_counter
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from .embeddings import EmbeddingCache, embedding_config_hash, validate_vectors
from .graph_retriever import GraphRetriever
from .graph import json_object
from .provenance import digest, lineage, serialize, stable_id
from .source_context import SourceContextResolver


def diverse(rows, score_field, limit, per_source):
    counts, selected = Counter(), []
    for row in sorted(rows, key=lambda r: (-r[score_field], r['chunk_id'])):
        key = (row['source_type'], row['source_id'])
        if counts[key] >= per_source:
            continue
        counts[key] += 1
        selected.append(dict(row))
        if len(selected) >= limit:
            break
    return selected


class IndicatorRetriever:
    """SOURCE-only candidates. Graph-only receives caller-visible explicit seeds."""
    def __init__(self, snapshot, index, provider, graph, config, run_id):
        self.snapshot, self.index, self.provider, self.graph = snapshot, index, provider, graph
        self.config, self.run_id = config, run_id
        self.settings = config['retrieval']
        self.graph_retriever = GraphRetriever(graph, snapshot, config['graph'])
        self.chunks = {r['chunk_id']: r for r in snapshot.tables['source_chunks']}
        self.entities = {(r['entity_type'], r['canonical_id']): r['entity_id'] for r in snapshot.tables['entities']}
        self.positions = {r['chunk_id']: i for i, r in enumerate(index.records)}
        self.source_positions = defaultdict(list)
        for key, chunk in self.chunks.items():
            self.source_positions[(chunk['source_type'], chunk['source_id'])].append(self.positions[key])
        self.query_cache = EmbeddingCache(snapshot.root / 'outputs/layer3/query_cache')
        self.fingerprint = embedding_config_hash(config['embeddings'], provider)
        self._query_vectors = {}
        self.context_resolver = SourceContextResolver(snapshot)

    def query_vectors(self, texts):
        vectors = []
        for text in texts:
            key = digest({'text': text, 'encoding': 'query', 'fingerprint': self.fingerprint})
            value = self._query_vectors.get(key)
            if value is None:
                value = self.query_cache.get(key, self.provider.dimensions)
            if value is None:
                value = validate_vectors(self.provider.embed_queries([text]), 1, self.provider.dimensions, True)[0]
                self.query_cache.put(key, value)
            self._query_vectors[key] = value
            vectors.append(value / np.linalg.norm(value.astype(np.float64)))
        return np.asarray(vectors, dtype=np.float64)

    def score_rows(self, texts, reference_ids, explicit_seeds=None, mode='hybrid'):
        start = perf_counter()
        q = self.query_vectors(texts)
        embedded = perf_counter()
        # The same exact cosine implementation and lexical tie break as the index.
        scores = np.clip(q @ self.index.vectors.T, -1., 1.)
        vector_rows, contributing, raw = {}, defaultdict(set), 0
        top_k = self.settings['vector_top_k_per_reference_chunk']
        if mode != 'graph':
            for n, score in enumerate(scores):
                ordered = sorted(range(len(score)), key=lambda i: (-float(score[i]), self.index.records[i]['chunk_id']))[:top_k]
                raw += len(ordered)
                for rank, i in enumerate(ordered, 1):
                    key = self.index.records[i]['chunk_id']
                    if reference_ids:
                        contributing[key].add(reference_ids[n])
                    old = vector_rows.get(key)
                    if old is None or float(score[i]) > old['vector_score']:
                        vector_rows[key] = self._row(key) | {'vector_score': float(score[i]), 'vector_rank': rank,
                            'graph_score': 0., 'graph_hops': None, 'graph_path_json': '[]'}
        vector_done = perf_counter()
        for rank, row in enumerate(sorted(vector_rows.values(), key=lambda r: (-r['vector_score'], r['chunk_id'])), 1):
            row['vector_rank'] = rank
        seeds = sorted(set(explicit_seeds or []))
        if mode == 'hybrid':
            seeds = sorted(set(seeds) | {self.entities[(r['source_type'], r['source_id'])] for r in vector_rows.values()})
        if mode == 'graph' and not seeds:
            raise ValueError('Graph-only requires explicit seeds')
        expanded = {'hits': [], 'entities': [], 'relations': [], 'support_paths': {}, 'metrics': {}}
        graph_rows = {}
        if mode != 'vector':
            expanded = self.graph_retriever.retrieve(seeds)
            # Only the best semantic chunk of each graph document enters the pool.
            best_scores = scores.max(axis=0)
            seed_strength = {key: max((r['vector_score'] + 1)/2 for r in vector_rows.values()
                if self.entities[(r['source_type'], r['source_id'])] == key) for key in seeds
                if any(self.entities[(r['source_type'], r['source_id'])] == key for r in vector_rows.values())}
            for entity in expanded['entities']:
                key = (entity['entity_type'], entity['canonical_id'])
                positions = self.source_positions.get(key, [])
                if not positions:
                    continue
                i = min(positions, key=lambda p: (-float(best_scores[p]), self.index.records[p]['chunk_id']))
                chunk_id = self.index.records[i]['chunk_id']
                if float(best_scores[i]) <= self.settings.get('graph_candidate_min_cosine', 0.):
                    continue
                path = expanded['support_paths'][entity['entity_id']]
                hops = len(path)
                seed, path_nodes = self.check_path(entity['entity_id'], path, seeds)
                # All permitted edge types are explicit facts of equal weight 1.
                support = seed_strength.get(seed, 1. if mode == 'graph' else 0.)
                graph_score = support / (1 + hops) if hops else 0.
                graph_rows[chunk_id] = self._row(chunk_id) | {'vector_score': float(best_scores[i]),
                    'vector_rank': None, 'graph_score': graph_score, 'graph_hops': hops,
                    'graph_path_json': serialize({'seed_entity_id': seed, 'entity_ids': path_nodes,
                        'relation_ids': path, 'seed_support': support, 'relation_strength': 1.,
                        'bounded': True, 'researcher_bridge_policy': 'resolved_only'})}
                if reference_ids:
                    contributing[chunk_id].update(reference_ids[n] for n in range(len(q))
                        if scores[n, i] == best_scores[i])
        graph_done = perf_counter()
        rows = dict(vector_rows)
        for key, row in graph_rows.items():
            if key in rows:
                row['vector_rank'] = rows[key]['vector_rank']
                row['vector_score'] = max(row['vector_score'], rows[key]['vector_score'])
            rows[key] = row
        for row in rows.values():
            row['retrieval_origin'] = ('VECTOR_AND_GRAPH' if row['chunk_id'] in vector_rows and row.get('graph_hops', 0) not in (None, 0)
                else 'VECTOR' if row['chunk_id'] in vector_rows else 'GRAPH_SEMANTIC_RECHECK')
            row['reference_chunk_ids'] = sorted(contributing[row['chunk_id']])
            row['hybrid_score'] = self.config['hybrid']['vector_weight'] * ((row['vector_score'] + 1)/2) + self.config['hybrid']['graph_weight'] * row['graph_score']
            row['retrieval_mode'] = mode.upper()
        field = 'vector_score' if mode == 'vector' else 'graph_score' if mode == 'graph' else 'hybrid_score'
        # Limit discovery metadata per SOURCE, then rank/limit SOURCES, never chunks as assessments.
        chosen = diverse(list(rows.values()), field, max(1,len(rows)), self.settings['max_chunks_per_source'])
        for rank, row in enumerate(chosen, 1):
            row['hybrid_rank'] = rank
        metrics = {'raw_vector_candidates': raw, 'vector_unique_chunks': len(vector_rows),
            'vector_unique_sources': len({(r['source_type'], r['source_id']) for r in vector_rows.values()}),
            'seed_entity_ids': seeds, 'graph_candidates': len(graph_rows), 'graph': expanded['metrics'],
            'embedding_latency_ms': (embedded-start)*1000, 'vector_query_latency_ms': (vector_done-start)*1000,
            'graph_expansion_latency_ms': (graph_done-vector_done)*1000, 'hybrid_query_latency_ms': (perf_counter()-start)*1000,
            'introduced_sources': sorted(set(r['source_id'] for r in graph_rows.values()) - set(r['source_id'] for r in vector_rows.values())),
            'ambiguous_bridge_uses': 0, 'invalid_paths': 0}
        metrics['vector_score_min'] = min((r['vector_score'] for r in vector_rows.values()), default=None)
        metrics['vector_score_max'] = max((r['vector_score'] for r in vector_rows.values()), default=None)
        metrics['vector_source_ids'] = sorted({r['source_id'] for r in vector_rows.values()})
        return chosen, expanded, metrics

    def retrieve_sources(self, texts, reference_ids, indicator_id=None, explicit_seeds=None, mode='hybrid'):
        discovery, expanded, metrics = self.score_rows(texts,reference_ids,explicit_seeds,mode)
        candidates, contexts = self.context_resolver.group_candidates(discovery,indicator_id,self.config,self.fingerprint,self.run_id,mode)
        metrics['candidate_sources'] = len(candidates)
        metrics['assessment_ready'] = sum(r['context_status']=='ASSESSMENT_READY' for r in candidates)
        metrics['discovery_only'] = sum(r['context_status']=='DISCOVERY_ONLY' for r in candidates)
        return candidates, contexts, expanded, metrics

    def _row(self, key):
        chunk = self.chunks[key]
        return {k: chunk[k] for k in ('chunk_id', 'document_id', 'source_id', 'source_type', 'field_name')} | {
            'chunk_text_hash': chunk['chunk_hash'], 'provenance_json': serialize(lineage(self.snapshot, chunk)),
            'layer3_run_id': self.run_id}

    def check_path(self, end, path, seeds):
        current, nodes = end, [end]
        for rid in reversed(path):
            relation = self.graph.relations[rid]
            endpoints = [relation['source_entity_id'], relation['target_entity_id']]
            if current not in endpoints:
                raise ValueError('Noncontiguous graph support path')
            current = endpoints[1] if current == endpoints[0] else endpoints[0]
            nodes.append(current)
        if current not in seeds or len(path) > self.config['graph']['max_hops']:
            raise ValueError('Graph path missing seed or exceeds hop limit')
        nodes.reverse()
        for key in nodes[:-1]:
            row = self.graph.nodes[key]
            if row['entity_type'] == 'RESEARCHER' and str(json_object(row['metadata_json']).get('identity_status')).upper() != 'RESOLVED':
                raise ValueError('Unresolved/ambiguous researcher used as bridge')
        return current, nodes

    def process(self):
        reference_by_indicator = defaultdict(list)
        for row in self.snapshot.tables['reference_chunks']:
            reference_by_indicator[row['source_id']].append(row)
        candidates, package_map, comparisons, all_metrics = [], {}, [], []
        for document in sorted(self.snapshot.tables['reference_documents'], key=lambda r: r['source_id']):
            indicator = document['source_id']
            references = sorted(reference_by_indicator[indicator], key=lambda r: r['chunk_id'])
            if not references:
                raise ValueError('Indicator has no real reference query text')
            ids, texts = [r['chunk_id'] for r in references], [r['text'] for r in references]
            hybrid, contexts, expansion, metrics = self.retrieve_sources(texts,ids,indicator)
            vector, _, _, vm = self.retrieve_sources(texts,ids,indicator,mode='vector')
            # Graph comparison seeds are explicit INDICATOR entities available before retrieval.
            # They are isolated in this snapshot; this limitation is reported, not hidden.
            graph_only, _, _, gm = self.retrieve_sources(texts, ids, indicator,
                explicit_seeds=[self.entities[('INDICATOR', indicator)]], mode='graph')
            candidates.extend(hybrid)
            package_map.update({r['context_package_id']:r for r in contexts})
            comparisons.append({'indicator_id': indicator, 'vector_candidates': len(vector), 'graph_candidates': len(graph_only),
                'hybrid_candidates': len(hybrid), 'ranking_changes': sum((a['source_type'],a['source_id']) != (b['source_type'],b['source_id']) for a,b in zip(vector, hybrid)),
                'introduced_sources': len({r['source_id'] for r in hybrid} - {r['source_id'] for r in vector}),
                'vector_sources': len({r['source_id'] for r in vector}), 'hybrid_sources': len({r['source_id'] for r in hybrid}),
                'expanded_entities': metrics['graph'].get('expanded_entity_count', 0),
                'vector_latency_ms': vm['hybrid_query_latency_ms'], 'graph_latency_ms': gm['hybrid_query_latency_ms'],
                'hybrid_latency_ms': metrics['hybrid_query_latency_ms'],
                'graph_seed_ids_json': serialize(gm['seed_entity_ids']),
                'vector_source_ids_json': serialize([r['source_id'] for r in vector]),
                'graph_source_ids_json': serialize([r['source_id'] for r in graph_only]),
                'hybrid_source_ids_json': serialize([r['source_id'] for r in hybrid]),
                'vector_results_json': serialize([{k:r[k] for k in ('source_id','source_type','discovery_chunk_ids','best_vector_score','graph_score','graph_hops','hybrid_retrieval_score','source_rank')} for r in vector]),
                'graph_results_json': serialize([{k:r[k] for k in ('source_id','source_type','discovery_chunk_ids','best_vector_score','graph_score','graph_hops','hybrid_retrieval_score','source_rank')} for r in graph_only]),
                'hybrid_results_json': serialize([{k:r[k] for k in ('source_id','source_type','discovery_chunk_ids','best_vector_score','graph_score','graph_hops','hybrid_retrieval_score','source_rank')} for r in hybrid])})
            all_metrics.append({'indicator_id': indicator, 'reference_queries': len(ids), **metrics})
            print('SOURCE_INDICATOR_RETRIEVAL', len(all_metrics), len(hybrid), flush=True)
        return candidates, [package_map[k] for k in sorted(package_map)], comparisons, all_metrics


def write_outputs(directory, candidates, packages):
    directory.mkdir(parents=True, exist_ok=True)
    from .contracts import source_candidate_arrow_schema, source_context_arrow_schema
    for name, rows in (('source_indicator_candidates', candidates), ('source_context_packages', packages)):
        schema = source_candidate_arrow_schema() if name == 'source_indicator_candidates' else source_context_arrow_schema()
        if rows and any(set(row) != set(schema.names) for row in rows):
            raise ValueError('Unexpected retrieval output columns')
        table = pa.Table.from_pylist(rows, schema=schema)
        pq.write_table(table, directory / (name + '.parquet'), compression='zstd')
        restored = pq.read_table(directory / (name + '.parquet'))
        if restored.to_pylist() != rows or restored.schema != schema:
            raise ValueError('Retrieval Parquet roundtrip mismatch')
