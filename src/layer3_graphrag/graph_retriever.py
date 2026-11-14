"""Bounded deterministic expansion of existing facts; no identity resolution."""
from collections import deque
from copy import deepcopy
from .graph import json_object


class GraphRetriever:
    def __init__(self, store, snapshot, settings=None):
        self.store = store
        self.snapshot = snapshot
        self.settings = dict(settings or {})
        if self.settings.get('researcher_bridge_policy', 'resolved_only') != 'resolved_only':
            raise ValueError('Researcher bridge policy must be resolved_only')
        self._isolated_nodes = set(store.validate()["isolated_nodes"])
        for name, default in (("max_hops", 2), ("max_neighbors", 20), ("max_total_nodes", 200)):
            value = self.settings.get(name, default)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
            self.settings[name] = value
        if not self.settings["max_total_nodes"]:
            raise ValueError("max_total_nodes must be positive")
        self._documents = {}
        self._chunks = {}
        for space in ("SOURCE", "REFERENCE"):
            prefix = space.lower()
            self._documents[space] = {}
            for row in snapshot.tables.get(prefix + "_documents", []):
                kind = "INDICATOR" if space == "REFERENCE" else row["source_type"]
                key = (kind, row["source_id"])
                self._documents[space].setdefault(key, []).append(row)
            self._chunks[space] = {}
            for row in snapshot.tables.get(prefix + "_chunks", []):
                self._chunks[space].setdefault(row["document_id"], []).append(row)

    def project_context(self,project_id):
        """Exact canonical seed; shared authorship never asserts project production."""
        seeds=[key for key,node in self.store.nodes.items()
            if node['entity_type']=='PROJECT' and node['canonical_id']==project_id]
        if len(seeds)!=1:raise ValueError('Proyecto sin nodo de grafo inequivoco: '+project_id)
        result=self.retrieve(seeds)
        from .security import remove_personal_identifiers
        def provenance(value):
            value=remove_personal_identifiers(value)
            if isinstance(value,dict):return {k:provenance(v) for k,v in value.items() if k!='original_values'}
            if isinstance(value,list):return [provenance(v) for v in value]
            return value
        return dict(project_id=project_id,seed_entity_id=seeds[0],version='PROJECT_RELATIONAL_CONTEXT_V1',
            evidence_role='RELATIONAL_CONTEXT_ONLY',
            entities=[{k:n[k] for k in ('entity_id','entity_type','canonical_id','label')} for n in result['entities']],
            relations=[dict(relation_id=r['relation_id'],source_entity_id=r['source_entity_id'],
                target_entity_id=r['target_entity_id'],relation_type=r['relation_type'],
                evidence_type=r['evidence_type'],attributes=json_object(r['attributes_json']),
                provenance=provenance(json_object(r['provenance_json']))) for r in result['relations']],
            support_paths=result['support_paths'],metrics=result['metrics'])

    def retrieve(self, seed_entity_ids, space="SOURCE"):
        if space not in {"SOURCE", "REFERENCE"}:
            raise ValueError("Graph retrieval space must be SOURCE or REFERENCE")
        settings = self.settings
        allowed_relations = settings.get("allowed_relation_types", settings.get("allowed_relations"))
        allowed_entities = settings.get("allowed_entity_types")
        requested = sorted(set(seed_entity_ids))
        known = [key for key in requested if key in self.store.nodes]
        allowed_seeds = [key for key in known if allowed_entities is None
                         or self.store.nodes[key]["entity_type"] in allowed_entities]
        seeds = allowed_seeds[:settings["max_total_nodes"]]
        distances = {key: 0 for key in seeds}
        paths = {key: [] for key in seeds}
        queue = deque(seeds)
        used_relations = {}
        blocked_bridges = set()
        truncated_neighbors = 0
        capacity_reached = len(allowed_seeds) > len(seeds)
        while queue:
            current = queue.popleft()
            if distances[current] >= settings["max_hops"]:
                continue
            node = self.store.nodes[current]
            status = json_object(node.get("metadata_json")).get("identity_status")
            normalized_status = status.upper() if isinstance(status, str) else status
            if (node["entity_type"] == "RESEARCHER" and normalized_status != "RESOLVED"
                    and not settings.get("expand_ambiguous_researchers", False)):
                blocked_bridges.add(current)
                continue
            neighbors = self.store.neighbors(current, allowed_relations, allowed_entities)
            # The neighbor limit counts entities; parallel facts retain their attributes.
            unique_neighbors = sorted({neighbor for neighbor, _ in neighbors})
            if settings.get('neighbor_priority') == 'resolved_researchers_first':
                def priority(key):
                    candidate = self.store.nodes[key]
                    status = str(json_object(candidate.get('metadata_json')).get('identity_status', '')).upper()
                    return (int(candidate['entity_type'] == 'RESEARCHER' and status != 'RESOLVED'), key)
                unique_neighbors.sort(key=priority)
            selected = set(unique_neighbors[:settings["max_neighbors"]])
            truncated_neighbors += max(0, len(unique_neighbors) - len(selected))
            for neighbor, relation in neighbors:
                if neighbor not in selected:
                    continue
                if neighbor not in distances:
                    if len(distances) >= settings["max_total_nodes"] or len(distances)-len(seeds) >= settings.get('max_expanded_entities', settings['max_total_nodes']):
                        capacity_reached = True
                        continue
                    distances[neighbor] = distances[current] + 1
                    paths[neighbor] = paths[current] + [relation["relation_id"]]
                    queue.append(neighbor)
                used_relations[relation["relation_id"]] = relation
        entities = [deepcopy(self.store.nodes[key]) for key in sorted(distances, key=lambda key: (distances[key], key))]
        hits = []
        seen_chunks = set()
        for node in entities:
            key = (node["entity_type"], node["canonical_id"])
            for document in sorted(self._documents[space].get(key, []), key=lambda row: row["document_id"]):
                for chunk in sorted(self._chunks[space].get(document["document_id"], []),
                                    key=lambda row: row["chunk_id"]):
                    if chunk["chunk_id"] in seen_chunks:
                        continue
                    seen_chunks.add(chunk["chunk_id"])
                    distance = distances[node["entity_id"]]
                    hits.append({**deepcopy(chunk), "source_space": space, "vector_score": None,
                                 "graph_distance": distance, "structured_relation_strength": 1.0 if distance else 0.0,
                                 "entity_id": node["entity_id"], "relation_ids": paths[node["entity_id"]][:]})
        hits.sort(key=lambda row: (row["graph_distance"], row["chunk_id"]))
        for rank, hit in enumerate(hits, start=1):
            hit["rank"] = rank
        hop_distribution = {str(hop): sum(distance == hop for distance in distances.values())
                            for hop in sorted(set(distances.values()))}
        eligible_relations = [row for row in self.store.relations.values()
                              if (allowed_relations is None or row["relation_type"] in allowed_relations)
                              and row["source_entity_id"] in self.store.nodes
                              and row["target_entity_id"] in self.store.nodes
                              and (allowed_entities is None or all(self.store.nodes[key]["entity_type"] in allowed_entities
                                   for key in (row["source_entity_id"], row["target_entity_id"])))]
        return {"hits": hits, "entities": entities,
                "relations": [deepcopy(used_relations[key]) for key in sorted(used_relations)],
                "support_paths": paths,
                "metrics": {"requested_seed_count": len(requested), "matched_seed_count": len(known),
                            "used_seed_count": len(seeds),
                            "seed_coverage": len(known) / len(requested) if requested else 0.0,
                            "expanded_entity_count": len(distances) - len(seeds),
                            "graph_expansion_coverage": (len(distances) - len(seeds)) / len(self.store.nodes) if self.store.nodes else 0.0,
                            "hop_distribution": hop_distribution,
                            "orphan_retrieval": len(set(distances) & self._isolated_nodes),
                            "relation_utilization": len(used_relations) / len(eligible_relations) if eligible_relations else 0.0,
                            "blocked_identity_bridges": len(blocked_bridges),
                            "ambiguous_bridge_uses": 0,
                            "truncated_neighbor_count": truncated_neighbors,
                            "capacity_reached": capacity_reached,
                            "missing_seed_ids": sorted(set(requested) - set(known))}}
