"""Project canonical entities and explicit memberships into graph-ready typed records."""

from .documents import metadata
from .security import excluded
from .provenance import extend
from .provenance import extend, serialize, text_hash



# Reuse canonical identity, including unresolved occurrences without resolving them.
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

# Only explicit canonical memberships; logical attributes participate in identity.
def build_relations(datasets, config, context):
    result = []
    for dataset, spec in config['relations'].items():
        source_type = config['datasets'][spec['source_dataset']]['entity_type']
        target_type = config['datasets'][spec['target_dataset']]['entity_type']
        for row in datasets[dataset]:
            source = source_type + ':' + row[spec['source_field']]
            target = target_type + ':' + row[spec['target_field']]
            attributes = {f: row.get(f) for f in spec['attribute_fields']}
            digest = text_hash(serialize([source, spec['relation_type'], target, attributes]))
            relation_id = 'REL_' + digest
            result.append({'relation_id': relation_id, 'source_entity_id': source,
                'relation_type': spec['relation_type'], 'target_entity_id': target,
                'attributes_json': serialize(attributes), 'evidence_type': 'STRUCTURED_CANONICAL',
                'provenance_json': extend(row, dataset, [row[spec['source_field']], row[spec['target_field']], attributes],
                    context, relation_id=relation_id, logical_key_hash=digest,
                    lineage_fields=[spec['source_field'], spec['target_field']] + spec['attribute_fields']),
                'layer2_run_id': context['layer2_run_id']})
    return result
