"""One independently authorized V3.3 discovery; reuse comparison is offline only.

Wrap the frozen coordinator's call(), not execute(). Never dispatch assessments.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from layer4_evaluation.indicators import global_discovery_v3_3 as gd, assessment_v3 as v3
from layer4_evaluation.indicators.experiment_inputs import read, sha256, verify_hashes
from layer4_evaluation.indicators.performance import usage_metrics
from layer4_evaluation.indicators.selection import canonical_hash
from layer4_evaluation.paths import resolve, legacy

STUDY = ROOT/'outputs/layer4/pruebas/validacion_v3_3'
ACTIVE = STUDY/'continuacion_prompt_v3_1'
PROJECTS = ('PROJ_20456','PROJ_21299')
spec = importlib.util.spec_from_file_location('frozen_discovery_coordinator', ROOT/'scripts/run_layer4_coverage_v3.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.pending')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temp.replace(path)


def directory(pid):
    require(pid in PROJECTS, 'Project outside the two-project scope')
    return STUDY/'cierre_homogeneo_v3_3'/pid


@contextmanager
def coordinator_directory(out):
    previous = c.OUT
    c.OUT = out
    try:
        yield
    finally:
        c.OUT = previous


def candidate_rows(plan):
    """Reproduce saved inputs/validation, not semantic decisions or inference."""
    historical = read(ACTIVE/'plan.json')
    rubrics = read(ACTIVE/'rubrics.json')
    rows = [json.loads(line) for line in (STUDY/'pilot_five.assessment_results.jsonl').read_text(encoding='utf-8').splitlines() if line]
    by_pair = {(r['project_id'],r['indicator_id']):r for r in rows}
    require(len(by_pair)==len(rows), 'Duplicate historical assessment pair')
    recovered = {}
    for name in plan['assessment_records']:
        path = resolve(ROOT,name)
        record = read(path)
        require(record['status']=='VALID' and record['project_id']==plan['project_ids'][0], 'Invalid historical assessment record')
        verify_hashes(ACTIVE, record['artifact_hashes'])
        phase = record['phase']
        attempt = ACTIVE/phase/'codex_runs'/record['project_id']/'attempt_1'
        call = read(attempt/'call.json')
        require(record['calls']==[call] and call['successful_transport'], 'Historical call mismatch')
        require(call['execution_id']==historical['execution_id'], 'Historical execution mismatch')
        saved_prompt = (attempt/'prompt.txt').read_text(encoding='utf-8')
        payload = json.loads(saved_prompt.split('\nINPUT_JSON:\n',1)[1])
        ids = [p['indicator_id'] for p in payload['indicators']]
        req = v3.make_input(dict(project_id=plan['project']['project_id'],fields=plan['project']['fields']),
            [plan['profiles'][iid] for iid in ids], plan['rules'], rubrics)
        require(req['prompt']==saved_prompt and canonical_hash(req)==record['request_sha256'], 'Assessment semantic input differs')
        require(call['prompt_sha256']==__import__('hashlib').sha256(saved_prompt.encode()).hexdigest(), 'Historical prompt hash mismatch')
        require(call['schema_sha256']==sha256(ACTIVE/'assessment.schema.json'), 'Historical schema hash mismatch')
        require(read(ACTIVE/'assessment.schema.json')==v3.schemas()['assessment_batch'], 'Assessment contract changed')
        require(call['response_sha256']==sha256(attempt/'response.json') and read(attempt/'response.json')==record['wrapper'], 'Historical response mismatch')
        require(call['events_sha256']==sha256(attempt/'events.jsonl') and call['stderr_sha256']==sha256(attempt/'stderr.txt'), 'Historical log hash mismatch')
        v3.validate_wrapper(record['wrapper'],plan['project']['project_id'],ids)
        for assessment in record['wrapper']['assessments']:
            iid = assessment['indicator_id']
            require(iid not in recovered, 'Multiple historical assessments require explicit resolution')
            require(rubrics[iid]['rubric_sha256']==plan['rubric_hashes'][iid], 'Rubric content/version changed')
            v3.check_rubric(plan['profiles'][iid],rubrics[iid])
            computed = v3.indicator_row(plan['project'],plan['profiles'][iid],
                {k:v for k,v in assessment.items() if k!='indicator_id'},rubrics[iid])
            require(computed['assessment_validation_status']=='VALID', 'Historical citations/temporal support invalid')
            original = by_pair.get((plan['project']['project_id'],iid))
            require(original is not None and all(original.get(k)==v for k,v in computed.items()), 'Historical row/confidence differs')
            require(original['assessment_version']==v3.VERSION, 'V2 cannot be transferred into V3')
            recovered[iid] = dict(row=original,proof=dict(original_record=name,original_record_sha256=sha256(path),
                original_execution_id=call['execution_id'],original_request_sha256=record['request_sha256'],
                original_response_sha256=call['response_sha256'],profile_sha256=rubrics[iid]['profile_sha256'],
                rubric_sha256=rubrics[iid]['rubric_sha256'],assessment_version=v3.VERSION,
                semantic_input_sha256=canonical_hash(dict(project=plan['project']['fields'],
                    profile=plan['profiles'][iid],rubric=rubrics[iid],rules=plan['rules'])),
                original_discovery_version=original['discovered_by']))
    return recovered


def prepare(pid, out=None):
    require(pid in PROJECTS, 'Project outside the two-project scope')
    out = Path(out) if out is not None else directory(pid)
    if (out/'plan.json').exists():
        check(out)
        return out
    require(not out.exists(), 'Uncertain preparation directory already exists')
    old = read(ACTIVE/'plan.json')
    rubrics = read(ACTIVE/'rubrics.json')
    project = next(p for p in old['projects'] if p['project_id']==pid)
    records = sorted(p.relative_to(ROOT).as_posix() for p in (ACTIVE/'records').glob('assessment_*/*.json') if p.stem==pid)
    source_paths = [ACTIVE/'plan.json',ACTIVE/'rubrics.json',ACTIVE/'assessment.schema.json',
        STUDY/'preparacion_cierre_v3_3.consumo.json',
        STUDY/'pilot_five.assessment_results.jsonl',ROOT/'outputs/layer4/final/resultado_capa4.xlsx',
        ROOT/'outputs/layer4/auditoria/cierre_v2/final_manifest.json',Path(__file__).resolve(),
        ROOT/'scripts/run_layer4_coverage_v3.py']
    source_paths += [ROOT/'src/layer4_evaluation/indicators'/n for n in ('global_discovery_v3_3.py','global_discovery.py',
        'assessment_v3.py','assessment_v2.py','confidence.py','codex_cli.py','performance.py','prompt.py')]
    hashes = {p.relative_to(ROOT).as_posix():sha256(p) for p in source_paths}
    for name in records:
        hashes[name] = sha256(ROOT/name)
        for artifact,digest in read(ROOT/name)['artifact_hashes'].items():
            hashes[(ACTIVE/artifact).relative_to(ROOT).as_posix()] = digest
    estimate_source = read(STUDY/'preparacion_cierre_v3_3.consumo.json')
    observed_ratio = max(x['input_tokens']/x['prompt_characters'] for x in estimate_source['observed_v33_calls'])
    request = gd.make_input(project,old['profiles'],old['rules'])
    plan = dict(version='PILOT_SINGLE_DISCOVERY_CONTROL_V1',execution_id=uuid.uuid4().hex,
        project_ids=[pid],project=project,profiles=old['profiles'],rules=old['rules'],
        runtime=old['runtime'],requested_model=old['requested_model'],timeout_seconds=900,
        maximum_new_calls=1,max_retries=0,maximum_assessments=0,
        discovery_version=gd.VERSION,input_version=gd.VERSION,compact_active=False,proposal_v3_4_active=False,
        assessment_version=v3.VERSION,assessment_records=records,
        formula='100 * (0.55 S + 0.45 K)',
        rubric_hashes={i:r['rubric_sha256'] for i,r in rubrics.items()},
        source_hashes=hashes,request_sha256=canonical_hash(request),
        estimated_total_tokens=math.ceil(len(request['prompt'])*observed_ratio*1.25)+12000,
        estimate_note='Observed character ratio with margin, not exact tokenization or a guaranteed upper bound',
        token_reservation=80000,postcall_review_threshold=60000,
        token_enforcement='Local pre-dispatch reservation and post-call stop; not a remote hard token cap',
        authorization_status='NOT_AUTHORIZED',official_publication_allowed=False)
    require(len(gd.historical.catalog(plan['profiles']))==48, 'Catalog differs')
    candidate_rows(plan)
    write(out/'plan.json',plan)
    write(out/'discovery.schema.json',gd.selection_schema())
    write(out/'manifest.json',dict(plan_sha256=sha256(out/'plan.json'),schema_sha256=sha256(out/'discovery.schema.json')))
    # Deliberately invalid until separately authorized. Merely supplying a path
    # or running execute is not an authorization.
    write(out/'authorization.example.json',dict(authorized=False,project_ids=[pid],phase='discovery',
        plan_sha256=sha256(out/'plan.json'),request_sha256=plan['request_sha256'],
        maximum_new_calls=1,max_retries=0,maximum_assessments=0,token_budget=80000,
        authorized_by='',authorized_at='',authorization_reference=''))
    return out


def check(out):
    plan,manifest = read(out/'plan.json'),read(out/'manifest.json')
    require(sha256(out/'plan.json')==manifest['plan_sha256'], 'Plan fingerprint changed')
    require(sha256(out/'discovery.schema.json')==manifest['schema_sha256'], 'Discovery schema changed')
    require(read(out/'discovery.schema.json')==gd.selection_schema(), 'Contract differs')
    require(plan['project_ids'] in [[p] for p in PROJECTS], 'Invalid project scope')
    require(plan['maximum_new_calls']==1 and plan['max_retries']==0 and plan['maximum_assessments']==0, 'Execution limits changed')
    require(plan['estimated_total_tokens']<=plan['token_reservation'], 'Pre-dispatch token estimate exceeds reservation; do not truncate')
    require(plan['discovery_version']==gd.VERSION and plan['input_version']==gd.VERSION and not plan['compact_active'] and not plan['proposal_v3_4_active'], 'Version drift')
    verify_hashes(ROOT,plan['source_hashes'])
    require(canonical_hash(gd.make_input(plan['project'],plan['profiles'],plan['rules']))==plan['request_sha256'], 'Request changed')
    return plan


def comparison(plan, selection, response_sha256):
    require(selection['project_id']==plan['project_ids'][0] and selection['version']==gd.VERSION, 'Selection identity/version mismatch')
    historical = candidate_rows(plan)
    entries = []
    for iid in selection['prioritized_ids']:
        item = historical.get(iid)
        entry = dict(project_id=selection['project_id'],indicator_id=iid,
            status='REUSABLE' if item else 'NEEDS_ASSESSMENT_NOT_AUTHORIZED',
            selection_version=gd.VERSION,selection_execution_id=plan['execution_id'],
            selection_response_sha256=response_sha256)
        if item:
            entry.update(assessment=item['row'],reuse_proof=item['proof'])
        entries.append(entry)
    return dict(project_id=selection['project_id'],entries=entries,
        historical_not_selected=sorted(set(historical)-set(selection['prioritized_ids'])),
        backlog_not_assessed=selection['backlog_ids'],assessments_dispatched=0,
        excluded_project_22027='V3.3 has zero candidates; historical assessments cannot enter this selection')


def verify(out):
    plan = check(out);pid=plan['project_ids'][0]
    path = out/'records/discovery'/(pid+'.json')
    require(path.exists(), 'No completed call; no automatic dispatch from verify')
    record = read(path)
    verify_hashes(out,record['artifact_hashes'])
    require(record['project_id']==pid and record['phase']=='discovery' and len(record['calls'])==1, 'Unexpected call record')
    require(len(list((out/'records').glob('*/*.json')))==1, 'More than one call/phase')
    require(len(list(out.glob('*/codex_runs/*/attempt_*/call.json')))==1, 'More than one native call')
    call=record['calls'][0];attempt=out/'discovery/codex_runs'/pid/'attempt_1'
    req=gd.make_input(plan['project'],plan['profiles'],plan['rules'])
    require(record['request_sha256']==canonical_hash(req), 'Call request differs')
    require(call['project_id']==pid and call['execution_id']==plan['execution_id'] and call['retry']==0, 'Call scope/retry differs')
    require(read(attempt/'call.json')==call and (attempt/'prompt.txt').read_text(encoding='utf-8')==req['prompt'], 'Native call/prompt differs')
    require(call['schema_sha256']==sha256(out/'discovery.schema.json'), 'Call schema differs')
    require(call['prompt_sha256']==__import__('hashlib').sha256(req['prompt'].encode()).hexdigest(), 'Prompt fingerprint differs')
    require(call['events_sha256']==sha256(attempt/'events.jsonl') and call['stderr_sha256']==sha256(attempt/'stderr.txt'), 'Native log differs')
    expected=c.CodexCliAssessmentProvider(out/'discovery/codex_runs',out/'discovery.schema.json',lambda p,i:req,
        command=plan['runtime']['command'],timeout=plan['timeout_seconds'],model=plan['requested_model'],
        max_retries=0,max_indicators=3,execution_id=plan['execution_id'],stop_on_uncertain=True)
    historical_attempt=legacy(ROOT,attempt)
    current_arguments=expected.arguments(attempt,attempt/'response.json')
    expected.schema=legacy(ROOT,expected.schema)
    require(call['arguments'] in (current_arguments,
        expected.arguments(historical_attempt,historical_attempt/'response.json')), 'Transport restrictions differ')
    metrics=usage_metrics(call)
    duration=call.get('performance',{}).get('wall_seconds',{}).get('value')
    tokens={k:metrics[k]['value'] for k in ('input_tokens','output_tokens','total_tokens')}
    status='PASS';error=None
    if record['status']!='VALID' or not call['successful_transport']:
        status,error='BLOCKED_ERROR',record['error']
    elif any(v is None for v in tokens.values()) or duration is None:
        status,error='BLOCKED_MISSING_METRICS','Missing actual tokens or duration; never retry automatically'
    elif tokens['total_tokens']>plan['token_reservation']:
        status,error='BLOCKED_TOKEN_BUDGET','Actual tokens exceed reserved budget'
    elif tokens['total_tokens']>plan['postcall_review_threshold']:
        status,error='PAUSED_TOKEN_REVIEW','Review actual consumption before any other independent authorization'
    if record['status']=='VALID':
        require(call['response_sha256']==sha256(attempt/'response.json') and read(attempt/'response.json')==record['wrapper'], 'Native response differs')
        selected=gd.validate_selection(record['wrapper'],plan['project'],plan['profiles'])
        write(out/'selection.json',selected)
        if status=='PASS':write(out/'reuse_comparison.json',comparison(plan,selected,call['response_sha256']))
    result=dict(status=status,error=error,project_id=pid,execution_id=plan['execution_id'],
        calls=1,retries=0,assessments_dispatched=0,tokens=tokens,wall_seconds=duration,
        further_dispatch_allowed=False,historical_files_unchanged=True)
    write(out/'verification.json',result)
    return result


def execute(out, authorization, runner=None):
    plan=check(out);pid=plan['project_ids'][0]
    record=out/'records/discovery'/(pid+'.json')
    if record.exists():return verify(out)  # Idempotent even after error/missing usage.
    require(authorization is not None and Path(authorization).is_file(), 'Independent authorization file required')
    auth=read(authorization)
    require(auth.get('authorized') is True and auth.get('project_ids')==[pid] and auth.get('phase')=='discovery', 'Authorization absent or project/phase mismatch')
    require(auth.get('plan_sha256')==sha256(out/'plan.json') and auth.get('request_sha256')==plan['request_sha256'], 'Authorization fingerprints mismatch')
    require(auth.get('maximum_new_calls')==1 and auth.get('max_retries')==0 and auth.get('maximum_assessments')==0, 'Authorization exceeds discovery-only scope')
    require(type(auth.get('token_budget')) is int and auth['token_budget']>=plan['token_reservation'], 'Insufficient pre-dispatch token reservation')
    require(all(isinstance(auth.get(k),str) and auth[k].strip() for k in ('authorized_by','authorized_at','authorization_reference')), 'Incomplete authorization reference')
    require(not (out/'discovery/codex_runs'/pid).exists(), 'UNCERTAIN_OUTCOME: original attempt exists; inspect instead of retry')
    # Exclusive durable claim prevents duplicate calls under concurrent invocations
    # or a crash before a record is finished. Never remove this claim to retry.
    try:
        with (out/'dispatch.claim.json').open('x',encoding='utf-8') as handle:
            json.dump(dict(project_id=pid,execution_id=plan['execution_id'],authorization_sha256=sha256(Path(authorization))),handle)
    except FileExistsError:
        raise ValueError('UNCERTAIN_OUTCOME: authorization already claimed; no new dispatch')
    write(out/'authorization.used.json',auth)
    if runner is None:
        for name,digest in plan['runtime']['executable_hashes'].items():
            require(sha256(Path(name))==digest,'CLI executable drift')
    req=gd.make_input(plan['project'],plan['profiles'],plan['rules'])
    def gate(wrapper,project_id,ids):
        require(project_id==pid and ids==[gd.MARKER], 'Wrong discovery transport envelope')
        gd.validate_selection(wrapper,plan['project'],plan['profiles'])
    # Only call() is reachable: execute(), catalog generation and assessments of
    # the historical coordinator are never invoked. call() fixes max_retries=0.
    with coordinator_directory(out):
        try:c.call('discovery',plan['project'],[dict(indicator_id=gd.MARKER)],req,'discovery.schema.json',gate,runner=runner)
        except Exception:
            if not record.exists():raise
    return verify(out)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','execute','verify'])
    parser.add_argument('--project',required=True,choices=PROJECTS)
    parser.add_argument('--authorization',type=Path)
    args=parser.parse_args();out=directory(args.project)
    if args.command=='prepare':
        prepare(args.project)
        print(json.dumps(dict(status='PREPARED_NOT_AUTHORIZED',project_id=args.project,plan=str(out/'plan.json'))))
    else:
        result=execute(out,args.authorization) if args.command=='execute' else verify(out)
        print(json.dumps(result,ensure_ascii=True,indent=2))
        if result['status']!='PASS':raise SystemExit(2)
