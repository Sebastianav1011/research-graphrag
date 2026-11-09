"""Pure deterministic identities, hashes and preservation of upstream lineage."""
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import quote
from .security import apply_email_privacy


def now():
    return datetime.now(timezone.utc).isoformat()


def serialize(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def file_hash(path):
    from layer2_processing.checkpoints import locate
    path=locate(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def stable_id(prefix, *parts):
    return prefix + '_' + '_'.join(quote(str(p), safe='').replace('_', '%5F') for p in parts)


def project_lineage(refs, fields, email_policy='reject'):
    """Carry exact relevant original values and locators, without unrelated personal data."""
    selected = set(fields)
    projected = []
    for ref in refs:
        mapping = {k: v for k, v in ref.get('field_mapping', {}).items() if k in selected}
        names = set()
        for original in mapping.values():
            names.update(original if isinstance(original, list) else [original])
        originals, redactions = {}, [r for r in ref.get('privacy_redactions', []) if r['original_field'] in names]
        for k, v in ref.get('original_values', {}).items():
            if k not in names:
                continue
            masked, count = apply_email_privacy(v, email_policy)
            originals[k] = masked
            if count:
                redactions.append({'original_field': k, 'kind': 'EMAIL', 'count': count,
                                   'input_value_sha256': text_hash(serialize(v)), 'pattern_version': 'email_regex_v1'})
        item = ({k: v for k, v in ref.items() if k not in {'original_values', 'field_mapping', 'source_record_id', 'privacy_redactions'}} |
            {'field_mapping': mapping, 'original_values': originals})
        if 'field_provenance' in item:
            item['field_provenance'] = {k:v for k,v in item['field_provenance'].items() if k in names}
        if 'knowledge_fields' in item:
            item['knowledge_fields'] = {k:v for k,v in item['knowledge_fields'].items() if k in selected}
        if redactions:
            item['privacy_redactions'] = redactions
        projected.append(item)
    return projected


def extend(row, dataset, canonical_id, context, lineage_fields=None, **extra):
    refs = json.loads(row['provenance_json'])
    fields = lineage_fields if lineage_fields is not None else sorted({k for ref in refs for k in ref['field_mapping']})
    return serialize({'layer1_run_id': context['layer1_run_id'],
        'layer2_run_id': context['layer2_run_id'], 'canonical_dataset': dataset,
        'canonical_id': canonical_id, 'config_version': context['config_version'],
        'config_hash': context['config_hash'], 'layer1': project_lineage(refs, fields, context.get('email_policy', 'reject')),
        'layer1_provenance_hash': text_hash(row['provenance_json']),
        'email_policy': context.get('email_policy', 'reject'),
        'lineage_fields': fields, 'lineage_projection': 'canonical_fields_v1', **extra})


def descendant(parent_json, **extra):
    parent = json.loads(parent_json)
    fields = extra.pop('lineage_fields', None)
    if fields is not None:
        parent['layer1'] = project_lineage(parent['layer1'], fields, parent.get('email_policy', 'reject'))
        parent['lineage_fields'] = fields
    return serialize(parent | extra)


def semantic_payload(value):
    """Remove only operational keys at the output/provenance envelope level."""
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k not in {'layer2_run_id', 'started_at', 'finished_at'}}
    return value


def payload_hash(rows):
    normalized = []
    for row in rows:
        item = dict(row)
        for key in ('provenance_json', 'metadata_json', 'attributes_json'):
            if key in item:
                item[key] = json.loads(item[key])
                if key == 'provenance_json':
                    item[key] = semantic_payload(item[key])
        normalized.append(semantic_payload(item))
    return text_hash(serialize(normalized))
