"""Bounded private coverage study, reusing the accepted CLI transport and telemetry."""
from datetime import datetime,timezone
from pathlib import Path
from collections import Counter
import argparse
import json
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from layer4_evaluation.indicators import global_discovery as gd,assessment_v3 as v3
from layer4_evaluation.indicators import semantic_fallback as baseline
from layer4_evaluation.indicators.codex_cli import CodexCliAssessmentProvider,inspect_runtime
from layer4_evaluation.indicators.experiment_inputs import read,sha256,verify_hashes
from layer4_evaluation.indicators.experiment import write_json as _write_json
from layer4_evaluation.indicators.performance import Measurement,usage_metrics,interval_union
from layer4_evaluation.indicators.selection import FIELDS,canonical_hash

OUT=ROOT/'outputs/layer4/pruebas/validacion_v3_3'
IDS=['PROJ_20022','PROJ_20456','PROJ_21299','PROJ_22027','PROJ_20899']
PHASES=['catalog_rubric','global_discovery','assessment_v3']


def write_json(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    _write_json(Path(path),value)


def prepare():
    if (OUT/'plan.json').exists():return verify()
    from layer4_evaluation.indicators.final_export import verify_final
    assert verify_final(ROOT,'config/layer4_final.yaml')['status']=='PASS'
    source=ROOT/'outputs/layer4/pruebas/piloto_v2/cierre_20'
    old=read(source/'plan.json')
    projects={p['project']['project_id']:p['project'] for p in old['projects']}
    assert all(pid in projects for pid in IDS)
    profiles={p['indicator_id']:p for p in gd.catalog(old['profiles'])}
    oldrows=baseline.effective_rows(ROOT,source)
    OUT.mkdir(parents=True,exist_ok=True)
    runtime=inspect_runtime()
    code=['scripts/run_layer4_coverage_v3.py','src/layer4_evaluation/indicators/global_discovery.py',
          'src/layer4_evaluation/indicators/assessment_v3.py','src/layer4_evaluation/indicators/codex_cli.py',
          'src/layer4_evaluation/indicators/assessment_v2.py','src/layer4_evaluation/indicators/confidence.py',
          'src/layer4_evaluation/indicators/performance.py','src/layer4_evaluation/indicators/prompt.py']
    inputs=dict(old['source_hashes'])
    for name in ('plan.json','manifest.json'):
        inputs[(source/name).relative_to(ROOT).as_posix()]=sha256(source/name)
    for p in sorted((source/'records').glob('*/*.json')):
        inputs[p.relative_to(ROOT).as_posix()]=sha256(p)
        for name,digest in read(p)['artifact_hashes'].items():inputs[(source/name).relative_to(ROOT).as_posix()]=digest
    for name in ('outputs/layer4/final/resultado_capa4.xlsx','outputs/layer4/auditoria/cierre_v2/final_manifest.json'):
        inputs[name]=sha256(ROOT/name)
    plan=dict(version='LAYER4_COVERAGE_STUDY_V3',execution_id=uuid.uuid4().hex,
        prepared_at=datetime.now(timezone.utc).isoformat(),project_ids=IDS,
        projects=[projects[i] for i in IDS],profiles=profiles,rules=old['rules'],baseline_rows=oldrows,
        baseline_directory=source.relative_to(ROOT).as_posix(),runtime=runtime,
        max_prioritized_per_project=6,assessment_batch_size=3,rubric_batch_size=16,
        maximum_new_calls=18,timeout_seconds=900,requested_model=None,
        source_hashes=inputs,code_hashes={name:sha256(ROOT/name) for name in code},
        human_acceptance=False,official_publication_allowed=False)
    write_json(OUT/'plan.json',plan)
    write_json(OUT/'rubric.schema.json',v3.rubric_response_schema())
    write_json(OUT/'discovery.schema.json',gd.selection_schema())
    write_json(OUT/'assessment.schema.json',v3.schemas()['assessment_batch'])
    write_json(OUT/'manifest.json',dict(execution_id=plan['execution_id'],plan_sha256=sha256(OUT/'plan.json'),
        prepared_hashes={p.name:sha256(p) for p in [OUT/'plan.json',OUT/'rubric.schema.json',OUT/'discovery.schema.json',OUT/'assessment.schema.json']}))
    write_json(OUT/'authorization.example.json',dict(plan_sha256=sha256(OUT/'plan.json'),
        institutional_text_authorized=False,project_ids=IDS,phases=PHASES,maximum_new_calls=18,
        authorized_by='',authorized_at='',authorization_reference=''))
    prompts={pid:len(gd.make_input(projects[pid],profiles,old['rules'])['prompt']) for pid in IDS}
    write_json(OUT/'preparation_summary.json',dict(projects=IDS,catalog_profiles=48,
        baseline_pairs_in_sample=sum(r['project_id'] in IDS for r in oldrows),
        max_assessments=30,max_calls=18,catalog_only_calls=3,discovery_calls=5,max_assessment_calls=10,
        discovery_prompt_characters=prompts,token_estimates=None,token_estimates_status='NOT_AVAILABLE',
        baseline_untouched=True,inference_performed=False))
    return verify()


def record_path(phase,pid):return OUT/'records'/phase/(pid+'.json')


def call(phase,project,profiles,request,schema,gate,runner=None):
    path=record_path(phase,project['project_id'])
    if path.exists():return read(path)
    runs=OUT/phase/'codex_runs'
    if (runs/project['project_id']).exists():raise ValueError('UNCERTAIN_OUTCOME: inspect original attempt, do not repeat')
    plan=read(OUT/'plan.json')
    if sum(len(read(p)['calls']) for p in (OUT/'records').glob('*/*.json'))>=plan['maximum_new_calls']:
        raise ValueError('Experiment call budget exhausted')
    provider=CodexCliAssessmentProvider(runs,OUT/schema,lambda p,i:request,command=plan['runtime']['command'],
        runner=runner,timeout=plan['timeout_seconds'],model=plan['requested_model'],max_retries=0,
        max_indicators=3,wrapper_validator=gate,execution_id=plan['execution_id'],stop_on_uncertain=True)
    error=None
    with Measurement() as total:
        try:provider.evaluate(dict(project_id=project['project_id'],fields=project['fields']),profiles)
        except Exception as exc:error=type(exc).__name__+': '+str(exc)[:500]
    artifacts={}
    for p in (runs/project['project_id']).glob('attempt_*/*'):
        if p.is_file():artifacts[p.relative_to(OUT).as_posix()]=sha256(p)
    result=dict(project_id=project['project_id'],phase=phase,wrapper=provider.last_output,
        calls=provider.calls,status='ERROR' if error else 'VALID',error=error,
        request_sha256=canonical_hash(request),artifact_hashes=artifacts,project_total=total.result)
    write_json(path,result)
    if error:raise ValueError('Experiment stopped; original error recorded: '+error)
    return result


def requests(plan,phase,pid,rubrics):
    profiles=plan['profiles']
    if phase.startswith('catalog_'):
        n=int(phase.split('_')[1])-1
        subset=dict(list(sorted(profiles.items()))[n*16:(n+1)*16])
        p=dict(project_id=v3.CATALOG_ID,fields={f:None for f in FIELDS})
        return p,[dict(indicator_id=v3.CATALOG_ID)],v3.make_rubric_input(subset),'rubric.schema.json',lambda w,pi,ids:v3.validate_rubric_wrapper(w,subset)
    p=next(p for p in plan['projects'] if p['project_id']==pid)
    if phase=='discovery':
        return p,[dict(indicator_id=gd.MARKER)],gd.make_input(p,profiles,plan['rules']),'discovery.schema.json',lambda w,pi,ids:gd.validate_selection(w,p,profiles)
    discovery=gd.validate_selection(read(record_path('discovery',pid))['wrapper'],p,profiles)
    n=int(phase.split('_')[1])-1
    selected=discovery['prioritized_ids'][n*3:(n+1)*3]
    chosen=[profiles[i] for i in selected]
    req=v3.make_input(dict(project_id=pid,fields=p['fields']),chosen,plan['rules'],rubrics)
    def validate(w,pi,ids):
        v3.validate_wrapper(w,pid,selected)
        for a in w['assessments']:
            errors=v3.validate(p['fields'],profiles[a['indicator_id']],{k:v for k,v in a.items() if k!='indicator_id'},rubrics[a['indicator_id']])
            if errors:raise ValueError('INVALID_ASSESSMENT: '+str(errors))
    return p,chosen,req,'assessment.schema.json',validate


def frozen_rubrics(plan):
    combined={}
    for n in range(1,4):
        subset=dict(list(sorted(plan['profiles'].items()))[(n-1)*16:n*16])
        path=record_path('catalog_'+str(n),v3.CATALOG_ID)
        if not path.exists():return None
        combined.update(v3.validate_rubric_wrapper(read(path)['wrapper'],subset))
    if (OUT/'rubrics.json').exists() and read(OUT/'rubrics.json')!=combined:raise ValueError('Catalog rubric drift')
    return combined


def execute(authorization,runner=None):
    before=verify();plan=read(OUT/'plan.json');auth=read(authorization)
    if (auth.get('plan_sha256')!=sha256(OUT/'plan.json') or auth.get('institutional_text_authorized') is not True
        or auth.get('project_ids')!=IDS or auth.get('phases')!=PHASES or auth.get('maximum_new_calls')!=18
        or any(not isinstance(auth.get(k),str) or not auth[k].strip() for k in ('authorized_by','authorized_at','authorization_reference'))):
        raise ValueError('BLOCKED: new authorization bound to five-project V3 study required')
    runtime=inspect_runtime(plan['runtime']['command'])
    if any(runtime[k]!=plan['runtime'][k] for k in ('command','cli_version','executable_hashes','exec_help_sha256','features_sha256')):
        raise ValueError('Runtime drift; no inference permitted')
    with baseline._lock(OUT):
        write_json(OUT/'authorization.used.json',auth)
        for n in range(1,4):
            args=requests(plan,'catalog_'+str(n),v3.CATALOG_ID,None)
            call('catalog_'+str(n),*args,runner=runner)
        rubrics=frozen_rubrics(plan)
        if not (OUT/'rubrics.json').exists():write_json(OUT/'rubrics.json',rubrics)
        for p in plan['projects']:
            pid=p['project_id'];completion=OUT/'completed'/(pid+'.json')
            if completion.exists():continue
            call('discovery',*requests(plan,'discovery',pid,rubrics),runner=runner)
            discovery=gd.validate_selection(read(record_path('discovery',pid))['wrapper'],p,plan['profiles'])
            for n in range(0,len(discovery['prioritized_ids']),3):
                phase='assessment_'+str(n//3+1)
                call(phase,*requests(plan,phase,pid,rubrics),runner=runner)
            paths=[x for x in (OUT/'records').glob('*/*') if x.stem==pid]
            write_json(completion,dict(project_id=pid,record_hashes={x.relative_to(OUT).as_posix():sha256(x) for x in paths}))
    result=verify();result['new_calls_this_invocation']=result['calls']-before['calls'];return result


def verify():
    manifest=read(OUT/'manifest.json');plan=read(OUT/'plan.json')
    assert sha256(OUT/'plan.json')==manifest['plan_sha256'],'Frozen study plan changed'
    verify_hashes(OUT,manifest['prepared_hashes']);verify_hashes(ROOT,plan['source_hashes']);verify_hashes(ROOT,plan['code_hashes'])
    rubrics=frozen_rubrics(plan)
    calls=[];assessments=[];discovered=[]
    for path in sorted((OUT/'records').glob('*/*.json')):
        r=read(path);assert r['status']=='VALID', 'Recorded failed/invalid phase requires review'
        verify_hashes(OUT,r['artifact_hashes'])
        p,profiles,request,schema,gate=requests(plan,r['phase'],r['project_id'],rubrics)
        gate(r['wrapper'],r['project_id'],[i['indicator_id'] for i in profiles])
        assert r['request_sha256']==canonical_hash(request)
        callpath=OUT/r['phase']/'codex_runs'/r['project_id']/'attempt_1'
        assert read(callpath/'response.json')==r['wrapper']
        assert r['calls']==[read(callpath/'call.json')]
        c=r['calls'][0]
        assert c['execution_id']==plan['execution_id'] and c['successful_transport'] and c['response_sha256']==sha256(callpath/'response.json')
        assert c['prompt_sha256']==__import__('hashlib').sha256(request['prompt'].encode()).hexdigest()
        assert c['schema_sha256']==sha256(OUT/schema)
        expected=CodexCliAssessmentProvider(OUT/r['phase']/'codex_runs',OUT/schema,lambda p,i:request,
            command=plan['runtime']['command'],timeout=plan['timeout_seconds'],model=plan['requested_model'],
            max_retries=0,max_indicators=3,wrapper_validator=gate,execution_id=plan['execution_id'],stop_on_uncertain=True)
        assert c['arguments']==expected.arguments(callpath,callpath/'response.json'),'Transport configuration drift'
        assert (callpath/'prompt.txt').read_text(encoding='utf-8')==request['prompt']
        assert c['events_sha256']==sha256(callpath/'events.jsonl') and c['stderr_sha256']==sha256(callpath/'stderr.txt')
        calls+=r['calls']
        if r['phase']=='discovery':discovered.append(gd.validate_selection(r['wrapper'],p,plan['profiles']))
        elif r['phase'].startswith('assessment_'):
            for a in r['wrapper']['assessments']:
                row=v3.indicator_row(p,plan['profiles'][a['indicator_id']],{k:v for k,v in a.items() if k!='indicator_id'},rubrics[a['indicator_id']])
                selected=gd.validate_selection(read(record_path('discovery',p['project_id']))['wrapper'],p,plan['profiles'])
                origin=next(c['candidate_source'] for c in selected['candidates'] if c['indicator_id']==a['indicator_id'])
                row.update(candidate_origin=origin,discovered_by=gd.VERSION)
                assessments.append(row)
    assert len({(r['project_id'],r['indicator_id']) for r in assessments})==len(assessments),'Duplicate study pair'
    completed=[]
    for path in sorted((OUT/'completed').glob('*.json')):
        r=read(path);verify_hashes(OUT,r['record_hashes'])
        assert r['project_id'] in IDS and r['project_id']==path.stem
        screen=next(x for x in discovered if x['project_id']==r['project_id'])
        actual={a['indicator_id'] for a in assessments if a['project_id']==r['project_id']}
        assert actual==set(screen['prioritized_ids']),'Completed project missing prioritized assessment'
        completed.append(path.stem)
    usage=[usage_metrics(c) for c in calls]
    metrics={key:sum(x[key]['value'] for x in usage) if usage and all(x[key]['value'] is not None for x in usage) else None
        for key in ('input_tokens','output_tokens','cached_tokens','total_tokens')}
    result=dict(status='PASS',experiment='V3_PRIVATE_PENDING_HUMAN_REVIEW',projects_completed=completed,calls=len(calls),
        rubric_count=len(rubrics or {}),assessments=len(assessments),decisions=dict(Counter(r['decision'] for r in assessments)),
        tokens=metrics,baseline_unchanged=True,human_acceptance=False,official_publication=False)
    write_json(OUT/'verification.json',result)
    write_json(OUT/'discovery_results.json',dict(projects=discovered))
    (OUT/'assessment_results.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in assessments),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','verify','execute'])
    parser.add_argument('--authorization',type=Path)
    args=parser.parse_args()
    if args.command=='execute' and not args.authorization:parser.error('--authorization required')
    result=prepare() if args.command=='prepare' else execute(args.authorization) if args.command=='execute' else verify()
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
