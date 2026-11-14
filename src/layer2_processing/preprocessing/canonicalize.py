import json
from collections import defaultdict
from urllib.parse import quote
import pyarrow as pa
import pyarrow.parquet as pq
from .contracts import fields, arrow_schema
from .normalize import header, name, stable_hash, text
from .provenance import anomaly, provenance, reference


def entity_id(domain, row):
    if domain == "proyectos":
        return "PROJ_" + quote(row["source_project_id"], safe="")
    if domain == "indicadores":
        return row["indicator_id"]
    if row.get("source_article_id"):
        return "ART_SRC_" + quote(row["source_article_id"], safe="")
    if row.get("eid"):
        return "ART_" + row["eid"]
    if row.get("doi"):
        return "ART_DOI_" + stable_hash(row["doi"])
    # No guessed equivalence based on title alone: full original occurrence content.
    spec = row.get("_spec", {})
    return "ART_HASH_" + stable_hash(spec.get("identity_source", row["_file"]),
                                    spec.get("identity_sheet", row.get("_sheet")), row["_raw"])


def canonical_entities(rows, domain, run_id):
    groups = defaultdict(list)
    for row in rows:
        groups[entity_id(domain, row)].append(row)
    key = {"proyectos": "project_id", "articulos": "article_id", "indicadores": "indicator_id"}[domain]
    result, events, rejected, accepted = [], [], [], []
    for cid, members in sorted(groups.items()):
        # Conflicting title/year under one trusted key is quarantined as a group.
        critical_fields = {"articulos": ["title", "publication_year"],
                           "proyectos": ["title"], "indicadores": ["indicator_name"]}[domain]
        conflict = any(len({name(r[f]) for r in members if r.get(f) is not None}) > 1 for f in critical_fields)
        if conflict:
            rejected.extend(members)
            for row in members:
                events.append(anomaly(run_id, domain, row["_file"], "CONFLICTING_SOURCE_ID", "ERROR",
                                      "One source ID refers to conflicting core values; group quarantined",
                                      row["_row"], cid))
            continue
        output = {f: None for f in fields(domain)}
        output[key] = cid
        ordered = sorted(members, key=lambda r: (r["_file"], r["_row"]))
        for f in fields(domain):
            if f == key:
                continue
            available = [r[f] for r in ordered if r.get(f) is not None]
            if available:
                output[f] = available[0]
                if len({json.dumps(v, ensure_ascii=False, sort_keys=True) for v in available}) > 1:
                    events.append(anomaly(run_id, domain, ordered[0]["_file"], "FIELD_CONFLICT", "WARNING",
                                          "Multiple values retained in provenance; representative uses first source row: " + f,
                                          ordered[0]["_row"], cid))
        output.update(provenance(ordered, run_id))
        for pos, row in enumerate(ordered):
            row["_canonical_id"] = cid
            accepted.append(row)
            if pos:
                events.append(anomaly(run_id, domain, row["_file"], "CANONICAL_DUPLICATE", "WARNING",
                                      "Repeated entity consolidated; all source occurrences retained", row["_row"], cid))
        result.append(output)
    return result, accepted, rejected, events


def enrich_project_titles(projects, members, run_id):
    """Join explicit project IDs; compare normalized text but publish original text."""
    import re
    groups = defaultdict(list)
    for row in members:
        pid = row.get("source_project_id")
        if pid and re.fullmatch(r"[\w.:/-]+", pid) and "project_title" in row.get("_mapping", {}):
            column = row["_mapping"]["project_title"]
            original = row["_parsed"].get(header(column))
            comparable = text(original)
            if comparable and len(comparable) >= 2 and comparable[0] == comparable[-1] == '"':
                comparable = text(comparable[1:-1])
            if comparable:
                groups[pid].append((row, original, comparable.casefold()))
    events = []
    enriched = conflicts = 0
    before = sum(p.get("title") is not None for p in projects)
    for project in projects:
        if project.get("title") is not None:
            continue
        candidates = sorted(groups.get(project["source_project_id"], []), key=lambda v: (v[0]["_file"], v[0].get("_sheet") or "", v[0]["_row"]))
        if not candidates:
            continue
        conflict = len({v[2] for v in candidates}) > 1
        refs = json.loads(project["provenance_json"])
        for row, original, _ in candidates:
            ref = reference(row)
            ref["field_mapping"] = {"title": row["_mapping"]["project_title"],
                                    "source_project_id": row["_mapping"]["source_project_id"]}
            ref["enrichment"] = {"field": "title", "join_key": "source_project_id",
                                 "join_value": project["source_project_id"],
                                 "status": "CONFLICT" if conflict else "CONSISTENT"}
            refs.append(ref)
        project["provenance_json"] = json.dumps(refs, ensure_ascii=False, sort_keys=True, default=str)
        if conflict:
            conflicts += 1
            events.append(anomaly(run_id, "proyectos", candidates[0][0]["_file"],
                                  "PROJECT_TITLE_CONFLICT", "WARNING",
                                  "Distinct member titles; title remains NULL: " + json.dumps(sorted({str(v[1]) for v in candidates}), ensure_ascii=False),
                                  candidates[0][0]["_row"], project["project_id"]))
        else:
            project["title"] = str(candidates[0][1])
            enriched += 1
    return events, {"with_title_before_enrichment": before, "titles_from_members": enriched,
                    "conflicts": conflicts, "without_title": sum(p.get("title") is None for p in projects)}


def canonical_researchers(entities, run_id):
    result = []
    for entity in entities:
        row = {f: entity.get(f) for f in fields("investigadores")}
        row.update(provenance(entity["_members"], run_id))
        result.append(row)
    return result


def organizations(rows, run_id):
    groups = defaultdict(list)
    attributes = {}
    for row in rows:
        for spec in row["_spec"].get("organizations", []):
            value = text(row["_parsed"].get(header(spec["column"])))
            if not value:
                continue
            parent = text(row["_parsed"].get(header(spec.get("parent_column", ""))))
            country = text(row["_parsed"].get(header(spec.get("country_column", ""))))
            oid = "ORG_" + stable_hash(spec["type"], name(value), name(parent), name(country))
            groups[oid].append(row)
            attributes[oid] = {"organization_id": oid, "organization_name": value,
                               "organization_name_normalized": name(value), "organization_type": spec["type"],
                               "parent_name": parent, "country": country}
    return [attributes[k] | provenance(groups[k], run_id) for k in sorted(groups)]


def relationships(candidates, assignments, projects, articles, run_id):
    tables = {"proyecto_investigador": defaultdict(list), "articulo_investigador": defaultdict(list)}
    events = []
    attributes = {}
    for row in candidates:
        domain = row["_candidate_domain"]
        rid = assignments[(row["_file"], row.get("_sheet"), row["_row"], domain)]
        target, value = None, None
        if row.get("source_project_id"):
            target = "proyecto_investigador"
            pid = "PROJ_" + quote(row["source_project_id"], safe="")
            if pid not in projects:
                events.append(anomaly(run_id, "investigadores", row["_file"], "ORPHAN_RELATION", "WARNING",
                                      "Explicit project membership points outside canonical project coverage",
                                      row["_row"], rid))
                continue
            value = {"project_id": pid, "researcher_id": rid, "role": row.get("role"),
                     "is_responsible": row.get("is_responsible")}
        elif domain == "articulos" and row.get("_canonical_id") in articles:
            target = "articulo_investigador"
            value = {"article_id": row["_canonical_id"], "researcher_id": rid,
                     "author_position": row.get("author_position"), "affiliation": row.get("affiliation")}
        if target:
            key = json.dumps(value, ensure_ascii=False, sort_keys=True)
            tables[target][key].append(row)
            attributes[key] = value
    return {t: [attributes[k] | provenance(groups[k], run_id) for k in sorted(groups)]
            for t, groups in tables.items()}, events


def write_parquet(path, rows, dataset):
    table = pa.Table.from_pylist(rows, schema=arrow_schema(dataset,
        allow_missing_title=dataset=='articulos' and any(r.get('title') is None for r in rows)))
    pq.write_table(table, path, compression="zstd")
