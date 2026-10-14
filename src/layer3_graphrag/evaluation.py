"""Retrieval experiments; unlabeled queries are explicitly unevaluable."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean
from typing import Any


LIST_FIELDS = ("expected_source_ids", "expected_entity_ids", "expected_relation_types")
MODES = {"vector", "graph", "hybrid"}


def validate_evaluation_queries(queries: list[dict]) -> list[dict]:
    seen: set[str] = set()
    validated = []
    for item in queries:
        if not isinstance(item, dict):
            raise ValueError("Evaluation query must be an object")
        query = dict(item)
        required = {"query_id", "query_text", "query_type", *LIST_FIELDS, "notes"}
        if not required.issubset(query):
            raise ValueError(f"Missing evaluation fields: {sorted(required-set(query))}")
        if set(query)-required-{"seed_entity_ids"}:
            raise ValueError("Unexpected evaluation fields")
        for field in ("query_id", "query_text", "query_type"):
            if not isinstance(query.get(field), str) or not query[field].strip():
                raise ValueError(f"Nonempty {field} required")
        if query["query_id"] in seen:
            raise ValueError("Duplicate evaluation query_id")
        seen.add(query["query_id"])
        for field in (*LIST_FIELDS, "seed_entity_ids"):
            value = query.get(field, [])
            if isinstance(value, str):
                try:
                    value = json.loads(value) if value.strip() else []
                except json.JSONDecodeError as error:
                    raise ValueError(f"{field} must be a JSON list") from error
            if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
                raise ValueError(f"{field} must be a list of nonempty strings")
            if len(set(value)) != len(value):
                raise ValueError(f"Duplicate values in {field}")
            query[field] = value
        if not isinstance(query.get("notes", ""), str):
            raise ValueError("notes must be a string")
        query.setdefault("notes", "")
        validated.append(query)
    return validated


def load_evaluation_queries(path: str | Path) -> list[dict]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    elif path.suffix.lower() == ".jsonl":
        value = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    elif path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            value = list(csv.DictReader(stream))
    else:
        raise ValueError("Evaluation format must be JSON, JSONL or CSV")
    if not isinstance(value, list):
        raise ValueError("Evaluation file must contain a list of queries")
    return validate_evaluation_queries(value)


def retrieval_metrics(retrieved_ids: list[str], expected_ids: list[str], k_values: list[int]) -> dict:
    """Rank unique source IDs once. Precision denominator is K even for short lists.

    MRR considers all returned unique sources. Recall denominator is the number
    of distinct relevant labels. Empty labels yield None, never fabricated zero.
    """
    if not k_values or any(not isinstance(k, int) or isinstance(k, bool) or k <= 0 for k in k_values):
        raise ValueError("k_values must contain positive integers")
    ordered = list(dict.fromkeys(retrieved_ids))
    expected = set(expected_ids)
    result = {"evaluable": bool(expected), "expected_count": len(expected), "retrieved_count": len(ordered)}
    result["mrr"] = next((1/rank for rank, source_id in enumerate(ordered, 1) if source_id in expected), 0.0) if expected else None
    result["at_k"] = {}
    for k in sorted(set(k_values)):
        hits = len(set(ordered[:k]) & expected)
        result["at_k"][str(k)] = {"precision": hits/k if expected else None,
                                    "recall": hits/len(expected) if expected else None,
                                    "hit_rate": float(hits > 0) if expected else None}
    return result


def _retrieved_source_ids(package: dict) -> list[str]:
    if 'source_candidates' in package:
        return [r['source_id'] for r in package['source_candidates']]
    chunks = package.get("retrieved_chunks", [])
    if chunks:
        if any(c.get("source_space", "SOURCE") != "SOURCE" for c in chunks):
            raise ValueError("Reference chunks cannot count as discovered SOURCES")
        return [c["source_id"] for c in chunks if c.get("source_id")]
    return [d["source_id"] for d in package.get("retrieved_documents", []) if d.get("source_id")]


def _mean_present(rows: list[dict], field: str) -> float | None:
    values = [row[field] for row in rows if isinstance(row.get(field), (int, float))]
    return mean(values) if values else None


def evaluate_results(results: list[dict] | dict[str, dict], queries: list[dict], k_values: list[int]) -> dict:
    queries = validate_evaluation_queries(queries)
    if isinstance(results, dict):
        by_id = results
    else:
        by_id = {item["query_id"]: item for item in results}
        if len(by_id) != len(results):
            raise ValueError("Duplicate result query_id")
    if set(by_id) != {q["query_id"] for q in queries}:
        raise ValueError("Results must match exactly the evaluation query set")
    rows = []
    graph_rows, latency_rows = [], []
    for query in queries:
        package = by_id[query["query_id"]]
        metrics = retrieval_metrics(_retrieved_source_ids(package), query["expected_source_ids"], k_values)
        entity_ids = {e["entity_id"] for e in package.get("retrieved_entities", []) if e.get("entity_id")}
        relation_types = {r["relation_type"] for r in package.get("retrieved_relations", []) if r.get("relation_type")}
        expected_entities = set(query["expected_entity_ids"])
        expected_relations = set(query["expected_relation_types"])
        rows.append({"query_id": query["query_id"], **metrics,
                     "expected_entity_coverage": len(entity_ids & expected_entities)/len(expected_entities) if expected_entities else None,
                     "expected_relation_type_coverage": len(relation_types & expected_relations)/len(expected_relations) if expected_relations else None})
        provided = package.get("metrics", {})
        graph = dict(provided.get("graph", {}))
        latency = dict(provided.get("latency_ms", provided.get("latency", {})))
        # Accept the query engine's flat metric dictionary as well.
        for key in ("seed_coverage", "graph_expansion_coverage", "orphan_retrieval", "relation_utilization"):
            if key in provided:
                graph[key] = provided[key]
        for key, value in provided.items():
            if key.endswith("_latency_ms"):
                latency[key] = value
        graph_rows.append(graph)
        latency_rows.append(latency)
    evaluable = [row for row in rows if row["evaluable"]]
    aggregate = {"query_count": len(rows), "evaluable_count": len(evaluable),
                 "unevaluable_count": len(rows)-len(evaluable),
                 "mrr": mean(r["mrr"] for r in evaluable) if evaluable else None,
                 "at_k": {str(k): {metric: mean(r["at_k"][str(k)][metric] for r in evaluable) if evaluable else None
                                       for metric in ("precision", "recall", "hit_rate")}
                          for k in sorted(set(k_values))}}
    graph_fields = {key for row in graph_rows for key in row if key != "hop_distribution"}
    graph_summary = {key: _mean_present(graph_rows, key) for key in sorted(graph_fields)}
    hops: dict[str, int] = {}
    for row in graph_rows:
        for hop, count in row.get("hop_distribution", {}).items():
            hops[str(hop)] = hops.get(str(hop), 0)+count
    if hops:
        graph_summary["hop_distribution"] = hops
    latency_fields = {key for row in latency_rows for key in row}
    return {"queries": rows, "aggregate": aggregate, "graph": graph_summary,
            "latency_ms": {key: _mean_present(latency_rows, key) for key in sorted(latency_fields)}}


def compare_engines(engines: dict[str, Any], queries: list[dict], k_values: list[int]) -> dict:
    """Same query set/seeds for all modes; no ground truth used as graph seeds."""
    if not engines or not set(engines).issubset(MODES):
        raise ValueError("Comparison modes must be vector, graph, hybrid")
    queries = validate_evaluation_queries(queries)
    reports = {}
    for mode, engine in engines.items():
        results = [engine.query(q["query_text"], query_id=q["query_id"], mode=mode,
                                seed_entity_ids=q["seed_entity_ids"] or None) for q in queries]
        reports[mode] = evaluate_results(results, queries, k_values)
    return {"modes": reports, "query_ids": [q["query_id"] for q in queries],
            "seeding_policy": "Explicit seed_entity_ids only; relevance labels never become seeds"}
