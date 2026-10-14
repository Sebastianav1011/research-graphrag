import re
from collections import Counter
from .normalize import date_value, header, identifier, text
from .provenance import anomaly

ID_FIELDS = {"proyectos": "source_project_id", "articulos": "source_article_id",
             "investigadores": "institutional_id", "indicadores": "indicator_id"}


def source_columns(value):
    return value if isinstance(value, list) else [value]


def mapped_values(original, mapping):
    # Lists are explicitly declared aliases, never guessed from column names.
    return {dest: original.get(header(source_columns(src)[0])) for dest, src in mapping.items()}


def map_rows(rows, spec):
    mapping = spec.get("mapping", {})
    result = []
    for original in rows:
        row = mapped_values(original, mapping)
        row.update({k: v for k, v in original.items() if k.startswith("_")})
        row["_mapping"] = mapping
        row["_spec"] = spec
        row["_parsed"] = {k: v for k, v in original.items() if not k.startswith("_")}
        result.append(row)
    return result


def validate_columns(headers, spec, domain, settings, run_id, path):
    mapping = spec.get("mapping", {})
    required = settings["validation"]["required_columns"].get(domain, [])
    missing = [field for field in required if not any(header(c) in headers for c in source_columns(mapping.get(field, "")))]
    # Explicit configured mappings may not silently disappear.
    absent = [dest for dest, src in mapping.items() if not source_columns(src) or
              any(header(c) not in headers for c in source_columns(src))]
    if any(isinstance(src, list) and dest not in {"institutional_id", "document_number"}
           for dest, src in mapping.items()):
        raise ValueError("Alias lists are restricted to personal institutional/document identifiers")
    fields = sorted(set(missing + absent))
    if fields:
        return [anomaly(run_id, domain, path, "MISSING_REQUIRED_COLUMN", "CRITICAL",
                        "Missing configured columns for: " + ", ".join(fields))]
    return []


def validate_rows(rows, domain, settings, run_id):
    events, accepted, rejected = [], [], []
    id_field = ID_FIELDS[domain]
    counts = Counter(identifier(r.get(id_field)) for r in rows if text(r.get(id_field)))
    seen = Counter()
    for row in rows:
        source_id = identifier(row.get(id_field))
        if domain == "articulos":
            source_id = source_id or row.get("eid") or row.get("doi")
        row["_source_id"] = source_id
        invalid = False

        def issue(code, severity, description):
            nonlocal invalid
            if severity in ("ERROR", "CRITICAL"):
                invalid = True
            events.append(anomaly(run_id, domain, row["_file"], code, severity, description,
                                  row["_row"], None if domain == "investigadores" else source_id))

        for field in settings["validation"]["required_fields"].get(domain, []):
            if not text(row.get(field)):
                issue("MISSING_REQUIRED_FIELD", "ERROR", "Required field is empty: " + field)
        if text(row.get(id_field)):
            key = identifier(row[id_field])
            seen[key] += 1
            if counts[key] > 1 and seen[key] > 1:
                issue("DUPLICATE_SOURCE_ID", "WARNING", "Repeated source identifier; consolidate with complete provenance")
        for field in ("source_project_id", "source_article_id", "institutional_id", "document_number", "external_id", "indicator_id"):
            values = row.get("_identity_values", {}).get(field, [row.get(field)])
            if any(value and (not re.fullmatch(r"[\w.:/-]+", str(value)) or str(value).casefold() in {"nan", "none", "null"}) for value in values):
                issue("INVALID_IDENTIFIER", "ERROR", "Invalid structured identifier in " + field)
        for field, pattern in (("doi", r"10\.\d{4,9}/\S+"), ("eid", r"2-s2\.0-\d+"),
                               ("email", r"[^\s@]+@[^\s@]+\.[^\s@]+"),
                               ("issn_isbn", r"(?:\d{7}[\dX]|\d{9}[\dX]|\d{13})")):
            if row.get(field) and not re.fullmatch(pattern, row[field], re.I):
                issue("INVALID_IDENTIFIER", "WARNING", "Invalid optional identifier excluded from canonical: " + field)
                row[field] = None
        for field in ("start_date", "end_date"):
            if row.get(field):
                try:
                    row[field] = date_value(row[field], settings["normalization"].get("date_formats"))
                except ValueError:
                    issue("INVALID_DATE", "ERROR", "Invalid date in " + field)
        if row.get("start_date") and row.get("end_date") and row["start_date"] > row["end_date"]:
            issue("IMPOSSIBLE_VALUE", "ERROR", "End date precedes start date")
        if row.get("publication_year"):
            try:
                year = int(row["publication_year"])
                if not settings["validation"]["year_min"] <= year <= settings["validation"]["year_max"]:
                    issue("IMPOSSIBLE_VALUE", "ERROR", "Year outside configured range")
                row["publication_year"] = year
            except (ValueError, TypeError):
                issue("INVALID_TYPE", "ERROR", "Publication year must be an integer")
        for field in ("author_position",):
            if row.get(field):
                try:
                    row[field] = int(row[field])
                    if row[field] < 1:
                        issue("IMPOSSIBLE_VALUE", "ERROR", field + " must be positive")
                except (ValueError, TypeError):
                    issue("INVALID_TYPE", "ERROR", field + " must be an integer")
        if row.get("is_responsible") is not None:
            value = str(row["is_responsible"]).casefold()
            options = {"si": True, "sí": True, "true": True, "1": True, "no": False, "false": False, "0": False}
            if value not in options:
                issue("INVALID_TYPE", "WARNING", "Unrecognized boolean excluded: is_responsible")
            row["is_responsible"] = options.get(value)
        (rejected if invalid else accepted).append(row)
    return accepted, rejected, events

