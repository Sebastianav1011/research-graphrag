"""Strict parsing. Every rejected row leaves an audit event."""
import csv
import io
from pathlib import Path
from openpyxl import load_workbook
from .normalize import header, text
from .provenance import anomaly, file_hash, now


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
