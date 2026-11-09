"""Private reports from recorded calls; missing metrics stay missing, reuse is explicit."""
from collections import Counter
from datetime import datetime
import csv
import json
from pathlib import Path
import statistics

from .performance import metric, usage_metrics, interval_union, describe, environment
from .experiment_inputs import read, sha256
from .experiment import read_jsonl, write_json
from .selection import canonical_hash


def flatten(row, name, value):
    row[name]=value['value']; row[name+'_status']=value['status']


def correlation(pairs):
    pairs=[(a,b) for a,b in pairs if a is not None and b is not None]
    if len(pairs)<3 or len({a for a,_ in pairs})<2 or len({b for _,b in pairs})<2:
        return None
    return statistics.correlation([a for a,_ in pairs],[b for _,b in pairs])


def projections_from_completed(projects):
    """A failed/uncertain transport is not a completed-project throughput sample."""
    values=[p['inference_seconds'] for p in projects if p['completion_status']=='VALID'
            and p['indicators_evaluated']>0 and p['inference_seconds_status']=='MEASURED']
    mean=statistics.mean(values) if values else None
    return [{'projects':n,'estimated_serial_seconds':n*mean if mean is not None else None,
        'completed_project_sample_n':len(values),'status':'ESTIMATED' if mean is not None else 'NOT_AVAILABLE',
        'assumptions':'same eligible text/candidate mix, serial project calls, same service/model/latency; completed projects only; excludes prep, validation, queue gaps; failed attempts reported separately; not end-to-end 2232 coverage'} for n in (50,100,2232)]


def collect(root, config_path=None):
    root=Path(root)
    if config_path:
        from .experiment import verify_prepared, validate_record
        config,out,manifest,data,selected,requests,runtime=verify_prepared(root,config_path)
        request_map={r['project_id']:r for r in requests}
        records=[]
        for p in selected:
            path=out/'records'/(p['project_id']+'.json')
            if path.exists():
                r=validate_record(read(path),p,data['profiles'],manifest,request_map[p['project_id']],out)
                calls=[read(c) for c in sorted((out/'codex_runs'/p['project_id']).glob('attempt_*/call.json'))]
                records.append((p,r,calls))
            else:
                records.append((p,None,[]))
        execution_id=manifest['execution_id']
        scope='CURRENT_V2_RUN'
        prepared_metrics=read(out/'preparation_metrics.json') if (out/'preparation_metrics.json').exists() else {}
    else:
        from .closure_audit import historical_records
        selected,hist=historical_records(root)
        records=[(p,r,[read(c) for c in sorted((origin/'codex_runs'/p['project_id']).glob('attempt_*/call.json'))])
                 for p,r,origin,_ in hist]
        execution_id='HISTORICAL20_'+sha256(root/'outputs/layer4/pruebas/piloto_v2/muestra_20/selection_manifest.json')[:16]
        scope='HISTORICAL_V1_BASELINE_NO_NEW_INFERENCE'
        prepared_metrics={}
    projects=[];assessments=[];intervals=[];seen_calls=set()
    for p,r,calls in records:
        for c in calls:
            key=canonical_hash({k:c.get(k) for k in ('project_id','timestamp','prompt_sha256','response_sha256')})
            if key in seen_calls:
                raise ValueError('Duplicate CLI call in performance population')
            seen_calls.add(key)
        returned=r.get('rows',[]) if r else []
        row={'execution_id':execution_id,'source_scope':scope,'project_id':p['project_id'],'siap_id':p['siap_id'],
            'indicators_requested':len(p['candidates']),'indicators_evaluated':len(returned),
            'codex_calls_recorded':len(calls),
            'new_codex_calls_current_invocation':0,
            'reused_for_report':True,'source_assessment_version':'ASSESSMENT_V2' if config_path else 'ASSESSMENT_V1',
            'model_requested':calls[0].get('requested_model') if calls else None,
            'model_observed':None,'model_observed_status':'NOT_AVAILABLE',
            'local_resource_scope':'PYTHON_COORDINATOR_ONLY_EXCLUDES_CLI_CHILD_AND_REMOTE',
            'retries':sum(c.get('retry',0)>0 for c in calls),
            'errors':sum(not c.get('successful_transport',False) for c in calls),
            'completion_status':r['status'] if r else 'NOT_EXECUTED',
            'text_characters':sum(len(v or '') for v in p['fields'].values()),
            'metric_provenance':'recorded monotonic telemetry when available; otherwise recorded UTC interval'}
        observed=[m.get('model') or m.get('model_name') for c in calls for m in c.get('model_observations',[])]
        observed=[m for m in observed if m]
        if observed:
            row.update(model_observed=';'.join(sorted(set(observed))),model_observed_status='MEASURED')
        call_wall=[];project_intervals=[]
        for c in calls:
            if c.get('timestamp') and c.get('finished_at'):
                a=datetime.fromisoformat(c['timestamp']).timestamp(); b=datetime.fromisoformat(c['finished_at']).timestamp()
                if b<a:
                    raise ValueError('Negative recorded interval')
                intervals.append((a,b));project_intervals.append((a,b))
                wall=c.get('performance',{}).get('wall_seconds',{}).get('value',b-a)
                call_wall.append(wall)
        perf=r.get('performance',{}) if r else {}
        total=perf.get('project_total',{})
        flatten(row,'inference_seconds',metric(interval_union(project_intervals) if project_intervals else None,
                                               scope='UNION_OF_RECORDED_CALL_INTERVALS'))
        flatten(row,'total_seconds',total.get('wall_seconds',metric()))
        initial_prepare=prepared_metrics.get(p['project_id'],{}).get('wall_seconds',{}).get('value')
        prepare=perf.get('preparation_seconds')
        flatten(row,'preparation_seconds',metric(initial_prepare+(prepare or 0) if initial_prepare is not None else prepare))
        flatten(row,'validation_seconds',metric(perf.get('validation_seconds')))
        flatten(row,'average_seconds_per_indicator',metric(
            row['inference_seconds']/len(returned) if returned and row['inference_seconds'] is not None else None,
            status='ESTIMATED' if returned and row['inference_seconds'] is not None else 'NOT_AVAILABLE',
            scope='CALL_WALL_DIVIDED_BY_INDICATORS_NOT_SEPARATE_MEASUREMENTS'))
        for target,source in (('local_ram_bytes','ram_bytes'),('local_peak_ram_bytes','peak_ram_bytes'),('local_cpu_seconds','cpu_seconds')):
            flatten(row,target,total.get(source,metric()))
        usage=[usage_metrics(c) for c in calls]
        for token in ('input_tokens','output_tokens','cached_tokens','total_tokens'):
            values=[u[token]['value'] for u in usage]
            flatten(row,token,metric(sum(values) if values and all(v is not None for v in values) else None))
        row['token_scope']='ORIGINAL_CALLS_ONCE; CACHED_TOKENS_SUBSET_OF_INPUT; NO_NEW_USAGE_BY_REPORT'
        row['retry_count_status']='MEASURED' if calls else 'NOT_AVAILABLE'
        row['invalid_assessments']=sum(a['assessment_validation_status']!='VALID' for a in returned)
        row['record_errors']=int(bool(r and r.get('error')))
        first=['project_id','siap_id','indicators_evaluated','codex_calls_recorded','inference_seconds',
               'inference_seconds_status','model_observed','completion_status']
        row={k:row[k] for k in first} | {k:v for k,v in row.items() if k not in first}
        projects.append(row)
        for assessment in returned:
            ar={'execution_id':execution_id,'project_id':p['project_id'],'siap_id':p['siap_id'],
                'indicator_id':assessment['indicator_id'],'decision':assessment['decision'],
                'validation_status':assessment['assessment_validation_status'],
                'call_scope':'SHARED_PROJECT_CALL_NO_PER_INDICATOR_TOKEN_ATTRIBUTION',
                'completion_status':r['status'],'reused_for_report':True,
                'wall_seconds_equal_share':row['average_seconds_per_indicator'],
                'wall_seconds_equal_share_status':row['average_seconds_per_indicator_status']}
            for name in ('input_tokens','output_tokens','cached_tokens','total_tokens','local_cpu_seconds','local_ram_bytes','local_peak_ram_bytes'):
                flatten(ar,name,metric())
            assessments.append(ar)
    measured=[p for p in projects if p['inference_seconds_status']=='MEASURED' and p['indicators_evaluated']]
    wall=interval_union(intervals)
    span=max(b for _,b in intervals)-min(a for a,_ in intervals) if intervals else None
    summary={'execution_id':execution_id,'scope':scope,'projects_selected':len(projects),
        'projects_evaluated':sum(p['indicators_evaluated']>0 for p in projects),
        'assessments_returned':len(assessments),'new_inference_calls':0,
        'original_calls_unique':len(seen_calls),'inference_wall_union_seconds':wall if intervals else None,
        'source_calendar_span_seconds_includes_gaps':span,
        'statistics':{k:describe(p[k] for p in projects if p[k+'_status']=='MEASURED') for k in
                      ('inference_seconds','total_seconds','preparation_seconds','validation_seconds',
                       'local_cpu_seconds','local_ram_bytes','local_peak_ram_bytes','input_tokens','output_tokens','cached_tokens','total_tokens')},
        'decisions':dict(Counter(a['decision'] for a in assessments)),
        'errors':sum(p['errors'] for p in projects),'retries':sum(p['retries'] for p in projects),
        'correlation_text_length_inference_seconds':correlation([(p['text_characters'],p['inference_seconds']) for p in measured]),
        'correlation_indicator_count_inference_seconds':correlation([(p['indicators_evaluated'],p['inference_seconds']) for p in measured]),
        'environment_reporting':environment(),'original_environment':'NOT_AVAILABLE unless pinned in source run',
        'average_inference_seconds_per_indicator':sum(p['inference_seconds'] for p in measured)/sum(p['indicators_evaluated'] for p in measured) if measured else None,
        'human_acceptance':'PENDING','formula_v2_approval':'PENDING'}
    stats=summary['statistics']['inference_seconds']
    for name in ('local_ram_bytes','local_peak_ram_bytes'):
        summary['statistics'][name]['total']=None
    summary['projections']=projections_from_completed(projects)
    return projects,assessments,summary


def markdown(projects,summary):
    def f(v):return 'NOT_AVAILABLE' if v is None else f'{v:.3f}'
    stats=summary['statistics']['inference_seconds']
    text=f'''# Desempeño de Capa 4

## 1. Objetivo del experimento
Documentar recursos observables por proyecto y evaluación. Ejecución: `{summary['execution_id']}`.
Población: **{summary['scope']}**. Este informe reutiliza registros; no invoca inferencia.
Proyectos evaluados: {summary['projects_evaluated']}; assessments: {summary['assessments_returned']}.

## 2. Entorno de ejecución
Entorno de generación del informe: {json.dumps(summary['environment_reporting'],ensure_ascii=False)}.
No se atribuye este entorno a las llamadas históricas. Entorno original: {summary['original_environment']}.

## 3. Modelo y configuración
Exclusivamente adaptador Codex CLI. Los campos model_requested y model_observed distinguen solicitud
y observación. Modelo ausente: NOT_AVAILABLE. No se deduce de la sesión de desarrollo.

## 4. Metodología utilizada
MEASURED: eventos/intervalos UTC registrados y telemetría directa cuando existe.
ESTIMATED: reparto igual por indicador y proyecciones con supuestos explícitos.
NOT_AVAILABLE: no observado; NULL no equivale a cero. Cada llamada original se cuenta una vez;
los tokens cacheados son un subconjunto de entrada y no se suman otra vez al total.
Tiempos compartidos no son mediciones independientes por indicador. La unión de intervalos
evita sumar solapamientos. Las pausas entre lotes no son tiempo activo de inferencia.

## 5. Desempeño por proyecto
| PROJECT | SIAP | Indicadores | Llamadas originales | Inferencia s | Estado |
|---|---|---:|---:|---:|---|
'''
    for p in projects:
        text+=f"| {p['project_id']} | {p['siap_id']} | {p['indicators_evaluated']} | {p['codex_calls_recorded']} | {f(p['inference_seconds'])} | {p['completion_status']} |\n"
    text+=f'''
## 6. Tiempo promedio y mediano de evaluación
Inferencia por proyecto: media {f(stats['mean'])} s, mediana {f(stats['median'])} s,
p90 {f(stats['p90'])} s, p95 {f(stats['p95'])} s. N medido: {stats['n']}.
Tiempo activo de pared (unión): {f(summary['inference_wall_union_seconds'])} s.
Extensión de calendario con pausas: {f(summary['source_calendar_span_seconds_includes_gaps'])} s.
Preparación/validación/total solo se informan donde existe telemetría; no se reconstruyen como cero.

## 7. Tiempo promedio por indicador
Razón de tiempos de inferencia de proyectos / assessments devueltos: {f(summary['average_inference_seconds_per_indicator'])} s.
El reparto por evaluación se identifica ESTIMATED; no se observaron intervalos individuales dentro de una llamada conjunta.

## 8. Tokens utilizados
Entrada: {summary['statistics']['input_tokens']['total']}; salida: {summary['statistics']['output_tokens']['total']};
cacheados: {summary['statistics']['cached_tokens']['total']}; total entrada + salida: {summary['statistics']['total_tokens']['total']}.
Estos totales describen solo llamadas con observación disponible (N en RESUMEN); no imputan faltantes.
Costo monetario: NOT_AVAILABLE. Generar/reutilizar este informe consume cero llamadas nuevas.

## 9. CPU y memoria locales
CPU: N={summary['statistics']['local_cpu_seconds']['n']}. RAM: N={summary['statistics']['local_ram_bytes']['n']}.
Los históricos sin telemetría permanecen NOT_AVAILABLE. V2 mide CPU del coordinador Python y RSS
muestreada cada 50 ms. Excluye el proceso hijo CLI y los servidores remotos; el pico muestreado
puede omitir transitorios. No se suman picos ni RSS como si fueran consumo acumulado.

## 10. Errores y reintentos
Errores técnicos registrados: {summary['errors']}; reintentos: {summary['retries']}.
Los estados por proyecto diferencian pendientes, errores y evaluaciones devueltas.

## 11. Cantidad de texto y tiempo
Pearson descriptivo caracteres/segundos: {f(summary['correlation_text_length_inference_seconds'])}.
No indica causalidad ni permite inferir tokens a partir de caracteres.

## 12. Cantidad de indicadores y tiempo
Pearson descriptivo indicadores/segundos: {f(summary['correlation_indicator_count_inference_seconds'])}.
Las llamadas conjuntas comparten preparación y contexto; la muestra es intencional y pequeña.

## 13. Proyección de procesamiento
| Proyectos | Segundos seriales estimados | Naturaleza |
|---:|---:|---|
'''
    for p in summary['projections']:
        text+=f"| {p['projects']} | {f(p['estimated_serial_seconds'])} | {p['status']} |\n"
    return text+'''
## 14. Supuestos y limitaciones
Media medida por proyecto, misma mezcla de textos y candidatos, mismo servicio/modelo y ejecución serial.
Excluye preparación, validación y pausas. No es SLA ni intervalo de confianza. Los 2.232 PROJECT
de 4B no son 2.232 candidatos elegibles de 4A: actualmente solo 280 tienen candidatos elegibles.
El procesamiento de todos requiere una decisión metodológica aparte; aquí no se reconstruye Capa 3.
Los modelos históricos no observados limitan comparabilidad. Los costos monetarios y recursos remotos no se estiman.

## 15. Conclusiones sobre eficiencia y escalabilidad
La infraestructura admite lotes y reanudación sin repetir inferencias compatibles. Esta línea base
permite planificar tiempo serial bajo supuestos, pero no demuestra calidad semántica ni superioridad
de V2. Faltan autorización de nuevas inferencias V2, comparación real, revisión humana y aprobación.
'''


def generate(root, config_path=None):
    from .closure_export import render_workbook
    from .experiment_export import sheet
    root=Path(root); projects,assessments,summary=collect(root,config_path)
    out=root/'outputs/layer4/performance';out.mkdir(parents=True,exist_ok=True)
    audit=root/'outputs/layer4/performance/historico_cierre';audit.mkdir(parents=True,exist_ok=True)
    with (out/'metricas_desempeno_capa4.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(projects[0]) if projects else ['execution_id'])
        writer.writeheader();writer.writerows(projects)
    (out/'informe_desempeno_capa4.md').write_text(markdown(projects,summary),encoding='utf-8')
    summary_rows=[]
    for name,values in summary['statistics'].items():
        for statistic,value in values.items():
            # Sums of RSS/persistent RAM are meaningless; omit them.
            if statistic=='total' and 'ram' in name:
                continue
            summary_rows.append({'metrica':name,'estadistico':statistic,'valor':value,
                                 'naturaleza':'MEASURED' if value is not None else 'NOT_AVAILABLE'})
    for p in summary['projections']:
        summary_rows.append({'metrica':f"projection_{p['projects']}_projects_serial_seconds",'estadistico':'projection',
                             'valor':p['estimated_serial_seconds'],'naturaleza':p['status']})
    spec={'sheets':[sheet('PROYECTOS',list(projects[0]) if projects else ['execution_id'],projects),
                    sheet('ASSESSMENTS',list(assessments[0]) if assessments else ['execution_id'],assessments),
                    sheet('RESUMEN',['metrica','estadistico','valor','naturaleza'],summary_rows)]}
    for tab in spec['sheets']:
        tab['widths']={c:max(20,min(55,len(c)*1.05)) for c in tab['columns']}
        tab['widths'].update(execution_id=44,source_scope=57,metric_provenance=100,
            token_scope=100,local_resource_scope=75,call_scope=75,metrica=47)
        tab['headerHeight']=45
        tab['freezeColumns']=2 if tab['name']!='RESUMEN' else 0
        tab['numericFormats']={c:('#,##0' if any(v in c for v in ('tokens','bytes','calls','indicators','retries','errors','characters')) else '0.000')
                               for c in tab['columns'] if not c.endswith('_status') and any(v in c for v in
                                    ('seconds','tokens','bytes','calls','indicators','retries','errors','characters','valor'))}
        tab['previewRanges']=['A1:D8'] if tab['name']=='RESUMEN' else ['A1:H4','I1:P4']
    render_workbook(root,spec,out/'reporte_desempeno_capa4.xlsx',audit)
    write_json(audit/('summary_'+summary['execution_id']+'.json'),summary)
    write_json(audit/'summary.json',summary)
    write_json(audit/'manifest.json',{'execution_id':summary['execution_id'],'scope':summary['scope'],
        'output_hashes':{p.name:sha256(p) for p in out.iterdir() if p.is_file()},
        'data_hash':canonical_hash({'projects':projects,'assessments':assessments,'summary':summary})})
    return summary
