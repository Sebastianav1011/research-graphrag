"""Order-independent identity resolution with conflict blocking at component level."""
from collections import defaultdict
from .normalize import name, stable_hash
from .provenance import anomaly

STRONG = ("institutional_id", "document_number", "external_id")


def evidence_values(row, field):
    return row.get("_identity_values", {}).get(field, [row[field]] if row.get(field) else [])


def resolve(records, run_id):
    """Exact institutional ID, then document, then external ID/name+email.

    Institutional and personal document namespaces never intersect. All evidence
    in a connected component must agree before any merge, including aliases in
    the same row. Names alone only flag ambiguity; they never create edges.
    Lowercase states retain the existing canonical contract.
    """
    parent = list(range(len(records)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)

    tokens, names = {}, defaultdict(list)
    for i, row in enumerate(records):
        normalized = row.get("normalized_name") or name(row.get("full_name"))
        row["normalized_name"] = normalized
        if normalized:
            names[normalized].append(i)
        keys = [(f, value) for f in STRONG for value in evidence_values(row, f)]
        if normalized and row.get("email"):
            keys.append(("name_email", (normalized, row["email"])))
        for key in keys:
            if key in tokens:
                union(i, tokens[key])
            else:
                tokens[key] = i
    groups = defaultdict(list)
    for i in range(len(records)):
        groups[find(i)].append(i)
    events, entities, assignments = [], [], {}
    for indices in groups.values():
        members = [records[i] for i in indices]
        values = {f: sorted({v for r in members for v in evidence_values(r, f)}) for f in (*STRONG, "document_type")}
        conflict = any(len(v) > 1 for v in values.values())
        anchor = next(((f, values[f][0]) for f in STRONG if values[f]), None)
        weak = next(((r["normalized_name"], r["email"]) for r in members if r.get("normalized_name") and r.get("email")), None)
        repeated_name = any(len(names[r["normalized_name"]]) > 1 for r in members if r.get("normalized_name"))
        if conflict:
            status, rule = "ambiguous", "conflicting_identifiers"
        elif anchor:
            status, rule = "resolved", "exact_" + anchor[0]
        elif weak:
            status, rule = "resolved", "exact_name_and_email"
        elif repeated_name:
            status, rule = "ambiguous", "name_without_corroboration"
        else:
            status, rule = "unresolved", "insufficient_identifiers"
        partitions = [members] if status == "resolved" else [[r] for r in members]
        for partition in partitions:
            first = sorted(partition, key=lambda r: (r["_file"], r["_row"]))[0]
            seed = anchor or ("name_email", weak)
            if status != "resolved":
                seed = ("source_occurrence", first["_file"], first.get("_sheet"), first["_row"], first["_raw"])
            rid = "RES_" + stable_hash(seed)
            entity = {"researcher_id": rid, "identity_status": status, "identity_rule": rule, "_members": partition, "_conflict_fields": sorted(f for f, v in values.items() if len(v) > 1)}
            for field in (*STRONG, "document_type", "full_name", "normalized_name", "email"):
                available = sorted({str(r[field]) for r in partition if r.get(field)})
                entity[field] = available[0] if available else None
            entities.append(entity)
            for r in partition:
                assignments[(r["_file"], r.get("_sheet"), r["_row"], r.get("_candidate_domain", "investigadores"))] = rid
                if status != "resolved":
                    events.append(anomaly(run_id, "investigadores", r["_file"],
                                          "IDENTITY_AMBIGUOUS" if status == "ambiguous" else "IDENTITY_UNRESOLVED",
                                          "WARNING", rule + ("; incompatible fields: " + ", ".join(entity["_conflict_fields"]) if conflict else ""), r["_row"], rid))
    return sorted(entities, key=lambda r: r["researcher_id"]), assignments, events
