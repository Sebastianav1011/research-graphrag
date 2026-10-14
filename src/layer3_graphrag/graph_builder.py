"""Build only structured edges supplied by an approved knowledge snapshot."""
from .graph_store import LocalGraphStore
from .security import remove_personal_identifiers
from .provenance import serialize
import json


def build_graph(snapshot, settings=None):
    settings = settings or {}
    nodes, relations = {}, {}
    for row in snapshot.tables["entities"]:
        entity_id = row.get("entity_id")
        if not entity_id or entity_id in nodes:
            raise ValueError(f"Missing or duplicate entity ID: {entity_id}")
        node = dict(row)
        for field in ('metadata_json', 'provenance_json'):
            original = json.loads(node[field])
            cleaned = remove_personal_identifiers(original)
            if cleaned != original:
                node[field] = serialize(cleaned)
        nodes[entity_id] = node
    for row in snapshot.tables["relations"]:
        relation_id = row.get("relation_id")
        if not relation_id or relation_id in relations:
            raise ValueError(f"Missing or duplicate relation ID: {relation_id}")
        relations[relation_id] = row
    store = LocalGraphStore(nodes, relations)
    report = store.validate()
    failures = [error for error in report["errors"]
                if error["code"] != "ORPHAN_RELATION" or settings.get("fail_on_orphan_relation", True)]
    if failures:
        raise ValueError(f"Graph integrity validation failed: {failures}")
    # Isolation is a reported property, not an invented relationship.
    return store
