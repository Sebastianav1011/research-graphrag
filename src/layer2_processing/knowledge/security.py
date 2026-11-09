"""Explicit deny lists; corpus leakage findings never expose personal values."""
import re
import unicodedata

MANDATORY_SENSITIVE = {'document_number', 'cedula', 'documento', 'email', 'birth_date',
    'fecha_nacimiento', 'marital_status', 'estado_civil', 'sex', 'sexo'}
MANDATORY_TECHNICAL = {'doi', 'eid', 'issn', 'issn_isbn', 'institutional_id', 'project_id', 'article_id', 'researcher_id'}
EMAIL_PATTERN = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')


def apply_email_privacy(value, policy='reject'):
    """Explicit user-authorized substitution only; never persist removed addresses."""
    if policy != 'mask':
        return value, 0
    if isinstance(value, str):
        return EMAIL_PATTERN.subn('[EMAIL_EXCLUDED]', value)
    if isinstance(value, list):
        transformed, count = [], 0
        for item in value:
            masked, redactions = apply_email_privacy(item, policy)
            transformed.append(masked)
            count += redactions
        return transformed, count
    return value, 0


def field_key(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.casefold()) if not unicodedata.combining(c))


def excluded(field, config, corpus=True):
    denied = MANDATORY_SENSITIVE | {field_key(f) for f in config['excluded_sensitive_fields']}
    if corpus:
        denied |= MANDATORY_TECHNICAL | {field_key(f) for f in config.get('excluded_corpus_fields', [])}
    return field_key(field) in denied


def pii_matcher(datasets, config):
    from functools import lru_cache
    sensitive = set()
    for rows in datasets.values():
        for row in rows:
            for field, value in row.items():
                if excluded(field, config, corpus=False) and isinstance(value, str) and value.strip():
                    # Short demographic values cannot be identified reliably in scientific prose.
                    if field_key(field) in {'email', 'document_number', 'cedula', 'documento'}:
                        sensitive.add(value.strip())
    # Exact token membership avoids a huge alternation over all institutional documents.
    word_identifiers = {v.casefold() for v in sensitive if re.fullmatch(r'\w+', v)}
    unusual = sorted(v for v in sensitive if not re.fullmatch(r'\w+', v))
    identifiers = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(v) for v in unusual) + r')(?!\w)', re.IGNORECASE) if unusual else None
    email = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
    @lru_cache(maxsize=4096)
    def matches(text):
        return bool(email.search(text) or (identifiers and identifiers.search(text)) or
            any(token.group().casefold() in word_identifiers for token in re.finditer(r'\w+', text)))
    return matches


def scan_corpus(chunks, datasets, config):
    matches = pii_matcher(datasets, config)
    return [{'chunk_id': c['chunk_id'], 'reason': 'EMAIL_OR_CANONICAL_PERSONAL_IDENTIFIER'}
            for c in chunks if matches(c['text'])]


def scan_package_structure(package, datasets, config):
    """Check source/reference columns and JSONs; report IDs/reasons, never PII values."""
    import json
    matches = pii_matcher(datasets, config)
    findings = []
    def inspect(value, identifier):
        if isinstance(value, dict):
            for field, child in value.items():
                if excluded(field, config, corpus=False):
                    findings.append({'object_id': identifier, 'reason': 'SENSITIVE_STRUCTURED_FIELD'})
                inspect(child, identifier)
        elif isinstance(value, list):
            for child in value:
                inspect(child, identifier)
        elif isinstance(value, str) and matches(value):
            findings.append({'object_id': identifier, 'reason': 'PERSONAL_IDENTIFIER_IN_STRUCTURED_VALUE'})
    for name, rows in package.items():
        if not name.startswith(('source_', 'reference_')):
            continue
        for row in rows:
            identifier = next(row[k] for k in ('chunk_id', 'section_id', 'document_id') if k in row)
            for field in row:
                if excluded(field, config, corpus=False):
                    findings.append({'object_id': identifier, 'reason': 'SENSITIVE_OUTPUT_COLUMN'})
            # Technical keys, offsets, file paths and hashes are not personal text.
            for field in ('title', 'text_original', 'text_normalized', 'text'):
                if row.get(field) and matches(row[field]):
                    findings.append({'object_id': identifier, 'reason': 'EMAIL_OR_CANONICAL_PERSONAL_IDENTIFIER'})
            if 'metadata_json' in row:
                inspect(json.loads(row['metadata_json']), identifier)
            provenance = json.loads(row['provenance_json'])
            for ref in provenance['layer1']:
                inspect(ref.get('original_values', {}), identifier)
    return [dict(object_id=identifier, reason=reason) for identifier, reason in sorted({(r['object_id'],r['reason']) for r in findings})]
