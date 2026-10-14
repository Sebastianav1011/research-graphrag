"""One canonical project/article record yields one independent source document."""
from .provenance import extend, serialize, stable_id
from .security import excluded


def metadata(row, spec, config):
    return serialize({f: row.get(f) for f in spec.get('metadata_fields', [])
                      if f in row and not excluded(f, config, corpus=False)})


def build_documents(datasets, config, context, reference=False):
    documents = []
    names = ['indicadores'] if reference else ['proyectos', 'articulos']
    for dataset in names:
        spec = config['datasets'][dataset]
        kind = 'INDICATOR_REFERENCE' if reference else spec['entity_type']
        for row in datasets[dataset]:
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
