"""Export the frozen five-project pilot and accepted 4B data. Never infer."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from run_paths import file_path as run_file

import pyarrow.parquet as pq

from layer4_evaluation.indicators import experiment as experiment
from layer4_evaluation.indicators.experiment_export import preserve_strings, sheet
from layer4_evaluation.indicators.preliminary_output import verify_workbook
from layer4_evaluation.indicators.experiment_inputs import read, safe_path, sha256, selected_territories
from layer4_evaluation.indicators.powerbi import COLUMNS, TERRITORY_COLUMNS, FIELD_NAMES, consumption_rows
from layer4_evaluation.indicators.review import evidence_locations, component_summary
from layer4_evaluation.indicators.selection import canonical_hash

VERSION = 'LAYER4_PILOT_INTEGRATED_DELIVERY_V1'
EXPECTED_IDS = ('PROJ_20022', 'PROJ_22027', 'PROJ_21410', 'PROJ_22037', 'PROJ_21457')
FILENAMES = ('resultado_capa4.xlsx', 'resumen_resultados.md', 'README.md')
DEFAULT_DELIVERY = 'outputs/layer4/auditoria/historicos/entrega_piloto_5'
DEFAULT_CONFIG = 'config/layer4_pilot.local.yaml'


def pilot_projects(selected, config, manifest):
    pilot = selected[:config['pilot_project_count']]
    if (config['project_count'] != 50 or manifest['assessments_requested'] != 77
            or tuple(p['project_id'] for p in pilot) != EXPECTED_IDS
            or sum(len(p['candidates']) for p in pilot) != 8):
        raise ValueError('Expected the original 50/77 experiment and exact 5/8 pilot')
    return pilot


def indicator_projection(projects, profiles, records):
    """Display explanation and unchanged quotes, with actual field/offset references.

    This delivery projection implements the user's requested presentation while
    retaining the frozen assessment and confidence contracts and all raw data.
    """
    rows = []
    audit = []
    for project in projects:
        record = records.get(project['project_id'], {})
        wrapper = record.get('wrapper') or {'assessments': []}
        assessment_map = {a['indicator_id']: a for a in wrapper['assessments']}
        for row in record.get('rows', []):
            if row['assessment_validation_status'] != 'VALID':
                continue
            if row['indicator_id'] not in assessment_map:
                raise ValueError('Validated row has no original model assessment')
            # Reuse the existing strict confidence/consumer projection first.
            base = consumption_rows([row], {project['project_id']: project['siap_id']})[0]
            assessment = assessment_map[row['indicator_id']]
            locations = evidence_locations(project, assessment)
            if any(not location['match_valid'] or not location['section_id'] for location in locations):
                raise ValueError('Evidence cannot be located in its published field')
            explanation = row['evidence_explanation'].strip()
            quotes = '\n\n'.join(f'[{i}] «{item["text"]}»' for i, item in enumerate(locations, 1))
            base['parrafo_evidencia'] = explanation + ('\n\nEvidencia literal:\n' + quotes if quotes else '')
            base['fuente_evidencia'] = '\n'.join(
                f'[{i}] {item["field"]} ({FIELD_NAMES[item["field"]]})' for i, item in enumerate(locations, 1)) or None
            base['ubicacion_evidencia'] = '\n'.join(
                f'[{i}] {FIELD_NAMES[item["field"]]}; caracteres [{item["start"]},{item["end"]}) '
                f'({"texto original" if item["coordinate_system"].startswith("original_") else "texto normalizado NFC y espacios"}; base 0, fin excluido)'
                for i, item in enumerate(locations, 1)) or None
            if list(base) != COLUMNS:
                raise ValueError('Consumer column order changed')
            rows.append(base)
            audit.append({'project_id': project['project_id'], 'siap_id': project['siap_id'],
                          'indicator_id': row['indicator_id'], 'decision': row['decision'],
                          'llm_explanation': explanation, 'locations': locations,
                          'validation': row['assessment_validation_status'], 'strength': row['support_strength'],
                          'confidence_version': row['confidence_version'],
                          **{key: row[key] for key in ('key_element_coverage', 'field_relevance_score', 'corroboration_score',
                                                     'support_strength_score', 'confidence_raw_score', 'confidence_probability')},
                          'original_record_sha256': canonical_hash(record)})
    if len({(r['siap_id'], r['indicador_id']) for r in rows}) != len(rows):
        raise ValueError('Duplicate published assessment')
    return rows, audit


def statistics(projects, records, territories, calls):
    rows = [r for p in projects for r in records.get(p['project_id'], {}).get('rows', [])]
    valid = [r for r in rows if r['assessment_validation_status'] == 'VALID']
    scores = [r['confidence_raw_score'] for r in valid if r['confidence_status'] == 'COMPUTED']
    covered = {r['siap_id'] for r in territories}
    attempted_projects = {call['project_id'] for call in calls}
    return {
        'projects_selected': len(projects), 'projects_with_structured_response': sum(bool(records.get(p['project_id'], {}).get('rows')) for p in projects),
        'assessments_expected': sum(len(p['candidates']) for p in projects),
        'assessments_attempted': sum(len(p['candidates']) for p in projects if p['project_id'] in attempted_projects),
        'assessments_returned': len(rows), 'assessments_valid': len(valid), 'assessments_invalid': len(rows)-len(valid),
        'assessments_without_structured_response': sum(len(p['candidates']) for p in projects)-len(rows),
        'decisions': {key: sum(r['decision']==key for r in valid) for key in ('SUPPORTED','INSUFFICIENT_EVIDENCE','NOT_SUPPORTED')},
        'confidence_computable': len(scores), 'confidence_min': min(scores) if scores else None,
        'confidence_mean': sum(scores)/len(scores) if scores else None, 'confidence_max': max(scores) if scores else None,
        'components': component_summary(valid), 'projects_with_resolved_territory': len(covered),
        'projects_without_resolved_territory': len(projects)-len(covered), 'territory_relationships': len(territories),
        'relationships_by_type': {key:sum(r['territory_type']==key for r in territories) for key in ('MUNICIPALITY','DEPARTMENT','COUNTRY')},
        'cli_calls_with_completed_audit': len(calls), 'technical_retries': sum(call['retry']>0 for call in calls),
        'errors': [{'project_id':p['project_id'],'error':records[p['project_id']].get('error'),'status':records[p['project_id']]['status']}
                   for p in projects if p['project_id'] in records and records[p['project_id']]['status']!='VALID'],
        'human_review': 'PENDING', 'calibration': 'NOT_CALIBRATED', 'confidence_is_probability': False,
    }


def territorial_audit(root, data, projects, territories):
    folder = root/'outputs/layer4/territorios/publicacion'
    ids = {p['project_id'] for p in projects}
    evidence = [r for r in pq.read_table(folder/'project_territory_evidence.parquet').to_pylist() if r['project_id'] in ids]
    ambiguous = [r for r in pq.read_table(folder/'project_territory_ambiguous.parquet').to_pylist() if r['project_id'] in ids]
    siap = {p['project_id']:p['siap_id'] for p in projects}
    resolved_keys = {(siap[r['project_id']],r['territory_type'],r['dane_code']) for r in evidence if r['resolution_status']=='RESOLVED'}
    if any((r['siap_id'],r['territory_type'],r['territory_code']) not in resolved_keys for r in territories):
        raise ValueError('Territory relationship has no accepted RESOLVED evidence')
    for row in ambiguous:
        if row['resolution_status']!='AMBIGUOUS' or row['dane_code'] is not None:
            raise ValueError('Unexpected ambiguous territorial publication')
    return evidence, ambiguous


def summary_markdown(projects, stats, indicators, territories, territorial_evidence, ambiguous, execution_status, model_observed=False):
    def score(value):return 'No calculada' if value is None else f'{value:.2f}'
    decisions = stats['decisions']
    types = stats['relationships_by_type']
    text = f'''# Resultados del piloto de Capa 4

**Estado: {execution_status}.** Muestra fija de cinco proyectos reales. Los resultados de indicadores son preliminares; la revisión humana independiente sigue pendiente. La publicación territorial de origen ya está aceptada.

| Evaluación de indicadores | Cantidad |
|---|---:|
| Proyectos seleccionados / con respuesta estructurada | {stats['projects_selected']} / {stats['projects_with_structured_response']} |
| Assessments previstos / intentados mediante CLI | {stats['assessments_expected']} / {stats['assessments_attempted']} |
| Ejecutados con respuesta estructurada / válidos / inválidos | {stats['assessments_returned']} / {stats['assessments_valid']} / {stats['assessments_invalid']} |
| Sin respuesta estructurada, incluidos pendientes y errores | {stats['assessments_without_structured_response']} |
| SUPPORTED / INSUFFICIENT_EVIDENCE / NOT_SUPPORTED | {decisions['SUPPORTED']} / {decisions['INSUFFICIENT_EVIDENCE']} / {decisions['NOT_SUPPORTED']} |
| Con confianza computable | {stats['confidence_computable']} |
| Confianza mínima / media / máxima | {score(stats['confidence_min'])} / {score(stats['confidence_mean'])} / {score(stats['confidence_max'])} |

Los reintentos no suman evaluaciones distintas. Solo se publican decisiones válidas. Un cero en los conteos de decisiones no significa que los casos pendientes sean NOT_SUPPORTED.

## Confianza

RAW_CONFIDENCE_V1 = 100 × (0.35K + 0.30F + 0.20C + 0.15S). K mide cobertura de elementos clave; F, relevancia del campo citado; C, corroboración entre campos sustantivos distintos; S es strength/4. Python comprueba las citas originales y calcula el score; Codex CLI no lo decide. Retrieval_score de Capa 3 sirve para recuperar candidatos y no mide evidencia de cumplimiento, por eso no se usa como confianza.

Solo SUPPORTED válido y computable recibe confianza. En las otras decisiones, errores o ausencia de elementos clave queda vacía según contrato. El puntaje no es probabilidad, exactitud ni resultado calibrado. No hay ground truth humano para reportar esas métricas.

Incluso un score de 100 no significa 100 % de acierto. Puntajes individuales: {('; '.join(f"SIAP {r['siap_id']} / {r['indicador_id']}: {score(r['confianza'])}" for r in indicators if r['confianza'] is not None)) or 'sin puntuaciones computables'}.

## Territorios de la muestra

{stats['projects_with_resolved_territory']} proyectos tienen territorio resuelto y {stats['projects_without_resolved_territory']} no lo tienen. Hay **{stats['territory_relationships']} relaciones**: {types['MUNICIPALITY']} MUNICIPALITY, {types['DEPARTMENT']} DEPARTMENT y {types['COUNTRY']} COUNTRY. Relaciones y proyectos son conteos diferentes. Se reutilizó 4B sin volver a procesarla.

| SIAP | PROJECT | Territorios publicados |
|---|---|---|
'''
    for project in projects:
        associated = [r for r in territories if r['siap_id']==project['siap_id']]
        description = '; '.join(f"{r['territory_name']} ({r['territory_type']}, {r['territory_code']})" for r in associated) or 'Sin territorio RESOLVED'
        text += f"| {project['siap_id']} | {project['project_id']} | {description} |\n"
    text += f"\nSe conservaron {len(territorial_evidence)} menciones territoriales de auditoría; varias pueden respaldar la misma relación. Hay {len(ambiguous)} menciones AMBIGUOUS en estos cinco proyectos. Las ambiguas no se publican como relaciones confirmadas ni se asigna un territorio por defecto.\n\n## Ejemplos reales\n\n"
    examples = []
    for decision in ('SUPPORTED','INSUFFICIENT_EVIDENCE','NOT_SUPPORTED'):
        candidate = next((r for r in indicators if r['estado_cumplimiento']==decision and r['siap_id'] not in {x['siap_id'] for x in examples}),None)
        if candidate:examples.append(candidate)
    if examples:
        for row in examples[:3]:
            associated = '; '.join(r['territory_name'] for r in territories if r['siap_id']==row['siap_id']) or 'sin territorio resuelto'
            # Use one literal already verified; never invent representative text.
            paragraph = row['parrafo_evidencia']
            first_quote = paragraph.split('Evidencia literal:\n',1)[1].split('\n\n',1)[0] if 'Evidencia literal:\n' in paragraph else 'Sin fragmento citado; consultar la explicación en el Excel.'
            text += f"- **SIAP {row['siap_id']} / {row['indicador_id']} — {row['estado_cumplimiento']}**. {first_quote} Fuente y ubicación: Excel. Territorio: {associated}. Confianza: {score(row['confianza'])}.\n"
    else:
        for pid in ('PROJ_20022','PROJ_21410','PROJ_22037'):
            project = next(p for p in projects if p['project_id']==pid)
            evidence = next((r for r in territorial_evidence if r['project_id']==pid and r['resolution_status']=='RESOLVED'),None)
            if evidence:
                name = next(r['territory_name'] for r in territories if r['siap_id']==project['siap_id'] and r['territory_code']==evidence['dane_code'])
                text += f"- **SIAP {project['siap_id']} / {pid}**: mención literal «{evidence['matched_text']}» en `{evidence['field_name']}`; territorio publicado: {name}. La evaluación de indicadores permanece pendiente.\n"
    text += '\n## Limitaciones y siguiente paso\n\n'
    if stats['assessments_attempted']==0:
        if 'no verificada' in execution_status:
            text += 'No se ha ejecutado inferencia real: falta verificar la constancia de autorización institucional para el proveedor configurado. La aprobación del flujo de trabajo no reemplaza ese permiso. '
        else:
            text += 'Todavía no hay respuestas de inferencia recuperadas en esta exportación. '
        text += 'La hoja de indicadores está vacía; el Excel conserva las relaciones territoriales aceptadas.\n\n'
    elif stats['errors'] or stats['assessments_invalid'] or stats['assessments_without_structured_response']:
        text += 'El piloto tiene errores, respuestas inválidas o faltantes. Se conservan las respuestas válidas y el diagnóstico privado; no se inventan decisiones para completar ocho. Revisar esos casos antes de continuar.\n\n'
    text += 'El piloto es pequeño e intencional y evalúa candidatos publicados, no el desempeño end-to-end del universo institucional. La validez semántica requiere revisión humana. Ocho verificaciones históricas de código siguen bloqueadas por los dos ZIP originales faltantes. No se ejecutan las 69 evaluaciones restantes; primero se revisa y aprueba este piloto.\n'
    if not model_observed:
        text += 'La CLI no informó un identificador verificable del modelo efectivo; no se atribuye un modelo por suposición.\n'
    if len(text.split())>1000:
        raise ValueError('Summary exceeds the two-page-equivalent word budget; inspect long model quotations')
    return text


def readme_markdown(status, config_path):
    return f'''# Capa 4 — entrega del piloto

Estado: **{status}**. Esta carpeta contiene únicamente el Excel de consumo, el resumen de resultados y esta guía.

La Capa 4 integra dos funcionalidades. **4A** toma campos originales de Capa 2 y candidatos recuperados por Capa 3; Codex CLI ejecuta la evaluación semántica mediante su modelo LLM configurado. Python valida estructura y citas y calcula RAW_CONFIDENCE_V1. **4B** toma Capa 2 y la referencia DANE de Capa 1 para resolver territorios. Su publicación ya está aceptada y aquí solo se consulta. Ambas ramas se unen en el Excel para Power BI.

`resultado_capa4.xlsx` tiene exactamente dos hojas. RESULTADO_INDICADORES contiene una fila por proyecto e indicador válido, su explicación, citas literales, campos de origen, ubicaciones y confianza cuando corresponde. No incluye decisiones pendientes o inválidas. TERRITORIOS contiene solo relaciones RESOLVED de los cinco proyectos; puede tener varias por proyecto o ninguna. Los códigos son texto: DANE para municipios/departamentos e INTERNAL para COUNTRY/000. Las hojas se relacionan por siap_id; tienen cobertura independiente y no deben combinarse como si cada proyecto tuviera una sola fila.

La confianza es un puntaje de evidencia, no una probabilidad ni exactitud. Se calcula en Python con 0.35K + 0.30F + 0.20C + 0.15S, multiplicado por 100: elementos clave, campo citado, corroboración y strength. Solo SUPPORTED válido y computable recibe valor; las celdas vacías no equivalen a cero. El resumen amplía esta interpretación.

La procedencia territorial está aceptada; las decisiones LLM del piloto son preliminares y requieren revisión humana independiente. Ni el piloto ni esta exportación conceden aceptación final de 4A. Los manifests, prompts, respuestas y auditorías completas permanecen en el directorio técnico privado. La entrega no incluye tablas personales, credenciales ni esos textos completos.

Para reproducir desde el repositorio, verificar primero las publicaciones y disponer de la autorización institucional aplicable. Ejecutar únicamente el piloto preparado con `uv run python scripts/run_layer4_experiment.py --config {config_path} execute-batch --stage pilot --authorization <constancia.json>`. Las respuestas compatibles guardadas se reutilizan. Regenerar estos tres archivos, sin nueva inferencia, con `uv run python scripts/export_layer4_pilot.py --config {config_path}`. No volver a ejecutar 4B. Las otras 69 evaluaciones exigen revisión y aprobación separada del piloto.
'''


def export_delivery_spec(root, spec, output):
    for tab in spec['sheets']:
        for values in [tab['columns'],*tab['rows']]:
            if len(values)!=7 or any(isinstance(v,str) and len(v)>32767 for v in values):
                raise ValueError('Excel cell/column bounds exceeded; never truncate evidence')
    if output.exists():
        return verify_workbook(output,spec)
    path=output.with_suffix('.spec.json')
    experiment.write_json(path,spec)
    node=shutil.which('node')
    if not node:raise RuntimeError('Artifact runtime requires Node')
    renderer=Path(root)/'scripts/render_layer4_pilot.mjs'
    args=[node,str(renderer),str(path),str(output)]
    done=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180,shell=False)
    if done.returncode:raise RuntimeError('Pilot workbook export failed: '+done.stderr[-1000:])
    preserve_strings(output,spec)
    done=subprocess.run([*args,'--render-saved'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180,shell=False)
    if done.returncode:raise RuntimeError('Pilot saved-workbook QA failed: '+done.stderr[-1000:])
    return verify_workbook(output,spec)


def build(root=ROOT, delivery_name=DEFAULT_DELIVERY, config_path=DEFAULT_CONFIG):
    root=Path(root).resolve()
    verified=experiment.verify_prepared(root,config_path)
    config,out,manifest,data,selected,requests,runtime=verified
    projects=pilot_projects(selected,config,manifest)
    request_map={r['project_id']:r for r in requests}
    records={}
    for project in projects:
        path=out/'records'/(project['project_id']+'.json')
        if path.exists():
            records[project['project_id']]=experiment.validate_record(read(path),project,data['profiles'],manifest,request_map[project['project_id']],out)
    indicators,indicator_audit=indicator_projection(projects,data['profiles'],records)
    territories=selected_territories(data,projects)
    evidence,ambiguous=territorial_audit(root,data,projects,territories)
    ids={p['project_id'] for p in projects}
    calls=[read(p) for p in sorted((out/'codex_runs').glob('*/attempt_*/call.json')) if p.parent.parent.name in ids]
    stats=statistics(projects,records,territories,calls)
    auth_path=root/'outputs/layer4/auditoria/historicos/experimento_50/authorization.pilot.user_attestation.json'
    auth=experiment.validate_authorization(auth_path,manifest,'pilot') if auth_path.exists() else None
    if stats['assessments_valid']==8:
        status='Piloto con ocho respuestas válidas; revisión humana pendiente'
    elif (run_file(out, '.execution.lock')).exists():
        status='Piloto en ejecución; resultados parciales'
    elif not calls and auth:
        status='Piloto pendiente de ejecución; autorización registrada por declaración del usuario'
    elif not calls:
        status='Piloto pendiente: autorización institucional no verificada'
    else:
        status='Piloto parcial; revisar errores o respuestas faltantes'
    public_spec={'sheets':[sheet('RESULTADO_INDICADORES',COLUMNS,indicators),sheet('TERRITORIOS',TERRITORY_COLUMNS,territories)]}
    summary=summary_markdown(projects,stats,indicators,territories,evidence,ambiguous,status,model_observed=any(c.get('model_observations') for c in calls))
    guide=readme_markdown(status,config_path)
    # Explicit requested fields only. Never silently modify a literal quotation.
    if any(re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', value) for value in [summary,guide,*[v for tab in public_spec['sheets'] for row in tab['rows'] for v in row if isinstance(v,str)]]):
        raise ValueError('Personal email in proposed delivery; inspect before export')
    code_hash=sha256(Path(__file__))
    renderer_hash=sha256(root/'scripts/render_layer4_pilot.mjs')
    snapshot=canonical_hash({'version':VERSION,'selection':manifest['selection_sha256'],'records':records,'spec':public_spec,'script_sha256':code_hash,'renderer_sha256':renderer_hash})
    technical=out/'pilot_delivery'/snapshot[:16]
    technical.mkdir(parents=True,exist_ok=True)
    target=safe_path(root,delivery_name)
    if target.parent!=(root/'outputs/layer4').resolve() or not target.name.startswith('entrega_piloto'):
        raise ValueError('Use a dedicated outputs/layer4/entrega_piloto* directory')
    previous_path=out/'pilot_delivery/latest_manifest.json'
    previous=read(previous_path) if previous_path.exists() else {}
    if target.exists():
        if set(p.name for p in target.iterdir())-set(FILENAMES):
            raise ValueError('Delivery folder contains unrelated files; preserve them')
        for path in target.iterdir():
            if previous.get('delivery_hashes',{}).get(path.name)!=sha256(path):
                raise ValueError('Preserve an existing or manually edited delivery')
    qa=export_delivery_spec(root,public_spec,technical/'resultado_capa4.xlsx')
    target.mkdir(parents=True,exist_ok=True)
    payloads={'resultado_capa4.xlsx':(technical/'resultado_capa4.xlsx').read_bytes(),
              'resumen_resultados.md':summary.encode('utf-8'),'README.md':guide.encode('utf-8')}
    for name,payload in payloads.items():
        temporary=target/(name+'.pending');temporary.write_bytes(payload);temporary.replace(target/name)
    experiment.write_jsonl(technical/'indicator_audit.jsonl',indicator_audit)
    experiment.write_jsonl(technical/'territory_evidence.jsonl',evidence)
    experiment.write_jsonl(technical/'territory_ambiguous.jsonl',ambiguous)
    result={'version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),'status':status,'snapshot':snapshot,
        'selection_sha256':manifest['selection_sha256'],'pilot_ids':[p['project_id'] for p in projects],
        'pilot_candidates':{p['project_id']:[c['indicator_id'] for c in p['candidates']] for p in projects},
        'statistics':stats,'cli_version':runtime['cli_version'],'requested_model':config['model'],
        'model_observations':[m for c in calls for m in c.get('model_observations',[])],
        'usage_observations':[u for c in calls for u in c.get('usage_observations',[])],
        'territory_manifest_sha256':sha256(root/config['territory_manifest']),
        'experiment_manifest_sha256':sha256(out/'experiment_manifest.json'),
        'code_hashes':{'scripts/export_layer4_pilot.py':code_hash,'scripts/render_layer4_pilot.mjs':renderer_hash,**manifest['code_hashes']},
        'authorization':auth,'authorization_kind':'USER_ATTESTATION_NO_FORMAL_DOCUMENT_SUPPLIED' if auth else None,
        'workbook_qa':qa,'territory_ambiguous_mentions':len(ambiguous),'territorial_processing_executed':False,
        'inference_executed_by_exporter':False,'academic_acceptance':False,
        'delivery_directory':target.relative_to(root).as_posix(),'delivery_hashes':{name:sha256(target/name) for name in FILENAMES},
        'technical_hashes':{p.relative_to(out).as_posix():sha256(p) for p in sorted(technical.iterdir()) if p.is_file()},
        'historical_checks_blocked':['archives/layer4/pre_namespace_migration.zip','archives/layer4/pre_layer1_unification.zip']}
    experiment.verify_hashes(root,read(out/'protected_inputs.json'))
    experiment.write_json(technical/'delivery_manifest.json',result)
    experiment.write_json(previous_path,result)
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default=DEFAULT_CONFIG)
    args=parser.parse_args()
    result=build(config_path=args.config)
    print(json.dumps({key:result[key] for key in ('status','pilot_ids','statistics','delivery_directory','workbook_qa')},ensure_ascii=True,indent=2))
