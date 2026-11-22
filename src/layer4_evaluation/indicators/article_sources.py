"""ARTICLE sources for the V5 evaluation: identity, evidence fields and provenance.

Articles go through exactly the same retrieval, request, transport, retry, decision
and confidence components as projects. This module only adapts the input record:

* Identity: the canonical ``article_id`` (one per publication after Layer 2
  deduplication; several researchers link to the same ID). Selection accepts the
  canonical ID or its EID; a DOI only when it designates a single article.
* Evidence: the abstract is the only citable section. It enters through the existing
  ``text__`` mechanism (substantive, original name kept): ``abstract`` ->
  ``text__abstract``, same text, same section and chunk IDs, with its raw column
  provenance remapped explicitly. Title and keywords stay orientation metadata.
* No relational context: articles are evaluated independently; researcher links
  remain in Knowledge for later analysis (Power BI), never as evidence.
"""
import json

FIELD_MAP = {'abstract': 'text__abstract'}
IDENTITY = 'ARTICLE_ID_CANONICO'
BIBLIOGRAPHIC = ('title', 'doi', 'eid', 'journal', 'publication_year', 'document_type')


def original_identifier(article):
    """Identifier shown in menus and results: the source `eid` exactly as written in the
    production CSV (e.g. 2-s2.0-85089837524), never prefixed or trimmed. Only when that
    column is empty in the source, the literal source DOI. The canonical article_id
    (ART_...) stays an internal key for Knowledge, checkpoints and transport."""
    import json
    values = {}
    for item in json.loads(article.get('provenance_json') or '[]'):
        original = item.get('original_values') or {}
        for key in ('eid', 'doi'):
            if key in original and key not in values:
                values[key] = original[key]
    eid = values['eid'] if 'eid' in values else article.get('eid')
    if isinstance(eid, str) and eid.strip():
        return eid, 'EID'
    doi = values['doi'] if 'doi' in values else article.get('doi')
    if isinstance(doi, str) and doi.strip():
        return doi, 'DOI'
    return article['article_id'], 'ID_INTERNO'


def original_identifiers(rows):
    """{canonical article_id: original identifier} for canonical article rows."""
    return {r['article_id']: original_identifier(r)[0] for r in rows}


def resolve(rows, requested):
    """Canonical article IDs for requested IDs/EIDs/DOIs; ambiguous or unknown IDs are errors."""
    by_id = {r['article_id']: r for r in rows}
    if len(by_id) != len(rows):
        raise ValueError('Canonico de articulos con IDs duplicados')
    by_eid, by_doi = {}, {}
    for r in rows:
        if r.get('eid'):
            by_eid.setdefault(r['eid'], []).append(r['article_id'])
        if r.get('doi'):
            by_doi.setdefault(r['doi'].casefold(), []).append(r['article_id'])
    resolved, unknown, ambiguous = [], [], []
    for value in requested:
        value = value.strip()
        matches = ([value] if value in by_id else by_eid.get(value) or by_doi.get(value.casefold()) or [])
        if not matches:
            unknown.append(value)
        elif len(matches) > 1:
            ambiguous.append(value)
        else:
            resolved.append(matches[0])
    if unknown:
        raise ValueError('Articulos no encontrados en el Knowledge activo: ' + ', '.join(unknown))
    if ambiguous:
        raise ValueError('DOI compartido por varios articulos canonicos; usar el ID o EID: ' + ', '.join(ambiguous))
    if len(resolved) != len(set(resolved)):
        raise ValueError('La seleccion repite la misma publicacion; cada articulo se evalua una sola vez')
    return resolved


def mapped(rows, ids):
    """Rename evidence fields of the selected articles only; text and IDs untouched."""
    return [dict(r, field_name=FIELD_MAP.get(r['field_name'], r['field_name']))
            if r.get('source_type') == 'ARTICLE' and r['source_id'] in ids else r for r in rows]


def _raw_sources(section, field):
    # Sections may already carry the evaluation name; provenance uses the Layer 2 name.
    original = {v: k for k, v in FIELD_MAP.items()}.get(section['field_name'], section['field_name'])
    sources = []
    for source in json.loads(section['provenance_json'])['layer1']:
        mapping = source.get('field_mapping', {})
        if original in mapping:
            source = dict(source, field_mapping=dict(mapping, **{field: mapping[original]}))
        sources.append(source)
    return sources


def article_input(article, sections, base_fields):
    """Evaluation input with the same keys as a project input plus bibliographic metadata."""
    matches = [s for s in sections if s['source_id'] == article['article_id']]
    if any(s['source_type'] != 'ARTICLE' for s in matches):
        raise ValueError('Secciones con tipo de fuente distinto del articulo canonico')
    fields = dict.fromkeys(base_fields, '')
    provenance = {}
    for s in matches:
        field = FIELD_MAP.get(s['field_name'], s['field_name'])
        if field in fields or field.startswith('text__'):
            fields[field] = s['text_original'] or ''
            provenance[field] = dict(section_id=s['section_id'], text_hash_original=s['text_hash_original'],
                source_file=article['record_source'], source_row=article['source_row'],
                raw_sources=_raw_sources(s, field))
    return dict(project_id=article['article_id'], siap_id=article['article_id'], identity_type=IDENTITY,
        source_type='ARTICLE', fields=fields, field_provenance=provenance, field_mapping=dict(FIELD_MAP),
        bibliographic={k: article.get(k) for k in BIBLIOGRAPHIC},
        input_path=article['record_source'], input_row=article['source_row'],
        missing_fields=[f for f, v in fields.items() if not v])


def has_evidence(article_input_value):
    return bool((article_input_value['fields'].get('text__abstract') or '').strip())


def inventory(root):
    """Read-only inventory of the active BASE Knowledge articles for the interactive menu."""
    from pathlib import Path
    import pyarrow.parquet as pq
    import knowledge_store
    active = knowledge_store.read_active(root)
    if not active:
        raise ValueError('No hay Knowledge BASE activo; preparar el conocimiento antes de seleccionar articulos')
    manifest, _ = knowledge_store.load_version(root, active['version_id'])
    workspace = Path(knowledge_store.location(root, manifest)) / 'workspace/outputs/layer2'
    articles = pq.read_table(workspace / 'canonical/articulos.parquet',
        columns=['article_id', 'eid', 'doi', 'title', 'publication_year', 'provenance_json']).to_pylist()
    for a in articles:
        a['original_id'], a['original_id_type'] = original_identifier(a)
        del a['provenance_json']
    with_abstract = {s['source_id'] for s in pq.read_table(workspace / 'knowledge/source_sections.parquet',
        columns=['source_id', 'field_name', 'text_original'], filters=[('field_name', '=', 'abstract')]).to_pylist()
        if (s['text_original'] or '').strip()}
    return [dict(a, has_abstract=a['article_id'] in with_abstract) for a in articles]
