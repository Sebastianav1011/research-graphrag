"""V3.3 evaluation with local Ollama transport; historical Codex verification only."""
from run_paths import file_path as run_file

from contextlib import contextmanager

from datetime import datetime, timezone

import getpass

import json

import math

import os

import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

from layer4_evaluation.indicators import assessment_v3 as v3, global_discovery_v3_3 as gd

from layer4_evaluation.indicators.ollama_provider import (
    OllamaClient, OllamaAssessmentProvider, context_guard, configuration as llm_configuration, create_client)

from layer4_evaluation.indicators.experiment_inputs import read, sha256, verify_hashes

from layer4_evaluation.indicators.performance import usage_metrics
from layer4_evaluation.indicators.review import evidence_locations

from layer4_evaluation.indicators.selection import FIELDS, canonical_hash

from layer4_evaluation.indicators.selection import substantive_fields
from layer4_evaluation.indicators.context_budget import VERSION as CONTEXT_VERSION
from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError, semantic_issues

BASE=ROOT/'outputs/layer4/final/candidatos/demo_en_vivo'

FROZEN=ROOT/'outputs/layer4/pruebas/validacion_v3_3/cierre_homogeneo_v3_3/closure.plan.json'

def require(value,message):
    if not value: raise ValueError(message)

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.pending')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)

def emit(value): print(json.dumps(value,ensure_ascii=True,indent=2),flush=True)

def now(): return datetime.now(timezone.utc).isoformat()


def aggregate_metrics(calls):
    observations = [usage_metrics(call) for call in calls]
    tokens = {key: (sum(values) if values and all(v is not None for v in values) else None)
        for key in ('input_tokens', 'output_tokens', 'total_tokens')
        for values in [[m.get(key, {}).get('value') for m in observations]]}
    walls = [c.get('performance', {}).get('wall_seconds', {}).get('value') for c in calls]
    return tokens, sum(walls) if walls and all(v is not None for v in walls) else None

def run_dir(name):
    require(re.fullmatch(r'[A-Za-z0-9_-]{1,80}',name),'--run solo admite letras, numeros, guion y guion bajo')
    return BASE/name

def assessment_from_row(row):
    return dict(assessment_version=row['assessment_version'],decision=row['decision'],support_strength=row['support_strength'],
        criterion_assessments=row['criterion_assessments'],explanation=row['evidence_explanation'],
        evidence=[dict(field=f,text=t,stage=s) for f,t,s in zip(row['evidence_source_fields'],row['evidence_texts'],row['evidence_stages'])])


def indicator_row(plan, project, assessment):
    """Reuse unchanged scoring; only the transport provenance label is new."""
    iid = assessment['indicator_id']
    row = v3.indicator_row(project, plan['profiles'][iid],
        {k:v for k,v in assessment.items() if k!='indicator_id'}, plan['rubrics'][iid])
    if plan.get('runtime', {}).get('provider') == 'ollama':
        row['assessment_engine'] = 'OLLAMA'
    elif plan.get('runtime', {}).get('provider') == 'openai':
        row['assessment_engine'] = 'OPENAI_API'
    return row

def check(directory):
    require(not (directory/'recovery.pending.json').exists(), 'Recuperacion incompleta; revisar recovery.pending.json antes de reanudar')
    manifest=read(directory/'manifest.json')
    require(sha256(directory/'plan.json')==manifest['plan_sha256'],'Plan modificado; no ejecutar')
    for name,digest in manifest['files'].items(): require(sha256(directory/name)==digest,'Texto revisado o entrada modificados: '+name)
    plan=read(directory/'plan.json');verify_hashes(ROOT,plan['source_hashes'])
    if plan.get('recovery'):
        verify_hashes(ROOT, plan['recovery']['archive_hashes'])
    if plan.get('checkpoint_migration'):
        verify_hashes(ROOT, plan['checkpoint_migration']['archive_hashes'])
    require(plan['discovery_version']==gd.VERSION and plan['assessment_version']==v3.VERSION and len(plan['profiles'])==48,'Configuracion incompatible')
    if plan.get('request_protocol') == CONTEXT_VERSION:
        require(set(plan['context_requests'])=={p['project_id'] for p in plan['projects']}, 'Cobertura de proyectos/contextos incompleta')
        for p in plan['projects']:
            requests=plan['context_requests'][p['project_id']]
            require(set(requests)==set(plan['profiles']), 'Cobertura de los 48 indicadores incompleta')
            for iid, request in requests.items():
                require(request['project_id']==p['project_id'] and
                    [i['indicator_id'] for i in request['payload']['indicators']]==[iid], 'Contexto de otro proyecto/indicador')
    return plan

def verify_run(directory):
    plan=check(directory);cache=read(directory/'cache.json');states=[];errors=[];usage=list(plan.get('recovery', {}).get('previous_usage', []))
    isolated_errors=[]
    local = plan.get('runtime', {}).get('provider') in ('ollama','openai')
    for p in plan['projects']:
        bounded = plan.get('request_protocol') == CONTEXT_VERSION
        pid=p['project_id'];state=dict(project_id=pid,siap_id=p['siap_id'],discovery_complete=bounded,
            selected=sorted(plan['profiles']) if bounded else [],rows=[],complete=False,reused=False,blocked_indicators={})
        if bounded:
            state['context_limits'] = {iid:r['context_selection']['status'] for iid,r in plan['context_requests'][pid].items()
                if r['context_selection']['status'] != 'READY'}
        if pid in cache:
            saved=cache[pid]
            require(not bounded, 'Cache de descubrimiento global incompatible con contextos por indicador; reusar solo llamadas verificadas del nuevo plan')
            if local:
                require(saved.get('provider') == plan['runtime']['provider'] and
                    saved.get('provider_binding_sha256') == sha256(directory/'provider.json'),
                    'Cache de proveedor incompatible: no reutilizar respuestas Codex como Ollama')
            require(saved['original_project']['fields']==p['fields'] and saved['original_project']['siap_id']==p['siap_id'],'Identidad/texto del cache difieren')
            selection=gd.validate_selection(saved['selection'],saved['original_project'],plan['profiles'])
            rows=saved['rows']
            require({r['indicator_id'] for r in rows}==set(selection['prioritized_ids']),'Cache incompleto')
            for row in rows:
                require(not v3.validate(p['fields'],plan['profiles'][row['indicator_id']],assessment_from_row(row),plan['rubrics'][row['indicator_id']]),'Cache invalido')
            state.update(discovery_complete=True,selected=selection['prioritized_ids'],rows=rows,complete=True,reused=True)
        else:
            for out in sorted((directory/'calls'/pid).glob('*')):
                if not out.is_dir(): continue
                cp=read(out/'plan.json')
                require(not bounded or cp['phase']=='assessment' and len(cp['indicator_ids'])==1,'Fase incompatible con contexto por indicador')
                require(cp['run_plan_sha256']==sha256(directory/'plan.json'),'Plan de llamada no coincide')
                request=request_for(plan,p,cp['phase'],cp['indicator_ids'])
                require(cp['request_sha256']==canonical_hash(request),'Request de llamada modificado')
                expected_schema=gd.selection_schema(p['fields']) if cp['phase']=='discovery' else v3.schemas(p['fields'])['assessment_batch']
                require(read(out/'schema.json')==expected_schema,'Schema modificado')
                record_path=out/'records'/cp['phase']/(pid+'.json')
                if not (out/'verification.json').exists():
                    if (out/'dispatch.claim.json').exists(): errors.append(pid+': UNCERTAIN_OUTCOME; hay claim sin verificacion; no reintentar')
                    continue
                verification=read(out/'verification.json');usage.append(verification)
                record=read(record_path);verify_hashes(out,record['artifact_hashes'])
                require(record['request_sha256']==cp['request_sha256'],'Registro/request difieren')
                if local and not record['calls'] and record['status'] == 'ERROR':
                    message=pid+': BLOCKED_ERROR; no llamada completada; conservar claim y revisar '+str(out)
                    errors.append(message)
                    if bounded and plan.get('isolate_indicator_errors'):
                        isolated_errors.append(message)
                        state['blocked_indicators'].update({iid:'BLOCKED_ERROR' for iid in cp['indicator_ids']})
                    continue
                retries=plan.get('token_limit_retries',0) if bounded else 0
                require(1 <= len(record['calls']) <= retries+1,'Numero de llamadas fuera del limite')
                for index, call in enumerate(record['calls']):
                    attempt=out/cp['phase']/('ollama_runs' if local else 'codex_runs')/pid/('attempt_'+str(index+1))
                    require(read(attempt/'call.json')==call and call['retry']==index,'Metadatos nativos/reintento diferentes')
                    require(index==len(record['calls'])-1 or call['exit_status']=='TOKEN_LIMIT','Solo se reintenta el limite de salida')
                    require(call['prompt_sha256']==__import__('hashlib').sha256(request['prompt'].encode()).hexdigest() and
                        (attempt/'prompt.txt').read_text(encoding='utf-8')==request['prompt'] and
                        call['schema_sha256']==sha256(out/'schema.json') and
                        call['events_sha256']==sha256(attempt/'events.jsonl') and
                        call['stderr_sha256']==sha256(attempt/'stderr.txt'),'Artefactos de intento diferentes')
                    if local:
                        require(call['runtime']==read(directory/'provider.json'),'Runtime de reintento diferente')
                        sent=read(attempt/'request.json')
                        require(sent['messages']==[dict(role='user',content=request['prompt'])] and
                            sent['format']==expected_schema,'Solicitud de reintento diferente')
                        options=sent['options'];configured=plan['runtime']['configuration']
                        require(options['num_ctx']==configured['num_ctx'] and
                            configured['num_predict']<=options['num_predict']<=max(configured['num_predict'],configured.get('max_predict',configured['num_predict'])),
                            'Presupuesto de reintento fuera del plan')
                native=record['calls'][-1]
                if local:
                    binding = read(directory/'provider.json')
                    require(native.get('provider') == plan['runtime']['provider'] and native['runtime'] == binding and
                        cp['runtime'] == binding and cp['provider_binding_sha256'] == sha256(directory/'provider.json'),
                        'Proveedor/modelo/digest no corresponden al checkpoint Ollama')
                    require(binding['configuration'] == plan['runtime']['configuration'], 'Configuracion de proveedor distinta del plan')
                    require(native['prompt_sha256'] == __import__('hashlib').sha256(request['prompt'].encode()).hexdigest(), 'Prompt Ollama modificado')
                require((attempt/'prompt.txt').read_text(encoding='utf-8')==request['prompt'] and
                    native['schema_sha256']==sha256(out/'schema.json'),'Prompt/schema nativos difieren')
                require(native['events_sha256']==sha256(attempt/'events.jsonl') and native['stderr_sha256']==sha256(attempt/'stderr.txt'),'Logs nativos diferentes')
                auth=read(out/'authorization.used.json')
                require(auth['plan_sha256']==sha256(out/'plan.json') and auth['request_sha256']==cp['request_sha256'] and auth['authorized'] is True,'Autorizacion de llamada no coincide')
                require(read(out/'dispatch.claim.json')['authorization_sha256']==sha256(out/'authorization.used.json'),'Claim/autorizacion difieren')
                if verification['status']!='PASS' or record['status']!='VALID':
                    message=pid+': '+verification['status']+'; '+str(record.get('error'))+'; ver '+str(out)
                    errors.append(message)
                    if bounded and plan.get('isolate_indicator_errors'):
                        isolated_errors.append(message)
                        state['blocked_indicators'].update({iid:verification['status'] for iid in cp['indicator_ids']})
                    continue
                require(native['successful_transport'] and native['response_sha256']==sha256(attempt/'response.json') and
                    read(attempt/'response.json')==record['wrapper'],'Respuesta nativa diferente/no valida')
                native_tokens,_=aggregate_metrics(record['calls'])
                require(all(verification['tokens'][k]==native_tokens[k] for k in ('input_tokens','output_tokens','total_tokens')) and
                    verification['tokens']['total_tokens']<=plan['budgets'][cp['phase']+'_postcall_review_threshold'],'Metricas ausentes o requieren revision')
                if cp['phase']=='discovery':
                    selection=gd.validate_selection(record['wrapper'],p,plan['profiles'])
                    state.update(discovery_complete=True,selected=selection['prioritized_ids'])
                else:
                    v3.validate_wrapper(record['wrapper'],pid,cp['indicator_ids'],p['fields'])
                    validate_context_evidence(request, record['wrapper'])
                    saved=read(out/'assessment.rows.json')
                    expected=[]
                    for a in record['wrapper']['assessments']:
                        row=indicator_row(plan,p,a)
                        require(row['assessment_validation_status']=='VALID','Assessment invalido')
                        expected.append(row)
                    require(saved['record_sha256']==sha256(record_path) and saved['rows']==expected,'Filas/confianzas guardadas difieren')
                    state['rows']+=saved['rows']
            ids=[r['indicator_id'] for r in state['rows']]
            require(len(ids)==len(set(ids)) and set(ids)<=set(state['selected']),'Assessment duplicado o no seleccionado')
            state['complete']=state['discovery_complete'] and set(ids)==set(state['selected']) and not any(e.startswith(pid+':') for e in errors)
        state['pending']=[i for i in state['selected'] if i not in {r['indicator_id'] for r in state['rows']}]
        states.append(state)
    return dict(status='BLOCKED' if errors else ('COMPLETE' if all(s['complete'] for s in states) else 'PARTIAL'),projects=states,errors=errors,
        blocking_errors=[e for e in errors if e not in isolated_errors],usage=usage,
        new_calls=sum(v['calls'] for v in usage),total_tokens=sum(v['tokens']['total_tokens'] for v in usage if v['tokens']['total_tokens'] is not None),
        missing_token_metrics=sum(v['tokens']['total_tokens'] is None for v in usage))

def request_for(plan,project,phase,ids):
    if plan.get('request_protocol') == CONTEXT_VERSION:
        require(phase=='assessment' and len(ids)==1, 'Cada contexto GraphRAG evalua exactamente un indicador')
        return plan['context_requests'][project['project_id']][ids[0]]
    return gd.make_input(project,plan['profiles'],plan['rules']) if phase=='discovery' else v3.make_input(
        dict(project_id=project['project_id'],fields=project['fields']),[plan['profiles'][i] for i in ids],plan['rules'],plan['rubrics'])


def validate_context_evidence(request, wrapper):
    if request.get('input_version') != CONTEXT_VERSION:
        return
    fields = request['payload']['project']['fields']
    for item in wrapper['assessments']:
        for index, evidence in enumerate(item['evidence']):
            if not evidence['text'] or evidence['text'] not in (fields.get(evidence['field']) or ''):
                raise AssessmentValidationError([dict(category='EVIDENCE_NOT_VERIFIABLE',
                    rule='QUOTE_NOT_IN_SENT_GRAPHRAG_CONTEXT: la cita no pertenece a los fragmentos enviados', path=f'$.evidence[{index}].text',
                    indicator_id=item.get('indicator_id'), field=evidence['field'])])

@contextmanager
def execution_lock():
    BASE.mkdir(parents=True,exist_ok=True)
    with (BASE/'execution.lock').open('a+b') as stream:
        stream.seek(0,2)
        if stream.tell()==0: stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            try: msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError: raise ValueError('Ya hay otra ejecucion en vivo activa')
            try: yield
            finally: stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            try: yield
            finally: fcntl.flock(stream,fcntl.LOCK_UN)

def execute(args):
    directory=run_dir(args.run)
    with execution_lock():
        plan=check(directory);state=verify_run(directory)
        require(not state['blocking_errors'],'Ejecucion detenida: '+'; '.join(state['blocking_errors']))
        if state['status']=='COMPLETE': return summary(state)
        auth_path=directory/'authorization.json'
        if not auth_path.exists():
            require(args.authorize,'Falta autorizacion: revisar review.txt y ejecutar execute --run NOMBRE --authorize')
            write(auth_path,dict(authorized=True,authorized_by=getpass.getuser(),authorized_at=now(),
                authorization_reference='Explicit execute --authorize after review of extracted project text',
                run_plan_sha256=sha256(directory/'plan.json'),review_sha256=sha256(directory/'review.json'),
                project_ids=[p['project_id'] for p in plan['projects']],maximum_new_calls=plan['maximum_calls'],
                token_reservation_cap=plan['total_token_reservation_cap'],max_retries=plan.get('token_limit_retries',0)))
        auth=read(auth_path)
        require(auth['authorized'] is True and auth['run_plan_sha256']==sha256(directory/'plan.json') and
            auth['review_sha256']==sha256(directory/'review.json') and auth['max_retries']==plan.get('token_limit_retries',0),'Autorizacion no coincide con texto revisado')
        require(plan.get('runtime', {}).get('provider') in ('ollama','openai'),
                'Plan historico Codex: solo verificable/exportable; crear una nueva ejecucion Ollama, sin reutilizar sus respuestas')
        settings = llm_configuration(plan['runtime']['configuration'])
        if plan.get('request_protocol') == CONTEXT_VERSION and not any(
                iid not in p['context_limits'] and iid not in p['blocked_indicators'] for p in state['projects'] for iid in p['pending']):
            write(directory/'status.json', summary(state))
            return summary(state)
        client = OllamaClient(settings) if settings['provider']=='ollama' else create_client(settings)
        runtime = client.inspect()  # Metadata only; no inference or download.
        binding_path = directory/'provider.json'
        if binding_path.exists():
            require(read(binding_path) == runtime, 'RUNTIME_DRIFT: modelo/digest/configuracion distintos del checkpoint Ollama')
        else:
            write(binding_path, runtime)
        while state['status']!='COMPLETE':
            run_root=next((p for p in directory.parents if (run_file(p, 'model.binding.json')).exists()),None)
            if run_root and (run_file(run_root, 'stop.request.json')).exists():
                write(directory/'status.json',dict(summary(state),status='INTERRUPTED'))
                return dict(summary(state),status='INTERRUPTED')
            require(not state['blocking_errors'],'Ejecucion bloqueada; no se reintenta: '+'; '.join(state['blocking_errors']))
            bounded = plan.get('request_protocol') == CONTEXT_VERSION
            runnable = [s for s in state['projects'] if not s['complete'] and
                (not bounded or any(i not in s['context_limits'] and i not in s['blocked_indicators'] for i in s['pending']))]
            if not runnable:
                write(directory/'status.json', summary(state))
                return summary(state)  # Explicit partial coverage, never invented decisions.
            st=runnable[0];p=next(p for p in plan['projects'] if p['project_id']==st['project_id'])
            require(any((p['fields'].get(f) or '').strip() for f in substantive_fields(p['fields'])),'No hay campos sustantivos; corregir la extraccion y preparar otra ejecucion antes de inferir')
            phase='assessment' if st['discovery_complete'] else 'discovery';ids=st['pending'][:3] if phase=='assessment' else []
            if bounded:
                ids=[i for i in st['pending'] if i not in st['context_limits'] and i not in st['blocked_indicators']][:1]
            request=request_for(plan,p,phase,ids);reservation=plan['budgets'][phase+'_reservation']
            retries=plan.get('token_limit_retries',0) if bounded else 0
            schema = gd.selection_schema(p['fields']) if phase=='discovery' else v3.schemas(p['fields'])['assessment_batch']
            estimate=(context_guard(request['prompt'],schema,settings,runtime,request['context_budget']) if bounded else
                math.ceil(len(request['prompt'])*plan['observed_character_ratio']*1.25)+12000)
            require(estimate<=reservation,'Solicitud excede reserva estimada; no truncar texto ni despachar')
            require(state['new_calls']<plan['maximum_calls'] and state['total_tokens']+reservation<=plan['total_token_reservation_cap'],'Presupuesto de ejecucion agotado')
            context_guard(request['prompt'], schema, settings, runtime, request.get('context_budget'))
            require(client.inspect() == runtime, 'RUNTIME_DRIFT: cambio de modelo o servidor antes de la llamada')
            number=len(list((directory/'calls'/p['project_id']).glob('assessment_*')))+1 if bounded else len(st['rows'])//3+1
            out=directory/'calls'/p['project_id']/('discovery' if phase=='discovery' else 'assessment_'+str(number))
            out.mkdir(parents=True,exist_ok=True)
            require(not (out/'dispatch.claim.json').exists(),'UNCERTAIN_OUTCOME: claim existente; no repetir')
            cp=dict(project_id=p['project_id'],phase=phase,indicator_ids=ids,run_plan_sha256=sha256(directory/'plan.json'),
                request_sha256=canonical_hash(request),runtime=runtime,provider_binding_sha256=sha256(binding_path),requested_model=plan['requested_model'],
                execution_id=plan['execution_id'],maximum_new_calls=1+retries,max_retries=retries,timeout_seconds=plan['timeout_seconds'],reservation=reservation,estimated_tokens=estimate)
            write(out/'plan.json',cp);write(out/'schema.json',schema)
            call_auth=dict(authorized=True,project_ids=[p['project_id']],phase=phase,indicator_ids=ids,plan_sha256=sha256(out/'plan.json'),
                request_sha256=cp['request_sha256'],token_budget=reservation,maximum_new_calls=1+retries,max_retries=retries,
                authorized_by=auth['authorized_by'],authorization_reference='Reviewed live-run authorization sha256='+sha256(auth_path),authorized_at=now())
            write(out/'authorization.used.json',call_auth)
            with (out/'dispatch.claim.json').open('x',encoding='utf-8') as stream: json.dump(dict(authorization_sha256=sha256(out/'authorization.used.json')),stream)
            def gate(wrapper,pid,indicator_ids):
                if phase=='discovery':
                    require(pid==p['project_id'] and indicator_ids==[gd.MARKER],'Envelope de descubrimiento difiere')
                    gd.validate_selection(wrapper,p,plan['profiles'])
                else:
                    v3.validate_wrapper(wrapper,pid,ids,p['fields'])
                    validate_context_evidence(request, wrapper)
                    for item in wrapper['assessments']:
                        assessment = {k:v for k,v in item.items() if k!='indicator_id'}
                        issues = semantic_issues(v3.validate(p['fields'],plan['profiles'][item['indicator_id']],
                            assessment,plan['rubrics'][item['indicator_id']]), assessment, item['indicator_id'])
                        if issues:
                            raise AssessmentValidationError(issues)
            emit(dict(status='CALL_STARTED',project_id=p['project_id'],phase=phase,indicator_ids=ids,token_reservation=reservation))
            provider = OllamaAssessmentProvider(out/phase/'ollama_runs', out/'schema.json', lambda p,i:request,
                settings=settings, client=client, runtime=runtime, wrapper_validator=gate,
                execution_id=plan['execution_id'], max_retries=0, max_indicators=3, token_limit_retries=retries)
            error = None
            try:
                provider.evaluate(dict(project_id=p['project_id'], fields=p['fields']),
                    [dict(indicator_id=gd.MARKER)] if phase=='discovery' else [plan['profiles'][i] for i in ids])
            except Exception as exc:
                error = str(exc)
            record_path = out/'records'/phase/(p['project_id']+'.json')
            artifacts = {f.relative_to(out).as_posix():sha256(f) for f in (out/phase/'ollama_runs').rglob('*') if f.is_file()}
            record = dict(project_id=p['project_id'], phase=phase, wrapper=provider.last_output,
                calls=provider.calls, status='ERROR' if error else 'VALID', error=error,
                request_sha256=canonical_hash(request), artifact_hashes=artifacts)
            write(record_path,record)
            tokens,wall=aggregate_metrics(record['calls'])
            status='PASS'
            if record['status']!='VALID' or not 1<=len(record['calls'])<=retries+1: status='BLOCKED_ERROR'
            elif wall is None or any(v is None for v in tokens.values()): status='BLOCKED_MISSING_METRICS'
            elif tokens['total_tokens']>reservation: status='BLOCKED_TOKEN_BUDGET'
            elif tokens['total_tokens']>plan['budgets'][phase+'_postcall_review_threshold']: status='PAUSED_TOKEN_REVIEW'
            if status=='PASS' and phase=='assessment':
                rows=[indicator_row(plan,p,a) for a in record['wrapper']['assessments']]
                write(out/'assessment.rows.json',dict(record_sha256=sha256(record_path),rows=rows))
            verify_hashes(out,record['artifact_hashes']);check(directory)
            recovered = plan.get('recovery', {})
            retry = max(0,len(record['calls'])-1)+int(recovered.get('project_id') == p['project_id'] and recovered.get('indicator_ids') == ids)
            result=dict(status=status,project_id=p['project_id'],phase=phase,indicator_ids=ids,calls=len(record['calls']),retries=retry,tokens=tokens,wall_seconds=wall,error=record['error'])
            if status!='PASS':
                result['provider'] = settings['provider']
            write(out/'verification.json',result);emit(result)
            state=verify_run(directory);write(directory/'status.json',summary(state))
            if status!='PASS' and not (bounded and plan.get('isolate_indicator_errors')):
                raise ValueError(status+': '+str(record['error'])+'. Sin reintento automatico. Revisar los artefactos privados de '+str(out)+'; se conservan las publicaciones anteriores.')
        return summary(state)

def summary(state):
    return {**{k:v for k,v in state.items() if k!='projects'},'projects':[{k:v for k,v in s.items() if k!='rows'} for s in state['projects']],
        'valid_assessments':sum(len(s['rows']) for s in state['projects'])}
