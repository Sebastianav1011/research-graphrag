"""Read-only queue snapshots. Monitoring never authorizes or repairs a run."""
from run_paths import file_path as run_file
from collections import Counter
from datetime import datetime
from pathlib import Path
import csv
import json
import sqlite3
from . import store as s


def snapshot(directory):
    directory=Path(directory)
    db=sqlite3.connect((directory/'queue.sqlite').resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    db.row_factory=sqlite3.Row
    try:
        db.execute('BEGIN')
        jobs=[dict(r) for r in db.execute('SELECT * FROM jobs')]
        projects=[r[0] for r in db.execute('SELECT pid FROM projects')]
        counts=Counter(j['status'] for j in jobs)
        usage=db.execute('SELECT COUNT(*),SUM(input_tokens),SUM(output_tokens),SUM(wall),SUM(input_tokens IS NULL OR output_tokens IS NULL) FROM usage').fetchone()
        imported_calls=db.execute("SELECT COUNT(*) FROM usage WHERE step='historical'").fetchone()[0]
        last=db.execute('SELECT at,stage,code,pid,iid FROM events ORDER BY seq DESC LIMIT 1').fetchone()
        stage=db.execute("SELECT value FROM meta WHERE key='stage'").fetchone()
        resource=db.execute("SELECT value FROM meta WHERE key='resource_wait'").fetchone()
        worker=s.read(run_file(directory, 'worker.json')) if (run_file(directory, 'worker.json')).exists() else {}
        info=s.process_info(worker['pid']) if worker.get('pid') else {}
        active=(info.get('alive') is True and worker.get('creation') is not None
                and info.get('creation')==worker['creation'] and worker.get('state') not in ('FINISHED','INTERRUPTED','FAILED'))
        groups={pid:[j for j in jobs if j['pid']==pid] for pid in projects}
        categories=Counter()
        for entries in groups.values():
            states=Counter(j['status'] for j in entries)
            if entries and states['PASS']==len(entries):category='completed'
            elif active and (states['RUNNING'] or states['WAITING_RESOURCES']):category='running'
            elif states['PASS']:category='partial'
            elif states['BLOCKED'] or states['UNCERTAIN']:category='failed'
            elif not entries:category='without_jobs'
            else:category='pending'
            categories[category]+=1
        total=len(jobs);passed=counts['PASS'];touched=sum(j['attempts']>0 for j in jobs)
        state=('COMPLETE' if total and passed==total else 'RUNNING' if active else
               'FAILED' if worker.get('state')=='FAILED' else
               'INTERRUPTED' if worker.get('state')=='INTERRUPTED' or worker.get('started_at') and worker.get('state')=='RUNNING' or touched and counts['RUNNING'] else
               'PARTIAL' if touched else 'PREPARED')
        current=next((j for j in jobs if j['status'] in ('RUNNING','WAITING_RESOURCES')),None)
        elapsed=None
        if worker.get('started_at') and (worker.get('finished_at') or last):
            end=datetime.now().astimezone().isoformat() if active else worker.get('finished_at') or last['at']
            elapsed=max(0,(datetime.fromisoformat(end)-datetime.fromisoformat(worker['started_at'])).total_seconds())
        result=dict(status=state,projects_total=len(projects),
            projects_processed=sum(bool(v) and all(j['status'] in ('PASS','BLOCKED','UNCERTAIN') for j in v) for v in groups.values()),
            processing_complete=bool(jobs) and all(j['status'] in ('PASS','BLOCKED','UNCERTAIN') for j in jobs),
            results_available=bool(passed),
            projects_with_partial_results=sum(0<sum(j['status']=='PASS' for j in v)<len(v) for v in groups.values()),
            **{'projects_'+k:categories[k] for k in ('completed','running','partial','failed','pending','without_jobs')},
            projects_with_errors=sum(any(j['status'] in ('BLOCKED','UNCERTAIN') for j in v) for v in groups.values()),
            indicators_total=total,evaluated=passed,pending=counts['PENDING'],running=counts['RUNNING'],
            blocked=counts['BLOCKED'],uncertain=counts['UNCERTAIN'],counts=dict(counts),
            blocked_details=[dict(project=j['pid'],indicator=j['iid'],error=j['error']) for j in jobs if j['status']=='BLOCKED'],
            progress_percent=round(100*passed/total,2) if total else None,
            progress_scope='Resultados validados PASS / trabajos proyecto-indicador del manifiesto; bloqueados no cuentan como completados.',
            calls=usage[0],input_tokens=usage[1],output_tokens=usage[2],wall_seconds=usage[3],missing_usage_metrics=usage[4] or 0,
            calls_imported=imported_calls,calls_this_run=usage[0]-imported_calls,
            current_project=current['pid'] if current else None,current_indicator=current['iid'] if current else None,
            stage=stage[0] if stage else 'prepared',last_activity=dict(last) if last else None,
            waiting_resources=counts['WAITING_RESOURCES'],resources=json.loads(resource[0]) if resource else None,
            elapsed_seconds=elapsed,elapsed_scope='Intervalo del worker hasta ultima actividad registrada si esta detenido',
            eta_seconds=None,eta_reason='No estimable: ejecucion detenida, errores pendientes o muestra insuficiente.',
            worker=dict(pid=worker.get('pid'),alive=bool(active),state=worker.get('state')),
            inference_calls=0,inference_calls_scope='Llamadas realizadas por esta consulta de status; calls informa las registradas en el run.')
        terminal=sum(j['attempts']>0 and j['status'] in ('PASS','BLOCKED','UNCERTAIN') for j in jobs)
        if active and terminal>=20 and not counts['BLOCKED'] and not counts['UNCERTAIN'] and elapsed:
            result.update(eta_seconds=elapsed/terminal*(counts['PENDING']+counts['RUNNING']+counts['WAITING_RESOURCES']),eta_reason='Extrapolacion orientativa de trabajos nuevos terminados; excluye resultados importados y no incluye futuras reparaciones.')
        return result
    finally:db.close()


def progress(root,run):
    directory=Path(run)/'autonomous/main'
    manifest=s.read(directory/'manifest.json')
    result=snapshot(directory)
    drift=[name for name,digest in manifest['code'].items() if not (Path(root)/name).is_file() or s.sha(Path(root)/name)!=digest]
    intake_error=None
    try:
        from . import scope
        cached={name:(value['size'],value['mtime_ns']) for name,value in manifest['source_inventory']['files'].items()}
        scope.check(root,manifest['source_inventory'],cached)
    except (ValueError,OSError) as exc:intake_error=str(exc)
    auth=s.read(directory/'authorization.json') if (directory/'authorization.json').exists() else {}
    authorized=auth.get('authorized') is True and auth.get('manifest_sha256')==s.sha(directory/'manifest.json')
    result.update(run_id=Path(run).name,code_drift=drift,inference_allowed=not drift and not intake_error and authorized,authorized=authorized,
                  integrity='LECTURA DE COLA; verificar integridad completa antes de reanudar')
    if intake_error:result.update(execution_state=result['status'],status='BLOCKED_INTEGRITY',integrity_error=intake_error)
    perf=Path(run)/'resultados/performance/resumen.csv'
    if perf.exists():
        with perf.open(encoding='utf-8-sig',newline='') as f:row=next(csv.DictReader(f,delimiter=';'),{})
        value=row.get('tiempo_total_activo_segundos')
        if value:result['recorded_active_seconds']=float(value.replace(',','.'))
    return result


def render(r):
    def duration(value):
        if value is None:return 'No disponible'
        seconds=int(value);return f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}'
    labels={'RUNNING':'EN PROCESO','COMPLETE':'COMPLETADO','INTERRUPTED':'INTERRUMPIDO','FAILED':'FALLIDO','PARTIAL':'PARCIAL / DETENIDO','PREPARED':'PREPARADO'}
    rows=['GRAPHRAG — ESTADO DE EJECUCIÓN','',f"Run ID: {r.get('run_id','')}",f"Estado: {labels.get(r['status'],r['status'])}",'']
    for key,label in [('total','seleccionados'),('completed','completados'),('running','en proceso'),('partial','con resultados parciales'),('pending','pendientes'),('failed','fallidos sin resultados válidos')]:
        rows.append(f"Proyectos {label}: {r['projects_'+key]}")
    rows.append(f"Proyectos procesados (incluidos los errores individuales): {r['projects_processed']}")
    rows.append(f"Proyectos sin trabajos LLM en el manifiesto: {r['projects_without_jobs']} (no se cuentan como evaluados)")
    rows.append(f"Proyectos con avance parcial, incluidos los activos: {r['projects_with_partial_results']}")
    rows += [f"Proyectos con errores (pueden ser parciales): {r['projects_with_errors']}",'',
        f"Indicadores evaluados válidos: {r['evaluated']} / {r['indicators_total']}",
        f"Indicadores pendientes: {r['pending']}; reclamados: {r['running']}; bloqueados: {r['blocked']}; inciertos: {r['uncertain']}",
        f"Progreso: {r['progress_percent']} %",r['progress_scope'],
        f"Proyecto actual / último reclamado: {r['current_project'] or 'Ninguno'}",
        f"Etapa actual / última: {r['stage']}",
        f"Tiempo registrado activo: {duration(r.get('recorded_active_seconds',r['elapsed_seconds']))}",
        f"Tiempo estimado restante: {duration(r['eta_seconds'])}",r['eta_reason'],
        f"Última actividad: {json.dumps(r['last_activity'],ensure_ascii=False)}",
        f"Llamadas LLM registradas: {r['calls']}; tokens conocidos entrada/salida: {r['input_tokens']}/{r['output_tokens']}",
        f"Llamadas nuevas: {r['calls_this_run']}; importadas verificadas: {r['calls_imported']}",
        f"Llamadas con métricas incompletas: {r['missing_usage_metrics']}"]
    if r.get('code_drift'):rows.append('Código cambiado: este run requiere su versión autorizada para reanudar; no se modifica el histórico.')
    if r.get('blocked_details'):
        reasons=Counter(item['error'] or 'SIN_DIAGNOSTICO' for item in r['blocked_details'])
        rows.append('Motivos de bloqueo: '+ '; '.join(f'{code}: {count}' for code,count in sorted(reasons.items())))
        rows.append('Detalle por proyecto e indicador disponible con --json (blocked_details).')
    if r.get('waiting_resources'):
        rows.append('ESPERA DE RAM: '+json.dumps(r.get('resources'),ensure_ascii=False))
    return '\n'.join(rows)
