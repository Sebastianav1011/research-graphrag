"""Only ephemeral synthetic rows; no reads of institutional snapshots."""
import json
from types import SimpleNamespace
import pytest

from src.layer3_graphrag.graph import build_graph
from src.layer3_graphrag.graph import LocalGraphStore
from src.layer3_graphrag.graph_retriever import GraphRetriever


def entity(key, kind, status=None):
    return {"entity_id": key, "entity_type": kind, "canonical_id": key.lower(), "label": key,
            "metadata_json": json.dumps({"identity_status": status} if status else {}),
            "provenance_json": '{"layer1_run_id":"synthetic-l1"}', "layer2_run_id": "synthetic-l2"}


def relation(key, source, target, kind="PROJECT_HAS_RESEARCHER", attributes=None):
    return {"relation_id": key, "source_entity_id": source, "target_entity_id": target,
            "relation_type": kind, "attributes_json": json.dumps(attributes or {}),
            "evidence_type": "STRUCTURED_CANONICAL", "provenance_json": "{}", "layer2_run_id": "synthetic-l2"}


def snapshot(nodes=None, edges=None):
    nodes = nodes if nodes is not None else [entity("P1", "PROJECT"), entity("P2", "PROJECT"),
                                           entity("R", "RESEARCHER", "RESOLVED"), entity("A", "ARTICLE"), entity("I", "INDICATOR")]
    edges = edges if edges is not None else [relation("e1", "P1", "R"), relation("e2", "P2", "R"),
                                           relation("e3", "A", "R", "ARTICLE_HAS_RESEARCHER")]
    source_docs = [{"document_id": "doc-" + node["entity_id"], "source_id": node["canonical_id"],
                    "source_type": node["entity_type"]} for node in nodes if node["entity_type"] in {"PROJECT", "ARTICLE"}]
    chunks = [{**doc, "chunk_id": "chunk-" + doc["document_id"], "section_id": "sec-" + doc["document_id"],
               "field_name": "abstract", "text": "Ephemeral test text", "provenance_json": "{}"} for doc in source_docs]
    return SimpleNamespace(tables={"entities": nodes, "relations": edges, "source_documents": source_docs,
                                  "source_chunks": chunks, "reference_documents": [], "reference_chunks": []})


def retrieve(settings=None, seeds=None, sample=None, space="SOURCE"):
    sample = sample or snapshot()
    return GraphRetriever(build_graph(sample), sample, settings).retrieve(seeds or ["P1"], space)


def test_build_preserves_original_identity_and_metadata():
    sample = snapshot()
    sample.tables["entities"][2]["metadata_json"] = '{"identity_status":"AMBIGUOUS","identity_rule":"upstream"}'
    store = build_graph(sample)
    assert store.nodes["R"] == sample.tables["entities"][2]
    assert store.validate()["isolated_nodes"] == ["I"]
    assert len(store.nodes) == 5


def test_project_relational_context_keeps_external_projects_and_literal_lineage():
    sample=snapshot()
    for edge in sample.tables['relations']:
        edge['provenance_json']=json.dumps({'layer1':[{'record_source':'base/members.csv',
            'source_row':2,'raw_sha256':'synthetic','original_values':{'documento':'PRIVATE'}}]})
    package=GraphRetriever(build_graph(sample),sample).project_context('p1')
    assert {n['entity_id'] for n in package['entities']}=={'P1','P2','R','A'}
    assert len(package['relations'])==3
    assert package['support_paths']['P2']==['e1','e2']
    assert package['relations'][0]['provenance']['layer1'][0]=={
        'record_source':'base/members.csv','source_row':2,'raw_sha256':'synthetic'}
    assert package['evidence_role']=='RELATIONAL_CONTEXT_ONLY'
    assert {r['relation_type'] for r in package['relations']}=={'PROJECT_HAS_RESEARCHER','ARTICLE_HAS_RESEARCHER'}
    with pytest.raises(ValueError,match='inequivoco'):
        GraphRetriever(build_graph(sample),sample).project_context('unselected_missing')


def test_read_only_project_relations_uses_published_graph_and_rejects_changed_facts(tmp_path,monkeypatch):
    from layer4_evaluation.indicators.scoped_retrieval import project_relations
    sample=snapshot();sample.manifest_hash='synthetic_knowledge'
    for edge in sample.tables['relations']:
        edge['provenance_json']='{"record_source":"base/members.csv","source_row":1}'
    publication=tmp_path/'outputs/layer3/publication'
    from copy import deepcopy
    graph=build_graph(deepcopy(sample));graph.save(publication/'graph')
    (publication/'_manifest.json').write_text('{}',encoding='utf-8')
    monkeypatch.setattr('layer3_graphrag.configuration.load_config',lambda *a:({'graph':{'max_hops':2}},'config_hash'))
    monkeypatch.setattr('layer3_graphrag.validate_inputs.validate_inputs',lambda *a:sample)
    checks=[]
    def verified(path,fingerprint):
        checks.append(fingerprint)
        return {'layer3_run_id':'synthetic_layer3'}
    monkeypatch.setattr('layer4_evaluation.indicators.scoped_retrieval.validate_publication',verified)
    packages=project_relations(tmp_path,[{'project_id':'p1'}])
    assert set(packages)=={'p1'} and checks==['synthetic_knowledge']
    assert {n['entity_id'] for n in packages['p1']['entities']}=={'P1','P2','A','R'}
    assert packages['p1']['knowledge_manifest_sha256']=='synthetic_knowledge'
    graph.relations['e1']['attributes_json']='{"changed":true}'
    graph.save(publication/'graph')
    with pytest.raises(ValueError,match='conocimiento aprobado'):
        project_relations(tmp_path,[{'project_id':'p1'}])


def test_unknown_identity_status_cannot_bridge():
    sample = snapshot()
    sample.tables['entities'][2]['metadata_json'] = '{}'
    result = retrieve(sample=sample)
    assert {node['entity_id'] for node in result['entities']} == {'P1', 'R'}
    assert result['metrics']['blocked_identity_bridges'] == 1


def test_calibrated_priority_reserves_neighbor_slot_for_resolved():
    nodes = [entity('P1','PROJECT'), entity('R0','RESEARCHER','AMBIGUOUS'), entity('R1','RESEARCHER','RESOLVED')]
    edges = [relation('e0','P1','R0'), relation('e1','P1','R1')]
    result = retrieve({'max_hops':1, 'max_neighbors':1, 'neighbor_priority':'resolved_researchers_first'},
        sample=snapshot(nodes, edges))
    assert {node['entity_id'] for node in result['entities']} == {'P1', 'R1'}
    assert result['metrics']['truncated_neighbor_count'] == 1


@pytest.mark.parametrize("table,key", [("entities", "entity_id"), ("relations", "relation_id")])
def test_duplicate_ids_rejected(table, key):
    sample = snapshot()
    sample.tables[table].append(dict(sample.tables[table][0]))
    with pytest.raises(ValueError, match="duplicate"):
        build_graph(sample)


@pytest.mark.parametrize("change", [{"target_entity_id": "MISSING"}, {"target_entity_id": "P1"},
                                    {"relation_type": "INFERRED_SIMILARITY"}, {"target_entity_id": "P2"},
                                    {"evidence_type": "INFERRED"}, {"attributes_json": "[1]"}])
def test_invalid_edges_rejected(change):
    sample = snapshot()
    sample.tables["relations"][0].update(change)
    with pytest.raises(ValueError, match="integrity"):
        build_graph(sample)


def test_logical_duplicates_rejected_and_distinct_attributes_retained():
    sample = snapshot()
    sample.tables["relations"].append(relation("another", "P1", "R"))
    with pytest.raises(ValueError, match="DUPLICATE_LOGICAL"):
        build_graph(sample)
    sample.tables["relations"][-1]["attributes_json"] = '{"role":"coauthor"}'
    store = build_graph(sample)
    assert len(store.neighbors("P1")) == 2


def test_save_load_determinism(tmp_path):
    sample = snapshot()
    first = build_graph(sample).save(tmp_path / "one").read_bytes()
    sample.tables["entities"].reverse()
    sample.tables["relations"].reverse()
    second = build_graph(sample).save(tmp_path / "two").read_bytes()
    assert first == second
    assert LocalGraphStore.load(tmp_path / "one").validate()["valid"]


def test_load_rejects_duplicate_ids(tmp_path):
    path = build_graph(snapshot()).save(tmp_path)
    payload = json.loads(path.read_text())
    payload["nodes"].append(dict(payload["nodes"][0]))
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="Duplicate"):
        LocalGraphStore.load(tmp_path)


@pytest.mark.parametrize("hops,expected", [(0, {"P1"}), (1, {"P1", "R"}), (2, {"P1", "R", "P2", "A"})])
def test_hop_limit_and_support_paths(hops, expected):
    result = retrieve({"max_hops": hops})
    assert {node["entity_id"] for node in result["entities"]} == expected
    if hops == 2:
        assert result["support_paths"]["A"] == ["e1", "e3"]
        assert result["metrics"]["hop_distribution"] == {"0": 1, "1": 1, "2": 2}


def test_max_neighbors_deterministic_and_total_cap():
    result = retrieve({"max_neighbors": 1}, seeds=["R"])
    assert {node["entity_id"] for node in result["entities"]} == {"R", "A"}
    result = retrieve({"max_total_nodes": 2})
    assert len(result["entities"]) == 2
    assert result["metrics"]["capacity_reached"]


def test_relation_and_entity_filters():
    result = retrieve({"allowed_relation_types": ["PROJECT_HAS_RESEARCHER"]})
    assert "A" not in {node["entity_id"] for node in result["entities"]}
    assert retrieve({"allowed_relation_types": []})["relations"] == []
    assert len(retrieve({"allowed_entity_types": ["PROJECT"]})["entities"]) == 1


def test_coverage_denominator_includes_legitimate_isolated_nodes():
    sample = snapshot()
    store = build_graph(sample)
    assert store.validate()["valid"]
    assert store.validate()["isolated_nodes"] == ["I"]
    result = GraphRetriever(store, sample).retrieve(["P1"])
    assert result["metrics"]["expanded_entity_count"] == 3
    assert result["metrics"]["graph_expansion_coverage"] == 3 / 5
    assert result["metrics"]["orphan_retrieval"] == 0


@pytest.mark.parametrize("status", ["AMBIGUOUS", "UNRESOLVED", "ambiguous", "unresolved"])
def test_ambiguous_preserved_but_not_bridge_without_explicit_opt_in(status):
    sample = snapshot()
    sample.tables["entities"][2]["metadata_json"] = json.dumps({"identity_status": status})
    result = retrieve(sample=sample)
    assert {node["entity_id"] for node in result["entities"]} == {"P1", "R"}
    assert result["metrics"]["blocked_identity_bridges"] == 1
    researcher = next(node for node in result["entities"] if node["entity_id"] == "R")
    assert json.loads(researcher["metadata_json"])["identity_status"] == status
    assert sample.tables["entities"][2]["metadata_json"] == researcher["metadata_json"]
    assert len(retrieve({"expand_ambiguous_researchers": True}, sample=sample)["entities"]) == 4


def test_reference_is_separate_and_never_source_evidence():
    sample = snapshot()
    sample.tables["reference_documents"] = [{"document_id": "reference-doc", "source_id": "i", "source_type": "INDICATOR_REFERENCE"}]
    sample.tables["reference_chunks"] = [{"chunk_id": "reference-chunk", "document_id": "reference-doc", "section_id": "reference-sec",
                                          "source_id": "i", "source_type": "INDICATOR_REFERENCE", "field_name": "definition",
                                          "text": "Indicator definition", "provenance_json": "{}"}]
    assert retrieve(seeds=["I"], sample=sample)["hits"] == []
    result = retrieve(seeds=["I"], sample=sample, space="REFERENCE")
    assert result["hits"][0]["source_space"] == "REFERENCE"
    assert result["metrics"]["orphan_retrieval"] == 1


def test_missing_seed_and_provenance_preserved():
    result = retrieve(seeds=["P1", "missing"])
    assert result["metrics"]["seed_coverage"] == 0.5
    assert result["metrics"]["missing_seed_ids"] == ["missing"]
    assert all(hit["provenance_json"] == "{}" for hit in result["hits"])
    assert all(hit["vector_score"] is None for hit in result["hits"])


@pytest.mark.parametrize("name", ["max_hops", "max_neighbors", "max_total_nodes"])
def test_negative_bounds_rejected(name):
    sample = snapshot()
    with pytest.raises(ValueError):
        GraphRetriever(build_graph(sample), sample, {name: -1})
