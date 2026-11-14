"""Strict source parsing, explicit column mapping and row validation before canonicalization."""

import csv
import io
from pathlib import Path
from openpyxl import load_workbook
from .normalize import header, text
from .provenance import anomaly, file_hash, now
import re
from collections import Counter
from .normalize import date_value, header, identifier, text
from .provenance import anomaly



# Strict parsing. Every rejected row leaves an audit event.
def ingest(path, domain, spec, settings, run_id):
    path = Path(path)
    rows, events = [], []
    meta = {"name": path.name, "path": str(path), "domain": domain, "processed_at": now(),
            "size": None, "sha256": None, "records_read": 0, "records_parsed": 0, "headers": []}
    meta["sheet"] = spec.get("sheet")

    def issue(code, severity, description, row=None):
        events.append(anomaly(run_id, domain, path, code, severity, description, row))

    if not path.is_file():
        issue("FILE_NOT_FOUND", "CRITICAL", "Configured source does not exist")
        return rows, events, meta
    meta.update(size=path.stat().st_size, sha256=file_hash(path))
    if not meta["size"]:
        issue("EMPTY_FILE", "CRITICAL", "Source has zero bytes")
        return rows, events, meta
    book = None
    try:
        if spec.get("type", path.suffix.lstrip(".")) == "xlsx":
            book = load_workbook(path, read_only=True, data_only=False)
            if spec.get("sheet") not in book.sheetnames:
                issue("MISSING_REQUIRED_SHEET", "CRITICAL", "Configured worksheet is absent")
                return rows, events, meta
            values = iter(book[spec["sheet"]].values)
            headers = list(next(values, []))
            parsed = ((i, list(row)) for i, row in enumerate(values, 2))
        else:
            raw = path.read_bytes()
            decoded = None
            encodings = [spec["encoding"]] if spec.get("encoding") else settings["encodings"]
            for encoding in encodings:
                try:
                    decoded = raw.decode(encoding, errors="strict")
                    meta["encoding"] = encoding
                    if encoding != encodings[0]:
                        issue("ENCODING_FALLBACK", "WARNING", "Used configured fallback encoding")
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            if decoded is None or "\x00" in decoded:
                issue("INVALID_ENCODING", "CRITICAL", "Cannot decode using configured encodings")
                return rows, events, meta
            if not decoded.strip():
                issue("EMPTY_FILE", "CRITICAL", "Source contains only whitespace")
                return rows, events, meta
            delimiter = spec.get("delimiter")
            if not delimiter:
                try:
                    delimiter = csv.Sniffer().sniff(decoded.splitlines()[0], delimiters="".join(settings["delimiters"])).delimiter
                except csv.Error:
                    issue("INVALID_DELIMITER", "CRITICAL", "No supported delimiter detected")
                    return rows, events, meta
            if delimiter not in settings["delimiters"]:
                issue("INVALID_DELIMITER", "CRITICAL", "Delimiter is not allowed")
                return rows, events, meta
            meta["delimiter"] = delimiter
            csv.field_size_limit(10_000_000)
            reader = csv.reader(io.StringIO(decoded, newline=""), delimiter=delimiter, strict=True)
            headers = next(reader, [])
            if len(headers) == 1 and any(d in headers[0] for d in settings["delimiters"] if d != delimiter):
                issue("INVALID_DELIMITER", "CRITICAL", "Header does not match configured delimiter")
                return rows, events, meta

            def csv_rows():
                while True:
                    start = reader.line_num + 1
                    try:
                        row = next(reader)
                    except StopIteration:
                        break
                    except csv.Error:
                        meta["records_read"] += 1
                        issue("MALFORMED_ROW", "CRITICAL", "CSV quoting error; remaining boundaries cannot be trusted", start)
                        break
                    yield start, row
            parsed = csv_rows()
        normalized_headers = [header(h) for h in headers]
        meta["headers"] = normalized_headers
        meta["original_headers"] = headers
        if not headers or any(not h for h in normalized_headers) or len(set(normalized_headers)) != len(headers):
            issue("DUPLICATE_HEADER", "CRITICAL", "Empty or duplicate normalized headers")
        else:
            for row_no, values in parsed:
                meta["records_read"] += 1
                if not values:
                    issue("EMPTY_RECORD", "ERROR", "Empty physical record", row_no)
                    continue
                if len(values) != len(headers):
                    issue("INVALID_COLUMN_COUNT", "ERROR", "Row width differs from header width", row_no)
                    continue
                if not any(text(v, settings.get("normalization")) is not None for v in values):
                    issue("EMPTY_RECORD", "ERROR", "Record contains no data", row_no)
                    continue
                if spec.get("type") == "xlsx" and any(isinstance(v, str) and v.startswith("=") for v in values):
                    issue("MALFORMED_ROW", "ERROR", "Formula cells are not accepted as reference data", row_no)
                    continue
                row = dict(zip(normalized_headers, values))
                row.update(_raw={str(k): v for k, v in zip(headers, values)}, _file=str(path), _row=row_no, _sheet=spec.get("sheet"))
                rows.append(row)
        if meta["records_read"] == 0:
            issue("EMPTY_FILE", "CRITICAL", "Source contains no data records")
    except (OSError, ValueError, csv.Error, KeyError) as exc:
        issue("MALFORMED_ROW", "CRITICAL", "Source parsing failed: " + type(exc).__name__)
    finally:
        if book is not None:
            book.close()
    meta["records_parsed"] = len(rows)
    return rows, events, meta

# Validate configured columns, map fields and validate parsed rows before canonicalization.
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
    if domain=='articulos' and spec.get('base_record_policy')=='BASE_VALID_ROWS_V1':
        required=[f for f in required if f!='title']
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
        official = domain == 'proyectos' and row.get('_spec', {}).get('project_contract')
        source_id = row.get(id_field) if official else identifier(row.get(id_field))
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
            if domain=='articulos' and field=='title' and row.get('_spec',{}).get('base_record_policy')=='BASE_VALID_ROWS_V1':
                continue  # BASE adapter already checked a trusted publication identifier.
            if official and field == 'source_project_id':
                continue
            if not text(row.get(field)):
                issue("MISSING_REQUIRED_FIELD", "ERROR", "Required field is empty: " + field)
        if not official and text(row.get(id_field)):
            key = identifier(row[id_field])
            seen[key] += 1
            if counts[key] > 1 and seen[key] > 1:
                issue("DUPLICATE_SOURCE_ID", "WARNING", "Repeated source identifier; consolidate with complete provenance")
        for field in ("source_project_id", "source_article_id", "institutional_id", "document_number", "external_id", "indicator_id"):
            if official and field == 'source_project_id':
                continue
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
