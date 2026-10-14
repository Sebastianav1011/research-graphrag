"""Quality report implementation; files are emitted only for actual candidate builds."""
import csv
import json
from pathlib import Path

from .embedding_pipeline import validate_vectors, vector_hash
from .provenance import serialize

REPORTS = ('missing_embeddings', 'embedding_dimension_errors', 'orphan_graph_nodes', 'orphan_graph_relations',
           'missing_chunk_links', 'retrieval_provenance_issues', 'index_consistency',
           'embedding_normalization_issues', 'retrieval_anomalies', 'privacy_issues')


def evaluate(snapshot, bundles, indexes, graph, config):
    reports = {name: [] for name in REPORTS}
    failures = []
    for space in ('SOURCE', 'REFERENCE'):
        import numpy as np
        chunks = {r['chunk_id']: r for r in snapshot.tables[space.lower() + '_chunks']}
        bundle = bundles[space]
        if config['embeddings']['normalize_embeddings'] and not np.allclose(np.linalg.norm(bundle.vectors, axis=1), 1., atol=1e-6, rtol=0):
            reports['embedding_normalization_issues'].append({'source_space': space, 'reason': 'Nonunit normalized embedding'})
        embedded = {r['chunk_id'] for r in bundle.records}
        reports['missing_embeddings'].extend({'id': key, 'source_space': space, 'reason': 'Missing embedding'} for key in sorted(set(chunks) - embedded))
        for key in sorted(embedded - set(chunks)):
            reports['missing_chunk_links'].append({'id': key, 'source_space': space, 'reason': 'Embedding refers to missing chunk'})
        try:
            validate_vectors(bundle.vectors, len(bundle.records), bundle.metadata['dimensions'])
            if any(vector_hash(bundle.vectors[i]) != row['embedding_hash'] for i, row in enumerate(bundle.records)):
                raise ValueError('Embedding checksum mismatch')
        except ValueError as exc:
            reports['embedding_dimension_errors'].append({'source_space': space, 'reason': str(exc)})
        try:
            indexes[space].validate()
            if {r['chunk_id'] for r in indexes[space].records} != embedded:
                raise ValueError('Index/embedding chunk coverage differs')
            if indexes[space].metadata.get('layer2_manifest_hash') != snapshot.manifest_hash:
                raise ValueError('Index uses another knowledge snapshot')
        except ValueError as exc:
            reports['index_consistency'].append({'source_space': space, 'reason': str(exc)})
        for chunk in chunks.values():
            upstream = json.loads(chunk['provenance_json'])
            if upstream.get('layer1_run_id') != snapshot.manifest['layer1_run_id'] or upstream.get('layer2_run_id') != snapshot.manifest['layer2_run_id']:
                reports['retrieval_provenance_issues'].append({'id': chunk['chunk_id'], 'source_space': space, 'reason': 'Manifest lineage mismatch'})
    validation = graph.validate()
    # Isolation is topology, not a missing upstream identity. Profile records it separately.
    upstream_entities = {row['entity_id'] for row in snapshot.tables['entities']}
    reports['orphan_graph_nodes'] = [{'id': key, 'reason': 'Node absent upstream'} for key in sorted(set(graph.nodes) - upstream_entities)]
    from .security import privacy_issues
    reports['privacy_issues'] = privacy_issues(list(graph.nodes.values())) + privacy_issues(list(graph.relations.values()))
    for error in validation['errors']:
        report = 'orphan_graph_relations' if error['code'] == 'ORPHAN_RELATION' else 'index_consistency'
        reports[report].append({'id': error.get('relation_id', error.get('entity_id')), 'reason': error['code']})
    for report in REPORTS:
        if not reports[report] or report == 'orphan_graph_nodes':
            continue
        if report == 'orphan_graph_relations' and not config['quality']['fail_on_orphan_relation']:
            continue
        if report == 'retrieval_provenance_issues' and not config['quality']['fail_on_missing_provenance']:
            continue
        failures.append(report)
    return {'status': 'PASS' if not failures else 'FAIL', 'failures': failures,
            'report_counts': {k: len(v) for k, v in reports.items()},
            'entities': len(graph.nodes), 'relations': len(graph.relations),
            'embedding_counts': {space: len(bundle.records) for space, bundle in bundles.items()}}, reports


def write_reports(directory, summary, reports):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for report in REPORTS:
        with (directory / (report + '.csv')).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['id', 'source_space', 'reason'], extrasaction='ignore')
            writer.writeheader()
            for row in reports[report]:
                writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v for k, v in row.items()})
    (directory / 'summary.json').write_text(serialize(summary), encoding='utf-8')
