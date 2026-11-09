"""Explicitly authorized paired experiment. Frozen corpus, no retrieval rebuild."""
import argparse
from copy import deepcopy
import csv
import ctypes
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from collections import Counter

from . import policy as p, store as s, phase1, phase11, phase12, minimal
from .engine import Worker, JobError
from .preparation_integrity import runtime_files
from layer4_evaluation.indicators import assessment_v3 as v3
from layer4_evaluation.indicators.selection import canonical_hash
from layer4_evaluation.indicators.ollama_provider import OllamaError

VERSION='PAIRED_EVALUATION_PHASE1_V1'
HISTORY='run_20261102_004408_677016'
REAL=[('PROJ_4836','DIV-04'),('PROJ_5501','ECO-04'),('PROJ_5501','ECO-07'),
      ('PROJ_5501','POL-08'),('PROJ_5501','SAL-06'),('PROJ_5501','TEC-03'),
      ('PROJ_5501','TEC-04'),('PROJ_5501','TEC-06'),('PROJ_4636','AMB-01'),
      ('PROJ_4636','COL-01'),('PROJ_4636','TEC-01'),('PROJ_4836','SAL-01'),
      ('PROJ_4836','SOC-01'),('PROJ_4836','ASC-01'),('PROJ_5501','TEC-01'),('PROJ_5501','ECO-01')]
CONTROLS=[
    ('SYNTH_DIALOGUE_POSITIVE','ASC-01','SUPPORTED',
     'CONTROL SINTETICO. El proyecto estableció y mantiene una mesa mensual de diálogo entre investigadores '
     'de la universidad y representantes de la comunidad. Ambas partes aportan sus saberes, acuerdan las '
     'preguntas y ajustan conjuntamente los métodos del proyecto. El acta de funcionamiento registra '
     'reuniones ya realizadas, intercambio recíproco y decisiones conjuntas incorporadas al trabajo.'),
    ('SYNTH_DIALOGUE_PARTIAL','ASC-01','INSUFFICIENT_EVIDENCE',
     'CONTROL SINTETICO. Investigadores universitarios y representantes comunitarios están identificados '
     'como futuros participantes del proyecto. Se propone crear una mesa para intercambiar saberes '
     'y decidir conjuntamente las preguntas. La mesa aún no se ha establecido ni realizado reuniones.'),
    ('SYNTH_INCOME_POSITIVE','ECO-01','SUPPORTED',
     'CONTROL SINTETICO. El proyecto desarrolló y validó con una empresa un nuevo proceso de fabricación '
     'que la empresa ya implementó. La comercialización de sus productos generó ingresos adicionales '
     'de 20 millones de pesos durante el último trimestre frente a la línea base comparable, según '
     'registros contables. La empresa atribuye ese incremento al proceso desarrollado e implementado '
     'por el proyecto; no se trata de ingresos proyectados ni de ventas anteriores.'),
    ('SYNTH_INCOME_NEGATIVE','ECO-01','NOT_SUPPORTED',
     'CONTROL SINTETICO. El proyecto realizó una revisión bibliográfica de poemas del siglo XIX. '
     'No desarrolló procesos ni productos económicos, no tuvo implementación empresarial y no '
     'generó ingresos adicionales. El documento no presenta comercialización ni una previsión de ingresos.')]


def location(root,name):
    from .lifecycle import safe_id
    safe_id(name)
    from run_paths import find_run
    return find_run(Path(root),Path(root)/'outputs/runs',name)


def synthetic(pid,iid,text,source_hash):
    fields=dict.fromkeys(('title','summary','methodology','objectives','expected_results','keywords'),'')
    fields['summary']=text
    sid=pid+'_SECTION';cid=pid+'_CHUNK'
    provenance=dict(record_source='assets/synthetic_sources.json',raw_sha256=source_hash,
                    source_sheet='SYNTHETIC',source_row=pid,synthetic=True)
    project=dict(project_id=pid,siap_id=pid,fields=fields,field_provenance={'summary':dict(
        section_id=sid,text_hash_original=canonical_hash(text),raw_sources=[provenance])})
    chunk=dict(chunk_id=cid,section_id=sid,source_id=pid,field_name='summary',text=text,char_start=0,char_end=len(text))
    section=dict(section_id=sid,source_id=pid,field_name='summary',text_original=text,
                 provenance_json=json.dumps({'layer1':[provenance]}),text_hash_original=canonical_hash(text))
    candidate=dict(source_id=pid,source_type='PROJECT',indicator_id=iid,discovery_chunks=[dict(
        chunk_id=cid,field_name='summary',vector_rank=1,vector_score=None,retrieval_origin='SYNTHETIC_CONTROL_FIXED')])
    return dict(project=project,chunks=[chunk],sections=[section],candidates=[candidate])


def prepare(root,name):
    started=time.perf_counter()
    root=Path(root).resolve();directory=location(root,name)
    if directory.exists():raise ValueError('El experimento ya existe; no se sobrescribe')
    source=root/'outputs/runs'/HISTORY/'autonomous/main';old=s.read(source/'manifest.json')
    binding=s.read(source/'graph.binding.json')
    if s.sha(source/'candidate_index.sqlite')!=binding['index_sha256']:
        raise ValueError('Indice historico incompatible con graph.binding.json')
    # Read-only historical artifacts; never invoke lifecycle or open writable queue.
    db=sqlite3.connect((source/'candidate_index.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    cases=[];origins={}
    try:
        for pid,iid in REAL:
            ref=old['projects'][pid];path=source/ref['path']
            if s.sha(path)!=ref['sha256']:raise ValueError('Input historico alterado: '+pid)
            data=s.read(path)
            all_candidates=[json.loads(r[0]) for r in db.execute(
                "SELECT value FROM rows WHERE kind='candidates' AND pid=?",(pid,))]
            if canonical_hash(all_candidates)!=binding['project_sha256'][pid]:raise ValueError('Candidatos historicos incompatibles')
            data['candidates']=[c for c in all_candidates if c['indicator_id']==iid]
            if len(data['candidates'])!=1:raise ValueError('Candidato historico no univoco')
            cases.append(dict(case_id=pid+'__'+iid,indicator_id=iid,origin='INSTITUTIONAL_OBSERVATION',data=data,
                reference=dict(status='PENDING_HUMAN_REVIEW',decision=None),design_target=None))
            origins[path.relative_to(root).as_posix()]=s.sha(path)
    finally:db.close()
    directory.mkdir(parents=True)
    s.write(directory/'assets/synthetic_sources.json',[dict(project_id=pid,indicator_id=iid,text=text,synthetic=True) for pid,iid,target,text in CONTROLS])
    control_hash=s.sha(directory/'assets/synthetic_sources.json')
    for pid,iid,target,text in CONTROLS:
        cases.append(dict(case_id=pid+'__'+iid,indicator_id=iid,origin='SYNTHETIC_CONTROL',
            data=synthetic(pid,iid,text,control_hash),reference=dict(status='PENDING_HUMAN_REVIEW',decision=None),
            design_target=target))  # Test intent, deliberately NOT a reference label.
    s.write(directory/'assets/cases.json',cases)
    with (directory/'references.pending.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['case_id','status','decision','reviewer','reviewed_at'])
        writer.writeheader();writer.writerows(dict(case_id=c['case_id'],status='PENDING_HUMAN_REVIEW') for c in cases)
    code=runtime_files(root)
    code['scripts/compare_evaluation.py']=s.sha(root/'scripts/compare_evaluation.py')
    origins[(source/'manifest.json').relative_to(root).as_posix()]=s.sha(source/'manifest.json')
    origins[(source/'candidate_index.sqlite').relative_to(root).as_posix()]=s.sha(source/'candidate_index.sqlite')
    origins[(source/'graph.binding.json').relative_to(root).as_posix()]=s.sha(source/'graph.binding.json')
    # Source bytes, not only extracted inputs, remain bound to approval.
    for case in cases[:16]:
        for field in case['data']['project']['field_provenance'].values():
            for raw in field.get('raw_sources',[]):
                path=Path(raw['record_source'])
                if not path.is_absolute():path=root/path
                if path.is_file():
                    if raw.get('raw_sha256') and s.sha(path)!=raw['raw_sha256']:raise ValueError('Fuente documental alterada')
                    origins[path.relative_to(root).as_posix()]=s.sha(path)
    policy=p.validate(s.read(root/'config/autonomous.json'))
    if policy['version']!=p.PHASE1:raise ValueError('La comparacion requiere la politica V2')
    policies={'baseline':old['policy'],'corrected':policy}
    for arm,limits in policies.items():
        manifest=dict(version=VERSION,execution_id=uuid.uuid4().hex,repository_root=str(root),
            policy=limits,llm=old['llm'],runtime=old['runtime'],profiles=old['profiles'],rubrics=old['rubrics'],
            role=arm,local_only=True,schema_version=v3.VERSION,
            prompts=dict(normative=p.NORMATIVE,repair=p.REPAIR,shard=p.SHARD,
                synthesis=phase1.INSTRUCTIONS if arm=='corrected' else p.SYNTHESIS,
                concise=p.CONCISE if arm=='corrected' else '',
                repair_feedback='SAFE_RULE_PATH_IDENTIFIERS_V1' if arm=='corrected' else 'STATIC_REPAIR_V1'))
        s.write(directory/arm/'manifest.json',manifest)
        queue=s.connect(directory/arm)
        for c in cases:
            pid=c['data']['project']['project_id'];iid=c['indicator_id']
            queue.execute('INSERT OR IGNORE INTO projects VALUES(?,?,?,?)',(pid,pid,'assets/cases.json',s.sha(directory/'assets/cases.json')))
            queue.execute('INSERT INTO jobs(pid,iid,status,updated) VALUES(?,?,?,?)',(pid,iid,'PENDING',s.now()))
        queue.close()
    files={n:s.sha(directory/n) for n in ('assets/cases.json','assets/synthetic_sources.json','baseline/manifest.json','corrected/manifest.json')}
    s.write(directory/'manifest.json',dict(version=VERSION,created_at=s.now(),source_run=HISTORY,
        cases=20,institutional_cases=16,synthetic_cases=4,code=code,sources=origins,files=files,
        local_only=True,model=old['llm']['model'],arms=['baseline','corrected'],
        baseline_definition='V1 policy and legacy engine branch; shared V3 acceptance rules unchanged',
        preparation_seconds=time.perf_counter()-started,
        allowed_operations=['LOCAL_OLLAMA_EVALUATION','BOUNDED_REPAIR','CRITERION_SHARDS','LLM_SYNTHESIS'],
        pending_reference_labels=True,scope='Exactly the 20 frozen project/indicator cases in each arm'))
    offline_synthesis(root,directory)
    return dict(status='REVIEW_REQUIRED',manifest=str(directory/'manifest.json'),manifest_sha256=s.sha(directory/'manifest.json'),cases=20,inference_calls=0)


def offline_synthesis(root,directory):
    """Replay budgets only: historical judgments are NOT new accepted assessments."""
    source=Path(root)/'outputs/runs'/HISTORY/'autonomous/main';old=s.read(source/'manifest.json')
    policy=s.read(directory/'corrected/manifest.json')['policy'];rows=[]
    for pid,iid in REAL[:8]:
        data=s.read(source/old['projects'][pid]['path']);requests=[];judgments=[];evidence=[];receipts={}
        for offset in range(0,len(old['rubrics'][iid]['criteria']),3):
            calls=sorted((source/'attempts'/pid/iid/('r0_shard_'+str(offset))).glob('*/transport/*/attempt_1/call.json'))
            call=next(c for c in reversed(calls) if s.read(c)['exit_status']==0)
            step=call.parents[3]/'step.json';response=call.parent/'response.json';item=s.read(response)['assessments'][0]
            requests.append(s.read(step)['request']);base=len(evidence);evidence+=item['evidence']
            judgments += [{**c,'evidence_indices':[i+base for i in c['evidence_indices']]} for c in item['criterion_assessments']]
            for path in (call,step,response):receipts[path.relative_to(root).as_posix()]=s.sha(path)
        evidence,judgments=phase1.merge(evidence,judgments)
        request=phase1.synthesis(data['project'],old['profiles'][iid],old['rubrics'][iid],requests,judgments,evidence)
        schema=p.schema(data['project']['fields'],policy,decision_only=True)
        budgets=[cb_estimate(request,schema,p.settings(old['llm'],policy,t,decision_only=True)) for t in range(len(policy['tiers']))]
        issues=v3.validate_criteria(data['project']['fields'],old['profiles'][iid],dict(criterion_assessments=judgments,evidence=evidence),old['rubrics'][iid],[c['criterion_id'] for c in judgments])
        rows.append(dict(project_id=pid,indicator_id=iid,prompt_bytes=len(request['prompt'].encode()),budgets=budgets,
            first_fitting_tier=next((i for i,b in enumerate(budgets) if b['fits']),None),
            criterion_contract_errors=issues,source_receipts=receipts,
            hypothetical_only=True,measured_input_tokens=None,inference_calls=0))
    s.write(directory/'offline_synthesis.json',rows)


def cb_estimate(request,schema,settings):
    from layer4_evaluation.indicators.context_budget import estimate
    return estimate(request['prompt'],schema,settings)


def case_inputs(root,directory,manifest):
    if 'case_source' not in manifest:return s.read(Path(directory)/'assets/cases.json')
    path=(Path(root)/manifest['case_source']).resolve()
    if not path.is_relative_to(Path(root).resolve()) or manifest['case_source'] not in manifest['sources']:
        raise ValueError('Fuente de casos fuera del manifiesto')
    cases={c['case_id']:c for c in s.read(path)}
    return [cases[cid] for cid in manifest['case_ids']]


def verify(root,directory,authorized=True):
    from layer2_processing.checkpoints import locate
    root=Path(root);directory=Path(directory);m=s.read(directory/'manifest.json')
    from .followup import VERSION as FOLLOWUP,IDS,PHASE12_VERSION,PHASE12_IDS
    from .minimal import VERSION as MINIMAL,IDS as MINIMAL_IDS
    known=(m['version']==VERSION and m['cases']==20 and m['arms']==['baseline','corrected'] or
           m['version']==FOLLOWUP and m['cases']==8 and m['arms']==['corrected'] and m['case_ids']==IDS or
           m['version']==PHASE12_VERSION and m['cases']==6 and m['arms']==['corrected'] and m['case_ids']==PHASE12_IDS or
           m['version']==MINIMAL and m['arms']==['corrected'] and
           0<m['cases']==len(m['case_ids'])==len(set(m['case_ids'])) and
           all(cid in MINIMAL_IDS for cid in m['case_ids']))
    if not known or m['local_only'] is not True:raise ValueError('Contrato experimental incompatible')
    for base,receipts in ((root,m['code']),(root,m['sources']),(directory,m['files'])):
        for name,digest in receipts.items():
            path=locate(base/name).resolve()
            if not path.is_relative_to(base.resolve()) or not path.is_file() or s.sha(path)!=digest:
                raise ValueError('INTEGRITY_MISMATCH: '+name+'; preparar otro experimento, no actualizar hashes')
    if authorized:
        auth=s.read(directory/'authorization.json') if (directory/'authorization.json').exists() else {}
        if auth.get('manifest_sha256')!=s.sha(directory/'manifest.json'):raise ValueError('Falta autorizacion exacta del manifiesto')
    return m


def authorize(root,name,digest):
    directory=location(root,name);verify(root,directory,authorized=False)
    if digest!=s.sha(directory/'manifest.json'):raise ValueError('SHA-256 distinto del manifiesto revisado')
    path=directory/'authorization.json'
    if path.exists():
        if s.read(path)['manifest_sha256']!=digest:raise ValueError('No sobrescribir autorizacion')
    else:s.write(path,dict(manifest_sha256=digest,authorized_at=s.now(),local_only=True))
    return dict(status='AUTHORIZED',manifest_sha256=digest)


def rss_bytes():
    """Coordinator working set, not Ollama memory or VRAM."""
    import os
    if os.name!='nt':
        try:return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
        except (OSError,ValueError):return None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(k,ctypes.c_size_t) for k in ('peak','working','qpeak','quota','ppeak','pool','page','pagepeak')]
    value=Counters();value.cb=ctypes.sizeof(value)
    kernel=ctypes.windll.kernel32;kernel.GetCurrentProcess.restype=wintypes.HANDLE
    get=ctypes.windll.psapi.GetProcessMemoryInfo
    get.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    return value.working if get(kernel.GetCurrentProcess(),ctypes.byref(value),value.cb) else None


class MemorySample:
    def __init__(self):self.stop=threading.Event();self.values=dict(coordinator_peak_rss_bytes=None,host_min_available_mib=None,samples=0)
    def sample(self):
        rss=rss_bytes()
        try:ram=p.free_ram_mb()
        except RuntimeError:ram=None
        if rss is not None:self.values['coordinator_peak_rss_bytes']=max(self.values['coordinator_peak_rss_bytes'] or 0,rss)
        if ram is not None:self.values['host_min_available_mib']=min(self.values['host_min_available_mib'] if self.values['host_min_available_mib'] is not None else ram,ram)
        self.values['samples']+=1
    def loop(self):
        while not self.stop.wait(1):self.sample()
    def __enter__(self):self.sample();self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start();return self
    def __exit__(self,*args):self.stop.set();self.thread.join(timeout=2);self.sample()


def execute(root,name,arm,*,client_factory=None,ram=None,sleep=None):
    session_started=time.perf_counter()
    directory=location(root,name);approved=verify(root,directory)
    if arm not in approved['arms']:raise ValueError('Brazo no autorizado; no repetir baseline historico')
    from scripts.pipeline_coordinator import lock
    work=directory/arm
    with lock(directory):
        verify(root,directory)
        manifest=s.read(work/'manifest.json')
        worker_class=Worker
        if approved['version']==minimal.VERSION:
            worker_class=minimal.MinimalWorker
        worker=worker_class(work,manifest,client_factory=client_factory,ram=ram,sleep=sleep)
        try:
            for case in case_inputs(root,directory,approved):
                verify(root,directory)  # No source, policy or code drift between jobs.
                data=case['data'];pid=data['project']['project_id'];iid=case['indicator_id']
                job=dict(worker.db.execute('SELECT * FROM jobs WHERE pid=? AND iid=?',(pid,iid)).fetchone())
                if job['status']=='PASS':
                    if not worker.adopt(job,data,commit=False):raise ValueError('Falta resultado PASS')
                    continue
                if job['status'] in ('BLOCKED','UNCERTAIN'):continue
                if worker.adopt(job,data):continue
                worker.db.execute("UPDATE jobs SET status='RUNNING',updated=? WHERE pid=? AND iid=?",(s.now(),pid,iid))
                timing=work/'timing'/f'{case["case_id"]}.json';prior=s.read(timing) if timing.exists() else {}
                started=time.perf_counter()
                memory=MemorySample()
                try:
                    with memory:
                        bundle=worker.evaluate(data,iid,0)
                        bundle['manifest_sha256']=s.sha(work/'manifest.json')
                        bundle['artifact_hashes']={f.relative_to(work).as_posix():s.sha(f) for f in (work/'attempts'/pid/iid).rglob('*') if f.is_file()}
                        s.write(work/'results'/pid/(iid+'.json'),bundle)
                        worker.adopt(job,data)
                except (JobError,OllamaError) as exc:
                    state='UNCERTAIN' if exc.code in ('UNCERTAIN_OUTCOME','TIMEOUT','INTERRUPTED') else 'BLOCKED'
                    worker.db.execute('UPDATE jobs SET status=?,error=?,updated=? WHERE pid=? AND iid=?',(state,exc.code,s.now(),pid,iid))
                    if exc.code in ('OUT_OF_MEMORY','RESOURCE_RAM_FLOOR','RESOURCE_DISK_FLOOR','RUNTIME_DRIFT'):break
                finally:
                    values=memory.values
                    for key,op in (('coordinator_peak_rss_bytes',max),('host_min_available_mib',min)):
                        valid=[v for v in (prior.get(key),values.get(key)) if v is not None]
                        values[key]=op(valid) if valid else None
                    s.write(timing,values|dict(total_active_seconds=prior.get('total_active_seconds',0)+time.perf_counter()-started,
                        measured_at=s.now(),ollama_process_peak_bytes=None,vram_peak_bytes=None))
        finally:
            worker.close()
            sessions=work/'execution_sessions.json'
            previous=s.read(sessions) if sessions.exists() else []
            s.write(sessions,previous+[dict(finished_at=s.now(),active_wall_seconds=time.perf_counter()-session_started)])
    return metrics(root,name)


def metrics(root,name,references=None):
    directory=location(root,name);approved=verify(root,directory,authorized=False)
    cases=case_inputs(root,directory,approved);labels={};reference_hash=None
    if references:
        reference_hash=s.sha(references)
        for row in csv.DictReader(Path(references).open(encoding='utf-8-sig')):
            if row['case_id'] in labels:raise ValueError('Referencia duplicada')
            if row['case_id'] not in {c['case_id'] for c in cases}:raise ValueError('Caso ajeno al manifiesto')
            if row['status']=='APPROVED_HUMAN_REVIEW':
                if row['decision'] not in ('SUPPORTED','INSUFFICIENT_EVIDENCE','NOT_SUPPORTED') or not row['reviewer'].strip() or not row['reviewed_at'].strip():raise ValueError('Referencia humana incompleta')
                labels[row['case_id']]=row['decision']
            elif row['status']!='PENDING_HUMAN_REVIEW':raise ValueError('Estado de referencia desconocido')
    summaries={};allrows=[]
    previous={r['case_id']:r for r in s.read(directory/'assets/previous_corrected.json')} if (directory/'assets/previous_corrected.json').exists() else {}
    v2_previous={r['case_id']:r for r in s.read(directory/'assets/previous_v2.json')} if (directory/'assets/previous_v2.json').exists() else {}
    for arm in approved['arms']:
        work=directory/arm;manifest=s.read(work/'manifest.json');db=sqlite3.connect((work/'queue.sqlite').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
        matrix={};rows=[]
        try:
            for case in cases:
                pid=case['data']['project']['project_id'];iid=case['indicator_id'];job=db.execute('SELECT * FROM jobs WHERE pid=? AND iid=?',(pid,iid)).fetchone()
                usage=db.execute('SELECT COUNT(*),SUM(input_tokens),SUM(output_tokens),SUM(wall) FROM usage WHERE pid=? AND iid=?',(pid,iid)).fetchone()
                bundle=s.read(work/job['result_path']) if job['status']=='PASS' else None
                timing=work/'timing'/f'{case["case_id"]}.json';t=s.read(timing) if timing.exists() else {}
                contradictions=0;context_errors=int('CONTEXT' in (job['error'] or ''));validation_errors=0
                native_decode=0.;native_load=0.;patch_calls=0;limited_calls=0
                successful_repairs=0;noop_patches=0;reevaluations=0
                for step in (work/'attempts'/pid/iid).glob('*/*/step.json'):
                    desc=s.read(step);call=step.parent/'transport'/pid/'attempt_1/call.json'
                    limited_calls+=int(desc['request']['context_selection']['evidence_limited'])
                    patch_calls+=int('repair_contract' in desc['request'])
                    if manifest['policy']['version']==p.PHASE12:
                        reevaluations+=int(desc['request'].get('repair_contract',{}).get('reevaluate',False))
                        successful_repairs+=int((step.parent/'repair.receipt.json').exists())
                        diagnostic=step.parent/'validation.diagnostics.json'
                        if diagnostic.exists():noop_patches+=int(any(i['rule']=='REPAIR_NO_EFFECT' for i in s.read(diagnostic).get('patch_issues',[])))
                    if not call.exists():continue
                    c=s.read(call);context_errors+=int('CONTEXT' in str(c['exit_status']));validation_errors+=int(c['exit_status']=='INVALID_ASSESSMENT')
                    native=call.parent/'native_response.json'
                    if native.exists():
                        n=s.read(native);native_decode+=n.get('eval_duration',0)/1e9;native_load+=n.get('load_duration',0)/1e9
                    ids=desc['request']['payload'].get('requested_criterion_ids')
                    if ids and c['exit_status']==0:
                        value=s.read(call.parent/'response.json')
                        if 'repair_contract' in desc['request']:
                            value=(phase12.apply_patch(desc['request'],value,case['data']['project'],manifest['profiles'][iid],manifest['rubrics'][iid],ids)
                                   if manifest['policy']['version']==p.PHASE12 else phase11.apply_patch(desc['request'],value))
                        assessment=value['assessments'][0]
                        contradictions+=bool(v3.validate_criteria(case['data']['project']['fields'],manifest['profiles'][iid],assessment,manifest['rubrics'][iid],ids))
                expected=labels.get(case['case_id']);pred=bundle['row']['decision'] if bundle else None
                scored=expected is not None and job['status'] in ('PASS','BLOCKED','UNCERTAIN')
                if scored:matrix.setdefault(expected,{});matrix[expected][pred or 'TECHNICAL_FAILURE']=matrix[expected].get(pred or 'TECHNICAL_FAILURE',0)+1
                rows.append(dict(case_id=case['case_id'],arm=arm,origin=case['origin'],status=job['status'],error=job['error'],
                    decision=pred,confidence=bundle['row']['confidence_raw_score'] if bundle else None,
                    evidence_limited_calls=limited_calls,scoped_patch_calls=patch_calls,
                    human_reference=expected,reference_status='APPROVED_HUMAN_REVIEW' if expected else 'PENDING_HUMAN_REVIEW',
                    correct=(expected==pred) if scored else None,calls=usage[0],input_tokens=usage[1] or 0,output_tokens=usage[2] or 0,
                    inference_http_seconds=usage[3] or 0,total_active_seconds=t.get('total_active_seconds'),
                    native_decode_seconds=native_decode,native_load_seconds=native_load,context_errors=context_errors,
                    accepted_shard_contract_violations=contradictions,validation_rejections=validation_errors,
                    coordinator_peak_rss_bytes=t.get('coordinator_peak_rss_bytes'),host_min_available_mib=t.get('host_min_available_mib'),
                    ollama_process_peak_bytes=None,vram_peak_bytes=None))
                if manifest['policy']['version']==p.PHASE12:
                    rows[-1].update(successful_repairs=successful_repairs,noop_patch_calls=noop_patches,bounded_reevaluation_calls=reevaluations)
                if approved['version']==minimal.VERSION:
                    rows[-1].update(clarification_needed=(work/'attempts'/pid/iid/'minimal/1/clarification.json').exists(),
                        clarification_calls=sum(u['step']=='clarification' for u in db.execute('SELECT step FROM usage WHERE pid=? AND iid=?',(pid,iid))),
                        evidence_retrieved=len(minimal.registry(case['data'],iid)),
                        evidence_used=len({eid for j in bundle.get('semantic_answer',{}).get('criteria',{}).values() for eid in j['evidence_ids']}) if bundle else None)
                    for version,observations in approved['historical'].items():
                        old=observations[case['case_id']]
                        rows[-1].update({version.lower()+'_'+k:old[k] for k in ('status','decision','confidence','calls','input_tokens','output_tokens','total_active_seconds','inference_http_seconds')})
                if previous:
                    ref=previous[case['case_id']]
                    rows[-1].update(previous_status=ref['metrics']['status'],previous_decision=ref['decision'],
                        previous_confidence=ref['confidence'],previous_calls=int(ref['metrics']['calls']),
                        previous_input_tokens=int(ref['metrics']['input_tokens']),previous_output_tokens=int(ref['metrics']['output_tokens']),
                        previous_inference_http_seconds=float(ref['metrics']['inference_http_seconds']),
                        previous_total_active_seconds=float(ref['metrics']['total_active_seconds']),
                        previous_evidence_limited_calls=ref['evidence_limited_calls'])
                if v2_previous:
                    ref=v2_previous[case['case_id']];obs=ref['metrics']
                    rows[-1].update(v2_status=obs['status'],v2_decision=ref['decision'],v2_confidence=ref['confidence'],
                        v2_calls=int(obs['calls']),v2_input_tokens=int(obs['input_tokens']),v2_output_tokens=int(obs['output_tokens']),
                        v2_total_active_seconds=float(obs['total_active_seconds']),v2_inference_http_seconds=float(obs['inference_http_seconds']))
        finally:db.close()
        sessions=s.read(work/'execution_sessions.json') if (work/'execution_sessions.json').exists() else []
        summaries[arm]=dict(cases=len(rows),human_reviewed=len(labels),status_counts=dict(Counter(r['status'] for r in rows)),
            experiment_active_wall_seconds=sum(t['active_wall_seconds'] for t in sessions),accuracy_by_category={k:dict(n=sum(v.values()),
            correct=v.get(k,0),accuracy=v.get(k,0)/sum(v.values())) for k,v in matrix.items()},confusion_matrix=matrix,
            totals={key:sum(r[key] or 0 for r in rows) for key in ('calls','input_tokens','output_tokens','inference_http_seconds','total_active_seconds','context_errors','accepted_shard_contract_violations','validation_rejections','evidence_limited_calls','scoped_patch_calls')})
        allrows+=rows
        if manifest['policy']['version']==p.PHASE12:
            summaries[arm]['totals'].update({key:sum(r[key] for r in rows) for key in ('successful_repairs','noop_patch_calls','bounded_reevaluation_calls')})
        if approved['version']==minimal.VERSION:
            summaries[arm]['totals'].update(clarification_calls=sum(r['clarification_calls'] for r in rows),clarification_needed=sum(r['clarification_needed'] for r in rows))
    s.write(directory/'metrics.json',dict(reference_sha256=reference_hash,arms=summaries,memory_scope='Host available RAM and coordinator RSS; Ollama/VRAM peaks NOT MEASURED'))
    with (directory/'metrics.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(allrows[0]));writer.writeheader();writer.writerows(allrows)
    return dict(status='METRICS',path=str(directory/'metrics.json'),arms=summaries)


def main(root,argv=None):
    parser=argparse.ArgumentParser(description='Comparacion aislada de 20 casos, autorizacion por SHA-256')
    parser.add_argument('command',choices=['prepare','authorize','run','metrics'])
    parser.add_argument('--name',required=True);parser.add_argument('--manifest-sha256');parser.add_argument('--arm',choices=['baseline','corrected']);parser.add_argument('--references')
    parser.add_argument('--followup-phase11',action='store_true',help='Preparar ocho casos, comparar con corrected historico sin repetir baseline')
    parser.add_argument('--followup-phase12',action='store_true',help='Preparar seis casos V4 con observaciones V2/V3; sin repetir baseline')
    parser.add_argument('--minimal-three',action='store_true',help='Prototipo de una llamada y una aclaracion excepcional; tres controles existentes')
    args=parser.parse_args(argv)
    if args.followup_phase11 and args.command!='prepare':parser.error('--followup-phase11 solo se admite al preparar')
    if args.followup_phase12 and (args.command!='prepare' or args.followup_phase11):parser.error('--followup-phase12 solo al preparar y sin --followup-phase11')
    if args.minimal_three and (args.command!='prepare' or args.followup_phase11 or args.followup_phase12):parser.error('--minimal-three solo al preparar y sin otras variantes')
    if args.command=='prepare':
        if args.minimal_three:
            from .minimal import prepare as prepare_minimal
            result=prepare_minimal(root,args.name)
        elif args.followup_phase11 or args.followup_phase12:
            from .followup import prepare as prepare_followup
            result=prepare_followup(root,args.name,phase12=args.followup_phase12)
        else:result=prepare(root,args.name)
    elif args.command=='authorize':
        if not args.manifest_sha256:parser.error('--manifest-sha256 obligatorio')
        result=authorize(root,args.name,args.manifest_sha256)
    elif args.command=='run':
        if not args.arm:parser.error('--arm obligatorio')
        result=execute(root,args.name,args.arm)
    else:result=metrics(root,args.name,args.references)
    print(json.dumps(result,ensure_ascii=True,indent=2))
