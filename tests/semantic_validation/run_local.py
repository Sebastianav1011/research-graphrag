"""Small real Ollama experiment. Explicit opt-in; never collected by pytest.

python -B -m tests.semantic_validation.run_local --execute-local
No API, embeddings, BASE build, original checkpoint writes or unbounded retries.
"""
import argparse,sys,time,shutil,subprocess
from copy import deepcopy
from pathlib import Path
from .harness import *

SELECTED=[
 'CUL-02__positivo','CUL-02__tematico','CUL-02__negacion','CUL-02__prospectivo_vago','CUL-02__plan_concreto__PROSPECTIVE_V2',
 'TEC-02__positivo','TEC-02__tematico','TEC-02__plan_concreto__PROSPECTIVE_V2',
 'ECO-02__positivo','ECO-02__plan_concreto__DEMONSTRATED','ECO-02__plan_concreto__PROSPECTIVE_V2','ECO-02__negacion',
 'TEC-07__exclusion','TEC-07__sin_informacion','TEC-07__publicacion_sin_adopcion','SOC-04__financiador']
HISTORICAL=[('21844','CUL-02'),('21736','CUL-02'),('21844','AMB-01'),('21750','TEC-02')]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute-local',action='store_true');args=parser.parse_args()
    if not args.execute_local:parser.error('Se requiere --execute-local; no hay inferencia implícita.')
    from layer4_evaluation.indicators import assessment_v3 as v3,prospective_v2 as p2,context_budget as cb,evidence_references as refs
    from layer4_evaluation.indicators.ollama_provider import OllamaClient,OllamaAssessmentProvider,configuration
    from layer4_evaluation import live_execution as live
    from autonomous_execution.policy import free_ram_mb
    settings=configuration(plans()[0]['runtime']['configuration']);assert settings['provider']=='ollama'
    runtime=OllamaClient(settings).inspect();ram=free_ram_mb()
    if ram<2048:
        write(OUT/'preflight_local_bloqueado.json',dict(status='BLOCKED_RESOURCE_PREFLIGHT',available_ram_mb=ram,required_ram_mb=2048,runtime=runtime,
            model_calls=0,selected_synthetic=SELECTED,selected_historical=HISTORICAL,
            explanation='Windows informa RAM física disponible insuficiente. No se alteró el umbral ni se enviaron inferencias.'))
        print('BLOCKED_RESOURCE_PREFLIGHT: RAM disponible '+str(ram)+' MiB; 0 llamadas de modelo.',flush=True)
        return
    token=read(ROOT/'config/qwen_tokenizer.json');token['path']=str(ROOT/token['path'])
    assert filehash(token['path'])==token['sha256']
    assert runtime['digest']==token['model_digest'] and runtime['model_metadata_sha256']==token['model_metadata_sha256']
    experiment=OUT/'inferencia_local/baseline_v1';experiment.mkdir(parents=True,exist_ok=True)
    preflight=dict(status='READY',runtime=runtime,available_ram_mb=ram,disk_free_gb=shutil.disk_usage(ROOT).free/1024**3,
        selected_synthetic=SELECTED,selected_historical=HISTORICAL,max_pairs=20,max_calls=60,
        original_run_read_only=True,knowledge_rebuild=False,paid_services=False,
        code_hashes={str(p.relative_to(ROOT)):filehash(p) for p in (ROOT/'src/layer4_evaluation').rglob('*.py')})
    write(experiment/'preflight.json',preflight)
    profiles,rubrics=catalog();indexed={c['case_id']:c for c in read(OUT/'corpus_congelado.json')};tasks=[]
    for name in SELECTED:
        c=indexed[name];iid=c['indicator_id'];pid='SYN_'+iid.replace('-','')+'_'+str(len(tasks)+1)
        project=dict(project_id=pid,siap_id=pid,fields={f:'' for f in ('title','keywords','summary','methodology','objectives','expected_results')})
        project['fields'].update(title='DATOS SINTÉTICOS CONTROLADOS, proyecto P',methodology=c['text'])
        rubric=rubrics[iid];version=p2.VERSION;mode=v3.PROSPECTIVE_V2;prompt=p2.PROMPT
        if c['mode']=='DEMONSTRATED':
            rubric=plans()[0]['catalog_derivation']['interpretations'][iid]['original_rubric'];version=v3.SK_VERSION;mode=v3.DEMONSTRATED;prompt='DEMONSTRATED_SK_PROMPT_V2_PARTIAL'
        req=cb.make_request(project,profiles[iid],rubric,project['fields'],evidence_references=True,assessment_version=version,evaluation_mode=mode,context_mode=v3.FULL_CONTEXT,prompt_version=prompt)
        tasks.append((c,project,iid,req,rubric,version))
    originals={(p['siap_id'],iid):(plan,p,iid,base,rec,dirs) for plan,p,iid,base,rec,dirs in original_attempts()}
    requests={};retrieval=dict(status='NOT_EXECUTED')
    try:
        import pyarrow.parquet as pq
        from layer4_evaluation.indicators.scoped_retrieval import project_relations,from_published_cache
        workspace=ROOT/'outputs/shared/base/versions/d778bfa52b4c1c69-6f580ffa/artifacts/workspace'
        projects=list({originals[k][1]['project_id']:originals[k][1] for k in HISTORICAL}.values())
        ps={iid:profiles[iid] for _,iid in HISTORICAL};rs={iid:rubrics[iid] for iid in ps}
        knowledge=workspace/'outputs/layer2/knowledge'
        chunks=pq.read_table(knowledge/'source_chunks.parquet').to_pylist();sections=pq.read_table(knowledge/'source_sections.parquet').to_pylist()
        relational=project_relations(workspace,projects)
        candidates,receipt=from_published_cache(workspace,projects,ps,chunks,relational)
        requests,diagnostics=cb.prepare_contexts(projects,ps,rs,settings,candidates,chunks,sections,evidence_references=True,
            assessment_version=p2.VERSION,evaluation_mode=v3.PROSPECTIVE_V2,context_mode=v3.RETRIEVED_CONTEXT,
            relational_contexts=relational,tokenizer=token,prompt_version=p2.PROMPT)
        retrieval=dict(status='EXECUTED_FROM_VERIFIED_CACHE',receipt=receipt,diagnostics=diagnostics)
    except Exception as e:
        retrieval=dict(status='BLOCKED_RETRIEVAL_REPLAY_FALLBACK',type=type(e).__name__,error=str(e),fallback='ORIGINAL_SEALED_CONTEXT_NO_NEW_RETRIEVAL')
    write(experiment/'retrieval.json',retrieval)
    for pid,iid in HISTORICAL:
        plan,project,_,base,rec,dirs=originals[(pid,iid)];old=plan['context_requests'][project['project_id']][iid]
        req=requests.get(project['project_id'],{}).get(iid,old)
        c=dict(case_id='HIST_'+pid+'_'+iid,indicator_id=iid,scenario='historical_new_inference',expected='PENDING_HUMAN',oracle_status='PENDING_HUMAN',mode='PROSPECTIVE_V2')
        tasks.append((c,project,iid,req,rubrics[iid],p2.VERSION))
    results=[]
    for c,project,iid,req,rubric,version in tasks:
        path=experiment/c['case_id'];result_file=path/'result.json'
        if result_file.exists():results.append(read(result_file));continue
        if path.exists():raise RuntimeError('Intento incompleto: conservar y revisar antes de reanudar '+str(path))
        path.mkdir();schema=refs.response_schema(req,project['fields'])
        req=deepcopy(req)
        if 'context_budget' not in req:req['context_budget']=cb.estimate(req['prompt'],schema,settings,tokenizer=token,cap=8000)
        assert req['context_budget']['fits']
        plan=dict(profiles={iid:profiles[iid]},rubrics={iid:rubric},assessment_version=version,evaluation_policy=dict(decision_policy=p2.DECISION_POLICY))
        write(path/'project.json',project);write(path/'request_original.json',req);write(path/'schema.json',schema);write(path/'plan.json',plan);write(path/'oracle.json',c)
        provider=OllamaAssessmentProvider(path/'ollama_runs',path/'schema.json',lambda p,ids:req,settings=settings,runtime=runtime,
            max_indicators=1,corrective_retries=2,token_limit_retries=2,correction_version=p2.CORRECTION if version==p2.VERSION else refs.VERSION,
            wrapper_validator=lambda w,pid,ids:live.check_wrapper(plan,project,req,pid,ids,w),
            wrapper_resolver=(lambda w:live.resolve_wrapper(plan,project,req,w)) if version==p2.VERSION else None)
        started=time.monotonic();assessment=None;error=None
        try:assessment=provider.evaluate(project,[profiles[iid]])[0]['assessment'];actual=assessment['decision']
        except Exception as e:actual='BLOCKED_ERROR';error=dict(type=type(e).__name__,message=str(e))
        confidence=v3.confidence(project['fields'],profiles[iid],assessment,rubric) if assessment else None
        r=dict(case_id=c['case_id'],indicator_id=iid,scenario=c['scenario'],scope='NEW_LOCAL_INFERENCE',mode=c['mode'],expected=c['expected'],
            oracle_status=c['oracle_status'],actual=actual,result=compare_expected(c,actual),assessment=assessment,confidence=confidence,
            calls=provider.calls,error=error,elapsed_seconds=round(time.monotonic()-started,3),evidence_sha256=digest(req['payload']['project']),
            prompt_sha256=digest(req['prompt']),path=str(path.relative_to(ROOT)))
        write(result_file,r);results.append(r);write(experiment/'results.json',results)
        print(json.dumps({k:r[k] for k in ('case_id','actual','expected','result','elapsed_seconds')})+' calls='+str(len(provider.calls)),flush=True)
    assert sum(len(r['calls']) for r in results)<=60
    write(experiment/'completion.json',dict(status='COMPLETED',pairs=len(results),calls=sum(len(r['calls']) for r in results),retrieval_status=retrieval['status']))
if __name__=='__main__':main()
