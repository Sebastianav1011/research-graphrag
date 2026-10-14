"""Orchestration with immutable inputs, isolated runs and guarded publication."""
import importlib.metadata
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from jsonschema import Draft202012Validator, FormatChecker

from common.config import read_config
from common.logging import get_logger
from common.paths import output_path, resolve_input
from .canonicalize import canonical_entities, canonical_researchers, organizations, relationships, write_parquet, enrich_project_titles
from .contracts import FIELDS, KEYS, logical_schema
from .identity import resolve
from .ingest import ingest
from .normalize import header, normalize_record, stable_hash, text
from .provenance import anomaly, file_hash, now
from .quality import RELEVANT, write_quality, write_csv
from .provenance import ANOMALY_COLUMNS
from .validate import map_rows, mapped_values, validate_columns, validate_rows

DOMAINS = ("proyectos", "articulos", "investigadores", "indicadores")


def source_specs(sources):
    for domain in DOMAINS:
        spec = sources.get(domain, {"enabled": False})
        if not spec.get("enabled", False):
            continue
        entries = spec.get("sources") or [dict(spec, path=p) for p in spec.get("paths", [spec.get("path")])]
        if not entries:
            entries = [{"path": None}]
        for entry in entries:
            yield domain, spec | entry


def preflight(root, sources, settings):
    dirs = {k: output_path(root, settings["directories"][k]) for k in ("staging", "canonical", "outputs")}
    protected = [root / p for p in ("data/raw", "data/reference", "data/samples", "config", "src", "scripts", "tests", "schemas", "templates", "docs", ".git", ".venv")]
    for path in dirs.values():
        for item in protected:
            item = item.resolve()
            if path.is_relative_to(item) or item.is_relative_to(path):
                raise ValueError("Output overlaps a protected input/code directory")
        for other in dirs.values():
            if path != other and (path.is_relative_to(other) or other.is_relative_to(path)):
                raise ValueError("Output directories must be disjoint")
    if len(set(dirs.values())) != 3:
        raise ValueError("Output directories must be distinct")
    for _, spec in source_specs(sources):
        if spec.get("path"):
            source = resolve_input(root, spec["path"])
            if any(source.is_relative_to(p) for p in dirs.values()):
                raise ValueError("An input cannot be inside an output directory")
    return dirs


def run(root, sources_path="config/sources.yaml", settings_path="config/layer1.yaml"):
    root = Path(root).resolve()
    run_id = "run_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    logger = get_logger()
    manifest = {"run_id": run_id, "pipeline_version": "1.0.0", "started_at": now(), "finished_at": None,
                "status": "RUNNING", "input_files": [], "records_read": {}, "records_staged": {},
                "records_accepted": {}, "records_rejected": {}, "records_canonical": {},
                "anomalies": {}, "output_files": []}
    events, rejected, batches = [], [], []
    datasets = {d: [] for d in FIELDS}
    dirs = {"outputs": root / "outputs/layer1", "staging": root / "data/staging", "canonical": root / "data/canonical"}
    lock = root / ".layer1.lock"
    acquired = False
    settings = {}
    try:
        with lock.open("x", encoding="utf-8") as stream:
            stream.write(run_id)
        acquired = True
        sources_file, settings_file = resolve_input(root, sources_path), resolve_input(root, settings_path)
        sources, settings = read_config(sources_file), read_config(settings_file)
        dirs = preflight(root, sources, settings)
        manifest["configuration"] = {"sources": str(sources_file), "sources_sha256": file_hash(sources_file),
                                     "settings": str(settings_file), "settings_sha256": file_hash(settings_file)}
        manifest["runtime"] = {p: importlib.metadata.version(p) for p in ("pandas", "numpy", "pyarrow", "openpyxl", "PyYAML", "jsonschema")}
        manifest["code_hashes"] = {str(p.relative_to(root)): file_hash(p) for p in sorted((root / "src").rglob("*.py"))}
        manifest["enabled_domains"] = {d: sources.get(d, {}).get("enabled", False) for d in DOMAINS}
        for directory in dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
        logger.info("[1/7] INGEST")
        seen_sources = set()
        for domain, spec in source_specs(sources):
            if not spec.get("path"):
                events.append(anomaly(run_id, domain, "", "FILE_NOT_FOUND", "CRITICAL", "Enabled domain has no configured source path"))
                continue
            path = resolve_input(root, spec["path"])
            key = (domain, str(path), spec.get("sheet"))
            if key in seen_sources:
                events.append(anomaly(run_id, domain, path, "DUPLICATE_SOURCE_CONFIG", "CRITICAL", "Same input configured more than once"))
                continue
            seen_sources.add(key)
            rows, issues, meta = ingest(path, domain, spec, settings, run_id)
            events.extend(issues)
            manifest["input_files"].append(meta)
            batches.append((domain, spec, rows, meta))
        if not batches:
            events.append(anomaly(run_id, "pipeline", "", "NO_SOURCES", "CRITICAL", "No enabled input sources"))
        logger.info("[2/7] VALIDATION")
        for domain, spec, rows, meta in batches:
            events.extend(validate_columns(meta["headers"], spec, domain, settings, run_id, meta["path"]))
            for section in ("researcher_mapping",):
                if spec.get(section):
                    events.extend(validate_columns(meta["headers"], {"mapping": spec[section]}, "optional",
                                                   settings, run_id, meta["path"]))
            for org in spec.get("organizations", []):
                if header(org["column"]) not in meta["headers"]:
                    events.append(anomaly(run_id, domain, meta["path"], "MISSING_REQUIRED_COLUMN", "CRITICAL",
                                          "Configured organization column missing"))
        logger.info("[3/7] STAGING")
        normalized = {d: [] for d in DOMAINS}
        for domain, spec, rows, meta in batches:
            mapped = map_rows(rows, spec)
            staging_dir = dirs["staging"] / domain / run_id
            staging_dir.mkdir(parents=True, exist_ok=True)
            staged = [{"source_row": r["_row"], "record_source": r["_file"], "etl_run_id": run_id,
                       "original_values_json": json.dumps(r["_raw"], ensure_ascii=False, default=str),
                       "interpreted_values_json": json.dumps({k: text(v, settings["normalization"]) for k, v in r.items() if not k.startswith("_")}, ensure_ascii=False),
                       "field_mapping_json": json.dumps(spec.get("mapping", {}), ensure_ascii=False)}
                      for r in mapped]
            stage_schema = pa.schema([("source_row", pa.int64()), ("record_source", pa.string()), ("etl_run_id", pa.string()),
                                      ("original_values_json", pa.string()), ("interpreted_values_json", pa.string()),
                                      ("field_mapping_json", pa.string())])
            destination = staging_dir / (stable_hash(meta["path"], spec.get("sheet")) + ".parquet")
            pq.write_table(pa.Table.from_pylist(staged, schema=stage_schema), destination)
            manifest["output_files"].append(str(destination))
            normalized[domain].extend(normalize_record(r, settings["normalization"]) for r in mapped)
        logger.info("[4/7] NORMALIZATION")
        manifest["source_quality"] = {}
        for domain, rows in normalized.items():
            required = settings["validation"]["required_fields"].get(domain, [])
            manifest["source_quality"][domain] = {
                "missing_required_fields": {f: sum(not text(r.get(f)) for r in rows) for f in required},
                "missing_by_field": {f: sum(r.get(f) is None for r in rows) for f in RELEVANT[domain]},
            }
        valid = {}
        for domain, rows in normalized.items():
            good, bad, issues = validate_rows(rows, domain, settings, run_id)
            valid[domain] = good
            rejected.extend(bad)
            events.extend(issues)
        for domain in ("proyectos", "articulos", "indicadores"):
            table, valid[domain], bad, issues = canonical_entities(valid[domain], domain, run_id)
            datasets[domain] = table
            rejected.extend(bad)
            events.extend(issues)
        issues, manifest["project_title_enrichment"] = enrich_project_titles(
            datasets["proyectos"], normalized["investigadores"], run_id)
        events.extend(issues)
        logger.info("[5/7] IDENTITY RESOLUTION")
        candidates = []
        for row in valid["investigadores"]:
            row["_candidate_domain"] = "investigadores"
            candidates.append(row)
        embedded_rejected = 0
        for domain in ("proyectos", "articulos"):
            for row in valid[domain]:
                mapping = row["_spec"].get("researcher_mapping")
                if not mapping:
                    continue
                candidate = mapped_values(row["_parsed"], mapping)
                if not any(text(v) for v in candidate.values()):
                    continue
                candidate.update({k: v for k, v in row.items() if k.startswith("_")})
                candidate["_mapping"] = mapping
                candidate["_candidate_domain"] = domain
                candidate = normalize_record(candidate, settings["normalization"])
                if domain == "proyectos":
                    candidate["source_project_id"] = row["source_project_id"]
                good, bad, issues = validate_rows([candidate], "investigadores", settings, run_id)
                candidates.extend(good)
                embedded_rejected += len(bad)
                events.extend(issues)
        entities, assignments, issues = resolve(candidates, run_id)
        events.extend(issues)
        datasets["investigadores"] = canonical_researchers(entities, run_id)
        manifest["identity_candidates"] = len(candidates)
        manifest["identity_resolution"] = {
            "rules": dict(Counter(e["identity_rule"] for e in entities)),
            "conflict_occurrences_by_field": dict(Counter(f for e in entities for f in e["_conflict_fields"])),
            "resolved_entities": sum(e["identity_status"] == "resolved" for e in entities),
            "safe_merged_occurrences": sum(len(e["_members"]) - 1 for e in entities if e["identity_status"] == "resolved"),
        }
        manifest["invalid_embedded_identities"] = embedded_rejected
        logger.info("[6/7] CANONICALIZATION")
        datasets["organizaciones"] = organizations([r for rows in valid.values() for r in rows], run_id)
        relations, issues = relationships(candidates, assignments,
                                         {r["project_id"] for r in datasets["proyectos"]},
                                         {r["article_id"] for r in datasets["articulos"]}, run_id)
        datasets.update(relations)
        events.extend(issues)
        for domain, rows in datasets.items():
            validator = Draft202012Validator(logical_schema(domain), format_checker=FormatChecker())
            seen_keys = set()
            for row in rows:
                validator.validate(row)
                key = tuple(row.get(k) for k in KEYS[domain])
                if key in seen_keys:
                    raise ValueError("Duplicate canonical key")
                seen_keys.add(key)
        for meta in manifest["input_files"]:
            path = Path(meta["path"])
            if meta["sha256"] and (not path.is_file() or file_hash(path) != meta["sha256"]):
                events.append(anomaly(run_id, meta["domain"], path, "INPUT_CHANGED", "CRITICAL", "Source changed during processing"))
        manifest["raw_unchanged"] = not any(e["anomaly_code"] == "INPUT_CHANGED" for e in events)
    except FileExistsError:
        if not acquired:
            logger.error("Another run holds .layer1.lock; no outputs changed")
            return manifest | {"status": "FAILED", "failure": "Concurrent run"}
        events.append(anomaly(run_id, "pipeline", "", "PIPELINE_FAILURE", "CRITICAL", "Output already exists"))
    except Exception as exc:
        events.append(anomaly(run_id, "pipeline", "", "PIPELINE_FAILURE", "CRITICAL", "Pipeline failed: " + type(exc).__name__))
        logger.error("Pipeline failed (%s); see local audit", type(exc).__name__)
    published = False
    previous = None
    run_dir = dirs["outputs"] / "runs" / run_id
    try:
        logger.info("[7/7] QUALITY + AUDIT")
        overrides = settings.get("errors", {}).get("severity_overrides", {})
        for event in events:
            requested = overrides.get(event["anomaly_code"])
            if requested in ("INFO", "WARNING", "ERROR", "CRITICAL") and event["severity"] != "CRITICAL":
                event["severity"] = requested
        maximum = settings.get("errors", {}).get("max_anomalies")
        failed = any(e["severity"] == "CRITICAL" for e in events)
        failed |= settings.get("errors", {}).get("fail_on_error", False) and any(e["severity"] == "ERROR" for e in events)
        failed |= maximum is not None and len(events) > maximum
        manifest["status"] = "FAILED" if failed else "SUCCESS"
        for domain in DOMAINS:
            meta_rows = [m for m in manifest["input_files"] if m["domain"] == domain]
            read = sum(m["records_read"] for m in meta_rows)
            staged = sum(m["records_parsed"] for m in meta_rows)
            rejected_keys = {(r["_file"], r["_row"]) for r in rejected
                             if any(r["_file"] == m["path"] for m in meta_rows)}
            structural = {(e["source_file"], e["source_row"]) for e in events if e["domain"] == domain
                          and e["anomaly_code"] in {"INVALID_COLUMN_COUNT", "EMPTY_RECORD", "MALFORMED_ROW"} and e["source_row"] is not None}
            rejected_count = len(rejected_keys | structural)
            manifest["records_read"][domain] = read
            manifest["records_staged"][domain] = staged
            manifest["records_rejected"][domain] = rejected_count
            manifest["records_accepted"][domain] = read - rejected_count
        run_dir = dirs["outputs"] / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        candidate_dir = run_dir / "canonical"
        candidate_dir.mkdir()
        if not failed:
            for domain, rows in datasets.items():
                write_parquet(candidate_dir / (domain + ".parquet"), rows, domain)
            manifest["records_canonical"] = {d: len(r) for d, r in datasets.items()}
            manifest["canonical_files"] = {d: {"rows": len(rows), "columns": len(FIELDS[d]) + 5,
                                              "sha256": file_hash(candidate_dir / (d + ".parquet"))}
                                           for d, rows in datasets.items()}
            manifest["output_files"].extend(str(dirs["canonical"] / (d + ".parquet")) for d in datasets)
        manifest["anomalies"] = dict(Counter(e["anomaly_code"] for e in events))
        manifest["finished_at"] = now()
        write_quality(run_dir, datasets, events, manifest, rejected)
        if not failed:
            (candidate_dir / ".gitkeep").touch()
            (candidate_dir / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            previous = run_dir / "previous_canonical"
            if dirs["canonical"].exists():
                dirs["canonical"].rename(previous)
            try:
                candidate_dir.rename(dirs["canonical"])
                published = True
            except Exception:
                if previous.exists():
                    previous.rename(dirs["canonical"])
                raise
        for kind in ("audit", "quality"):
            shutil.copytree(run_dir / kind, dirs["outputs"] / kind, dirs_exist_ok=True)
        manifests = dirs["outputs"] / "manifests"
        manifests.mkdir(parents=True, exist_ok=True)
        manifest["output_files"].extend(str(p) for kind in ("audit", "quality") for p in (run_dir / kind).iterdir())
        manifest["output_files"].append(str(manifests / (run_id + ".json")))
        serialized = json.dumps(manifest, ensure_ascii=False, indent=2)
        (manifests / (run_id + ".json")).write_text(serialized, encoding="utf-8")
        (dirs["outputs"] / "latest_run.json").write_text(serialized, encoding="utf-8")
        if published:
            (dirs["canonical"] / "_manifest.json").write_text(serialized, encoding="utf-8")
        logger.info("status=%s read=%s canonical=%s anomalies=%s", manifest["status"],
                    sum(manifest["records_read"].values()), sum(len(r) for r in datasets.values()), len(events))
        return manifest
    except Exception as exc:
        if published:
            dirs["canonical"].rename(run_dir / "failed_canonical")
            if previous is not None and previous.exists():
                previous.rename(dirs["canonical"])
        manifest["status"] = "FAILED"
        manifest["finished_at"] = now()
        manifest["records_canonical"] = {}
        events.append(anomaly(run_id, "pipeline", "", "PUBLICATION_FAILURE", "CRITICAL",
                              "Output publication failed: " + type(exc).__name__))
        manifest["anomalies"] = dict(Counter(e["anomaly_code"] for e in events))
        # Best effort if the filesystem itself failed: never claim successful publication.
        try:
            manifests = dirs["outputs"] / "manifests"
            manifests.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(manifest, ensure_ascii=False, indent=2)
            (manifests / (run_id + ".json")).write_text(serialized, encoding="utf-8")
            (dirs["outputs"] / "latest_run.json").write_text(serialized, encoding="utf-8")
            write_csv(dirs["outputs"] / "audit/anomalies.csv", events, ANOMALY_COLUMNS)
        except OSError:
            logger.error("Cannot persist failure audit: output filesystem unavailable")
        logger.error("Publication failed (%s)", type(exc).__name__)
        return manifest
    finally:
        if acquired:
            lock.unlink(missing_ok=True)
