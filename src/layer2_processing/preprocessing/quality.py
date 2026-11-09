import csv
import json
from collections import Counter
from .contracts import FIELDS
from .provenance import ANOMALY_COLUMNS

RELEVANT = {
    "proyectos": ["source_project_id", "title", "summary", "methodology", "objectives"],
    "articulos": ["title", "doi", "eid", "abstract"],
    "investigadores": ["institutional_id", "document_number", "external_id", "full_name", "email"],
    "indicadores": ["indicator_id", "indicator_name", "category", "dimension"],
}


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        # CSVs are inspection artifacts. Neutralize formula injection; Parquet remains exact.
        for row in rows:
            writer.writerow({k: ("'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v)
                             for k, v in row.items()})


PRODUCTION_CONFLICT_COLUMNS = ["source_id", "source_file", "source_row", "title", "year", "doi", "eid",
                               "conflict_type", "conflict_group", "resolution_status", "description"]


def production_conflicts(events, rejected):
    # Reuse quarantine decisions; this is a review projection, not a second resolver.
    indexed = {(r["_file"], r["_row"]): r for r in rejected}
    result = []
    for event in events:
        if event["domain"] != "articulos" or event["anomaly_code"] != "CONFLICTING_SOURCE_ID":
            continue
        row = indexed[(event["source_file"], event["source_row"])]
        result.append({"source_id": row.get("_source_id"), "source_file": row["_file"], "source_row": row["_row"],
                       "title": row.get("title"), "year": row.get("publication_year"), "doi": row.get("doi"), "eid": row.get("eid"),
                       "conflict_type": event["anomaly_code"], "conflict_group": event["source_object_id"],
                       "resolution_status": "UNRESOLVED", "description": event["description"]})
    return sorted(result, key=lambda r: (r["conflict_group"], r["source_file"], r["source_row"]))


def write_quality(output, datasets, events, manifest, rejected):
    quality = output / "quality"
    quality.mkdir(parents=True, exist_ok=True)
    completeness, domains = [], {}
    for domain, rows in datasets.items():
        counts = {}
        for field in FIELDS[domain]:
            present = sum(r.get(field) is not None and r.get(field) != [] for r in rows)
            missing = len(rows) - present
            completeness.append({"dataset": domain, "field": field, "total": len(rows),
                                 "present": present, "missing": missing,
                                 "completeness_pct": round(100 * present / len(rows), 2) if rows else None})
            counts[field] = missing
        selected = RELEVANT.get(domain, list(FIELDS[domain]))
        denominator = len(rows) * len(selected)
        domains[domain] = {
            "total": len(rows), "missing_by_field": counts,
            "completeness_pct": round(100 * sum(len(rows) - counts[f] for f in selected) / denominator, 2) if denominator else None,
            "duplicate_anomalies": sum(e["domain"] == domain and e["anomaly_code"] in {"DUPLICATE_SOURCE_ID", "CANONICAL_DUPLICATE"} for e in events),
        }
    identities = Counter(r["identity_status"] for r in datasets["investigadores"])
    domains["investigadores"]["identity_status"] = dict(identities)
    domains["investigadores"]["with_identifier"] = sum(any(r.get(f) for f in ("institutional_id", "document_number", "external_id")) for r in datasets["investigadores"])
    duplicate_rows = {(e["domain"], e["source_file"], e["source_row"]) for e in events
                      if e["anomaly_code"] in {"DUPLICATE_SOURCE_ID", "CANONICAL_DUPLICATE"}}
    summary = {
        "run_id": manifest["run_id"], "status": manifest["status"], "domains": domains,
        "records_read": manifest["records_read"], "records_staged": manifest["records_staged"],
        "records_accepted": manifest["records_accepted"], "records_rejected": manifest["records_rejected"],
        "records_canonical": {d: len(r) for d, r in datasets.items()},
        "duplicates": len(duplicate_rows), "anomalies": len(events),
        "anomalies_by_severity": dict(Counter(e["severity"] for e in events)),
        "anomalies_by_code": dict(Counter(e["anomaly_code"] for e in events)),
        "identities": dict(identities),
        "source_quality": manifest.get("source_quality", {}),
        "project_title_enrichment": manifest.get("project_title_enrichment", {}),
        "identity_resolution": manifest.get("identity_resolution", {}),
        "scope_isolation": manifest.get("scope_isolation", {"policy":"GLOBAL"}),
        "note": "Read/accepted/rejected count source rows; canonical counts entities and relationships separately.",
    }
    (quality / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(quality / "completeness.csv", completeness, ["dataset", "field", "total", "present", "missing", "completeness_pct"])
    write_csv(quality / "production_conflicts.csv", production_conflicts(events, rejected), PRODUCTION_CONFLICT_COLUMNS)
    filters = {
        "project_title_conflicts": lambda e: e["anomaly_code"] == "PROJECT_TITLE_CONFLICT",
        "duplicate_records": lambda e: e["anomaly_code"] in {"DUPLICATE_SOURCE_ID", "CANONICAL_DUPLICATE"},
        "invalid_records": lambda e: e["severity"] in {"ERROR", "CRITICAL"},
        "identity_conflicts": lambda e: e["anomaly_code"] == "IDENTITY_AMBIGUOUS",
        "unresolved_entities": lambda e: e["anomaly_code"] == "IDENTITY_UNRESOLVED",
    }
    for filename, predicate in filters.items():
        write_csv(quality / (filename + ".csv"), [e for e in events if predicate(e)], ANOMALY_COLUMNS)
    write_csv(output / "audit" / "anomalies.csv", events, ANOMALY_COLUMNS)
    # Readable rejected payloads remain private alongside audit files.
    with (quality / "rejected_records.jsonl").open("w", encoding="utf-8") as stream:
        for row in rejected:
            stream.write(json.dumps({k: row.get(k) for k in ("_file", "_row", "_raw")}, ensure_ascii=False, default=str) + "\n")
    return summary
