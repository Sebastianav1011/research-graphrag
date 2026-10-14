"""Provider-independent graph storage with a deterministic local JSON backend."""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
import json
from pathlib import Path

ENTITY_TYPES = frozenset({"PROJECT", "ARTICLE", "RESEARCHER", "ORGANIZATION", "INDICATOR"})
RELATION_ENDPOINTS = {
    "PROJECT_HAS_RESEARCHER": ("PROJECT", "RESEARCHER"),
    "ARTICLE_HAS_RESEARCHER": ("ARTICLE", "RESEARCHER"),
}


def json_object(value):
    """Read structured metadata without coercing identity or inventing attributes."""
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError("Graph metadata must contain a JSON object")
    return result


class GraphStore(ABC):
    @abstractmethod
    def neighbors(self, entity_id, allowed_relations=None, allowed_entity_types=None): ...

    @abstractmethod
    def save(self, directory): ...

    @classmethod
    @abstractmethod
    def load(cls, directory): ...

    @abstractmethod
    def validate(self): ...


class LocalGraphStore(GraphStore):
    """Directed facts, traversable both ways; original entity IDs are retained."""

    def __init__(self, nodes=None, relations=None):
        self.nodes = deepcopy(nodes or {})
        self.relations = deepcopy(relations or {})
        self._adjacency = {key: [] for key in self.nodes}
        for relation_id, row in sorted(self.relations.items()):
            for endpoint in {row.get("source_entity_id"), row.get("target_entity_id")}:
                if endpoint in self._adjacency:
                    self._adjacency[endpoint].append(relation_id)

    def neighbors(self, entity_id, allowed_relations=None, allowed_entity_types=None):
        """Return sorted (neighbor_id, relation) pairs; explicit empty filters deny all."""
        relation_filter = None if allowed_relations is None else set(allowed_relations)
        entity_filter = None if allowed_entity_types is None else set(allowed_entity_types)
        result = []
        for relation_id in self._adjacency.get(entity_id, []):
            row = self.relations[relation_id]
            if relation_filter is not None and row["relation_type"] not in relation_filter:
                continue
            neighbor_id = (row["target_entity_id"] if row["source_entity_id"] == entity_id
                           else row["source_entity_id"])
            neighbor = self.nodes.get(neighbor_id)
            if neighbor is None:
                continue
            if entity_filter is not None and neighbor["entity_type"] not in entity_filter:
                continue
            result.append((neighbor_id, deepcopy(row)))
        return sorted(result, key=lambda item: (item[0], item[1]["relation_id"]))

    def validate(self):
        errors = []
        logical_edges = set()
        connected = set()
        for key, row in sorted(self.nodes.items()):
            if key != row.get("entity_id") or not key:
                errors.append({"code": "NODE_ID_MISMATCH", "entity_id": key})
            if row.get("entity_type") not in ENTITY_TYPES:
                errors.append({"code": "INVALID_ENTITY_TYPE", "entity_id": key})
            try:
                json_object(row.get("metadata_json"))
            except (ValueError, TypeError):
                errors.append({"code": "INVALID_NODE_METADATA", "entity_id": key})
        for key, row in sorted(self.relations.items()):
            source, target = row.get("source_entity_id"), row.get("target_entity_id")
            kind = row.get("relation_type")
            if key != row.get("relation_id") or not key:
                errors.append({"code": "RELATION_ID_MISMATCH", "relation_id": key})
            if source not in self.nodes or target not in self.nodes:
                errors.append({"code": "ORPHAN_RELATION", "relation_id": key})
                continue
            connected.update((source, target))
            if source == target:
                errors.append({"code": "UNEXPECTED_SELF_LOOP", "relation_id": key})
            if kind not in RELATION_ENDPOINTS:
                errors.append({"code": "INVALID_RELATION_TYPE", "relation_id": key})
            elif (self.nodes[source]["entity_type"], self.nodes[target]["entity_type"]) != RELATION_ENDPOINTS[kind]:
                errors.append({"code": "INVALID_ENDPOINT_TYPES", "relation_id": key})
            if row.get("evidence_type") != "STRUCTURED_CANONICAL":
                errors.append({"code": "INVALID_RELATION_EVIDENCE", "relation_id": key})
            try:
                attributes = json.dumps(json_object(row.get("attributes_json")), sort_keys=True,
                                        ensure_ascii=False, separators=(",", ":"))
            except (ValueError, TypeError):
                errors.append({"code": "INVALID_RELATION_ATTRIBUTES", "relation_id": key})
                continue
            signature = (source, kind, target, attributes)
            if signature in logical_edges:
                errors.append({"code": "DUPLICATE_LOGICAL_RELATION", "relation_id": key})
            logical_edges.add(signature)
        return {"valid": not errors, "errors": errors,
                "isolated_nodes": sorted(set(self.nodes) - connected),
                "entity_count": len(self.nodes), "relation_count": len(self.relations)}

    def save(self, directory):
        """Write only into the caller's candidate directory; publication is external."""
        result = self.validate()
        if not result["valid"]:
            raise ValueError(f"Cannot save invalid graph: {result['errors']}")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        payload = {"format_version": 1, "nodes": [self.nodes[key] for key in sorted(self.nodes)],
                   "relations": [self.relations[key] for key in sorted(self.relations)]}
        path = directory / "graph.json"
        path.write_text(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                   separators=(",", ":")) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, directory):
        payload = json.loads((Path(directory) / "graph.json").read_text(encoding="utf-8"))
        if payload.get("format_version") != 1:
            raise ValueError("Unsupported graph format")
        node_rows, relation_rows = payload["nodes"], payload["relations"]
        nodes = {row["entity_id"]: row for row in node_rows}
        relations = {row["relation_id"]: row for row in relation_rows}
        if len(nodes) != len(node_rows) or len(relations) != len(relation_rows):
            raise ValueError("Duplicate graph IDs")
        result = cls(nodes, relations)
        validation = result.validate()
        if not validation["valid"]:
            raise ValueError(f"Invalid stored graph: {validation['errors']}")
        return result
