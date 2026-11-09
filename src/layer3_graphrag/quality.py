"""Validate embedding/index/graph integrity and SOURCE candidate/context provenance/privacy; write quality reports."""

import csv
import json
from pathlib import Path
from .embeddings import validate_vectors, vector_hash
from .provenance import serialize
import math
from collections import defaultdict
from .source_context import SourceContextResolver
from .security import privacy_issues



# Quality report implementation; files are emitted only for actual candidate builds.
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

# Validate SOURCE+INDICATOR outputs, section reconstruction and discovery lineage.
def validate_retrieval(snapshot, graph, candidates, packages, config, *, considered_indicators=None):
    resolver = SourceContextResolver(snapshot)
    chunks = resolver.chunks
    refs = {r['chunk_id']:r for r in snapshot.tables['reference_chunks']}
    contexts = {p['context_package_id']:p for p in packages}
    issues, anomalies, seen, by_indicator = [], [], set(), defaultdict(list)
    if len(contexts)!=len(packages): anomalies.append({'id':'source_context_packages','reason':'Duplicate SOURCE context package'})
    traceable = 0
    for row in candidates:
        key = (row['indicator_id'],row['source_type'],row['source_id'],row['document_id'])
        if key in seen: anomalies.append({'id':row['candidate_id'],'reason':'Duplicate SOURCE/indicator'})
        seen.add(key); by_indicator[row['indicator_id']].append(row)
        package=contexts.get(row['context_package_id'])
        expected=resolver.reconstruct(row['source_type'],row['source_id'],row['document_id'],row['layer3_run_id'])
        discovery=row['discovery_chunk_ids']
        valid=bool(discovery) and all(k in chunks and all(chunks[k][f]==row[f] for f in ('source_id','source_type','document_id')) for k in discovery)
        if not valid or package != expected or row['provenance_json'] != resolver.provenance(expected,discovery):
            issues.append({'id':row['candidate_id'],'reason':'SOURCE/discovery/section lineage mismatch'})
        else: traceable += 1
        for field in ('context_status','source_context_hash','available_field_names'):
            if row[field]!=expected[field]: anomalies.append({'id':row['candidate_id'],'reason':'SOURCE context mismatch: '+field})
        if row['orientation_section_ids']!=[s['section_id'] for s in expected['orientation_sections']] or row['substantive_section_ids']!=[s['section_id'] for s in expected['substantive_sections']]:
            anomalies.append({'id':row['candidate_id'],'reason':'Missing or invalid SOURCE sections'})
        if len(discovery)>config['retrieval']['max_chunks_per_source'] or len(set(discovery))!=len(discovery):
            anomalies.append({'id':row['candidate_id'],'reason':'Discovery chunk limits/duplicates'})
        if valid and (row['discovery_field_names'] != [chunks[k]['field_name'] for k in discovery] or [d['chunk_id'] for d in row['discovery_chunks']] != discovery or row['discovery_retrieval_origins'] != [d['retrieval_origin'] for d in row['discovery_chunks']]):
            anomalies.append({'id':row['candidate_id'],'reason':'Discovery metadata alignment error'})
        if not row['reference_chunk_ids'] or any(k not in refs or refs[k]['source_id']!=row['indicator_id'] for k in row['reference_chunk_ids']):
            anomalies.append({'id':row['candidate_id'],'reason':'Invalid reference contributors'})
        v,g,h=row['best_vector_score'],row['graph_score'],row['hybrid_retrieval_score']
        expected_score=config['hybrid']['vector_weight']*((v+1)/2)+config['hybrid']['graph_weight']*g
        if not all(math.isfinite(s) for s in (v,g,h)) or not -1.000001<=v<=1.000001 or not 0<=g<=1 or not 0<=h<=1.000001 or abs(h-expected_score)>1e-12:
            anomalies.append({'id':row['candidate_id'],'reason':'SOURCE retrieval score error'})
        if any(k in row for k in ('indicator_match','confidence_score','confidence_level','evidence_explanation','evidence_chunk_ids','decision','supported')):
            anomalies.append({'id':row['candidate_id'],'reason':'Forbidden Layer 4 assessment field'})
        path=json.loads(row['graph_path_json'])
        if path:
            nodes,relations=path['entity_ids'],path['relation_ids']
            if len(relations)>config['graph']['max_hops'] or len(nodes)!=len(relations)+1 or nodes[-1]!=row['source_type']+':'+row['source_id']:
                anomalies.append({'id':row['candidate_id'],'reason':'Invalid graph path shape'})
            for n,rid in enumerate(relations):
                edge=graph.relations.get(rid)
                if edge is None or {edge['source_entity_id'],edge['target_entity_id']}!={nodes[n],nodes[n+1]}:
                    anomalies.append({'id':row['candidate_id'],'reason':'Invalid graph relation path'})
            for node in nodes[:-1]:
                entity=graph.nodes.get(node)
                if entity is None or entity['entity_type']=='RESEARCHER' and str(json.loads(entity['metadata_json']).get('identity_status')).upper()!='RESOLVED':
                    anomalies.append({'id':row['candidate_id'],'reason':'Invalid/ambiguous/unresolved bridge'})
    for indicator, rows in by_indicator.items():
        if len(rows)>config['retrieval']['final_candidates_per_indicator'] or [r['source_rank'] for r in rows]!=list(range(1,len(rows)+1)):
            anomalies.append({'id':indicator,'reason':'SOURCE count/rank error'})
    expected_indicators={r['source_id'] for r in snapshot.tables['reference_documents']}
    # Examining the catalogue does not require finding a candidate for each ID.
    # New callers supply the complete query ledger; historical callers retain
    # their original coverage check when that ledger is unavailable.
    if considered_indicators is None:
        if set(by_indicator)!=expected_indicators: anomalies.append({'id':'source_indicator_candidates','reason':'Indicator coverage mismatch'})
    else:
        considered=list(considered_indicators)
        if len(considered)!=len(set(considered)) or set(considered)!=expected_indicators:
            anomalies.append({'id':'source_indicator_candidates','reason':'Indicator query coverage mismatch'})
        if not set(by_indicator)<=expected_indicators:
            anomalies.append({'id':'source_indicator_candidates','reason':'Candidate indicator outside catalogue'})
    if set(contexts)!={r['context_package_id'] for r in candidates}: anomalies.append({'id':'source_context_packages','reason':'Context/candidate coverage mismatch'})
    privacy=privacy_issues(candidates)+privacy_issues(packages)
    return {'status':'PASS' if not issues and not anomalies and not privacy else 'FAIL','candidate_count':len(candidates),
        'context_package_count':len(packages),'indicator_count':len(expected_indicators),'traceable':traceable,
        'provenance_coverage':traceable/len(candidates) if candidates else 0,'provenance_issues':len(issues),
        'anomalies':len(anomalies),'privacy_issues':len(privacy),
        'context_status_counts':{s:sum(r['context_status']==s for r in candidates) for s in ('ASSESSMENT_READY','DISCOVERY_ONLY')}},issues,anomalies,privacy
