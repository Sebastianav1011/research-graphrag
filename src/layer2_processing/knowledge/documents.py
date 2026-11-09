"""Build SOURCE and REFERENCE documents and sections; normalize fields and compose reference chunks."""

import json
from .provenance import extend, serialize, stable_id
from .security import excluded
from .provenance import descendant, stable_id, text_hash
from .text_normalization import as_text, normalize, words
from .security import excluded, apply_email_privacy
from .chunking import build_chunks



# One canonical project/article record yields one independent source document.
def metadata(row, spec, config):
    return serialize({f: row.get(f) for f in spec.get('metadata_fields', [])
                      if f in row and not excluded(f, config, corpus=False)})


def document_values(row, spec):
    """Hydrate only preprocessing-authorized fields from their original occurrences."""
    row = dict(row)
    for ref in json.loads(row['provenance_json']):
        for field in ref.get('extra_text_fields', []):
            if field in spec.get('text_fields', []):
                column = ref['field_mapping'][field]
                value = ref['original_values'].get(column)
                if isinstance(value, str) and value.strip():
                    previous = row.get(field, '')
                    if value.strip() not in previous.split('\n\n'):
                        row[field] = (previous + '\n\n' + value.strip()).strip()
    return row


def has_document_text(row, spec, config):
    values = document_values(row, spec)
    return any(normalize(as_text(values.get(f)), config['normalization'])
               for f in spec.get('text_fields', []) if not excluded(f, config))


def build_documents(datasets, config, context, reference=False):
    documents = []
    names = ['indicadores'] if reference else ['proyectos', 'articulos']
    for dataset in names:
        spec = config['datasets'][dataset]
        kind = 'INDICATOR_REFERENCE' if reference else spec['entity_type']
        for row in datasets[dataset]:
            if not reference and not has_document_text(row, spec, config):
                # Preserve the canonical record/entity. An empty source document
                # would fabricate a corpus object without any authorized text.
                continue
            canonical_id = row[spec['id_field']]
            document_id = stable_id('DOC', kind, canonical_id)
            documents.append({'document_id': document_id, 'source_id': canonical_id, 'source_type': kind,
                'title': row.get(spec['label_field']), 'canonical_dataset': dataset,
                'canonical_run_id': context['layer1_run_id'], 'metadata_json': metadata(row, spec, config),
                'provenance_json': extend(row, dataset, canonical_id, context, document_id=document_id,
                    lineage_fields=[spec['id_field'], spec['label_field']] + spec.get('text_fields', []) +
                        [f for f in spec.get('metadata_fields', []) if not excluded(f, config, corpus=False)]),
                'layer2_run_id': context['layer2_run_id']})
    return documents

# Sections retain nulls, configured field order and upstream field mappings.
def build_sections(documents, datasets, config, context):
    index = {name: {r[config['datasets'][name]['id_field']]: r for r in rows}
             for name, rows in datasets.items() if name in config['datasets']}
    sections = []
    for document in documents:
        dataset = document['canonical_dataset']
        row = document_values(index[dataset][document['source_id']], config['datasets'][dataset])
        for order, field in enumerate(config['datasets'][dataset].get('text_fields', [])):
            if field not in row or excluded(field, config):
                continue
            input_text = as_text(row[field])
            original, redactions = apply_email_privacy(input_text, config.get('privacy', {}).get('email_policy', 'reject'))
            section_id = stable_id('SEC', document['source_type'], document['source_id'], field)
            semantics = [ref['knowledge_fields'][field] for ref in json.loads(row['provenance_json'])
                         if field in ref.get('knowledge_fields', {})]
            sections.append({'section_id': section_id, 'document_id': document['document_id'],
                'source_id': document['source_id'], 'source_type': document['source_type'],
                'field_name': field, 'field_order': order, 'text_original': original,
                'text_normalized': '', 'char_count': 0, 'word_count': 0, 'text_hash': '',
                'text_hash_original': text_hash(original if original is not None else ''),
                'text_hash_normalized': '', 'provenance_json': descendant(document['provenance_json'],
                    section_id=section_id, source_field=field,
                    lineage_fields=[field],
                    text_hash_input=text_hash(input_text if input_text is not None else ''),
                    email_redactions=redactions,
                    original_representation='list_joined_newlines' if isinstance(row[field], list) else 'scalar'),
                'layer2_run_id': context['layer2_run_id']})
            if semantics:
                sections[-1]['provenance_json'] = descendant(sections[-1]['provenance_json'], knowledge_semantics=semantics)
    return sections


def normalize_sections(sections, config):
    for section in sections:
        text = normalize(section['text_original'], config['normalization'])
        digest = text_hash(text)
        section.update(text_normalized=text, char_count=len(text), word_count=len(words(text)),
                       text_hash=digest, text_hash_normalized=digest)
        section['provenance_json'] = descendant(section['provenance_json'],
            text_hash_original=section['text_hash_original'], text_hash_normalized=digest)
    return sections

# Indicator descriptions are reference knowledge, never evidence of compliance.
def build_reference(datasets, config, context):
    documents = build_documents(datasets, config, context, reference=True)
    sections = normalize_sections(build_sections(documents, datasets, config, context), config)
    return documents, sections, build_chunks(sections, config, context)
