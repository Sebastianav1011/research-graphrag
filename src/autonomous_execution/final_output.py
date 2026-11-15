"""Read-only projection of persisted assessments into the official user template.

Executable fingerprints still gate inference. Offline projection verifies the
authorized manifest, original inputs, response receipts and stored confidence;
it never rewrites a historical manifest or opens its checkpoint for writing.
"""
from pathlib import Path
import json
import sqlite3

import pyarrow.parquet as pq
from . import store as s
from layer2_processing.checkpoints import locate

COLUMNS=['siap_id','investigador_id','indicador_id','estado_cumplimiento',
         'parrafo_evidencia','fuente_evidencia','ubicacion_evidencia','confianza','territorio']
from layer4_evaluation.thesis_output import (TEMPLATE, COLUMNS as THESIS_COLUMNS, SHEETS as THESIS_SHEETS,
    DEFAULT_CONTRACT, POSITIVE_CONTRACT, ALL_CONTRACT, VALID_CONTRACT, GENERAL_COLUMNS)
SHEETS={name:list(THESIS_COLUMNS) for name in THESIS_SHEETS}
TERRITORY_SOURCE_COLUMNS=['id_proyecto','id_articulo','tipo_territorio_id','codigo_dane',
    'fuente_evidencia','ubicacion_evidencia']


def connect_readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)


def template_path(root=None):
    return (Path(root) if root is not None else Path(__file__).resolve().parents[2])/TEMPLATE


def load_template(root=None):
    """Validate the versioned thesis template; never replace its stored bytes."""
    from openpyxl import load_workbook
    path=template_path(root)
    book=load_workbook(path)
    try:
        if book.sheetnames!=list(SHEETS):raise ValueError('Hojas de la plantilla oficial incompatibles')
        for name,columns in SHEETS.items():
            sheet=book[name]
            if [c.value for c in sheet[1]]!=columns:raise ValueError('Columnas de la plantilla oficial incompatibles: '+name)
            if any(c.value is not None for row in sheet.iter_rows(min_row=2) for c in row):
                raise ValueError('La plantilla oficial debe estar vacia: '+name)
    except BaseException:
        book.close();raise
    return book


def style(sheet):
    from openpyxl.styles import Alignment
    from openpyxl.utils import get_column_letter
    sheet.auto_filter.ref=f'A1:{get_column_letter(sheet.max_column)}{max(1,sheet.max_row)}'
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment=Alignment(wrap_text=True,vertical='top')
            if isinstance(cell.value,str):cell.data_type='s'
        if sheet.title=='INDICADORES':
            row[5].number_format='0.00'
            sheet.row_dimensions[row[0].row].height=max(60,min(180,20+len(str(row[6].value or ''))*.18))


def render(root,records,target,territories=(),*,contract=DEFAULT_CONTRACT):
    """Keep unassessed ARTICLEs empty; project geography comes from its citations."""
    from layer4_evaluation.thesis_output import render as render_thesis
    render_thesis(root,target,records,contract=contract)


def prepare_projection(root,run,projects):
    """Bind deterministic territories and the official template before approval.

    Use only the selected, hashed project inputs, never a global territorial
    publication from another documentary snapshot. Original texts/offsets and
    the existing recognizer are unchanged.
    """
    from copy import deepcopy
    from layer2_processing.preprocessing.dane_reference import load_reference
    from layer4_evaluation.territories.matching import extract_territories,FIELDS
    from layer4_evaluation.territories.pipeline import validate_result
    root=Path(root).resolve();run=Path(run).resolve();directory=run/'autonomous/main'
    book=load_template(root);book.close()
    reference_dir=locate(root/'outputs/layer2/reference')
    dimension,reference=load_reference(reference_dir)
    source=locate(root/reference['source_file'])
    if s.sha(source)!=reference['source_sha256']:raise ValueError('Fuente DANE modificada')
    documents=[];sections=[];adapted=[];inputs={};field_adapters=[]
    for pid,receipt in sorted(projects.items()):
        path=directory/receipt['path']
        if s.sha(path)!=receipt['sha256']:raise ValueError('Entrada territorial modificada: '+pid)
        data=s.read(path);project=data['project'];inputs[pid]=project
        original=data['sections']
        if any(row['source_id']!=pid or row['source_type']!='PROJECT' for row in original):
            raise ValueError('Seccion territorial fuera del proyecto')
        doc_ids={row['document_id'] for row in original}
        if len(doc_ids)!=1:raise ValueError('Documento territorial no univoco: '+pid)
        documents.append(dict(source_id=pid,source_type='PROJECT',document_id=next(iter(doc_ids))))
        sections.extend(original)
        for row in original:
            copy=deepcopy(row);field=row['field_name']
            if field.startswith('text__'):
                raw=project.get('field_provenance',{}).get(field,{}).get('raw_sources',[])
                authorizations=[r.get('knowledge_fields',{}).get(field,{}) for r in raw]
                categories={a.get('category') for a in authorizations if a.get('authorization')=='AUTHORIZED'}
                if authorizations and all(a.get('authorization')=='AUTHORIZED' for a in authorizations) and len(categories)==1:
                    category=next(iter(categories))
                    if category in FIELDS:
                        copy['field_name']=category
                        field_adapters.append(dict(section_id=row['section_id'],original=field,authorized_category=category))
            adapted.append(copy)
    result=extract_territories(documents,adapted,dimension)
    original_fields={row['section_id']:row['field_name'] for row in sections}
    for key in ('evidence','ambiguous','national_mentions'):
        for row in result.get(key,[]):row['field_name']=original_fields[row['section_id']]
    quality=validate_result(documents,sections,dimension,result)
    rows=[]
    for relation in result['relationships']:
        pid=relation['project_id']
        fields=[row['field_name'] for row in result['evidence'] if all(row[k]==relation[k] for k in ('project_id','territory_type','dane_code'))]
        names,locations=source_labels(inputs[pid],fields)
        rows.append(dict(zip(TERRITORY_SOURCE_COLUMNS,[inputs[pid]['siap_id'],None,relation['territory_type'],relation['dane_code'],names,locations])))
    path=directory/'territories.json'
    s.write(path,dict(rows=rows,result=result,quality=quality,reference=reference,field_adapters=field_adapters,
        project_inputs={pid:value['sha256'] for pid,value in projects.items()}))
    dependencies=[path,template_path(root),source,*[p for p in reference_dir.iterdir() if p.is_file()]]
    files={}
    for path in dependencies:
        resolved=path.resolve()
        if not resolved.is_relative_to(root):raise ValueError('Recurso de exportacion fuera del repositorio')
        files[resolved.relative_to(root).as_posix()]=s.sha(resolved)
    return dict(template=TEMPLATE.as_posix(),territories='territories.json',filename='resultado_final.xlsx'),files


def _rows(path):
    path=locate(path)
    return pq.read_table(path).to_pylist() if path.is_file() else []


def researchers(root,run,project):
    """Only exact institutional joins; never substitute canonical hash IDs."""
    from knowledge_store import knowledge_workspace, run_state
    state=run_state(run)
    bases=[knowledge_workspace(run)/'outputs/layer2/canonical']
    if not (state.get('knowledge_ref') or state.get('knowledge_build')):
        bases.append(root/'outputs/layer2/canonical')
    for base in bases:
        projects=_rows(base/'proyectos.parquet')
        ids={p['project_id'] for p in projects if p.get('source_project_id')==project['siap_id']}
        people={r['researcher_id']:r.get('institutional_id') for r in _rows(base/'investigadores.parquet')}
        found={people.get(r['researcher_id']) for r in _rows(base/'proyecto_investigador.parquet') if r['project_id'] in ids}
        found.discard(None);found.discard('')
        if found:return sorted(found)
    return [None]


def source_labels(project,fields):
    columns=[];locations=[]
    for field in dict.fromkeys(fields):
        provenance=project.get('field_provenance',{}).get(field,{})
        for raw in provenance.get('raw_sources',[]):
            original=raw.get('field_mapping',{}).get(field) or field.removeprefix('text__')
            if isinstance(original,list):original=', '.join(original)
            if original not in columns:columns.append(original)
            parts=[Path(raw.get('record_source','')).name]
            if raw.get('source_sheet'):parts.append('hoja '+str(raw['source_sheet']))
            if raw.get('source_row') is not None:parts.append('fila '+str(raw['source_row']))
            if len(parts)==1:parts.append('sección '+original)
            label='; '.join(parts)
            if label not in locations:locations.append(label)
    return '\n'.join(columns),'\n'.join(locations)


def project_records(root,run,territorial_codes=None,*,positive_only=False,output_contract=None):
    from .engine import check_result_contract
    from layer4_evaluation.live_execution import assessment_from_row
    from layer4_evaluation.live_execution import validate_context_evidence
    from layer4_evaluation.indicator_csv import TerritoryCodes
    resolve_codes=TerritoryCodes(root) if territorial_codes is not None else None
    directory=run/'autonomous/main';manifest=s.read(directory/'manifest.json')
    digest=s.sha(directory/'manifest.json');auth=s.read(directory/'authorization.json')
    if auth.get('authorized') is not True or auth.get('manifest_sha256')!=digest:
        raise ValueError('Manifiesto original no autorizado o alterado')
    for name,expected in manifest['files'].items():
        path=locate(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or s.sha(path)!=expected:
            raise ValueError('Dependencia original alterada: '+name)
    db=connect_readonly(directory/'queue.sqlite')
    db.row_factory=sqlite3.Row
    try:jobs=[dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY pid,iid')]
    finally:db.close()
    expected=sum(map(len,manifest['project_indicators'].values())) if manifest.get('project_indicators') else len(manifest['projects'])*len(manifest['profiles'])
    if len(jobs)!=expected:raise ValueError('Cobertura original incompleta')
    records=[];audit=[];export_exclusions=[]
    for job in jobs:
        pid,iid=job['pid'],job['iid']
        if pid not in manifest['projects'] or iid not in manifest['profiles'] or (
                manifest.get('project_indicators') and iid not in manifest['project_indicators'][pid]):
            raise ValueError('Pareja fuera del manifiesto original')
        source=directory/manifest['projects'][pid]['path']
        if s.sha(source)!=manifest['projects'][pid]['sha256']:raise ValueError('Texto original alterado')
        data=s.read(source);project=data['project'];fields=[];score=None
        if job['status']=='PASS':
            result=(directory/job['result_path']).resolve()
            if not result.is_relative_to(directory.resolve()) or s.sha(result)!=job['result_hash']:
                raise ValueError('Resultado persistido alterado')
            bundle=s.read(result)
            if bundle.get('manifest_sha256')!=digest:raise ValueError('Resultado de otro manifiesto')
            check_result_contract(manifest,bundle)
            row=bundle['row']
            assessment=bundle['wrapper']['assessments'][0]
            if (row.get('project_id')!=pid or row.get('indicator_id')!=iid or
                    row.get('assessment_validation_status')!='VALID' or
                    assessment_from_row(row)!={k:v for k,v in assessment.items() if k!='indicator_id'}):
                raise ValueError('Decisión persistida incompatible con su recibo')
            for name,value in bundle.get('artifact_hashes',{}).items():
                path=(directory/name).resolve()
                if not path.is_relative_to(directory.resolve()) or s.sha(path)!=value:raise ValueError('Auditoría original alterada')
            validate_context_evidence(bundle['request'],bundle['wrapper'])
            if resolve_codes is not None:
                territorial_codes[project['siap_id'],iid]=resolve_codes(project,bundle['wrapper']['assessments'][0])
            decision=row['decision'];score=row['confidence_raw_score'];paragraph=row['evidence_explanation']
            fields=row['evidence_source_fields']
            if not fields:fields=[e['field'] for e in bundle.get('evidence_registry',{}).values()]
        else:
            decision='REVIEW_REQUIRED';paragraph='Evaluación pendiente de revisión.'
            for stage in ('clarification','minimal'):
                attempt=directory/'attempts'/pid/iid/stage/'1'
                path=attempt/'transport'/pid/'attempt_1/response.raw.txt'
                if not path.exists():continue
                try:
                    raw=s.read(path)
                    if isinstance(raw,dict) and isinstance(raw.get('why'),str):
                        paragraph='Provisional, requiere revisión: '+raw['why']
                        fields=[e['field'] for e in s.read(attempt/'step.json')['request'].get('evidence_registry',{}).values()]
                        break
                except (ValueError,KeyError):continue
        names,locations=source_labels(project,fields)
        # Only explicit, accepted territorial data can populate this optional field.
        territory=project.get('territory')
        if output_contract in (ALL_CONTRACT,VALID_CONTRACT):
            if output_contract==VALID_CONTRACT and job['status']!='PASS':
                audit.append(dict(project_id=pid,indicator_id=iid,status=job['status'],decision=None,confidence=None))
                continue
            from layer4_evaluation.thesis_output import indicator_record
            from layer4_evaluation.indicators.review import evidence_locations
            records.append(indicator_record(project,iid,
                row=row if job['status']=='PASS' else None,
                status=job['status'],
                locations=evidence_locations(project,bundle['wrapper']['assessments'][0]) if job['status']=='PASS' else (),
                territory_codes=(territorial_codes or {}).get((project['siap_id'],iid),[])))
            audit.append(dict(project_id=pid,indicator_id=iid,status=job['status'],decision=decision,confidence=score))
            continue
        if positive_only:
            audit.append(dict(project_id=pid,indicator_id=iid,status=job['status'],decision=decision,confidence=score))
            if job['status']=='PASS' and decision=='SUPPORTED':
                from layer4_evaluation.thesis_output import positive_record
                from layer4_evaluation.indicators.review import evidence_locations
                assessment=bundle['wrapper']['assessments'][0]
                try:
                    records.append(positive_record(project,row,evidence_locations(project,assessment),
                        (territorial_codes or {}).get((project['siap_id'],iid),[])))
                except (ValueError,KeyError,TypeError) as exc:
                    export_exclusions.append(dict(project_id=pid,indicator_id=iid,reason=str(exc)))
            continue
        for researcher in researchers(root,run,project):
            records.append(dict(zip(COLUMNS,[project['siap_id'],researcher,iid,decision,paragraph,names,locations,score,territory])))
        audit.append(dict(project_id=pid,indicator_id=iid,status=job['status'],decision=decision,confidence=score))
    from collections import Counter
    decisions=Counter(r['decision'] for r in audit if r['status']=='PASS')
    by_project={pid:[r for r in audit if r['project_id']==pid] for pid in manifest['projects']}
    processed=sum(bool(rows) and all(r['status'] in ('PASS','BLOCKED','UNCERTAIN') for r in rows) for rows in by_project.values())
    summary=dict(selected_projects=len(by_project),processed_projects=processed,
        completed_projects=sum(bool(rows) and all(r['status']=='PASS' for r in rows) for rows in by_project.values()),
        expected_assessments=len(audit),valid_assessments=sum(decisions.values()),
        supported=decisions['SUPPORTED'],insufficient_evidence=decisions['INSUFFICIENT_EVIDENCE'],not_supported=decisions['NOT_SUPPORTED'],
        blocked_assessments=sum(r['status'] in ('BLOCKED','UNCERTAIN') for r in audit),
        pending_assessments=sum(r['status'] not in ('PASS','BLOCKED','UNCERTAIN') for r in audit),
        processing_complete=bool(audit) and processed==len(by_project),results_available=bool(decisions))
    return records,dict(summary,export_exclusions=export_exclusions,manifest_sha256=digest,evaluations=audit,code_changed_since_inference=[
        name for name,h in manifest['code'].items() if not (root/name).is_file() or s.sha(root/name)!=h])


def export(root,run,*,output_contract=DEFAULT_CONTRACT):
    """New root-level projection only. Historical queue/manifests/logs stay intact."""
    root=Path(root).resolve();run=Path(run).resolve()
    if not run.is_relative_to(root/'outputs/runs'):raise ValueError('Run fuera de outputs/runs')
    from layer4_evaluation.indicator_csv import write_results
    codes_by_pair={}
    if output_contract not in (ALL_CONTRACT,POSITIVE_CONTRACT,VALID_CONTRACT):raise ValueError('Contrato desconocido')
    columns=GENERAL_COLUMNS if output_contract==VALID_CONTRACT else THESIS_COLUMNS
    records,audit=project_records(root,run,codes_by_pair,positive_only=output_contract==POSITIVE_CONTRACT,
        output_contract=output_contract)
    manifest=s.read(run/'autonomous/main/manifest.json')
    projection=manifest.get('final_projection')
    territories=[]
    if projection:
        if (projection.get('template') not in (TEMPLATE.as_posix(),'data/templates/plantilla_resultado_final_indicadores_territorios.xlsx')
                or projection.get('territories')!='territories.json' or projection.get('filename')!='resultado_final.xlsx'
                or set(projection)!={'template','territories','filename'}):
            raise ValueError('Proyeccion final incompatible')
        path=run/'autonomous/main'/projection['territories']
        from run_paths import pinned_hash
        if pinned_hash(root,manifest['files'],path)!=s.sha(path):raise ValueError('Territorios fuera del manifiesto')
        territories=s.read(path)['rows']
    from run_paths import file_path
    target=file_path(run,'resultado_indicadores.xlsx' if output_contract in (ALL_CONTRACT,VALID_CONTRACT) else projection['filename'] if projection else 'resultado_final_indicadores.xlsx')
    target.parent.mkdir(parents=True,exist_ok=True)
    render(root,records,target,territories,contract=output_contract)
    csv_result=write_results(run,columns,records,codes_by_pair)
    audit.update(path=str(target),sha256=s.sha(target),rows=len(records),sheets=list(SHEETS),columns={name:columns for name in THESIS_SHEETS},
        exported_rows=len(records),note=('Excel vacio: no hay evaluaciones SUPPORTED; las evaluaciones insuficientes y los errores se conservan en el recibo.'
            if not audit['supported'] else 'Excel vacio: ningun SUPPORTED supero los controles de exportacion; consultar export_exclusions.' if not records
            else 'Se exportaron los positivos verificados, incluidos los de proyectos incompletos.'),
        output_contract=output_contract,positive_results_only=output_contract==POSITIVE_CONTRACT,
        template=str(TEMPLATE),template_sha256=s.sha(template_path(root)),
        territory_rows=sum(bool(r['territorio_region']) for r in records),inference_calls=0,
        csv=csv_result)
    if output_contract==ALL_CONTRACT:audit['note']='Todos los indicadores seleccionados; decisiones, confianzas y estados técnicos persistidos.'
    if output_contract==VALID_CONTRACT:audit['note']='Evaluaciones validas con sus confianzas originales; errores y limites de recuperacion solo en auditoria.'
    s.write(target.with_suffix('.receipt.json'),audit)
    result=dict(status='PARTIAL' if audit['export_exclusions'] or any(r['status']!='PASS' for r in audit['evaluations']) else 'COMPLETE',
        path=str(target),rows=len(records),evaluations=len(audit['evaluations']),inference_calls=0,csv=csv_result)
    result.update({k:audit[k] for k in ('selected_projects','processed_projects','completed_projects','expected_assessments',
        'valid_assessments','supported','insufficient_evidence','not_supported','blocked_assessments','pending_assessments',
        'processing_complete','results_available','exported_rows','note','export_exclusions')})
    from run_storage import archive_export
    return archive_export(root,run,result)


def status(root,run):
    records,audit=project_records(Path(root).resolve(),Path(run).resolve())
    from collections import Counter
    counts=dict(Counter(r['status'] for r in audit['evaluations']))
    manifest=s.read(Path(run)/'autonomous/main/manifest.json')
    filename='resultado_final.xlsx' if manifest.get('final_projection') else 'resultado_final_indicadores.xlsx'
    from run_paths import file_path
    complete=file_path(Path(run),'resultado_indicadores.xlsx')
    target=complete if complete.exists() else file_path(Path(run),filename)
    return dict(status='ARCHIVED_RESULTS',run_id=Path(run).name,counts=counts,
        indicators_total=len(audit['evaluations']),evaluated=counts.get('PASS',0),
        authorized=True,inference_allowed=False,code_drift=audit['code_changed_since_inference'],
        integrity='ORIGINAL_MANIFEST_INPUTS_AND_RESULTS_VERIFIED; pinned code required for inference',
        final_export=str(target))
