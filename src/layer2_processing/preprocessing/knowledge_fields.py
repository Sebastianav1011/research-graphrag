"""Auditable header/content classification. Detection never grants authorization."""
import re
import unicodedata


def normalized(value):
    value = ''.join(c for c in unicodedata.normalize('NFD', str(value)) if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+', value.lower()))


def contains(label, alias):
    return bool(normalized(alias)) and (' ' + normalized(alias) + ' ') in (' ' + label + ' ')


def describe_columns(headers, rows, mapping, catalog, selected=None, decisions=()):
    """Classify using whole tokens/phrases and data types, without copying cell texts."""
    selected = selected or {}
    decisions = {d['column']: d for d in decisions}
    mapped = {column: field for field, columns in mapping.items() for column in columns}
    result = []
    for column in headers:
        label = normalized(column)
        values = [r.get(column) for _, r in rows if r.get(column) not in (None, '')]
        namespaces = [name for name, aliases in catalog.get('identifier_namespaces', {}).items()
                      if label in {normalized(a) for a in aliases}]
        categories = [name for name, aliases in catalog.get('categories', {}).items()
                      if any(contains(label, a) for a in aliases)]
        overrides = {normalized(k): v for k,v in catalog.get('column_overrides', {}).items()}
        override = overrides.get(label)
        if override:
            if override not in catalog.get('categories', {}):
                raise ValueError('Categoria de conocimiento no configurada: ' + override)
            categories = [override]
        specific = [c for c in categories if c not in catalog.get('fallback_categories', [])]
        categories = specific or categories
        decision = decisions.get(column, {})
        field = mapped.get(column)
        item = dict(column=column, canonical_field=field, categories=categories,
                    identifier_namespaces=namespaces, category=categories[0] if len(categories) == 1 else None)
        typed_metadata = any(contains(label, a) for a in catalog.get('metadata_aliases', []))
        sensitive = any(contains(label, a) for a in catalog.get('sensitive_aliases', []))
        reason = decision.get('reason', '')
        blocked = reason in ('EXCLUDED_OR_SENSITIVE_HEADER', 'POSSIBLE_PERSONAL_OR_TECHNICAL_CONTENT')
        textual = bool(values) and all(isinstance(v, str) for v in values)
        if sensitive or reason == 'POSSIBLE_PERSONAL_OR_TECHNICAL_CONTENT':
            item.update(role='excluded_sensitive', authorization='DENIED', reason=reason or 'SENSITIVE_HEADER')
        elif namespaces or field and (field.endswith('_id') or field in ('doi', 'eid', 'document_number')):
            item.update(role='identifier', authorization='METADATA_ONLY')
        elif field in ('title','keywords'):
            item.update(role='metadata',authorization='METADATA_ONLY')
        elif typed_metadata:
            item.update(role='metadata', authorization='METADATA_ONLY')
        elif blocked:
            item.update(role='excluded_sensitive', authorization='DENIED', reason=reason)
        elif len(categories) > 1 or categories and values and not textual:
            item.update(role='ambiguous', authorization='REVIEW_REQUIRED', reason='MULTIPLE_CATEGORIES' if len(categories) > 1 else 'NON_TEXT_VALUES')
        elif column in selected.values() or field and field not in ('title', 'keywords') and categories:
            item.update(role='authorized_knowledge', authorization='AUTHORIZED')
        elif categories and textual:
            item.update(role='knowledge_candidate', authorization='PENDING_AUTHORIZATION')
        elif field:
            item.update(role='metadata', authorization='METADATA_ONLY')
        else:
            item.update(role='unknown', authorization='NOT_AUTHORIZED')
        if categories:
            item['statement_kind'] = ('intended' if 'objectives' in categories or any(contains(label, a) for a in catalog.get('prospective_aliases', []))
                                      else 'reported_not_verified')
        result.append(item)
    return result


def partition_text_aliases(mapping, catalog, rows):
    """Keep equivalent-name text columns separate, never resolve them as competing IDs."""
    mapping = {field: list(columns) for field, columns in mapping.items()}
    extra = []
    for field in catalog.get('canonical_text_fields', []):
        if len(mapping.get(field, [])) > 1:
            columns = mapping[field]
            populated = [c for c in columns if any(r.get(c) not in (None, '') for _, r in rows)]
            first = (populated or columns)[0]
            extra.extend(c for c in columns if c != first)
            mapping[field] = [first]
    return mapping, extra


def analyze_columns(headers, rows, mapping, catalog, policy, selector):
    """Use the existing privacy selector; category consent is explicit configuration."""
    mapping, aliases = partition_text_aliases(mapping, catalog, rows)
    initial = describe_columns(headers, rows, mapping, catalog)
    consent = policy.get('authorized_categories', [])
    if not isinstance(consent, list) or not all(isinstance(c, str) for c in consent):
        raise ValueError('text_columns.authorized_categories debe ser una lista de categorias')
    allowed = set(consent)
    unknown = allowed - set(catalog.get('categories', {}))
    if unknown:
        raise ValueError('Categorias autorizadas desconocidas: ' + ', '.join(sorted(unknown)))
    approved = [c['column'] for c in initial if c['category'] in allowed and c['role'] == 'knowledge_candidate']
    policy = policy | {'include': list(dict.fromkeys(policy.get('include', []) + aliases + approved))}
    selected, decisions = selector(headers, rows, mapping, policy)
    classification = describe_columns(headers, rows, mapping, catalog, selected, decisions)
    # Consent never bypasses ambiguity, sensitive fields or technical metadata.
    denied = {c['column'] for c in classification if c['role'] in ('ambiguous', 'metadata', 'identifier', 'excluded_sensitive')}
    selected = {f: c for f, c in selected.items() if c not in denied}
    for decision in decisions:
        if decision['column'] in denied and decision.get('selected'):
            decision.update(selected=False, reason='CLASSIFICATION_REQUIRES_REVIEW_OR_METADATA')
    return mapping, selected, decisions, classification
