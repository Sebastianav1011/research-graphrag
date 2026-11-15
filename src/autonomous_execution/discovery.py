"""Prepare auditable, provisional BGE candidates over the existing GraphRAG.

No compliance decisions, confidence, category filters, quotas or LLM calls.
The full catalogue is checked against each selected project's own passages.
"""
from run_paths import file_path as run_file
from copy import deepcopy
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from . import store as s
from layer3_graphrag.provenance import digest
from layer4_evaluation.indicators.performance import timed, measured_run


def admission_settings(config):
    values=config['retrieval']['candidate_admission']
    keys={'calibration_status','min_profile_cosine','min_criterion_cosine','min_focused_cosine'}
    if set(values)!=keys or values['calibration_status']!='PROVISIONAL_PENDING_HUMAN_REVIEW':
        raise ValueError('Configuracion de admision provisional incompatible')
    for key in keys-{'calibration_status'}:
        value=values[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<value<=1:
            raise ValueError('Umbral de admision invalido: '+key)
    return dict(values)


def substantive(snapshot,chunk):
    """Honor native fields and the intake's explicit additional-field consent."""
    from layer3_graphrag.source_context import FIELD_ROLES
    from layer3_graphrag.graph import json_object
    field=chunk['field_name']
    if field in FIELD_ROLES[chunk['source_type']]['substantive']:return True
    if not field.startswith('text__'):return False
    raw=json_object(chunk['provenance_json']).get('layer1',[])
    return bool(raw) and all(r.get('knowledge_fields',{}).get(field,{}).get('authorization')=='AUTHORIZED' for r in raw)


@timed('recuperacion')
def select(retriever,profiles,rubrics,project_ids,settings):
    """Independent gates on the SAME original passage; never a rank cutoff.

    Profile, standalone criterion and profile+criterion cosines are retrieval
    signals only. Even a selected criterion still requires Qwen's interpretation.
    """
    snapshot=retriever.snapshot
    if set(profiles)!=set(rubrics):raise ValueError('Catalogo y rubricas incompatibles')
    references={iid:[] for iid in profiles}
    for row in snapshot.tables['reference_chunks']:
        if row['source_id'] in references:references[row['source_id']].append(row)
    by_project={pid:[] for pid in sorted(project_ids)}
    sections={row['section_id']:row for row in snapshot.tables['source_sections']}
    for pos,record in enumerate(retriever.index.records):
        chunk=retriever.chunks[record['chunk_id']]
        if chunk['source_id'] in by_project and chunk['source_type']=='PROJECT' and substantive(snapshot,chunk):
            section=sections[chunk['section_id']]
            # Layer 2 defines chunk offsets over text_normalized and retains
            # text_original separately; normalization can change its length.
            if (section['source_id']!=chunk['source_id'] or section['field_name']!=chunk['field_name'] or
                not 0<=chunk['char_start']<chunk['char_end']<=len(section['text_normalized']) or
                section['text_normalized'][chunk['char_start']:chunk['char_end']]!=chunk['text']):
                raise ValueError('Fragmento semantico no verificable en text_normalized: '+chunk['chunk_id'])
            by_project[chunk['source_id']].append(pos)
    queries=[];keys=[]
    for iid in sorted(profiles):
        refs=sorted(references[iid],key=lambda r:r['chunk_id'])
        if not refs:raise ValueError('Indicador sin referencia documental: '+iid)
        for ref in refs:keys.append((iid,'profile',ref['chunk_id']));queries.append(ref['text'])
        for criterion in rubrics[iid]['criteria']:
            cid,text=criterion['criterion_id'],criterion['criterion']
            keys.extend([(iid,'criterion',cid),(iid,'focused',cid)])
            queries.extend([text,profiles[iid]['indicator_name']+'\nCriterio institucional: '+text])
    vectors=retriever.query_vectors(queries)
    scores=np.clip(vectors @ retriever.index.vectors.T,-1.,1.)
    lookup={key:scores[n] for n,key in enumerate(keys)}
    audit=[];chosen=[];contexts={}
    config=deepcopy(retriever.config)
    # These bounds limit retrieval metadata in the historical ranking. During
    # admission every source/passage is considered; they never limit candidates.
    config['retrieval']['final_candidates_per_indicator']=max(1,len(snapshot.tables['source_documents']))
    config['retrieval']['max_chunks_per_source']=max(1,len(retriever.index.records))
    old_top=retriever.settings['vector_top_k_per_reference_chunk']
    old_chunks=retriever.settings['max_chunks_per_source']
    retriever.settings['vector_top_k_per_reference_chunk']=max(1,len(retriever.index.records))
    retriever.settings['max_chunks_per_source']=max(1,len(retriever.index.records))
    try:
        for iid in sorted(profiles):
            refs=sorted(references[iid],key=lambda r:r['chunk_id'])
            discovery,expanded,metrics=retriever.score_rows([r['text'] for r in refs],[r['chunk_id'] for r in refs])
            rows={row['chunk_id']:row for row in discovery}
            profile_score=np.max([lookup[(iid,'profile',r['chunk_id'])] for r in refs],axis=0)
            indicator_hits=[]
            for pid,positions in by_project.items():
                criteria=[];admitted=set()
                for criterion in rubrics[iid]['criteria']:
                    cid=criterion['criterion_id'];passages=[]
                    for pos in positions:
                        chunk=retriever.chunks[retriever.index.records[pos]['chunk_id']]
                        signals=dict(profile_cosine=float(profile_score[pos]),
                            criterion_cosine=float(lookup[(iid,'criterion',cid)][pos]),
                            focused_cosine=float(lookup[(iid,'focused',cid)][pos]))
                        passes=all(signals[name]>=settings['min_'+name] for name in signals)
                        if passes:admitted.add(chunk['chunk_id'])
                        passages.append(dict(chunk_id=chunk['chunk_id'],section_id=chunk['section_id'],field=chunk['field_name'],
                            char_start=chunk['char_start'],char_end=chunk['char_end'],text_sha256=chunk['chunk_hash'],
                            failed_gates=[key for key in signals if signals[key]<settings['min_'+key]],
                            meets_gates=passes,**signals))
                    criteria.append(dict(criterion_id=cid,criterion_text=criterion['criterion'],
                        query_sha256=digest(criterion['criterion']),passages=passages))
                hits=[rows[key] for key in sorted(admitted)]
                indicator_hits.extend(hits)
                audit.append(dict(project_id=pid,indicator_id=iid,selected=bool(admitted),
                    reason='SAME_SUBSTANTIVE_PASSAGE_MATCHES_PROFILE_AND_CRITERION' if admitted else
                        'NO_AUTHORIZED_SUBSTANTIVE_PASSAGE' if not positions else 'NO_PASSAGE_MEETS_ALL_PROVISIONAL_SEMANTIC_GATES',
                    criterion_signals=criteria,discovery_chunk_ids=sorted(admitted),
                    matching_criteria=[c['criterion_id'] for c in criteria if any(p['meets_gates'] for p in c['passages'])],
                    graph_contribution=any(rows[key].get('graph_hops') not in (None,0) for key in admitted),
                    graph_relation_count=len(retriever.graph.relations),
                    semantic_adjudication='PENDING_HUMAN_REVIEW',compliance_decided=False))
            candidates,packages=retriever.context_resolver.group_candidates(indicator_hits,iid,config,retriever.fingerprint,retriever.run_id)
            chosen.extend(candidates);contexts.update({row['context_package_id']:row for row in packages})
    finally:
        retriever.settings['vector_top_k_per_reference_chunk']=old_top
        retriever.settings['max_chunks_per_source']=old_chunks
    pairs={pid:sorted(row['indicator_id'] for row in audit if row['project_id']==pid and row['selected']) for pid in by_project}
    sensitivity={}
    for floor in (.38,.40,.42,.44,.46):
        sensitivity[str(floor)]={pid:sum(any(all(p[key]>=floor for key in
            ('profile_cosine','criterion_cosine','focused_cosine')) for c in row['criterion_signals'] for p in c['passages'])
            for row in audit if row['project_id']==pid) for pid in by_project}
    return dict(settings=settings,project_indicators=pairs,catalog_ids=sorted(profiles),
        method='BGE_PROFILE_AND_CRITERION_SAME_ORIGINAL_PASSAGE',
        substantive_passages_considered={pid:len(positions) for pid,positions in by_project.items()},
        comparisons=audit,selection_is_compliance=False,confidence_used=False,
        threshold_sensitivity=sensitivity,calibration_note='EXPLORATORY_SAMPLE_ONLY; NO_HUMAN_RECALL_OR_PRECISION_ESTIMATE',
        excluded_is_not_not_supported=True,graph_relations=len(retriever.graph.relations)),chosen,list(contexts.values())


def build(root,run):
    """Child process: local embeddings, original GraphRAG, no Ollama access."""
    from scripts import pipeline_coordinator as coordinator
    from .preparation_integrity import catalog
    from layer3_graphrag.configuration import load_config
    from layer3_graphrag.embeddings import create_provider
    from layer3_graphrag.pipeline import load_artifacts
    from layer3_graphrag.validate_inputs import validate_inputs
    from layer3_graphrag.indicator_retrieval import IndicatorRetriever
    from layer3_graphrag.contracts import source_candidate_arrow_schema
    root,run=Path(root).resolve(),Path(run).resolve()
    if (run/'autonomous/main/manifest.json').exists():raise ValueError('Descubrimiento previo al manifiesto exclusivamente')
    state=coordinator.check(root,run);execution=s.read(run_file(run, 'execution.json'))
    selected=coordinator.scope_projects(root,run,execution['selection'],execution.get('project_ids'))
    data,_=catalog(root)
    from knowledge_store import knowledge_workspace
    workspace=knowledge_workspace(run);config,_=load_config(workspace)
    settings=admission_settings(config)
    coordinator.graph(root,run,build=True)
    snapshot=validate_inputs(workspace,config)
    if {row['source_id'] for row in snapshot.tables['reference_documents']}!=set(data['profiles']):
        raise ValueError('Referencias de descubrimiento distintas del catalogo oficial')
    provider=create_provider(config['embeddings'])
    manifest,indexes,graph=load_artifacts(workspace,snapshot,config,provider)
    canonical=pq.read_table(workspace/'outputs/layer2/canonical/proyectos.parquet').to_pylist()
    pids=[row['project_id'] for row in canonical if row['source_project_id'] in selected]
    retriever=IndicatorRetriever(snapshot,indexes['SOURCE'],provider,graph,config,manifest['layer3_run_id'])
    audit,candidates,contexts=select(retriever,data['profiles'],data['rubrics'],pids,settings)
    from layer3_graphrag.quality import validate_retrieval
    verification_config=deepcopy(config)
    verification_config['retrieval']['max_chunks_per_source']=max(1,len(indexes['SOURCE'].records))
    verification_config['retrieval']['final_candidates_per_indicator']=max(1,len(snapshot.tables['source_documents']))
    quality,issues,anomalies,privacy=validate_retrieval(snapshot,graph,candidates,contexts,verification_config,
        considered_indicators=audit['catalog_ids'])
    if quality['status']!='PASS':raise ValueError('Candidatos sin integridad verificable: '+str([r['reason'] for r in issues+anomalies]))
    audit['quality']=quality
    candidate_path=run_file(run, 'discovery_candidates.parquet')
    candidate_path.parent.mkdir(parents=True,exist_ok=True)
    pq.write_table(pa.Table.from_pylist(candidates,schema=source_candidate_arrow_schema()),candidate_path,compression='zstd')
    audit.update(graph_manifest_sha256=s.sha(workspace/'outputs/layer3/publication/_manifest.json'),
        knowledge_manifest_sha256=s.sha(workspace/'outputs/layer2/knowledge/_manifest.json'),
        catalog_sha256=digest(dict(profiles=data['profiles'],rubrics=data['rubrics'])),
        embedding_fingerprint=retriever.fingerprint,candidates_sha256=s.sha(candidate_path),
        candidate_context_ids=[row['context_package_id'] for row in contexts],inference_calls=0)
    s.write(run_file(run, 'discovery.json'),audit)
    return audit


@measured_run
def prepare(root,run):
    """End BGE's process before manifest review or any subsequent Qwen worker."""
    root,run=Path(root).resolve(),Path(run).resolve()
    if not run.is_relative_to(root/'outputs/runs'):raise ValueError('Descubrimiento fuera de runs')
    if not (run_file(run, 'discovery.json')).exists():
        run_file(run,'discovery.stdout.log').parent.mkdir(parents=True,exist_ok=True)
        command=[sys.executable,str(root/'src/autonomous_execution/graph_worker.py'),
            '--run-path',run.relative_to(root).as_posix(),'--prepare-discovery']
        options=dict(cwd=root,stdin=subprocess.DEVNULL,close_fds=True)
        if sys.platform=='win32':options['creationflags']=subprocess.CREATE_NO_WINDOW
        with (run_file(run, 'discovery.stdout.log')).open('ab') as out,(run_file(run, 'discovery.stderr.log')).open('ab') as err:
            error_start=err.tell()
            result=subprocess.run(command,stdout=out,stderr=err,**options)
        if result.returncode:
            detail='exit_code='+str(result.returncode)
            with (run_file(run, 'discovery.stderr.log')).open('rb') as err:
                err.seek(0,2);err.seek(max(error_start,err.tell()-8192))
                lines=err.read().decode('utf-8',errors='replace').splitlines()
            if lines:
                try:
                    failure=json.loads(lines[-1])
                except json.JSONDecodeError:
                    failure={}
                if isinstance(failure,dict) and failure.get('error_message'):
                    detail=str(failure.get('error_type','Error'))+': '+str(failure['error_message'])
            raise ValueError('DISCOVERY_PREPARATION_FAILED: '+detail+'; revisar '+str(run_file(run, 'discovery.stderr.log')))
    return validate_saved(run)


def validate_saved(run):
    """Validate existing discovery without spawning workers or writing metrics."""
    run=Path(run)
    audit=s.read(run_file(run, 'discovery.json'))
    candidate=run_file(run, 'discovery_candidates.parquet')
    if s.sha(candidate)!=audit['candidates_sha256']:raise ValueError('Candidatos de descubrimiento modificados')
    if len(audit['catalog_ids'])!=48 or len(set(audit['catalog_ids']))!=48:
        raise ValueError('Descubrimiento requiere los 48 indicadores oficiales')
    expected={(pid,iid) for pid in audit['project_indicators'] for iid in audit['catalog_ids']}
    rows=audit['comparisons']
    if len(rows)!=len(expected) or {(r['project_id'],r['indicator_id']) for r in rows}!=expected:
        raise ValueError('Cobertura de descubrimiento incompleta o duplicada')
    actual={(r['source_id'],r['indicator_id']) for r in pq.read_table(candidate).to_pylist()}
    selected={(r['project_id'],r['indicator_id']) for r in rows if r['selected']}
    if actual!=selected or selected!={(pid,iid) for pid,ids in audit['project_indicators'].items() for iid in ids}:
        raise ValueError('Seleccion de candidatos incompatible con el registro')
    return audit
