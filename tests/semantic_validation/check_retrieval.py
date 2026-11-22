"""Exercise real cached GraphRAG retrieval without embedding or model calls."""
from .harness import *
def main():
    from layer4_evaluation.indicators.scoped_retrieval import project_relations,from_published_cache
    from layer4_evaluation.indicators import context_budget as cb,assessment_v3 as v3,prospective_v2 as p2
    import pyarrow.parquet as pq
    selected={('21844','CUL-02'),('21736','CUL-02'),('21844','AMB-01'),('21750','TEC-02')}
    projects={};original={};settings=None
    for plan,p,iid,base,rec,dirs in original_attempts():
        if (p['siap_id'],iid) in selected:
            projects[p['project_id']]=p;original[(p['project_id'],iid)]=plan['context_requests'][p['project_id']][iid];settings=plan['runtime']['configuration']
    profiles,rubrics=catalog();ps={iid:profiles[iid] for _,iid in selected};rs={iid:rubrics[iid] for iid in ps}
    workspace=ROOT/'outputs/shared/base/versions/d778bfa52b4c1c69-6f580ffa/artifacts/workspace';token=read(ROOT/'config/qwen_tokenizer.json');token['path']=str(ROOT/token['path'])
    try:
        knowledge=workspace/'outputs/layer2/knowledge';chunks=pq.read_table(knowledge/'source_chunks.parquet').to_pylist();sections=pq.read_table(knowledge/'source_sections.parquet').to_pylist()
        relations=project_relations(workspace,list(projects.values()))
        candidates,receipt=from_published_cache(workspace,list(projects.values()),ps,chunks,relations)
        requests,diagnostics=cb.prepare_contexts(list(projects.values()),ps,rs,settings,candidates,chunks,sections,evidence_references=True,assessment_version=p2.VERSION,
            evaluation_mode=v3.PROSPECTIVE_V2,context_mode=v3.RETRIEVED_CONTEXT,relational_contexts=relations,tokenizer=token,prompt_version=p2.PROMPT)
        checks=[]
        for (pid,iid),old in original.items():
            new=requests[pid][iid];chosen=new['context_selection']['selected']
            checks.append(dict(project_id=pid,indicator_id=iid,status=new['context_selection']['status'],own_sources_only=all(c['source_id']==pid for c in chosen),
                old_evidence_hash=digest(old['payload']['project']),new_evidence_hash=digest(new['payload']['project']),same_evidence=old['payload']['project']==new['payload']['project']))
        assert all(c['own_sources_only'] and c['status']=='READY' for c in checks)
        write(OUT/'recuperacion_real.json',dict(status='EXECUTED_FROM_VERIFIED_CACHE',model_calls=0,embeddings_generated=0,receipt=receipt,diagnostics=diagnostics,checks=checks))
        write(OUT/'contextos_recuperados_nuevos.json',requests)
        print('VERIFIED_CACHE_RETRIEVAL:',len(checks),'selected pairs;',sum(c['same_evidence'] for c in checks),'identical historical evidence')
    except Exception as e:
        write(OUT/'recuperacion_real.json',dict(status='BLOCKED_RETRIEVAL',type=type(e).__name__,error=str(e),model_calls=0,embeddings_generated=0));raise
if __name__=='__main__':main()
