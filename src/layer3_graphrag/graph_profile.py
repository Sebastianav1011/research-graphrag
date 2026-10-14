"""Physical graph topology and identity bridge profile, without inferred facts."""
from collections import Counter
import numpy as np
from .graph_store import json_object


def profile_graph(graph):
    parents = {k: k for k in graph.nodes}
    degrees = Counter()
    def find(k):
        while parents[k] != k:
            parents[k] = parents[parents[k]]
            k = parents[k]
        return k
    statuses = {k: str(json_object(v.get('metadata_json')).get('identity_status', '')).upper()
        for k, v in graph.nodes.items() if v['entity_type'] == 'RESEARCHER'}
    status_edges = Counter()
    for relation in graph.relations.values():
        a, b = relation['source_entity_id'], relation['target_entity_id']
        parents[find(a)] = find(b)
        degrees[a] += 1
        degrees[b] += 1
        status_edges[statuses.get(b, 'UNKNOWN')] += 1
    components = Counter(find(k) for k in graph.nodes)
    values = [degrees[k] for k in graph.nodes]
    researcher_degree = [degrees[k] for k, status in statuses.items() if status == 'RESOLVED']
    return {'nodes_total': len(graph.nodes), 'edges_total': len(graph.relations),
        'nodes_by_type': dict(Counter(v['entity_type'] for v in graph.nodes.values())),
        'edges_by_type': dict(Counter(v['relation_type'] for v in graph.relations.values())),
        'connected_components': len(components), 'largest_component': max(components.values(), default=0),
        'isolated_nodes': sum(v == 0 for v in values),
        'degree': {'min': min(values, default=0), 'max': max(values, default=0),
            **{f'p{p}': float(np.percentile(values, p)) if values else 0 for p in (50, 90, 95, 99)}},
        'researchers': dict(Counter(statuses.values())), 'resolved_bridge_edges': status_edges['RESOLVED'],
        'blocked_ambiguous_bridges': sum(status == 'AMBIGUOUS' and degrees[k] >= 2 for k, status in statuses.items()),
        'blocked_unresolved_bridges': sum(status == 'UNRESOLVED' and degrees[k] >= 2 for k, status in statuses.items()),
        'blocked_ambiguous_bridge_edges': status_edges['AMBIGUOUS'],
        'blocked_unresolved_bridge_edges': status_edges['UNRESOLVED'],
        'resolved_researcher_degree_p95': float(np.percentile(researcher_degree, 95)) if researcher_degree else 0}
