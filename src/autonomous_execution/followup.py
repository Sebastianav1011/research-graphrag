"""Eight-case phase 1.1 preparation, reusing the paired runner without a new baseline."""
from copy import deepcopy
import csv
from pathlib import Path
import uuid
from . import policy as p,store as s,phase1,phase11,phase12 as v4
from .preparation_integrity import runtime_files

VERSION='FOLLOWUP_EVALUATION_PHASE11_V1'
PREVIOUS='outputs/runs/phase1_20_v1'
IDS=['SYNTH_DIALOGUE_POSITIVE__ASC-01','SYNTH_DIALOGUE_PARTIAL__ASC-01',
     'SYNTH_INCOME_POSITIVE__ECO-01','SYNTH_INCOME_NEGATIVE__ECO-01',
     'PROJ_4836__SAL-01','PROJ_5501__TEC-01','PROJ_5501__TEC-03','PROJ_5501__TEC-04']
PHASE12_VERSION='FOLLOWUP_EVALUATION_PHASE12_V1'
PHASE12_PREVIOUS='outputs/runs/phase11_8_v2'
PHASE12_IDS=IDS[:4]+IDS[-2:]


def prepare(root,name,*,phase12=False):
    from .comparison import location
    root=Path(root).resolve();directory=location(root,name)
    previous_relative=PHASE12_PREVIOUS if phase12 else PREVIOUS
    previous=root/previous_relative
    ids=PHASE12_IDS if phase12 else IDS
    version=PHASE12_VERSION if phase12 else VERSION
    if directory.exists():raise ValueError('El experimento ya existe; no se sobrescribe')
    old=s.read(previous/'manifest.json')
    # Verify documentary receipts, not historical executable hashes against new code.
    origins={}
    for base,receipts in ((root,old['sources']),(previous,old['files'])):
        for path,digest in receipts.items():
            from layer2_processing.checkpoints import locate
            target=locate(base/path).resolve()
            if not target.is_relative_to(root) or s.sha(target)!=digest:raise ValueError('Referencia historica alterada: '+path)
            origins[target.relative_to(root).as_posix()]=digest
    cases_by_id={c['case_id']:c for c in s.read(previous/'assets/cases.json')}
    cases=[deepcopy(cases_by_id[cid]) for cid in ids]
    source_manifest=s.read(previous/'corrected/manifest.json')
    config='config/autonomous_phase12.json' if phase12 else 'config/autonomous_phase11.json'
    policy=p.validate(s.read(root/config))
    if policy['version']!=(p.PHASE12 if phase12 else p.PHASE11):raise ValueError('Politica incompatible con la fase solicitada')
    metrics={r['case_id']:r for r in csv.DictReader((previous/'metrics.csv').open(encoding='utf-8-sig')) if r['arm']=='corrected'}
    references=[]
    for c in cases:
        pid=c['data']['project']['project_id'];iid=c['indicator_id'];result=previous/'corrected/results'/pid/(iid+'.json')
        bundle=s.read(result) if result.exists() else None
        observations=[]
        for step in (previous/'corrected/attempts'/pid/iid).glob('*/*/step.json'):
            observations.append(s.read(step)['request']['context_selection']['evidence_limited'])
        references.append(dict(case_id=c['case_id'],metrics=metrics[c['case_id']],
            decision=bundle['row']['decision'] if bundle else None,
            confidence=bundle['row']['confidence_raw_score'] if bundle else None,
            criterion_assessments=bundle['row']['criterion_assessments'] if bundle else None,
            result_path=result.relative_to(root).as_posix() if bundle else None,
            evidence_limited_calls=sum(observations),reference_status='PENDING_HUMAN_REVIEW',
            provenance='PREVIOUS_MODEL_OBSERVATION_NOT_GROUND_TRUTH'))
        # Bind all previous attempts/results/timings for the selected cases.
        paths=list((previous/'corrected/attempts'/pid/iid).rglob('*'))
        paths += [result,previous/'corrected/timing'/(c['case_id']+'.json')]
        for target in paths:
            if target.is_file():origins[target.relative_to(root).as_posix()]=s.sha(target)
    for filename in ('manifest.json','metrics.csv','authorization.json'):
        target=previous/filename;origins[target.relative_to(root).as_posix()]=s.sha(target)
    directory.mkdir(parents=True)
    s.write(directory/'assets/cases.json',cases)
    s.write(directory/'assets/previous_corrected.json',references)
    if phase12:
        s.write(directory/'assets/previous_v2.json',[r for r in s.read(previous/'assets/previous_corrected.json') if r['case_id'] in ids])
    # Provenance in the unchanged synthetic case data references this exact asset.
    s.write(directory/'assets/synthetic_sources.json',s.read(previous/'assets/synthetic_sources.json'))
    if s.sha(directory/'assets/synthetic_sources.json')!=s.sha(previous/'assets/synthetic_sources.json'):
        raise ValueError('La copia sintetica debe conservar sus bytes canonicos')
    with (directory/'references.pending.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['case_id','status','decision','reviewer','reviewed_at']);w.writeheader()
        w.writerows(dict(case_id=c['case_id'],status='PENDING_HUMAN_REVIEW') for c in cases)
    arm=directory/'corrected'
    arm_manifest=dict(version=version,execution_id=uuid.uuid4().hex,repository_root=str(root),
        policy=policy,llm=source_manifest['llm'],runtime=source_manifest['runtime'],
        profiles=source_manifest['profiles'],rubrics=source_manifest['rubrics'],local_only=True,
        schema_version=source_manifest['schema_version'],prompts=dict(normative=p.NORMATIVE,repair=p.REPAIR,
            concise=p.CONCISE,shard=p.SHARD,synthesis=phase1.INSTRUCTIONS,
            fidelity=phase11.FIDELITY,scoped_repair=phase11.REPAIR,version=phase11.VERSION))
    if phase12:
        arm_manifest['prompts'].update(fidelity=v4.CLASSIFICATION,scoped_repair=v4.REPAIR,version=v4.VERSION)
        arm_manifest['repair_plan']=dict(max_attempts_per_step=policy['attempts_per_step'],
            sequence=['INITIAL','LOCAL_PATCH','AFFECTED_CRITERIA_REEVALUATION'][:policy['attempts_per_step']],
            regenerate_entire_assessment=False,source_coverage='NO_LOSS_RETRIEVED_INTERVALS_V1',diagnostics=v4.VERSION)
    s.write(arm/'manifest.json',arm_manifest)
    db=s.connect(arm)
    try:
        for c in cases:
            pid=c['data']['project']['project_id'];iid=c['indicator_id']
            db.execute('INSERT OR IGNORE INTO projects VALUES(?,?,?,?)',(pid,pid,'assets/cases.json',s.sha(directory/'assets/cases.json')))
            db.execute('INSERT INTO jobs(pid,iid,status,updated) VALUES(?,?,?,?)',(pid,iid,'PENDING',s.now()))
    finally:db.close()
    code=runtime_files(root);code['scripts/compare_evaluation.py']=s.sha(root/'scripts/compare_evaluation.py')
    if phase12:code[config]=s.sha(root/config)
    files={path:s.sha(directory/path) for path in ('assets/cases.json','assets/previous_corrected.json',
        'assets/synthetic_sources.json','corrected/manifest.json')}
    if phase12:files['assets/previous_v2.json']=s.sha(directory/'assets/previous_v2.json')
    if phase12:
        offline_budgets(directory,cases,arm_manifest,previous)
        files['offline_budgets.json']=s.sha(directory/'offline_budgets.json')
    outer=dict(version=version,created_at=s.now(),cases=len(ids),case_ids=ids,
        arms=['corrected'],previous_experiment=previous_relative,comparison='FROZEN_PREVIOUS_CORRECTED_NO_BASELINE_INFERENCE',
        code=code,files=files,sources=origins,local_only=True,model=source_manifest['llm']['model'],
        institutional_cases=sum(c['origin']=='INSTITUTIONAL_OBSERVATION' for c in cases),synthetic_cases=4,pending_reference_labels=True,
        allowed_operations=['LOCAL_OLLAMA_EVALUATION','SCOPED_RESPONSE_PATCHES','CRITERION_SHARDS',
            'LOSSLESS_CRITERION_SUBDIVISION','LLM_SYNTHESIS'],scope=f'Only the {len(ids)} frozen cases, one corrected arm')
    if phase12:outer['allowed_operations']+=['INTEGRAL_DIAGNOSTICS','AFFECTED_CRITERIA_REEVALUATION']
    s.write(directory/'manifest.json',outer)
    return dict(status='REVIEW_REQUIRED',manifest=str(directory/'manifest.json'),
        manifest_sha256=s.sha(directory/'manifest.json'),cases=len(ids),baseline_calls_planned=0,inference_calls=0)


def offline_budgets(directory,cases,manifest,previous):
    """Estimate complete V4 inputs and historical-error repairs; never infer/adjudicate."""
    from .packing import pack
    from .engine import JobError
    from layer4_evaluation.indicators import context_budget as cb
    rows=[];policy=manifest['policy']
    for case in cases:
        project=case['data']['project'];iid=case['indicator_id'];pid=project['project_id']
        profile=manifest['profiles'][iid];rubric=manifest['rubrics'][iid]
        schema=p.schema(project['fields'],policy,criterion_ids=[c['criterion_id'] for c in rubric['criteria']])
        original=previous/'corrected/attempts'/pid/iid/'r0_full/1/transport'/pid/'attempt_1/response.raw.txt'
        raw=s.read(original)
        prior_request=s.read(original.parents[3]/'step.json')['request']
        historical_issues=v4.diagnose(project,profile,rubric,prior_request,raw)
        for mode in ('INITIAL','LOCAL_PATCH','AFFECTED_CRITERIA_REEVALUATION'):
            checks=[]
            if mode!='INITIAL' and not historical_issues:
                rows.append(dict(case_id=case['case_id'],mode=mode,checks=[],first_fitting_tier=None,
                    required_for_historical_output=False,estimated_only=True,inference_calls=0))
                continue
            for tier in range(len(policy['tiers'])):
                settings=p.settings(manifest['llm'],policy,tier)
                try:
                    request=pack(case['data'],profile,rubric,settings,schema,preserve=True,integral=True,concise=True)
                    transport=schema
                    if mode!='INITIAL':
                        issues=v4.diagnose(project,profile,rubric,request,raw)
                        if not issues:break
                        request,transport=v4.patch_request(request,schema,raw,issues,project,profile,rubric,
                            reevaluate=mode=='AFFECTED_CRITERIA_REEVALUATION')
                    budget=cb.estimate(request['prompt'],transport,settings)
                    checks.append(dict(tier=tier,**budget,source_characters={f:len(v or '') for f,v in request['payload']['project']['fields'].items()},
                        source_hash=request['coverage_receipt']['source_hash'],sources_removed=[]))
                except JobError as exc:checks.append(dict(tier=tier,code=exc.code,fits=False))
            rows.append(dict(case_id=case['case_id'],mode=mode,checks=checks,
                first_fitting_tier=next((r['tier'] for r in checks if r['fits']),None),
                required_for_historical_output=bool(checks),estimated_only=True,inference_calls=0))
    s.write(directory/'offline_budgets.json',rows)
