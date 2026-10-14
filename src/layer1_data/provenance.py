import hashlib
import json
from datetime import datetime, timezone

ANOMALY_COLUMNS = ["etl_run_id", "domain", "source_file", "source_row",
                   "source_object_id", "anomaly_code", "severity", "description"]


def now():
    return datetime.now(timezone.utc).isoformat()


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def anomaly(run_id, domain, path, code, severity, description, row=None, source_id=None):
    return dict(zip(ANOMALY_COLUMNS, [run_id, domain, str(path), row, source_id, code, severity, description]))


def reference(record):
    return {
        "record_source": record["_file"], "source_row": record["_row"],
        "source_record_id": record.get("_source_id"),
        "original_values": record["_raw"], "field_mapping": record.get("_mapping", {}),
        "source_sheet": record.get("_sheet"),
    }


def provenance(records, run_id):
    refs = sorted([reference(r) for r in records], key=lambda r: (r["record_source"], r["source_row"]))
    first = refs[0]
    return {
        "record_source": first["record_source"], "source_row": first["source_row"],
        "source_record_id": first["source_record_id"], "etl_run_id": run_id,
        "provenance_json": json.dumps(refs, ensure_ascii=False, sort_keys=True, default=str),
    }

