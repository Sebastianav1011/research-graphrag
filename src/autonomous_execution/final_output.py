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
TEMPLATE=Path('data/templates/plantilla_resultado_final_indicadores_territorios.xlsx')
SHEETS={
    'INDICADORES':['id_proyecto','id_articulo','id_investigador','id_indicador',
        'estado_cumplimiento','confianza','parrafo_evidencia','fuente_evidencia','ubicacion_evidencia'],
    'TERRITORIOS':['id_proyecto','id_articulo','tipo_territorio_id','codigo_dane',
        'fuente_evidencia','ubicacion_evidencia'],
}


def connect_readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)


def template_path(root=None):
    return (Path(root) if root is not None else Path(__file__).resolve().parents[2])/TEMPLATE


def load_template(root=None):
    """The user-supplied workbook is authoritative; never regenerate or replace it."""
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


def render(root,records,target,territories=()):
    """Project validated data into the official workbook, preserving its headers/styles."""
    book=load_template(root)
    try:
        sheet=book['INDICADORES']
        for index,record in enumerate(records,2):
            values=[record['siap_id'],None,record['investigador_id'],record['indicador_id'],
                record['estado_cumplimiento'],record['confianza'],record['parrafo_evidencia'],
                record['fuente_evidencia'],record['ubicacion_evidencia']]
            for column,value in enumerate(values,1):sheet.cell(index,column,value)
        sheet=book['TERRITORIOS']
        for index,record in enumerate(territories,2):
            if set(record)!=set(SHEETS['TERRITORIOS']):raise ValueError('Columnas territoriales incompatibles')
            for column,name in enumerate(SHEETS['TERRITORIOS'],1):sheet.cell(index,column,record[name])
        for sheet in book:
            # The template includes formatted blank rows. Data always starts at 2.
            last=(len(records) if sheet.title=='INDICADORES' else len(territories))+1
            if sheet.max_row>last:sheet.delete_rows(last+1,sheet.max_row-last)
            style(sheet)
        temporary=Path(target).with_suffix('.pending.xlsx')
        book.save(temporary);temporary.replace(target)
    finally:book.close()


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
        rows.append(dict(zip(SHEETS['TERRITORIOS'],[inputs[pid]['siap_id'],None,relation['territory_type'],relation['dane_code'],names,locations])))
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
    for base in (run/'workspace/outputs/layer2/canonical',root/'outputs/layer2/canonical'):
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


def project_records(root,run,territorial_codes=None):
    from .engine import result_row
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
    records=[];audit=[]
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
            row=result_row(project,manifest['profiles'][iid],manifest['rubrics'][iid],bundle['wrapper'],manifest['llm']['provider'])
            if row!=bundle['row']:raise ValueError('Decisión o confianza persistida incompatible')
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
        for researcher in researchers(root,run,project):
            records.append(dict(zip(COLUMNS,[project['siap_id'],researcher,iid,decision,paragraph,names,locations,score,territory])))
        audit.append(dict(project_id=pid,indicator_id=iid,status=job['status'],decision=decision,confidence=score))
    return records,dict(manifest_sha256=digest,evaluations=audit,code_changed_since_inference=[
        name for name,h in manifest['code'].items() if not (root/name).is_file() or s.sha(root/name)!=h])


def export(root,run):
    """New root-level projection only. Historical queue/manifests/logs stay intact."""
    root=Path(root).resolve();run=Path(run).resolve()
    if not run.is_relative_to(root/'outputs/runs'):raise ValueError('Run fuera de outputs/runs')
    from layer4_evaluation.indicator_csv import write_results
    codes_by_pair={}
    records,audit=project_records(root,run,codes_by_pair)
    manifest=s.read(run/'autonomous/main/manifest.json')
    projection=manifest.get('final_projection')
    territories=[]
    if projection:
        if projection!=dict(template=TEMPLATE.as_posix(),territories='territories.json',filename='resultado_final.xlsx'):
            raise ValueError('Proyeccion final incompatible')
        path=run/'autonomous/main'/projection['territories']
        from run_paths import pinned_hash
        if pinned_hash(root,manifest['files'],path)!=s.sha(path):raise ValueError('Territorios fuera del manifiesto')
        territories=s.read(path)['rows']
    from run_paths import file_path
    target=file_path(run,projection['filename'] if projection else 'resultado_final_indicadores.xlsx')
    target.parent.mkdir(parents=True,exist_ok=True)
    render(root,records,target,territories)
    csv_result=write_results(run,COLUMNS,records,codes_by_pair)
    audit.update(path=str(target),sha256=s.sha(target),rows=len(records),sheets=list(SHEETS),columns=SHEETS,
        template=str(TEMPLATE),template_sha256=s.sha(template_path(root)),
        territory_rows=len(territories),missing_researcher_ids=sum(r['investigador_id'] is None for r in records),inference_calls=0,
        csv=csv_result)
    s.write(target.with_suffix('.receipt.json'),audit)
    result=dict(status='PARTIAL' if any(r['status']!='PASS' for r in audit['evaluations']) else 'COMPLETE',
        path=str(target),rows=len(records),evaluations=len(audit['evaluations']),inference_calls=0,csv=csv_result)
    from run_storage import archive_export
    return archive_export(root,run,result)


def status(root,run):
    records,audit=project_records(Path(root).resolve(),Path(run).resolve())
    from collections import Counter
    counts=dict(Counter(r['status'] for r in audit['evaluations']))
    manifest=s.read(Path(run)/'autonomous/main/manifest.json')
    filename='resultado_final.xlsx' if manifest.get('final_projection') else 'resultado_final_indicadores.xlsx'
    return dict(status='ARCHIVED_RESULTS',run_id=Path(run).name,counts=counts,
        indicators_total=len(audit['evaluations']),evaluated=counts.get('PASS',0),
        authorized=True,inference_allowed=False,code_drift=audit['code_changed_since_inference'],
        integrity='ORIGINAL_MANIFEST_INPUTS_AND_RESULTS_VERIFIED; pinned code required for inference',
        final_export=str(Path(run)/filename))
