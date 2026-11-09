"""Closure controls around the existing coordinator call(); no semantic changes.

Each execution consumes a separately fingerprinted one-call authorization.
Preparation and status are offline. Existing pilot responses remain immutable.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from layer4_evaluation.indicators import assessment_v3 as v3, global_discovery_v3_3 as gd
from layer4_evaluation.indicators.experiment_inputs import read, sha256, verify_hashes
from layer4_evaluation.indicators.performance import usage_metrics
from layer4_evaluation.indicators.selection import canonical_hash
from layer4_evaluation.paths import resolve

spec=importlib.util.spec_from_file_location('pilot_control',ROOT/'scripts/run_layer4_pilot_discovery_v3_3.py')
pilot=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot)
c=pilot.c
STUDY=pilot.STUDY
OUT=STUDY/'cierre_homogeneo_v3_3'
write=pilot.write
require=pilot.require


def prepare():
    if (OUT/'closure.plan.json').exists():return check()
    preparation=read(STUDY/'preparacion_cierre_v3_3.plan.json')
    verify_hashes(ROOT,preparation['protected_hashes'])
    source=read(resolve(ROOT,preparation['source_plan']))
    old=read(pilot.ACTIVE/'plan.json');rubrics=read(pilot.ACTIVE/'rubrics.json')
    require(source['profiles']==old['profiles'] and source['rules']==old['rules'],'Source semantics differ')
    projects={x['project']['project_id']:x['project'] for x in source['projects']}
    require(set(projects)==set(preparation['scope']) and len(projects)==20,'Official twenty differ')
    require(len(old['profiles'])==len(rubrics)==48,'Catalog differs')
    for iid,profile in old['profiles'].items():v3.check_rubric(profile,rubrics[iid])
    selections={};reused={};protected=dict(preparation['protected_hashes'])
    for item in preparation['reuse_discovery']:
        pid=item['project_id'];path=resolve(ROOT,item['response_path'])
        require(sha256(path)==item['response_sha256'],'Existing discovery response differs')
        gd.validate_selection(read(path),projects[pid],old['profiles'])
        selections[pid]=path.relative_to(ROOT).as_posix()
        protected[path.relative_to(ROOT).as_posix()]=sha256(path)
    for pid in ('PROJ_20456','PROJ_21299'):
        require(pilot.verify(pilot.directory(pid))['status']=='PASS','Pilot discovery blocked')
        path=pilot.directory(pid)/'discovery/codex_runs'/pid/'attempt_1/response.json'
        selections[pid]=path.relative_to(ROOT).as_posix();protected[selections[pid]]=sha256(path)
    for pid in ('PROJ_20022','PROJ_20456','PROJ_21299'):
        if pid=='PROJ_20022':
            p=dict(project=projects[pid],project_ids=[pid],profiles=old['profiles'],rules=old['rules'],
                assessment_records=sorted(f.relative_to(ROOT).as_posix() for f in (pilot.ACTIVE/'records').glob('assessment_*/*.json') if f.stem==pid),
                rubric_hashes={i:r['rubric_sha256'] for i,r in rubrics.items()})
        else:p=pilot.check(pilot.directory(pid))
        available=pilot.candidate_rows(p)
        selected=gd.validate_selection(read(ROOT/selections[pid]),projects[pid],old['profiles'])['prioritized_ids']
        for iid in selected:
            if iid in available:reused[pid+'|'+iid]=available[iid]
    code=[Path(__file__),ROOT/'scripts/run_layer4_pilot_discovery_v3_3.py',ROOT/'scripts/run_layer4_coverage_v3.py']
    code+=list((ROOT/'src/layer4_evaluation/indicators').glob('*.py'))+[ROOT/'src/layer4_evaluation/paths.py']
    for p in code:protected[p.relative_to(ROOT).as_posix()]=sha256(p)
    observations=read(STUDY/'preparacion_cierre_v3_3.consumo.json')['observed_v33_calls']
    ratio=max(x['input_tokens']/x['prompt_characters'] for x in observations)
    plan=dict(execution_id=uuid.uuid4().hex,prepared_at=datetime.now(timezone.utc).isoformat(),
        project_ids=preparation['scope'],projects=projects,profiles=old['profiles'],rubrics=rubrics,rules=old['rules'],
        discovery_version=gd.VERSION,assessment_version=v3.VERSION,formula='100 * (0.55S + 0.45K)',
        compact_active=False,proposal_v3_4_active=False,runtime=old['runtime'],requested_model=old['requested_model'],
        batches=preparation['batches'],budgets=preparation['call_token_budgets'],total_cap=preparation['total_token_reservation_cap'],
        maximum_calls=preparation['maximum_new_calls'],observed_character_ratio=ratio,
        source_hashes=protected,selections=selections,reused=reused,publication_allowed=False)
    write(OUT/'closure.plan.json',plan)
    write(OUT/'closure.manifest.json',dict(plan_sha256=sha256(OUT/'closure.plan.json')))
    return check()


def check():
    plan=read(OUT/'closure.plan.json')
    require(sha256(OUT/'closure.plan.json')==read(OUT/'closure.manifest.json')['plan_sha256'],'Closure plan changed')
    verify_hashes(ROOT,plan['source_hashes'])
    require(plan['discovery_version']==gd.VERSION and plan['assessment_version']==v3.VERSION and
        len(plan['profiles'])==48 and not plan['compact_active'] and not plan['proposal_v3_4_active'],'Frozen configuration differs')
    return plan


def discovery_path(plan,pid):
    if pid in plan['selections']:return ROOT/plan['selections'][pid]
    path=OUT/pid/'closure_discovery/records/discovery'/(pid+'.json')
    return path if path.exists() else None


def canonical_sal05(wrapper,project,profiles):
    """Authorized metadata-only derivation; never infer or change an LLM decision."""
    require(project['project_id']=='PROJ_22292','Recovery outside authorized project')
    official=[p for p in gd.historical.catalog(profiles) if p['indicator_id']=='SAL-05']
    require(len(official)==1 and official[0]['indicator_category']=='IMPACTO_MAS_ALLA_ACADEMIA','Ambiguous authoritative category')
    matches=[x for x in wrapper['assessments'][0]['rejected'] if x['indicator_id']=='SAL-05']
    require(len(matches)==1 and matches[0]['indicator_category']=='IMPACTO_MAS_ALLA_ACMIA','Not the authorized metadata error')
    derived=deepcopy(wrapper)
    item=next(x for x in derived['assessments'][0]['rejected'] if x['indicator_id']=='SAL-05')
    item['indicator_category']=official[0]['indicator_category']
    selection=gd.validate_selection(derived,project,profiles)
    return derived,selection


def recovered_discovery(plan,out):
    """Read an exact audited derivation; retain the original ERROR and its cost."""
    proof_path=out/'recovery.json'
    if not proof_path.exists():return None
    proof=read(proof_path)
    require(proof.get('status')=='VALID_METADATA_DERIVATION' and proof.get('new_inference_calls')==0,'Recovery proof invalid')
    paths=[out/'records/discovery/PROJ_22292.json',out/'verification.json',out/'plan.json',out/'manifest.json',out/'schema.json',
        out/'authorization.json',out/'authorization.used.json',out/'dispatch.claim.json',OUT/'closure.plan.json']
    paths+=list((out/'discovery/codex_runs/PROJ_22292/attempt_1').glob('*'))
    expected={p.relative_to(ROOT).as_posix() for p in paths if p.is_file()}
    require(set(proof['source_hashes'])==expected,'Incomplete original recovery fingerprints')
    verify_hashes(ROOT,proof['source_hashes'])
    require(sha256(out/'response.canonical.json')==proof['derived_response_sha256'],'Derived response changed')
    record=read(out/'records/discovery/PROJ_22292.json');verification=read(out/'verification.json');cp=read(out/'plan.json')
    require(record['status']=='ERROR' and record['wrapper'] is None and len(record['calls'])==1,'Unexpected original outcome')
    call=record['calls'][0];attempt=out/'discovery/codex_runs/PROJ_22292/attempt_1'
    require(read(attempt/'call.json')==call and call['exit_status']==0 and call['retry']==0 and
        call['technical_error']=='ValueError: Discovery category does not match published catalog','Other transport/validation failure cannot be recovered')
    verify_hashes(out,record['artifact_hashes'])
    require(call['response_sha256']==sha256(attempt/'response.json'),'Native response fingerprint differs')
    require(verification['status']=='BLOCKED_ERROR' and verification['calls']==1 and verification['retries']==0,'Original QA differs')
    require(all(type(verification['tokens'].get(k)) is int and verification['tokens'][k]>=0 for k in ('input_tokens','output_tokens','total_tokens')) and
        verification['tokens']['total_tokens']<=min(cp['reservation'],plan['budgets']['discovery_postcall_review_threshold']) and
        isinstance(verification['wall_seconds'],(int,float)) and verification['wall_seconds']>0,'Usage missing or budget requires separate review')
    project=plan['projects']['PROJ_22292'];request=gd.make_input(project,plan['profiles'],plan['rules'])
    require(record['request_sha256']==cp['request_sha256']==canonical_hash(request) and
        (attempt/'prompt.txt').read_text(encoding='utf-8')==request['prompt'],'Original semantic input differs')
    require(read(out/'schema.json')==gd.selection_schema(),'Discovery contract differs')
    manifest=read(out/'manifest.json')
    require(sha256(out/'plan.json')==manifest['plan_sha256'] and sha256(out/'schema.json')==manifest['schema_sha256'],'Original call manifest differs')
    auth=read(out/'authorization.used.json')
    require(auth.get('authorized') is True and auth['project_ids']==['PROJ_22292'] and auth['phase']=='discovery' and
        auth['maximum_new_calls']==1 and auth['max_retries']==0 and auth['plan_sha256']==sha256(out/'plan.json') and
        auth['request_sha256']==cp['request_sha256'] and auth==read(out/'authorization.json') and
        read(out/'dispatch.claim.json')['authorization_sha256']==sha256(out/'authorization.json'),'Original independent authorization differs')
    expected_wrapper,selection=canonical_sal05(read(attempt/'response.json'),project,plan['profiles'])
    require(read(out/'response.canonical.json')==expected_wrapper,'Derivation changes more than the authorized category')
    require(proof['profile_sha256']==canonical_hash(plan['profiles']['SAL-05']),'Authoritative profile differs')
    return expected_wrapper,selection


def territorial_check():
    """Consume accepted territorial data; historical PNG completeness is separate."""
    from layer4_evaluation.territorial_consumption import verify_consumption
    plan=read(OUT/'closure.plan.json')
    return verify_consumption(ROOT,selected=list(plan['projects'].values()))


def project_status(plan,pid):
    path=discovery_path(plan,pid)
    result=dict(project_id=pid,discovery_complete=False,selected=[],rows=[],pending=[],complete=False)
    if path is None:return result
    value=read(path)
    if 'wrapper' in value:
        verification=path.parents[2]/'verification.json'
        recovery=recovered_discovery(plan,path.parents[2]) if pid=='PROJ_22292' else None
        if recovery is not None:value=recovery[0]
        else:
            require(verification.exists() and read(verification)['status']=='PASS','Discovery QA incomplete or blocked')
            require(value['status']=='VALID','Discovery failure; no automatic retry');value=value['wrapper']
    selected=gd.validate_selection(value,plan['projects'][pid],plan['profiles'])['prioritized_ids']
    rows={iid:plan['reused'][pid+'|'+iid]['row'] for iid in selected if pid+'|'+iid in plan['reused']}
    for record in (OUT/pid).glob('closure_assessment_*/records/assessment/*.json'):
        verification=record.parents[2]/'verification.json'
        require(verification.exists() and read(verification)['status']=='PASS','Assessment QA incomplete or blocked')
        item=read(record);require(item['status']=='VALID','Assessment failure; no automatic retry')
        for assessment in item['wrapper']['assessments']:
            iid=assessment['indicator_id'];require(iid in selected and iid not in rows,'Duplicate/unselected assessment')
            row=v3.indicator_row(plan['projects'][pid],plan['profiles'][iid],
                {k:v for k,v in assessment.items() if k!='indicator_id'},plan['rubrics'][iid])
            require(row['assessment_validation_status']=='VALID','Invalid saved assessment')
            row.update(discovered_by=gd.VERSION,assessment_execution_id=item['calls'][0]['execution_id'],
                       assessment_record=record.relative_to(ROOT).as_posix())
            rows[iid]=row
    result.update(discovery_complete=True,selected=selected,rows=list(rows.values()),
        pending=[iid for iid in selected if iid not in rows],complete=all(iid in rows for iid in selected))
    return result


def batch_number(plan,pid):
    return next(b['batch'] for b in plan['batches'] if pid in b['project_ids'])


def budget_status(plan):
    used={b['batch']:dict(tokens=0,calls=0) for b in plan['batches']}
    for pid in ('PROJ_20456','PROJ_21299'):
        v=read(pilot.directory(pid)/'verification.json')
        require(v['status']=='PASS','Prior discovery did not pass')
        used[1]['tokens']+=v['tokens']['total_tokens'];used[1]['calls']+=1
    for path in OUT.glob('PROJ_*/closure_*/verification.json'):
        v=read(path)
        recovered=v['project_id']=='PROJ_22292' and v['phase']=='discovery' and recovered_discovery(plan,path.parent) is not None
        require(v['status']=='PASS' or recovered,'Closure halted: review failed/over-budget call '+str(path))
        number=batch_number(plan,v['project_id']);used[number]['tokens']+=v['tokens']['total_tokens'];used[number]['calls']+=1
    return used


def next_call(plan,pid):
    require(pid in plan['projects'],'Project outside official twenty')
    territorial_check()
    used=budget_status(plan)
    number=batch_number(plan,pid)
    for batch in plan['batches']:
        if batch['batch']<number:
            require(all(project_status(plan,p)['complete'] for p in batch['project_ids']),'Previous batch incomplete')
    state=project_status(plan,pid)
    if state['complete']:return None
    if not state['discovery_complete']:phase='discovery';ids=[];name='closure_discovery'
    else:
        phase='assessment';ids=state['pending'][:3]
        existing=[p for p in (OUT/pid).glob('closure_assessment_*') if (p/'verification.json').exists()]
        name='closure_assessment_'+str(len(existing)+1)
    # Never create another attempt if an earlier attempt has an uncertain outcome.
    for folder in (OUT/pid).glob('closure_*'):
        if (folder/'dispatch.claim.json').exists() and not (folder/'verification.json').exists():
            raise ValueError('UNCERTAIN_OUTCOME: inspect existing claim; never retry')
    project=plan['projects'][pid]
    if phase=='discovery':request=gd.make_input(project,plan['profiles'],plan['rules'])
    else:request=v3.make_input(dict(project_id=pid,fields=project['fields']),[plan['profiles'][i] for i in ids],plan['rules'],plan['rubrics'])
    reservation=plan['budgets'][phase+'_reservation']
    estimate=math.ceil(len(request['prompt'])*plan['observed_character_ratio']*1.25)+12000
    require(estimate<=reservation,'Estimated request exceeds reservation; no truncation')
    batch=next(b for b in plan['batches'] if b['batch']==number)
    require(used[number]['tokens']+reservation<=batch['token_reservation_cap'],'Batch token reservation exhausted')
    require(sum(v['tokens'] for v in used.values())+reservation<=plan['total_cap'],'Global token reservation exhausted')
    require(used[number]['calls']<batch['maximum_new_calls'] and sum(v['calls'] for v in used.values())<plan['maximum_calls'],'Call budget exhausted')
    return dict(project_id=pid,batch=number,phase=phase,indicator_ids=ids,out=OUT/pid/name,
                request=request,reservation=reservation,estimated_tokens=estimate)


def prepare_call(pid):
    plan=check();task=next_call(plan,pid)
    if task is None:return dict(status='COMPLETE',project_id=pid)
    out=task['out'];out.mkdir(parents=True,exist_ok=True)
    path=out/'plan.json'
    callplan=dict(project_id=pid,phase=task['phase'],indicator_ids=task['indicator_ids'],batch=task['batch'],
        execution_id=plan['execution_id'],maximum_new_calls=1,max_retries=0,runtime=plan['runtime'],
        timeout_seconds=900,requested_model=plan['requested_model'],closure_plan_sha256=sha256(OUT/'closure.plan.json'),
        request_sha256=canonical_hash(task['request']),reservation=task['reservation'],estimated_tokens=task['estimated_tokens'])
    if path.exists():require(read(path)==callplan,'Prepared call differs')
    else:
        write(path,callplan)
        schema=gd.selection_schema() if task['phase']=='discovery' else v3.schemas()['assessment_batch']
        write(out/'schema.json',schema)
        write(out/'manifest.json',dict(plan_sha256=sha256(path),schema_sha256=sha256(out/'schema.json')))
        write(out/'authorization.example.json',dict(authorized=False,project_ids=[pid],phase=task['phase'],
            indicator_ids=task['indicator_ids'],plan_sha256=sha256(path),request_sha256=callplan['request_sha256'],
            maximum_new_calls=1,max_retries=0,token_budget=task['reservation'],authorized_by='',authorized_at='',authorization_reference=''))
    return dict(status='PREPARED',out=str(out),**{k:callplan[k] for k in ('project_id','phase','indicator_ids','reservation','estimated_tokens')})


def execute(out,authorization,runner=None):
    out=Path(out).resolve();plan=check();cp=read(out/'plan.json');pid=cp['project_id'];phase=cp['phase']
    require(out.is_relative_to(OUT.resolve()/pid),'Call directory outside project')
    if (out/'verification.json').exists():return read(out/'verification.json')
    task=next_call(plan,pid)
    require(task is not None and task['out'].resolve()==out,'Only the exact next pending work may execute')
    manifest=read(out/'manifest.json')
    require(sha256(out/'plan.json')==manifest['plan_sha256'] and sha256(out/'schema.json')==manifest['schema_sha256'],'Call manifest changed')
    require(cp['closure_plan_sha256']==sha256(OUT/'closure.plan.json') and cp['request_sha256']==canonical_hash(task['request']),'Call input changed')
    auth=read(authorization)
    for key,expected in dict(authorized=True,project_ids=[pid],phase=phase,indicator_ids=cp['indicator_ids'],
        plan_sha256=sha256(out/'plan.json'),request_sha256=cp['request_sha256'],maximum_new_calls=1,max_retries=0,token_budget=task['reservation']).items():
        require(auth.get(key)==expected,'Independent authorization mismatch: '+key)
    require(all(isinstance(auth.get(k),str) and auth[k].strip() for k in ('authorized_by','authorized_at','authorization_reference')),'Authorization reference missing')
    if runner is None:
        runtime=c.inspect_runtime(plan['runtime']['command'])
        require(all(runtime[k]==plan['runtime'][k] for k in ('command','cli_version','executable_hashes','exec_help_sha256','features_sha256')),'CLI runtime drift')
    require(not (out/phase/'codex_runs'/pid).exists(),'Original attempt exists; never retry')
    with (out/'dispatch.claim.json').open('x',encoding='utf-8') as handle:
        json.dump(dict(authorization_sha256=sha256(authorization),project_id=pid,phase=phase),handle)
    write(out/'authorization.used.json',auth)
    ids=cp['indicator_ids'];project=plan['projects'][pid]
    def gate(wrapper,project_id,indicator_ids):
        if phase=='discovery':
            require(project_id==pid and indicator_ids==[gd.MARKER],'Discovery envelope differs')
            gd.validate_selection(wrapper,project,plan['profiles'])
        else:
            require(project_id==pid and indicator_ids==ids,'Assessment envelope differs')
            v3.validate_wrapper(wrapper,pid,ids)
            for a in wrapper['assessments']:
                errors=v3.validate(project['fields'],plan['profiles'][a['indicator_id']],
                    {k:v for k,v in a.items() if k!='indicator_id'},plan['rubrics'][a['indicator_id']])
                require(not errors,'Invalid assessment: '+str(errors))
    profiles=[dict(indicator_id=gd.MARKER)] if phase=='discovery' else [plan['profiles'][i] for i in ids]
    with pilot.coordinator_directory(out):
        try:c.call(phase,project,profiles,task['request'],'schema.json',gate,runner=runner)
        except Exception:
            if not c.record_path(phase,pid).exists():raise
        record=read(c.record_path(phase,pid))
    metrics=usage_metrics(record['calls'][0]) if len(record['calls'])==1 else {}
    tokens={k:metrics.get(k,{}).get('value') for k in ('input_tokens','output_tokens','total_tokens')}
    wall=record['calls'][0].get('performance',{}).get('wall_seconds',{}).get('value') if record['calls'] else None
    status='PASS'
    if record['status']!='VALID' or len(record['calls'])!=1:status='BLOCKED_ERROR'
    elif wall is None or any(v is None for v in tokens.values()):status='BLOCKED_MISSING_METRICS'
    elif tokens['total_tokens']>task['reservation']:status='BLOCKED_TOKEN_BUDGET'
    elif tokens['total_tokens']>plan['budgets'][phase+'_postcall_review_threshold']:status='PAUSED_TOKEN_REVIEW'
    verify_hashes(out,record['artifact_hashes']);verify_hashes(ROOT,plan['source_hashes'])
    result=dict(status=status,error=record['error'],project_id=pid,phase=phase,indicator_ids=ids,calls=len(record['calls']),
        retries=0,tokens=tokens,wall_seconds=wall,assessments_dispatched=len(ids),further_dispatch_allowed=False)
    write(out/'verification.json',result)
    return result


def status():
    plan=check();projects=[project_status(plan,p) for p in plan['project_ids']]
    result=dict(projects=projects,budgets=budget_status(plan),publication_performed=False)
    write(OUT/'closure.status.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','prepare-call','execute','status'])
    parser.add_argument('--project');parser.add_argument('--out',type=Path);parser.add_argument('--authorization',type=Path)
    args=parser.parse_args()
    if args.command=='prepare':p=prepare();value=dict(status='PREPARED',projects=len(p['projects']),reusable=len(p['reused']))
    elif args.command=='prepare-call':value=prepare_call(args.project)
    elif args.command=='execute':value=execute(args.out,args.authorization)
    else:value=status()
    print(json.dumps(value,ensure_ascii=False,indent=2))
    if value.get('status','PASS').startswith(('BLOCKED','PAUSED')):raise SystemExit(2)
