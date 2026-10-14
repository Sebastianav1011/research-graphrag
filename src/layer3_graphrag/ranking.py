"""Configurable retrieval signals; no confidence or indicator decisions."""
import math
from copy import deepcopy


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
