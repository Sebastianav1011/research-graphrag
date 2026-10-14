"""Reuse canonical identity, including unresolved occurrences without resolving them."""
from .document_builder import metadata
from .security import excluded
from .provenance import extend


def build_entities(datasets, config, context):
    result = []
    for dataset, spec in config['datasets'].items():
        for row in datasets[dataset]:
            canonical_id = row[spec['id_field']]
            result.append({'entity_id': spec['entity_type'] + ':' + canonical_id,
                'entity_type': spec['entity_type'], 'canonical_id': canonical_id,
                'label': row.get(spec['label_field']), 'metadata_json': metadata(row, spec, config),
                'provenance_json': extend(row, dataset, canonical_id, context,
                    lineage_fields=[spec['id_field'], spec['label_field']] +
                        [f for f in spec.get('metadata_fields', []) if not excluded(f, config, corpus=False)]),
                'layer2_run_id': context['layer2_run_id']})
    return result
