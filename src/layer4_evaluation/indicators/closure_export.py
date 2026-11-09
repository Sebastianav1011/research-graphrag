"""One official publication, gated on actual V2 execution and human acceptance."""
from collections import Counter
from datetime import datetime,timezone
import csv
import json
import math
from pathlib import Path
import shutil
import uuid

from . import experiment
from .experiment_inputs import read, sha256, verify_hashes, selected_territories
from .experiment_export import sheet, export_spec
from .powerbi import COLUMNS, TERRITORY_COLUMNS, FIELD_NAMES
from .review import evidence_locations, human_metrics
from .selection import canonical_hash


def render_workbook(root,spec,output,audit):
    """Reuse existing Artifact Tool authoring and saved-workbook QA. Sidecars stay private."""
    directory=Path(audit)/canonical_hash(spec)[:20]
    directory.mkdir(parents=True,exist_ok=True)
    candidate=directory/Path(output).name
    qa=export_spec(root,spec,candidate)
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    # Copy via a candidate on the destination volume; replace only after QA.
    temporary=Path(output).with_suffix('.xlsx.pending')
    shutil.copyfile(candidate,temporary)
    temporary.replace(output)
    return qa


def consumer_rows(selected,records):
    rows=[];seen=set()
    for p in selected:
        record=records[p['project_id']]
        by_id={a['indicator_id']:a for a in record['wrapper']['assessments']}
        for row in record['rows']:
            if row['assessment_validation_status']!='VALID' or row['validation_errors']:
                raise ValueError('Official V2 publication rejects invalid assessments')
            if row['assessment_version']!='ASSESSMENT_V2' or row['confidence_version']!='EVIDENCE_CONFIDENCE_V2':
                raise ValueError('Official publication requires explicit V2 versions')
            score=row['confidence_raw_score']
            if (row['confidence_status']!='COMPUTED' or isinstance(score,bool) or not isinstance(score,(int,float))
                    or not math.isfinite(score) or not 0<=score<=100):
                raise ValueError('V2 valid assessment must have a finite score, including actual zero')
            if row['confidence_probability'] is not None or row['confidence_level'] is not None:
                raise ValueError('No calibrated probability/level is available')
            if row['decision'] not in ('SUPPORTED','INSUFFICIENT_EVIDENCE','NOT_SUPPORTED'):
                raise ValueError('Unknown semantic decision')
            key=p['siap_id'],row['indicator_id']
            if not isinstance(key[0],str) or not key[0] or key in seen:
                raise ValueError('Missing/duplicate SIAP+indicator')
            seen.add(key)
            locations=evidence_locations(p,by_id[row['indicator_id']])
            if any(not e['match_valid'] or not e['section_id'] for e in locations):
                raise ValueError('Unverifiable published evidence location')
            if len(locations)!=len(row['evidence_texts']):
                raise ValueError('Evidence alignment mismatch')
            # Only literal quotations enter the evidence column. Semantic
            # explanations and criterion judgements remain in the private audit.
            rows.append(dict(zip(COLUMNS,[p['siap_id'],row['indicator_id'],row['decision'],
                '\n\n'.join(f'[{i}] {e["text"]}' for i,e in enumerate(locations,1)) or None,
                '\n'.join(f'[{i}] SIAP {p["siap_id"]}; {e["field"]}' for i,e in enumerate(locations,1)) or None,
                '\n'.join(f'[{i}] {FIELD_NAMES[e["field"]]}; section_id={e["section_id"]}; '
                           f'[{e["start"]},{e["end"]}); {e["coordinate_system"]}' for i,e in enumerate(locations,1)) or None,
                score])))
    return rows


def comparison(root,config_path):
    config,out,manifest,data,selected,requests,runtime=experiment.verify_prepared(root,config_path)
    rows=experiment.read_jsonl(out/'technical_results.jsonl')
    result=[]
    for r in rows:
        v1,v2=r.get('v1_comparison_score'),r['confidence_raw_score']
        result.append({'project_id':r['project_id'],'indicator_id':r['indicator_id'],
            'score_v1':v1,'score_v2':v2,'absolute_difference':abs(v2-v1) if v1 is not None and v2 is not None else None,
            'signed_difference':v2-v1 if v1 is not None and v2 is not None else None,
            'decision':r['decision'],'strength':r['support_strength'],
            'conceptual_coverage':r.get('conceptual_coverage'),'evidence_fields':len(set(r['evidence_source_fields'])),
            'variation_reason':'V1 not applicable to non-SUPPORTED; NULL is not zero' if r['decision']!='SUPPORTED' else
                'V2 excludes F/C, increases S weight and uses structured conceptual rubric; V1 uses CLEAR-only binary projection',
            'comparison_scope':'SAME_V2_JUDGEMENT_LEGACY_FORMULA_PROJECTION_NOT_REUSED_V1_ASSESSMENT',
            'human_review':None})
    folder=out/'qa';folder.mkdir(exist_ok=True)
    with (folder/'confidence_comparison.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(result[0]) if result else ['project_id','indicator_id','score_v1','score_v2','absolute_difference'])
        writer.writeheader();writer.writerows(result)
    caps=[]
    assessed={(r['project_id'],r['indicator_id']):r for r in rows}
    for cap in (2,3,5):
        keys=[(p['project_id'],c['indicator_id']) for p in selected for c in p['eligible_candidates'][:cap]]
        present=[assessed[k] for k in keys if k in assessed]
        caps.append({'candidate_cap':cap,'published_pairs':len(keys),'assessed_pairs':len(present),
            'pending_pairs':len(keys)-len(present),
            'decisions':dict(Counter(r['decision'] for r in present if r['assessment_validation_status']=='VALID')),
            'correctly_justified_supported':None,'human_relevance':None,
            'incremental_inference_seconds':None,'monetary_cost':None,
            'status':'PENDING_COMPLEMENTARY_INFERENCE_AND_HUMAN_REVIEW'})
    experiment.write_json(folder/'candidate_comparison.json',{'same_project_ids':[p['project_id'] for p in selected],
        'comparisons':caps,'selected_initial_cap':config['candidate_limit_per_project'],
        'final_cap_approved':False,'reason':'Initial conservative cap; no automatic expansion without measured benefit.'})
    return {'evaluations_compared':len(result),'comparable_numeric_scores':sum(r['absolute_difference'] is not None for r in result),
            'mean_absolute_difference':sum(r['absolute_difference'] for r in result if r['absolute_difference'] is not None)/sum(r['absolute_difference'] is not None for r in result) if any(r['absolute_difference'] is not None for r in result) else None,
            'candidate_comparisons':caps,'v2_approved':False}


def review(root,config_path):
    config,out,manifest,data,selected,requests,runtime=experiment.verify_prepared(root,config_path)
    from .assessment_v2 import rubric
    folder=out/'reviews';folder.mkdir(exist_ok=True)
    labels=[];blind=[];sources=[];criteria=[];diagnostics=[]
    rows=experiment.read_jsonl(out/'technical_results.jsonl')
    for p in selected:
        for c in p['candidates']:
            labels.append({'project_id':p['project_id'],'indicator_id':c['indicator_id'],
                'human_label':None,'reviewer_id':None,'independent':None,'reviewed_at':None,
                'evidence_valid':None,'conceptual_mapping_valid':None,'temporal_valid':None,'rubric_valid':None,
                'case_A_to_F':None,'notes':None})
            blind.append({'project_id':p['project_id'],'siap_id':p['siap_id'],'indicator_id':c['indicator_id'],
                          'human_label':None,'reviewer_id':None,'independent':None})
        for field,text in p['fields'].items():
            for start in range(0,max(1,len(text or '')),800):
                sources.append({'project_id':p['project_id'],'field':field,'start':start,'text':(text or '')[start:start+800]})
    for iid in sorted({c['indicator_id'] for p in selected for c in p['candidates']}):
        profile=data['profiles'][iid]
        for criterion in rubric(profile)['criteria']:
            criteria.append({'indicator_id':iid,**criterion,'definition':profile['descripcion_ampliada'],
                'favorable_evidence':profile['favorable_evidence'],'insufficient_evidence':profile['insufficient_evidence'],
                'rubric_approved':None})
    for r in rows:
        diagnostics.append({'project_id':r['project_id'],'indicator_id':r['indicator_id'],'decision':r['decision'],
            'strength':r['support_strength'],'coverage':r.get('conceptual_coverage'),
            'confidence_v1':r.get('v1_comparison_score'),'confidence_v2':r['confidence_raw_score'],
            'criteria':json.dumps(r.get('criterion_assessments'),ensure_ascii=False),
            'explanation':r['evidence_explanation'],'quotes':'\n\n'.join(r['evidence_texts'])})
    template={'selection_sha256':manifest['selection_sha256'],'technical_results_sha256':sha256(out/'technical_results.jsonl'),
              'status':'PENDING_REAL_HUMAN_REVIEW','labels':labels}
    # Never overwrite actual human input when refreshing the review package.
    target=folder/('human_review.template.'+template['technical_results_sha256'][:16]+'.json')
    if not target.exists():
        experiment.write_json(target,template)
    approval_template=folder/('final_approval.template.'+template['technical_results_sha256'][:16]+'.json')
    if not approval_template.exists():
        experiment.write_json(approval_template,{'selection_sha256':manifest['selection_sha256'],
            'technical_results_sha256':template['technical_results_sha256'],'human_review_sha256':None,
            'confidence_version':'EVIDENCE_CONFIDENCE_V2','candidate_limit_per_project':config['candidate_limit_per_project'],
            'formula_v2_approved':False,'candidate_cap_approved':False,'approved':False,
            'approved_by':None,'approved_at':None,'formula_comparison_reference':None,'candidate_comparison_reference':None})
    guide=[{'field':'selection_sha256','instruction':manifest['selection_sha256']},
           {'field':'technical_results_sha256','instruction':template['technical_results_sha256']},
           {'field':'protocol','instruction':'Blind human labels first using FUENTES and CRITERIOS; then inspect DIAGNOSTICOS. Complete JSON template with human identity, timestamp and evidence/semantic/temporal/rubric review. Never have the development agent pose as human reviewer.'},
           {'field':'cases','instruction':'A one strong quote; B distributed evidence; C thematic only; D expected not achieved; E partial; F insufficient text. Mark absent real cases rather than inventing them.'}]
    spec={'sheets':[sheet('ETIQUETADO',list(blind[0]),blind),
        sheet('FUENTES',['project_id','field','start','text'],sources),
        sheet('CRITERIOS',list(criteria[0]),criteria),
        sheet('DIAGNOSTICOS',list(diagnostics[0]) if diagnostics else ['project_id','indicator_id','decision'],diagnostics),
        sheet('GUIA',['field','instruction'],guide)]}
    for tab in spec['sheets']:
        tab['widths']={'text':105,'criterion':85,'definition':110,'favorable_evidence':100,
            'insufficient_evidence':100,'criteria':135,'explanation':110,'quotes':120,'instruction':140,
            'field':28,'project_id':24,'indicator_id':22,'rubric_approved':25}
        tab['headerHeight']=45
        tab['previewRanges']={'FUENTES':['A1:D5'],'CRITERIOS':['A1:E3'],
            'GUIA':['A1:B5'],'ETIQUETADO':['A1:F5']}.get(tab['name'],['A1:G4'])
    render_workbook(root,spec,folder/'revision_humana_v2.xlsx',out/'qa/review_workbook')
    return {'status':'PENDING_HUMAN_REVIEW','pairs':len(labels),'json_template':str(target.relative_to(root)),
            'workbook':str((folder/'revision_humana_v2.xlsx').relative_to(root))}


def review_metrics(root,config_path,review_path):
    config,out,manifest,data,selected,requests,runtime=experiment.verify_prepared(root,config_path)
    review_data=read(review_path)
    if review_data.get('selection_sha256')!=manifest['selection_sha256'] or review_data.get('technical_results_sha256')!=sha256(out/'technical_results.jsonl'):
        raise ValueError('Human labels refer to stale/different results')
    rows=[r for r in experiment.read_jsonl(out/'technical_results.jsonl') if r['assessment_validation_status']=='VALID']
    metrics=human_metrics(rows,review_data.get('labels',[]))
    for values in metrics['per_reviewer'].values():
        matrix=values['confusion_matrix']
        values['supported_false_positives']=sum(matrix[t]['SUPPORTED'] for t in matrix if t!='SUPPORTED')
        values['supported_false_negatives']=sum(matrix['SUPPORTED'][p] for p in matrix if p!='SUPPORTED')
    metrics.update(selection_sha256=manifest['selection_sha256'],
        technical_results_sha256=sha256(out/'technical_results.jsonl'),
        input_review_sha256=sha256(review_path))
    (out/'qa').mkdir(exist_ok=True)
    experiment.write_json(out/'qa/independent_human_metrics.json',metrics)
    return metrics


def acceptance_gate(manifest, selected, records, review_data, approval, technical_hash):
    if len(selected)!=20 or len({p['project_id'] for p in selected})!=20 or len({p['siap_id'] for p in selected})!=20:
        raise ValueError('Exactly 20 distinct verified PROJECT and SIAP identities required')
    expected={(p['project_id'],c['indicator_id']) for p in selected for c in p['candidates']}
    rows=[r for record in records.values() for r in record['rows']]
    actual=[(r['project_id'],r['indicator_id']) for r in rows]
    if set(actual)!=expected or len(actual)!=len(expected) or any(r['assessment_validation_status']!='VALID' for r in rows):
        raise ValueError('BLOCKED: final V2 inference incomplete or invalid')
    if review_data.get('selection_sha256')!=manifest['selection_sha256'] or review_data.get('technical_results_sha256')!=technical_hash:
        raise ValueError('Human review refers to stale/different results')
    labels=review_data.get('labels',[])
    keys=[(l['project_id'],l['indicator_id']) for l in labels]
    if set(keys)!=expected or len(keys)!=len(expected):
        raise ValueError('All final assessments require independent human review')
    decisions={(r['project_id'],r['indicator_id']):r['decision'] for r in rows}
    for label in labels:
        if (not label.get('reviewer_id') or not label.get('reviewed_at') or label.get('independent') is not True
                or any(label.get(k) is not True for k in ('evidence_valid','conceptual_mapping_valid','temporal_valid','rubric_valid'))):
            raise ValueError('Human evidence/conceptual/temporal/rubric checks incomplete or rejected')
        if label.get('human_label')!=decisions[label['project_id'],label['indicator_id']]:
            raise ValueError('Human/model disagreement requires resolution before official publication')
    if (approval.get('selection_sha256')!=manifest['selection_sha256'] or approval.get('technical_results_sha256')!=technical_hash
            or approval.get('human_review_sha256')!=canonical_hash(review_data)
            or approval.get('confidence_version')!='EVIDENCE_CONFIDENCE_V2'
            or approval.get('candidate_limit_per_project')!=manifest['config']['candidate_limit_per_project']
            or any(approval.get(k) is not True for k in ('formula_v2_approved','candidate_cap_approved','approved'))
            or not approval.get('approved_by') or not approval.get('approved_at')
            or not approval.get('formula_comparison_reference') or not approval.get('candidate_comparison_reference')):
        raise ValueError('BLOCKED: human formula/candidate-cap/final acceptance missing or stale')
    return human_metrics(rows,labels)


def publish(root,config_path,approval_path=None,review_path=None):
    root=Path(root)
    verified=experiment.verify_prepared(root,config_path)
    config,out,manifest,data,selected,requests,runtime=verified
    if not experiment.is_v2(config):
        raise ValueError('Official exporter accepts only the V2 closure run')
    publication_root=root/'outputs/layer4/auditoria/cierre_v2'
    publication_root.mkdir(parents=True,exist_ok=True)
    with experiment.run_lock(out),experiment.run_lock(publication_root):
        experiment.verify(root,config_path)
        records={p.stem:read(p) for p in (out/'records').glob('*.json')}
        if not approval_path or not review_path:
            raise ValueError('BLOCKED: actual V2 completion, human review and formula/candidate approval required; no official workbook published')
        review_data,approval=read(review_path),read(approval_path)
        technical_hash=sha256(out/'technical_results.jsonl')
        metrics=acceptance_gate(manifest,selected,records,review_data,approval,technical_hash)
        indicators=consumer_rows(selected,records)
        territories=selected_territories(data,selected)
        spec={'sheets':[sheet('RESULTADO_INDICADORES',COLUMNS,indicators),sheet('TERRITORIOS',TERRITORY_COLUMNS,territories)]}
        publication_id=canonical_hash({'spec':spec,'execution_id':manifest['execution_id'],
            'technical_results_sha256':technical_hash,'approval_sha256':sha256(approval_path),
            'review_sha256':sha256(review_path)})[:20]
        directory=root/'outputs/layer4/auditoria/cierre_v2/publications'/publication_id
        directory.mkdir(parents=True,exist_ok=True)
        candidate=directory/'resultado_capa4.xlsx'
        qa=render_workbook(root,spec,candidate,directory/'qa')
        verify_hashes(root,read(out/'protected_inputs.json'))
        for source,name in ((review_path,'human_review.accepted.json'),(approval_path,'final_approval.accepted.json')):
            target=directory/name
            if Path(source).resolve()!=target.resolve():
                shutil.copyfile(source,target)
        destination=root/'outputs/layer4/final/resultado_capa4.xlsx'
        destination.parent.mkdir(parents=True,exist_ok=True)
        if any(p.name!='resultado_capa4.xlsx' for p in destination.parent.iterdir()):
            raise ValueError('Official folder must contain only resultado_capa4.xlsx')
        publication={'status':'CAPA_4_COMPLETE','version':'LAYER4_FINAL_V2','execution_id':manifest['execution_id'],
            'config_path':str(config_path),'selection_sha256':manifest['selection_sha256'],
            'technical_results_sha256':technical_hash,'confidence_version':'EVIDENCE_CONFIDENCE_V2',
            'approval_sha256':sha256(approval_path),'human_review_sha256':sha256(review_path),
            'approval_snapshot':(directory/'final_approval.accepted.json').relative_to(root).as_posix(),
            'review_snapshot':(directory/'human_review.accepted.json').relative_to(root).as_posix(),
            'human_metrics':metrics,'assessment_count':len(indicators),'projects':20,'territory_rows':len(territories),
            'decisions':dict(Counter(r['estado_cumplimiento'] for r in indicators)),
            'workbook_sha256':sha256(candidate),'qa':qa,'published_at':datetime.now(timezone.utc).isoformat(),
            'protected_inputs':read(out/'protected_inputs.json')}
        experiment.write_json(directory/'publication_manifest.json',publication)
        # Journal makes interrupted publication detectable by verify-final.
        journal=root/'outputs/layer4/auditoria/cierre_v2/publication_pending.json'
        experiment.write_json(journal,{'candidate':str(candidate.relative_to(root)),
                                     'expected_sha256':publication['workbook_sha256']})
        if destination.exists() and sha256(destination)!=publication['workbook_sha256']:
            history=root/'outputs/layer4/auditoria/cierre_v2/publications'/('previous_'+uuid.uuid4().hex)
            history.mkdir();shutil.copy2(destination,history/destination.name)
        temporary=destination.with_suffix('.xlsx.pending')
        shutil.copyfile(candidate,temporary);temporary.replace(destination)
        experiment.write_json(root/'outputs/layer4/auditoria/cierre_v2/final_manifest.json',publication)
        journal.unlink()
        return publication


def verify_final(root,config_path):
    from .preliminary_output import verify_workbook
    root=Path(root)
    if (root/'outputs/layer4/auditoria/cierre_v2/.execution.lock').exists():
        raise ValueError('BLOCKED: official publication writer active; retry after it finishes')
    if (root/'outputs/layer4/auditoria/cierre_v2/publication_pending.json').exists():
        raise ValueError('BLOCKED: interrupted official publication; inspect journal')
    manifest_path=root/'outputs/layer4/auditoria/cierre_v2/final_manifest.json'
    if not manifest_path.exists():
        return {'status':'BLOCKED','cause':'No accepted V2 publication; inference, human review and formula/candidate approval pending'}
    publication=read(manifest_path)
    verify_hashes(root,publication['protected_inputs'])
    experiment.verify(root,config_path)
    config,out,manifest,data,selected,requests,runtime=experiment.verify_prepared(root,config_path)
    if publication['execution_id']!=manifest['execution_id'] or publication['technical_results_sha256']!=sha256(out/'technical_results.jsonl'):
        raise ValueError('Official publication does not match verified execution')
    workbook=root/'outputs/layer4/final/resultado_capa4.xlsx'
    if set(p.name for p in workbook.parent.iterdir())!={'resultado_capa4.xlsx'} or sha256(workbook)!=publication['workbook_sha256']:
        raise ValueError('Official output/hash mismatch')
    records={p.stem:read(p) for p in (out/'records').glob('*.json')}
    verify_hashes(root,{publication['approval_snapshot']:publication['approval_sha256'],
                        publication['review_snapshot']:publication['human_review_sha256']})
    acceptance_gate(manifest,selected,records,read(root/publication['review_snapshot']),
                    read(root/publication['approval_snapshot']),publication['technical_results_sha256'])
    spec={'sheets':[sheet('RESULTADO_INDICADORES',COLUMNS,consumer_rows(selected,records)),
                    sheet('TERRITORIOS',TERRITORY_COLUMNS,selected_territories(data,selected))]}
    return {'status':'PASS','publication_status':publication['status'],'qa':verify_workbook(workbook,spec),
            'protected_files':len(publication['protected_inputs'])}
