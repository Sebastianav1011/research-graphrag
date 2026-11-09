import csv
import json
import pytest

from src.layer3_graphrag.evaluation import (retrieval_metrics, load_evaluation_queries,
                                          evaluate_results, compare_engines)


def query(query_id="q", labels=None):
    return dict(query_id=query_id, query_text="consulta", query_type="source",
                expected_source_ids=["A", "C"] if labels is None else labels,
                expected_entity_ids=["entity"], expected_relation_types=["LINK"], notes="fixture")


def package(query_id="q"):
    return dict(query_id=query_id,
                retrieved_chunks=[dict(source_id=s, source_space="SOURCE") for s in ("A", "A", "B", "C")],
                retrieved_entities=[dict(entity_id="entity")], retrieved_relations=[dict(relation_type="LINK")],
                metrics=dict(graph=dict(seed_coverage=0.5, hop_distribution={"0": 1, "1": 2}),
                             latency=dict(total_query_latency_ms=12)))


def test_metrics_use_unique_source_units_and_k_denominator():
    result = retrieval_metrics(["A", "A", "B", "C"], ["A", "C", "C"], [1, 2, 5])
    assert result["at_k"]["2"] == dict(precision=0.5, recall=0.5, hit_rate=1.0)
    assert result["at_k"]["5"]["precision"] == 2/5
    assert result["at_k"]["5"]["recall"] == 1
    assert result["mrr"] == 1
    assert retrieval_metrics(["B", "C"], ["C"], [1])["mrr"] == 0.5


def test_no_hits_is_zero_but_empty_labels_are_unevaluable():
    assert retrieval_metrics([], ["A"], [1])["at_k"]["1"]["precision"] == 0
    result = retrieval_metrics(["A"], [], [1])
    assert result["evaluable"] is False
    assert result["mrr"] is None
    assert result["at_k"]["1"]["recall"] is None


def test_aggregation_excludes_unlabeled_queries_and_preserves_graph_metrics():
    result = evaluate_results([package(), package("q2")], [query(), query("q2", [])], [2])
    assert result["aggregate"]["evaluable_count"] == 1
    assert result["aggregate"]["unevaluable_count"] == 1
    assert result["aggregate"]["at_k"]["2"]["precision"] == 0.5
    assert result["queries"][0]["expected_entity_coverage"] == 1
    assert result["queries"][0]["expected_relation_type_coverage"] == 1
    assert result["graph"]["hop_distribution"] == {"0": 2, "1": 4}
    assert result["latency_ms"]["total_query_latency_ms"] == 12


@pytest.mark.parametrize("extension", ["json", "jsonl", "csv"])
def test_loader_formats(tmp_path, extension):
    target = tmp_path/f"queries.{extension}"
    if extension == "json":
        target.write_text(json.dumps([query()]))
    elif extension == "jsonl":
        target.write_text(json.dumps(query())+"\n")
    else:
        record = query()
        for key in ("expected_source_ids", "expected_entity_ids", "expected_relation_types"):
            record[key] = json.dumps(record[key])
        with target.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(record))
            writer.writeheader()
            writer.writerow(record)
    assert load_evaluation_queries(target)[0]["expected_source_ids"] == ["A", "C"]


def test_loader_rejects_duplicates_and_python_expression_lists(tmp_path):
    target = tmp_path/"queries.json"
    target.write_text(json.dumps([query(), query()]))
    with pytest.raises(ValueError, match="Duplicate"):
        load_evaluation_queries(target)
    item = query()
    item["expected_source_ids"] = "['unsafe-python-list']"
    target.write_text(json.dumps([item]))
    with pytest.raises(ValueError, match="JSON list"):
        load_evaluation_queries(target)


@pytest.mark.parametrize("mutation", ["missing", "extra", "repeated_labels"])
def test_loader_matches_strict_contract(tmp_path, mutation):
    record = query()
    if mutation == "missing":
        del record["notes"]
    elif mutation == "extra":
        record["confidence"] = 0.5
    else:
        record["expected_source_ids"] = ["A", "A"]
    target = tmp_path/"queries.json"
    target.write_text(json.dumps([record]))
    with pytest.raises(ValueError):
        load_evaluation_queries(target)


def test_result_set_mismatch_and_reference_evidence_rejected():
    with pytest.raises(ValueError, match="exactly"):
        evaluate_results([], [query()], [1])
    result = package()
    result["retrieved_chunks"][0]["source_space"] = "REFERENCE"
    with pytest.raises(ValueError, match="Reference"):
        evaluate_results([result], [query()], [1])


def test_comparison_uses_same_queries_without_label_leakage():
    class Engine:
        def __init__(self): self.calls = []
        def query(self, text, query_id=None, mode=None, seed_entity_ids=None):
            self.calls.append((text, query_id, mode, seed_entity_ids))
            return package(query_id)
    engines = {mode: Engine() for mode in ("vector", "graph", "hybrid")}
    result = compare_engines(engines, [query()], [1, 2])
    assert set(result["modes"]) == set(engines)
    assert all(engine.calls[0][3] is None for engine in engines.values())
    assert {engine.calls[0][1] for engine in engines.values()} == {"q"}


def test_empty_experiment_is_not_a_pass():
    result = evaluate_results([], [], [1])
    assert result["aggregate"]["evaluable_count"] == 0
    assert result["aggregate"]["mrr"] is None
    assert result["graph"] == {}
    assert result["latency_ms"] == {}
