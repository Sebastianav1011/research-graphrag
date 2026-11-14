"""Export every verified assessment, including negatives without literal quotes.

Read-only recovery of existing runs. No inference, checkpoint migration or status
updates. Kept separate from the evidence-only Power BI projection so historical
code fingerprints and that projection's academic contract remain intact.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT)]
from layer4_evaluation import live_execution as live
from scripts import pipeline_coordinator as coordinator
from run_paths import file_path

HEADERS = ['ID del proyecto','ID interno del proyecto','Indicador','Nombre del indicador',
    'Estado de cumplimiento','Párrafo de evidencia o justificación','Fuente o columna de origen',
    'Confianza calculada (0–100)','Estado de validación','Tipo de texto','Estado de confianza',
    'Referencias exactas de evidencia o contexto','Registro de evaluación']
SUMMARY_HEADERS = ['ID del proyecto','Evaluados válidos','Positivos','Negativos','Evidencia insuficiente',
    'Bloqueados','Pendientes','Total indicadores','Proyecto completo','Sin contexto recuperado',
    'Bloqueos de contexto','Errores de evaluación','Estado del proyecto']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(root, run):
    coordinator.check(root, run)
    return [dict(directory=str(d),state=live.verify_run(d))
        for d in sorted((run/'workspace/outputs/layer4').glob('batch_*'))]


def write_exports(root, run, verified):
    """Project already verified states without applying a positive-evidence filter."""
    destination=run/'resultados'
    names=['indicadores_parciales_recuperados.xlsx','indicadores_parciales_recuperados.csv',
        'informe_resultados_parciales_recuperados.md','diagnostico_recuperacion_parcial.json']
    if any((destination/n).exists() for n in names):
        raise FileExistsError('La recuperación ya existe; conservarla y elegir otros nombres antes de repetir')
    # Office owner files are transient locks, not result/checkpoint artifacts.
    office_locks=[p.relative_to(run).as_posix() for p in run.rglob('~$*') if p.is_file()]
    original={p.relative_to(run).as_posix():digest(p) for p in run.rglob('*')
              if p.is_file() and not p.name.startswith('~$')}
    execution=live.read(file_path(run,'execution.json'))
    contract=live.read(root/execution['evaluation_contract']['path']) if isinstance(execution.get('evaluation_contract'),dict) and 'path' in execution['evaluation_contract'] else live.read(root/'data/contratos/tesis_comparacion_30.v1.json')
    expected=contract['project_ids']
    if len(expected)!=30 or len(set(expected))!=30:
        raise ValueError('Se requieren los 30 IDs únicos del contrato')
    states={}; rows=[]; coverage=[]; errors=[]; error_rules=Counter(); attempts=Counter(); lineage=[]
    for batch in verified:
        directory=Path(batch['directory']); plan=live.check(directory)
        projects={p['project_id']:p for p in plan['projects']}
        for state in batch['state']['projects']:
            p=projects[state['project_id']]; pid=p['siap_id']
            if pid not in expected or pid in states:
                raise ValueError('Identidad de proyecto ajena o duplicada')
            states[pid]=state
            valid={r['indicator_id']:r for r in state['rows']}
            for iid in state['selected']:
                raw=('VALID' if iid in valid else state['blocked_indicators'].get(iid)
                     or state.get('context_limits',{}).get(iid) or 'PENDING')
                effective=raw
                if raw=='NO_EVIDENCE_FITS':
                    request=plan['context_requests'][p['project_id']][iid]
                    if request['context_selection']['selected'] and all(
                            c['field'] not in coordinator.substantive_fields(p['fields'])
                            for c in request['context_selection']['selected']) and not request['context_selection']['omitted']:
                        effective='NO_SUBSTANTIVE_CONTEXT'
                status=('VALID' if raw=='VALID' else 'PENDING' if raw in ('PENDING','NO_RETRIEVED_EVIDENCE') else 'BLOCKED')
                coverage.append(dict(project_id=pid,indicator_id=iid,status=status,original_status=raw,effective_reason=effective,
                    decision=valid[iid]['decision'] if iid in valid else None))
            for call_dir in (directory/'calls'/p['project_id']).glob('*'):
                if not (call_dir/'verification.json').exists(): continue
                cp=live.read(call_dir/'plan.json'); receipt=live.read(call_dir/'verification.json')
                for iid in cp['indicator_ids']: attempts[pid]+=1
                if receipt['status']!='PASS':
                    item=dict(project_id=pid,indicator_ids=cp['indicator_ids'],status=receipt['status'],
                        error=receipt.get('error'),record=call_dir.relative_to(run).as_posix())
                    errors.append(item)
                    record=live.read(call_dir/'records'/cp['phase']/(p['project_id']+'.json'))
                    for rule in {i['rule'] for c in record['calls'] for i in c.get('validation_issues',[])}:
                        error_rules[rule]+=1
            for iid,row in valid.items():
                assessment=live.assessment_from_row(row)
                if row['assessment_validation_status']!='VALID' or live.v3.validate(p['fields'],plan['profiles'][iid],assessment,plan['rubrics'][iid]):
                    raise ValueError('Evaluación sin validación normativa: '+pid+'/'+iid)
                paths=[d for d in (directory/'calls'/p['project_id']).glob('*') if (d/'assessment.rows.json').exists()
                    and any(r['indicator_id']==iid and r==row for r in live.read(d/'assessment.rows.json')['rows'])]
                if len(paths)!=1: raise ValueError('Registro de evaluación no único')
                call_dir=paths[0];request=plan['context_requests'][p['project_id']][iid]
                selected=request['context_selection']['selected']
                locations=live.evidence_locations(p,assessment)
                if any(not e['match_valid'] or not e['section_id'] for e in locations):
                    raise ValueError('Referencia de evidencia no verificable')
                text='\n\n'.join(row['evidence_texts']) if locations else row['evidence_explanation']
                origin_fields=row['evidence_source_fields'] if locations else list(dict.fromkeys(s['field'] for s in selected))
                refs=[]
                for field in origin_fields:
                    provenance=p['field_provenance'][field]
                    for source in provenance['raw_sources']:
                        if field in source.get('field_mapping',{}):
                            refs.append(dict(field=field,file=source['record_source'],source_row=source['source_row'],
                                column=source['field_mapping'][field],section_id=provenance['section_id']))
                exact=dict(kind='VERIFIED_QUOTES' if locations else 'REVIEWED_CONTEXT_NOT_A_QUOTE',
                    evidence=locations,selected_context=selected,raw_sources=refs)
                references=json.dumps(exact,ensure_ascii=False,separators=(',',':'))
                values=[pid,p['project_id'],iid,row['indicator_name'],row['decision'],text,
                    '\n'.join(origin_fields),row.get('confidence_raw_score'),'VALID',
                    'CITA_LITERAL_VERIFICADA' if locations else 'JUSTIFICACIÓN_DEL_MODELO',
                    row.get('confidence_status'),references,call_dir.relative_to(run).as_posix()]
                if any(isinstance(x,str) and len(x)>32767 for x in values):
                    raise ValueError('Texto excede capacidad de celda; no se trunca')
                rows.append(values)
                lineage.append(dict(project_id=pid,indicator_id=iid,record=values[-1],references=exact))
    if set(states)!=set(expected): raise ValueError('Cobertura de los 30 proyectos incompleta en los planes')
    rows.sort(key=lambda r:(r[0],r[2])); summary=[]
    for pid in expected:
        items=[c for c in coverage if c['project_id']==pid]; count=Counter(c['status'] for c in items)
        decisions=Counter(c['decision'] for c in items if c['status']=='VALID')
        reasons=Counter(c['effective_reason'] for c in items)
        if len(items)!=48 or sum(count.values())!=48: raise ValueError('Cobertura distinta de 48')
        summary.append([pid,count['VALID'],decisions['SUPPORTED'],decisions['NOT_SUPPORTED'],
            decisions['INSUFFICIENT_EVIDENCE'],count['BLOCKED'],count['PENDING'],len(items),
            'SI' if states[pid]['complete'] else 'NO',reasons['NO_RETRIEVED_EVIDENCE'],
            reasons['NO_EVIDENCE_FITS']+reasons['NO_SUBSTANTIVE_CONTEXT'],len(states[pid]['blocked_indicators']),
            'PARTIAL' if count['VALID'] else 'BLOCKED' if attempts[pid] else 'PENDING'])
    totals=dict(valid=len(rows),positive=sum(s[2] for s in summary),negative=sum(s[3] for s in summary),
        insufficient=sum(s[4] for s in summary),blocked=sum(s[5] for s in summary),pending=sum(s[6] for s in summary),
        projects_with_valid=sum(s[1]>0 for s in summary),projects_with_attempts=len(attempts),
        complete_projects=sum(s[8]=='SI' for s in summary),technical_errors=len(errors),
        no_retrieved=sum(s[9] for s in summary),
        no_evidence_fits=sum(c['effective_reason']=='NO_EVIDENCE_FITS' for c in coverage),
        no_substantive_context=sum(c['effective_reason']=='NO_SUBSTANTIVE_CONTEXT' for c in coverage),
        verified_quotes=sum(len(x['references']['evidence']) for x in lineage))
    if len({(r[0],r[2]) for r in rows})!=len(rows): raise ValueError('Evaluaciones duplicadas')
    destination.mkdir(parents=True,exist_ok=True)
    payload=dict(headers=HEADERS,rows=rows,summary_headers=SUMMARY_HEADERS,summary=summary,totals=totals,run_id=run.name)
    with tempfile.TemporaryDirectory(prefix='tesis-partial-') as temp:
        source=Path(temp)/'verified-data.json';source.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
        subprocess.run(['node',str(root/'scripts/export_verified_partial_workbook.mjs'),str(source),str(destination/names[0])],check=True,cwd=root)
    with (destination/names[1]).open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream,delimiter=';');writer.writerow(HEADERS);writer.writerows(rows)
    report=f'''# Resultados parciales recuperados para reunión de tesis

Run: `{run.name}`. Estado conservado: **PARTIAL**.

Se verificaron los 15 planes de lote, sus manifiestos, huellas de entradas/código,
autorizaciones, registros nativos, respuestas, referencias y validadores V3.
Se recuperaron **{totals['valid']} evaluaciones técnicamente válidas de {totals['projects_with_valid']}/30 proyectos**.
Hubo llamadas de evaluación para {totals['projects_with_attempts']} proyectos. Ninguno completó sus 48 indicadores.

**SUPPORTED: {totals['positive']}. NOT_SUPPORTED: {totals['negative']}. INSUFFICIENT_EVIDENCE: {totals['insufficient']}.**
No se recuperó ningún indicador positivo ni cita literal de impacto. NOT_SUPPORTED expresa
que el modelo no encontró respaldo en los fragmentos recibidos; no demuestra inexistencia
de impacto en la realidad. Los párrafos recuperados son justificaciones del modelo,
copiadas de los registros, y se identifican como tales. La confianza se conserva como
valor calculado original, no como probabilidad ni certeza de ausencia de impacto.

## Por qué se mostraba 0/30 y el CSV estaba vacío

El contador de proyectos exige 48 evaluaciones válidas por proyecto. Las 190 evaluaciones
están repartidas en 19 proyectos, todos incompletos. El exportador original aplica un
filtro adicional: exige criterios con apoyo positivo y citas verificables. Las 190
evaluaciones negativas válidas tienen evidence vacío y se excluyeron de esa proyección,
aunque siguen intactas en evaluaciones_validas.json y los registros de llamada.
La exportación recuperada incluye todas las decisiones válidas y conserva ese archivo original.

## Bloqueos y pendientes

- {totals['technical_errors']} evaluaciones bloqueadas por errores de validación.
- {totals['no_evidence_fits']} pares bloqueados porque la evidencia no cabe en el presupuesto.
- {totals['no_substantive_context']} pares sin contexto sustantivo, aunque título/palabras clave sí caben.
- {totals['no_retrieved']} pares pendientes sin fragmentos recuperados. No son evaluaciones negativas.
- Total sin evaluación válida: {totals['blocked']+totals['pending']} de 1440 pares proyecto–indicador.

Los errores técnicos observados por evaluación fallida fueron:
'''
    for rule,count in error_rules.most_common(): report+=f'\n- `{rule}`: {count} evaluaciones fallidas.'
    report+='\n\nEvaluaciones bloqueadas técnicamente:\n\n| Proyecto | Indicador | Estado |\n| --- | --- | --- |\n'
    for item in errors:
        report+=f"| {item['project_id']} | {', '.join(item['indicator_ids'])} | {item['status']} |\n"
    report+='\n## Cobertura por proyecto\n\n| Proyecto | Válidos | Positivos | Negativos | Bloqueados | Pendientes |\n| --- | ---: | ---: | ---: | ---: | ---: |\n'
    for s in summary: report+=f'| {s[0]} | {s[1]} | {s[2]} | {s[3]} | {s[5]} | {s[6]} |\n'
    report+='''
## Limitaciones y trabajo restante

La revisión humana de las rúbricas permanece pendiente. No se generalizan los negativos
a los 48 indicadores ni a todos los proyectos. Para completar el contrato faltan las
evaluaciones bloqueadas y pendientes, revisar los errores de fuerza positiva sin citas,
la cobertura de recuperación y el presupuesto de contexto. Esta recuperación no ejecutó
modelos, embeddings ni APIs y no cambió estados, proyectos ni fingerprints.

El detalle de cada uno de los 1440 pares, sus estados originales, errores y las huellas
de los archivos originales consta en diagnostico_recuperacion_parcial.json.
Resultados contiene exclusivamente evaluaciones VALID. Resumen conserva los 30 proyectos.
'''
    with (destination/names[2]).open('x',encoding='utf-8') as stream: stream.write(report)
    unchanged=all((run/name).is_file() and digest(run/name)==value for name,value in original.items())
    if not unchanged: raise ValueError('Un artefacto original cambió durante la recuperación; revisar antes de entregar')
    audit=dict(run_id=run.name,status='PARTIAL',generated_at=datetime.now(timezone.utc).isoformat(),
        totals=totals,coverage=coverage,errors=errors,error_rules=dict(error_rules),lineage=lineage,
        original_files_sha256=original,original_files_unchanged=True,excluded_transient_office_locks=office_locks,
        output_files_sha256={name:digest(destination/name) for name in names[:3]})
    with (destination/names[3]).open('x',encoding='utf-8') as stream: json.dump(audit,stream,ensure_ascii=False,indent=2)
    return dict(totals=totals,files=[str(destination/name) for name in names])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True,type=Path)
    args=parser.parse_args();run=args.run.resolve()
    if not run.is_relative_to((ROOT/'outputs/runs').resolve()): raise ValueError('Run fuera de outputs/runs')
    print(json.dumps(write_exports(ROOT,run,collect(ROOT,run)),ensure_ascii=False,indent=2))


if __name__=='__main__': main()
