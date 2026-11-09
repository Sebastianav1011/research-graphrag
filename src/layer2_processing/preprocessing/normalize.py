"""Pure normalizers: no enrichment, inference, or network access."""
import hashlib
import json
import re
import unicodedata
from datetime import datetime
from urllib.parse import unquote


def text(value, options=None):
    options = options or {}
    if value is None:
        return None
    value = unicodedata.normalize(options.get("unicode_form", "NFC"), str(value))
    value = "".join(c for c in value if unicodedata.category(c) != "Cf")
    value = re.sub(r"\s+", " ", value).strip()
    return None if value in options.get("null_tokens", ["", "NULL", "null", "N/A", "n/a"]) else value


def name(value):
    value = text(value)
    return value.casefold() if value else None


def header(value):
    value = unicodedata.normalize("NFKD", text(value) or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def identifier(value):
    value = text(value)
    return re.sub(r"^(\d+)\.0$", r"\1", value) if value else None


def doi(value):
    value = text(value)
    if not value:
        return None
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", "", value, flags=re.I)
    return unquote(value).casefold().strip()


def eid(value):
    value = identifier(value)
    return re.sub(r"^https?://[^?]+\?eid=", "", value).split("&")[0] if value else None


def issn_isbn(value):
    value = text(value)
    return re.sub(r"[\s-]+", "", value).upper() if value else None


def email(value):
    return name(value)


def date_value(value, formats=None):
    value = text(value)
    if not value:
        return None
    formats = formats or ["%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"]
    for fmt in dict.fromkeys(["%Y-%m-%d", *formats]):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError("Invalid calendar date")


def keywords(value, separator=";"):
    value = text(value)
    return list(dict.fromkeys(filter(None, (text(v) for v in value.split(separator))))) if value else None


def stable_hash(*parts):
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def normalize_record(record, options):
    result = {k: text(v, options) for k, v in record.items() if not k.startswith("_")}
    for field in record.get("_spec", {}).get("unwrap_quoted_fields", []):
        value = result.get(field)
        if value and len(value) >= 2 and value[0] == value[-1] == '"':
            result[field] = text(value[1:-1], options)
    for field in ("institutional_id", "document_number", "external_id", "source_project_id", "source_article_id", "indicator_id"):
        if field in result:
            result[field] = (record[field] if field == 'source_project_id' and record.get('_spec', {}).get('project_contract')
                             else identifier(result[field]))
    for field, fn in (("doi", doi), ("eid", eid), ("issn_isbn", issn_isbn), ("email", email)):
        if field in result:
            result[field] = fn(result[field])
    if "full_name" in result:
        result["normalized_name"] = name(result["full_name"])
    if "keywords" in result:
        result["keywords"] = keywords(result["keywords"], options.get("keyword_separator", ";"))
    for field in ("start_date", "end_date"):
        if result.get(field):
            try:
                result[field] = date_value(result[field], options.get("date_formats"))
            except ValueError:
                pass
    result.update({k: v for k, v in record.items() if k.startswith("_")})
    # Preserve all normalized alias evidence, including contradictions in one row.
    alias_values = {}
    for field in ("institutional_id", "document_number"):
        sources = record.get("_mapping", {}).get(field)
        if not isinstance(sources, list):
            continue
        values = []
        for source in sources:
            value = text(record.get("_parsed", {}).get(header(source)), options)
            if field in record.get("_spec", {}).get("unwrap_quoted_fields", []):
                if value and len(value) >= 2 and value[0] == value[-1] == '"':
                    value = text(value[1:-1], options)
            value = identifier(value)
            if value is not None:
                values.append(value)
        alias_values[field] = sorted(set(values))
        result[field] = alias_values[field][0] if len(alias_values[field]) == 1 else None
    if alias_values:
        result["_identity_values"] = alias_values
    return result
