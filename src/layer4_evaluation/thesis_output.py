"""Versioned thesis projections; technical states remain in audit diagnostics."""
import math
from pathlib import Path

COLUMNS=['proyecto/articulo_siap_id','indicador_id','estado_cumplimiento',
    'parrafo_evidencia','fuente_evidencia','ubicacion_evidencia','territorio_region','confianza']
SHEETS=['Proyectos','Artículos']
TEMPLATE=Path('data/templates/plantilla_resultado_tesis.xlsx')
POSITIVE_CONTRACT='THESIS_POSITIVE_OUTPUT_V1'
ALL_CONTRACT='THESIS_ALL_INDICATORS_V1'
VALID_CONTRACT='THESIS_VALID_ASSESSMENTS_V2'
GENERAL_COLUMNS=[c for c in COLUMNS if c!='territorio_region']
DEFAULT_CONTRACT=VALID_CONTRACT
DECISIONS={'SUPPORTED','INSUFFICIENT_EVIDENCE','NOT_SUPPORTED'}


def positive_record(project,row,locations,territory_codes=()):
    """Project a validated positive, without deriving a decision, quote or score."""
    if row['assessment_validation_status']!='VALID' or row['decision']!='SUPPORTED':
        raise ValueError('La salida final admite exclusivamente SUPPORTED VALID')
    score=row.get('confidence_raw_score')
    if row.get('confidence_status')!='COMPUTED' or type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=100:
        raise ValueError('Confianza calculada verificable requerida')
    if not locations or not row.get('evidence_explanation'):
        raise ValueError('Cumplimiento positivo sin explicación o evidencia')
    return _evidence_record(project,row,locations,territory_codes)


def _evidence_record(project,row,locations,territory_codes):
    """Shared literal-evidence projection; never synthesize a decision or score."""
    columns=[]; references=[]; quotes=[]
    for index,evidence in enumerate(locations,1):
        if not evidence['match_valid'] or not evidence['section_id'] or evidence['start'] is None:
            raise ValueError('Evidencia sin localización verificada')
        raw=project['field_provenance'][evidence['field']]['raw_sources']
        sources=[s for s in raw if evidence['field'] in s.get('field_mapping',{})]
        if not sources: raise ValueError('Evidencia sin columna original')
        quotes.append(f'[{index}] '+evidence['text'])
        for source in sources:
            name=source['field_mapping'][evidence['field']]
            names=name if isinstance(name,list) else [name]
            if any(not isinstance(n,str) or not n.strip() or n.strip().casefold() in ('graphrag','llm') for n in names):
                raise ValueError('Nombre de columna original inválido')
            for n in names:
                if n not in columns: columns.append(n)
            references.append(f'[{index}] archivo={Path(source["record_source"]).name}; '
                f'hoja={source.get("source_sheet") or ""}; fila={source["source_row"]}; '
                f'columna={", ".join(names)}; campo={evidence["field"]}; '
                f'section_id={evidence["section_id"]}; [{evidence["start"]},{evidence["end"]}); '
                + evidence['coordinate_system'])
    codes=sorted(set(territory_codes))
    if any(not isinstance(c,str) or len(c) not in (2,5) or not c.isascii() or not c.isdigit() for c in codes):
        raise ValueError('Territorio sin código geográfico verificado')
    paragraph=row.get('evidence_explanation') or ''
    if quotes:paragraph+='\n\nEvidencia literal:\n'+'\n\n'.join(quotes)
    return dict(zip(COLUMNS,[project['siap_id'],row['indicator_id'],row['decision'],
        paragraph or None,'\n'.join(columns) or None,'\n'.join(references) or None,
        '; '.join(codes) or None,row.get('confidence_raw_score')]))


def indicator_record(project,indicator_id,*,row=None,status=None,locations=(),territory_codes=()):
    """Represent a stored valid assessment or its actual unresolved technical state."""
    if row is None:
        if not status or status=='VALID' or status in DECISIONS:
            raise ValueError('Estado técnico persistido requerido')
        return dict(zip(COLUMNS,[project['siap_id'],indicator_id,status,None,None,None,None,None]))
    if (row['indicator_id']!=indicator_id or row['assessment_validation_status']!='VALID'
            or row['decision'] not in DECISIONS):
        raise ValueError('Evaluación persistida incompatible')
    score=row.get('confidence_raw_score')
    if row.get('confidence_status')!='COMPUTED' or type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=100:
        raise ValueError('Confianza calculada verificable requerida')
    if row['decision']=='SUPPORTED':return positive_record(project,row,locations,territory_codes)
    return _evidence_record(project,row,locations,territory_codes)


def verify_records(records,contract=DEFAULT_CONTRACT):
    if contract not in (POSITIVE_CONTRACT,ALL_CONTRACT,VALID_CONTRACT):raise ValueError('Contrato desconocido')
    seen=set()
    for row in records:
        if set(row) not in ([set(COLUMNS),set(GENERAL_COLUMNS)] if contract==VALID_CONTRACT else [set(COLUMNS)]):raise ValueError('Columnas del contrato final incompatibles')
        state=row['estado_cumplimiento']
        if contract==VALID_CONTRACT and state not in DECISIONS:raise ValueError('Salida principal requiere evaluacion valida')
        if contract==POSITIVE_CONTRACT and state!='SUPPORTED':
            raise ValueError('Contrato histórico: solo SUPPORTED')
        key=row[COLUMNS[0]],row['indicador_id']
        if key in seen: raise ValueError('Fuente+indicador duplicado')
        seen.add(key)
        required=COLUMNS[:6] if state=='SUPPORTED' else COLUMNS[:3]
        if any(not isinstance(row[k],str) or not row[k].strip() for k in required):
            raise ValueError('Identidad y evidencia final obligatorias')
        if (row['fuente_evidencia'] or '').strip().casefold() in ('graphrag','llm'):
            raise ValueError('La fuente debe identificar la columna original')
        if state not in DECISIONS:
            if any(row[k] is not None for k in COLUMNS[3:]):
                raise ValueError('Estado técnico sin evaluación: evidencia y confianza NULL')
            continue
        if type(row['confianza']) not in (int,float) or not math.isfinite(row['confianza']) or not 0<=row['confianza']<=100:
            raise ValueError('Confianza final inválida')


def render(root,target,projects=(),articles=(),*,contract=DEFAULT_CONTRACT):
    """Fill the versioned repository template through the existing Excel writer."""
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment
    projects,articles=list(projects),list(articles)
    columns=GENERAL_COLUMNS if contract==VALID_CONTRACT else COLUMNS
    if contract==VALID_CONTRACT:
        projects=[{c:r[c] for c in columns} for r in projects if r['estado_cumplimiento'] in DECISIONS]
        articles=[{c:r[c] for c in columns} for r in articles if r['estado_cumplimiento'] in DECISIONS]
    verify_records(projects,contract);verify_records(articles,contract)
    book=load_workbook(Path(root)/TEMPLATE)
    try:
        if book.sheetnames!=SHEETS: raise ValueError('Hojas de plantilla final incompatibles')
        for sheet,records in zip(book,(projects,articles)):
            if [c.value for c in sheet[1]]!=COLUMNS: raise ValueError('Columnas de plantilla final incompatibles')
            if contract==VALID_CONTRACT:sheet.delete_cols(7)
            if any(c.value is not None for r in sheet.iter_rows(min_row=2) for c in r):
                raise ValueError('La plantilla final contiene resultados')
            if sheet.max_row>1:sheet.delete_rows(2,sheet.max_row-1)
            for record in records:
                sheet.append([record[c] for c in columns])
                for cell in sheet[sheet.max_row][:7]:
                    cell.data_type='s' if isinstance(cell.value,str) else cell.data_type
                    cell.alignment=Alignment(wrap_text=True,vertical='top')
                sheet.cell(sheet.max_row,len(columns)).number_format='0.00'
            sheet.freeze_panes='A2';sheet.auto_filter.ref=f'A1:{"G" if contract==VALID_CONTRACT else "H"}{max(1,sheet.max_row)}'
        target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_suffix('.pending.xlsx')
        book.save(temporary)
        # XLSX timestamps are packaging metadata, not evaluation data. Preserve
        # template properties and fix ZIP timestamps for byte-repeatable exports.
        from io import BytesIO
        from zipfile import ZipFile
        with ZipFile(Path(root)/TEMPLATE) as template:
            properties=template.read('docProps/core.xml') if 'docProps/core.xml' in template.namelist() else None
        packed=BytesIO()
        with ZipFile(temporary) as source,ZipFile(packed,'w') as destination:
            for entry in source.infolist():
                entry.date_time=(1980,1,1,0,0,0)
                data=source.read(entry.filename)
                if entry.filename=='docProps/core.xml':
                    if properties is not None:data=properties
                    else:
                        import re
                        data=re.sub(rb'(<dcterms:(?:created|modified)\b[^>]*>)[^<]+',
                            rb'\g<1>1980-01-01T00:00:00Z',data)
                destination.writestr(entry,data)
        temporary.write_bytes(packed.getvalue())
        check=load_workbook(temporary,read_only=True,data_only=True)
        try:
            if check.sheetnames!=SHEETS:raise ValueError('Hojas exportadas incompatibles')
            for sheet,records in zip(check,(projects,articles)):
                actual=list(sheet.values)
                if list(actual[0])!=columns or actual[1:]!=[tuple(r[c] for c in columns) for r in records]:
                    raise ValueError('Verificación Excel final fallida')
        finally:check.close()
        temporary.replace(target)
    finally:book.close()


def persisted_records(root,run,*,contract=DEFAULT_CONTRACT):
    """Audit sealed plans and stored receipts, without executing assessment/scoring."""
    import json
    import hashlib
    from layer4_evaluation.indicators.review import evidence_locations
    root,run=Path(root).resolve(),Path(run).resolve()
    def read(path):return json.loads(path.read_text(encoding='utf-8'))
    def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    def pinned(base,name,digest):
        path=(base/name).resolve()
        if not path.is_relative_to(base.resolve()) or sha(path)!=digest:
            raise ValueError('Artefacto persistido alterado: '+str(path))
        return path
    def unique(items,key):
        result={}
        for item in items:
            identity=key(item)
            if identity in result:raise ValueError('Identidad duplicada: '+str(identity))
            result[identity]=item
        return result
    coverage=read(run/'resultados/estado_indicadores.json')
    saved=read(run/'resultados/evaluaciones_validas.json')
    key=lambda x:(x['siap_id'],x['indicator_id'])
    states=unique(coverage['indicators'],key);valid=unique(saved['assessments'],key)
    execution=read(run/'estado/execution.json')
    selection=execution['project_ids']
    if len(set(selection))!=len(selection):raise ValueError('Selección duplicada')
    projects={};profiles=None;expected=set();receipts={};catalog_hashes={}
    from knowledge_store import evaluation_dir
    base=evaluation_dir(run)
    for directory in sorted(base.glob('batch_*')):
        manifest=read(directory/'manifest.json')
        plan_path=pinned(directory,'plan.json',manifest['plan_sha256']);plan=read(plan_path)
        if plan.get('evaluation_policy',{})!=execution.get('evaluation_policy',{}):
            raise ValueError('No mezclar modos incompatibles en la exportacion')
        catalog_hashes[directory.name]=manifest['plan_sha256']
        for name,digest in manifest['files'].items():pinned(directory,name,digest)
        auth=read(directory/'authorization.json')
        if not auth.get('authorized') or auth['run_plan_sha256']!=sha(plan_path):
            raise ValueError('Plan sin autorización persistida')
        if profiles is not None and profiles!=plan['profiles']:raise ValueError('Catálogos incompatibles')
        profiles=plan['profiles']
        for p in plan['projects']:
            pid=p['siap_id']
            if pid not in selection or pid in projects:raise ValueError('Proyecto ajeno o ambiguo')
            projects[pid]=p
            expected.update((pid,iid) for iid in profiles)
            for call in sorted((directory/'calls'/p['project_id']).glob('*')):
                if not (call/'verification.json').exists():continue
                cp=read(call/'plan.json');receipt=read(call/'verification.json')
                if cp['run_plan_sha256']!=sha(plan_path) or cp['project_id']!=p['project_id']:
                    raise ValueError('Llamada de otro plan/proyecto')
                if cp['indicator_ids']!=receipt['indicator_ids'] or cp['phase']!='assessment':
                    raise ValueError('Identidad de recibo incompatible')
                record_path=call/'records'/cp['phase']/(p['project_id']+'.json')
                record=read(record_path)
                for name,digest in record['artifact_hashes'].items():pinned(call,name,digest)
                rows=[]
                if receipt['status']=='PASS':
                    rows_file=read(call/'assessment.rows.json')
                    if rows_file['record_sha256']!=sha(record_path):raise ValueError('Registro de evaluación alterado')
                    rows=rows_file['rows']
                    if {r['indicator_id'] for r in rows}!=set(cp['indicator_ids']):
                        raise ValueError('Cobertura del recibo incompatible')
                for iid in cp['indicator_ids']:
                    pair=pid,iid
                    if pair in receipts:raise ValueError('Recibos duplicados')
                    receipts[pair]=(receipt['status'],next((r for r in rows if r['indicator_id']==iid),None))
    if set(projects)!=set(selection) or not profiles or set(states)!=expected:
        raise ValueError('No se puede reconstruir inequívocamente la selección y su catálogo')
    if set(valid)!={k for k,v in states.items() if v['status']=='VALID'}:
        raise ValueError('Evaluaciones válidas y cobertura difieren')
    records=[]
    for pair,item in sorted(states.items()):
        pid,iid=pair;p=projects[pid];row=valid.get(pair)
        if row is None:
            if pair in receipts and receipts[pair][0]!=item['status']:
                raise ValueError('Estado técnico y recibo difieren')
            if item['status']=='BLOCKED_ERROR' and pair not in receipts:
                raise ValueError('Bloqueo sin recibo')
            if item.get('decision') is not None:raise ValueError('Estado técnico con decisión fabricada')
            consumer=indicator_record(p,iid,status=item['status'])
        else:
            status,original=receipts.get(pair,(None,None))
            if status!='PASS' or dict(original,siap_id=pid)!=row or row['decision']!=item['decision']:
                raise ValueError('Evaluación consolidada y registro original difieren')
            if row['project_id']!=p['project_id']:raise ValueError('Identificador institucional incompatible')
            sizes=[len(row[k]) for k in ('evidence_source_fields','evidence_texts','evidence_stages')]
            if len(set(sizes))!=1:raise ValueError('Evidencia persistida incompleta')
            evidence=[dict(field=f,text=t,stage=s) for f,t,s in zip(
                row['evidence_source_fields'],row['evidence_texts'],row['evidence_stages'])]
            locations=evidence_locations(p,dict(evidence=evidence))
            consumer=indicator_record(p,iid,row=row,locations=locations)
        if contract==ALL_CONTRACT or contract==VALID_CONTRACT and consumer['estado_cumplimiento'] in DECISIONS or consumer['estado_cumplimiento']=='SUPPORTED':records.append(consumer)
    verify_records(records,contract)
    return records,dict(run_id=run.name,status=coverage['status'],output_contract=contract,
        **({'evaluation_policy':execution['evaluation_policy']} if execution.get('evaluation_policy') else {}),
        expected_assessments=len(expected),valid_assessments=len(valid),catalog_indicators=len(profiles),
        sealed_plan_sha256=catalog_hashes,inference_calls=0,scoring_calls=0)


def recover_export(root,run,*,contract=ALL_CONTRACT):
    """Offline entry to the SAME template/CSV writers; original files are read only."""
    import json
    import hashlib
    from collections import Counter
    from layer4_evaluation.indicator_csv import write_results
    root,run=Path(root).resolve(),Path(run).resolve()
    if not run.is_relative_to(root/'outputs/runs'):raise ValueError('Run fuera de outputs/runs')
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    directory=run/'resultados'
    target=directory/'resultado_indicadores_completo.xlsx'
    receipt=directory/'exportacion_completa.receipt.json'
    csv_target=directory/'indicadores_completos.csv'
    for path in (target,receipt,csv_target,target.with_suffix('.pending.xlsx'),csv_target.with_suffix('.csv.pending')):
        if path.exists():raise FileExistsError(path)
    original={p.relative_to(run).as_posix():sha(p) for p in run.rglob('*') if p.is_file()}
    records,audit=persisted_records(root,run,contract=contract)
    # Preserve accepted existing territorial codes rather than re-running recognition.
    import csv
    codes={};territories={}
    old=directory/'indicadores.csv'
    if old.exists():
        with old.open(encoding='utf-8-sig',newline='') as stream:
            for row in csv.DictReader(stream,delimiter=';'):
                pair=row[COLUMNS[0]],row['indicador_id']
                territories[pair]=row.get('territorio_region') or None
    for record in records:
        record['territorio_region']=territories.get((record[COLUMNS[0]],record['indicador_id']))
    render(root,target,records,contract=contract)
    columns=GENERAL_COLUMNS if contract==VALID_CONTRACT else COLUMNS
    result=write_results(run,columns,records,codes,filename=csv_target.name,
        territorial_filename=None,exclusive=True)
    for name,digest in original.items():
        if sha(run/name)!=digest:raise ValueError('Original modificado durante exportación: '+name)
    audit.update(rows=len(records),states=dict(Counter(r['estado_cumplimiento'] for r in records)),
        per_project=dict(Counter(r[COLUMNS[0]] for r in records)),
        zero_confidence=sum(r['confianza']==0 for r in records),
        null_confidence=sum(r['confianza'] is None for r in records),
        original_files_sha256=original,original_files_unchanged=True,
        output_files_sha256={p.name:sha(p) for p in (target,csv_target)},
        excel=str(target),csv=result,sheets=SHEETS,columns=columns,
        template_sha256=sha(root/TEMPLATE),power_bi_desktop_tested=False)
    with receipt.open('x',encoding='utf-8') as stream:json.dump(audit,stream,ensure_ascii=False,indent=2)
    return {k:v for k,v in audit.items() if k!='original_files_sha256'}


if __name__=='__main__':
    import argparse
    import json
    parser=argparse.ArgumentParser(description='Exportación offline desde resultados persistidos; sin inferencia ni scoring.')
    parser.add_argument('--run',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(recover_export(Path(__file__).resolve().parents[2],args.run),ensure_ascii=True,indent=2))
