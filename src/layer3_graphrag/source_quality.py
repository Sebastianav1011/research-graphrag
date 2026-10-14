"""Validate SOURCE+INDICATOR outputs, section reconstruction and discovery lineage."""
import json
import math
from collections import defaultdict
from .source_context import SourceContextResolver
from .security import privacy_issues


def validate_retrieval(snapshot, graph, candidates, packages, config):
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
    if set(by_indicator)!=expected_indicators: anomalies.append({'id':'source_indicator_candidates','reason':'Indicator coverage mismatch'})
    if set(contexts)!={r['context_package_id'] for r in candidates}: anomalies.append({'id':'source_context_packages','reason':'Context/candidate coverage mismatch'})
    privacy=privacy_issues(candidates)+privacy_issues(packages)
    return {'status':'PASS' if not issues and not anomalies and not privacy else 'FAIL','candidate_count':len(candidates),
        'context_package_count':len(packages),'indicator_count':len(expected_indicators),'traceable':traceable,
        'provenance_coverage':traceable/len(candidates) if candidates else 0,'provenance_issues':len(issues),
        'anomalies':len(anomalies),'privacy_issues':len(privacy),
        'context_status_counts':{s:sum(r['context_status']==s for r in candidates) for s in ('ASSESSMENT_READY','DISCOVERY_ONLY')}},issues,anomalies,privacy
