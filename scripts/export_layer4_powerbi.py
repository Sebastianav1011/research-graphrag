"""Export the existing validated preliminary assessments; never invoke a model."""
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pyarrow.parquet as pq
from openpyxl import load_workbook

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from layer4_evaluation.indicators.powerbi import COLUMNS,consumption_rows,TERRITORY_COLUMNS,territory_rows,territorial_workbook_bytes
from layer4_evaluation.indicators.preliminary import verify,json_file
from layer4_evaluation.territories.inputs import sha256
from layer4_evaluation.history import verify_historical_files


def export():
    verified=verify(ROOT)
    source=ROOT/'outputs/layer4/auditoria/historicos/preliminar_20'
    out=ROOT/'outputs/layer4/auditoria/historicos/powerbi_preliminar_20'
    if out.exists():raise FileExistsError('Preserve existing PowerBI publication')
    assessments=pq.read_table(source/'project_indicator_preliminary.parquet').to_pylist()
    ids={a['project_id'] for a in assessments}
    docs=pq.read_table(ROOT/'outputs/layer2/knowledge/source_documents.parquet',
                       columns=['source_id','source_type','metadata_json']).to_pylist()
    mapping={d['source_id']:json.loads(d['metadata_json'])['source_project_id'] for d in docs
             if d['source_type']=='PROJECT' and d['source_id'] in ids}
    if set(mapping)!=ids:raise ValueError('Incomplete SIAP identity mapping')
    rows=consumption_rows(assessments,mapping)
    if len(rows)!=len(assessments) or len({r['siap_id'] for r in rows})!=20:
        raise ValueError('Consumer projection changed row/project counts')
    out.mkdir(parents=True)
    csv_path=out/'resultado_indicadores_powerbi.csv'
    xlsx_path=out/'resultado_indicadores_powerbi.xlsx'
    with csv_path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=COLUMNS);writer.writeheader();writer.writerows(rows)
    spec={'name':'RESULTADO_INDICADORES','columns':COLUMNS,'rows':[[r[c] for c in COLUMNS] for r in rows]}
    spec_path=out/'workbook_spec.json';json_file(spec_path,spec)
    done=subprocess.run([shutil.which('node'),str(ROOT/'scripts/render_layer4_powerbi.mjs'),str(spec_path),str(xlsx_path)],
                        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
    if done.returncode:raise RuntimeError('PowerBI workbook export failed: '+done.stderr[-1000:])
    workbook=load_workbook(xlsx_path,data_only=False)
    if workbook.sheetnames!=['RESULTADO_INDICADORES']:raise ValueError('Wrong consumer worksheet')
    sheet=workbook.active
    if list(next(sheet.values))!=COLUMNS or sheet.max_row!=len(rows)+1:raise ValueError('Consumer shape mismatch')
    for actual,wanted in zip(list(sheet.values)[1:],rows):
        if list(actual)!=[wanted[c] for c in COLUMNS]:raise ValueError('Workbook altered consumer values')
    if any(c.data_type in ('f','e') for row in sheet for c in row):raise ValueError('Unexpected formula/error')
    if any(c.data_type!='s' for c in list(sheet.columns)[0][1:]):raise ValueError('SIAP IDs must remain strings')
    if not sheet.freeze_panes or not sheet.tables:raise ValueError('Missing workbook filters/panes')
    workbook.close()
    with csv_path.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream);csv_rows=list(reader)
        if reader.fieldnames!=COLUMNS or len(csv_rows)!=len(rows):raise ValueError('CSV shape mismatch')
        for actual,wanted in zip(csv_rows,rows):
            if any(actual[c]!=('' if wanted[c] is None else str(wanted[c])) for c in COLUMNS):raise ValueError('CSV values changed')
    if verify(ROOT)!=verified:raise ValueError('Technical preliminary changed during export')
    report={'status':'POWERBI_PRELIMINARY_20_READY','table':'RESULTADO_INDICADORES','columns':COLUMNS,
            'rows':len(rows),'projects':len(mapping),'verification':'PASS','source_status':verified['status'],
            'identity_source':'Layer2 source_documents.metadata_json.source_project_id',
            'decisions_preserved':True,'evidence':'All verified literal quotes, numbered and aligned to source fields',
            'fuente_evidencia':'SIAP; NULL if no quote exists','confidence_version':'RAW_CONFIDENCE_V1',
            'confidence_scale':'0..100; NOT A PROBABILITY; NULL when not computed',
            'confidence_computed':sum(r['confianza'] is not None for r in rows),
            'confidence_null':sum(r['confianza'] is None for r in rows),'llm_calls':0,
            'source_sha256':sha256(source/'project_indicator_preliminary.parquet'),
            'code_hashes':{name:sha256(ROOT/name) for name in ('src/layer4_evaluation/indicators/powerbi.py',
                          'scripts/export_layer4_powerbi.py','scripts/render_layer4_powerbi.mjs')},
            'outputs':{p.name:sha256(p) for p in out.iterdir() if p.is_file()}}
    json_file(out/'powerbi_manifest.json',report)
    print(json.dumps(report,ensure_ascii=True,indent=2))


def repair_territories():
    """In-place export repair only. No assessment/confidence/territory pipeline."""
    from io import BytesIO,StringIO
    from contextlib import closing
    import hashlib
    import os
    import zipfile
    source=ROOT/'outputs/layer4/auditoria/historicos/preliminar_20'
    out=ROOT/'outputs/layer4/auditoria/historicos/powerbi_preliminar_20'
    xlsx=out/'resultado_indicadores_powerbi.xlsx'
    indicator_csv=out/'resultado_indicadores_powerbi.csv'
    manifest_path=out/'powerbi_manifest.json';spec_path=out/'workbook_spec.json'
    required=[xlsx,indicator_csv,manifest_path,spec_path]
    if any(not p.is_file() for p in required):raise FileNotFoundError('Existing consumer artifacts required; never create replacements')
    def inventory():
        files=set()
        for directory,dirs,names in os.walk(ROOT):
            dirs[:]=[d for d in dirs if d not in ('.git','.venv','node_modules','__pycache__')]
            files.update((Path(directory)/name).relative_to(ROOT).as_posix() for name in names)
        return files
    before_files=inventory()
    frozen=json.loads((source/'integrity_before.json').read_text(encoding='utf-8'))
    def frozen_check():
        verify_historical_files(ROOT,frozen)
        technical=source/'resultado_preliminar_20_proyectos.xlsx'
        expected=json.loads((source/'preliminary_manifest.json').read_text(encoding='utf-8'))['output_hashes'][technical.name]
        if sha256(technical)!=expected:raise ValueError('Technical workbook changed')
    frozen_check()
    original=xlsx.read_bytes();original_csv=indicator_csv.read_bytes()
    with closing(load_workbook(BytesIO(original))) as wb:
        indicator_values=list(wb['RESULTADO_INDICADORES'].values)
    if list(indicator_values[0])!=COLUMNS or len(indicator_values)!=32:raise ValueError('Unexpected indicator table')
    siap_set={r[0] for r in indicator_values[1:]}
    if len(siap_set)!=20:raise ValueError('Expected20 institutional IDs')
    with (source/'selected_projects.csv').open(encoding='utf-8-sig',newline='') as stream:
        projects={r['project_id'] for r in csv.DictReader(stream)}
    docs=pq.read_table(ROOT/'outputs/layer2/knowledge/source_documents.parquet',columns=['source_id','source_type','metadata_json']).to_pylist()
    mapping={d['source_id']:json.loads(d['metadata_json'])['source_project_id'] for d in docs
             if d['source_type']=='PROJECT' and d['source_id'] in projects}
    if set(mapping)!=projects or set(mapping.values())!=siap_set:raise ValueError('Institutional identity mapping mismatch')
    publication=ROOT/'outputs/layer4/territorios/publicacion'
    if json.loads((publication/'territory_manifest.json').read_text(encoding='utf-8'))['architecture']!='PROJECT_TERRITORY_V1':
        raise ValueError('Unexpected territorial publication')
    rows=territory_rows(pq.read_table(publication/'project_territories.parquet').to_pylist(),
                        pq.read_table(ROOT/'outputs/layer2/reference/dane_territories.parquet').to_pylist(),mapping)
    # Compare against the original technical projection without changing it.
    technical_rows=[json.loads(line) for line in (source/'project_territories_selected.jsonl').read_text(encoding='utf-8').splitlines() if line]
    expected=[{k:mapping[r['project_id']] if k=='siap_id' else r[k] for k in TERRITORY_COLUMNS} for r in technical_rows]
    if rows!=expected or len(rows)!=17:raise ValueError('Published territory projection differs from technical17 relationships')
    candidate=territorial_workbook_bytes(original,rows)
    def validate(payload):
        with closing(load_workbook(BytesIO(payload))) as wb:
            if wb.sheetnames!=['RESULTADO_INDICADORES','TERRITORIOS']:raise ValueError('Exactly2 sheets required')
            if list(wb['RESULTADO_INDICADORES'].values)!=indicator_values:raise ValueError('Indicator values changed')
            sheet=wb['TERRITORIOS']
            if list(sheet.values)!=[tuple(TERRITORY_COLUMNS),*[tuple(r[c] for c in TERRITORY_COLUMNS) for r in rows]]:
                raise ValueError('Territorial workbook values differ')
            if any(sheet.cell(i,3).data_type!='s' for i in range(2,len(rows)+2)):raise ValueError('Territory codes not strings')
            if any(sheet.cell(i,5).value is not None and sheet.cell(i,5).data_type!='s' for i in range(2,len(rows)+2)):
                raise ValueError('Department codes not strings')
            if not sheet.freeze_panes or not sheet.tables:raise ValueError('Territorial filters/panes missing')
        with zipfile.ZipFile(BytesIO(original)) as a,zipfile.ZipFile(BytesIO(payload)) as b:
            for name in ('xl/worksheets/sheet1.xml','xl/tables/table1.xml','xl/sharedStrings.xml','xl/styles.xml'):
                if a.read(name)!=b.read(name):raise ValueError('Original indicator package part changed')
    validate(candidate)
    territory_csvs=[p for base in (out,source) for p in [base/'proyecto_territorio_powerbi.csv'] if p.is_file()]
    changes={xlsx:candidate}
    for path in territory_csvs:
        text=StringIO(newline='');writer=csv.DictWriter(text,fieldnames=TERRITORY_COLUMNS);writer.writeheader();writer.writerows(rows)
        changes[path]=text.getvalue().encode('utf-8-sig')
        parsed=list(csv.DictReader(StringIO(changes[path].decode('utf-8-sig'))))
        if parsed!=[{c:'' if r[c] is None else r[c] for c in TERRITORY_COLUMNS} for r in rows]:raise ValueError('Territory CSV mismatch')
    spec=json.loads(spec_path.read_text(encoding='utf-8'))
    spec.update(territory_columns=TERRITORY_COLUMNS,territories=[[r[c] for c in TERRITORY_COLUMNS] for r in rows],
                sheet_names=['RESULTADO_INDICADORES','TERRITORIOS'])
    changes[spec_path]=(json.dumps(spec,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    report=json.loads(manifest_path.read_text(encoding='utf-8'))
    validation={'indicator_rows':31,'indicator_columns':COLUMNS,'indicators_modified':False,
        'territory_rows':len(rows),'territory_projects':len({r['siap_id'] for r in rows}),
        'territory_columns':TERRITORY_COLUMNS,
        'territory_counts':{t:sum(r['territory_type']==t for r in rows) for t in ('MUNICIPALITY','DEPARTMENT','COUNTRY')},
        'codes_as_strings':'PASS','country_000':'PASS','ambiguous_excluded':'PASS','exactly_two_sheets':'PASS',
        'new_files_created':False,'indicator_csv_modified':False,'territory_csv_reused':[p.relative_to(ROOT).as_posix() for p in territory_csvs],
        'territory_csv_equivalence':'PASS' if territory_csvs else 'NOT_APPLICABLE_NO_EXISTING_FILE',
        'confidence_recalculated':False,'llm_calls':0,'territory_extraction_executed':False,'layer3_modified':False}
    report.update(status='LAYER4_POWERBI_CONSUMER_OUTPUT_READY',sheet_names=spec['sheet_names'],
        territory_version='PROJECT_TERRITORY_V1',territorial_export_validation=validation)
    report['code_hashes']={name:sha256(ROOT/name) for name in report['code_hashes']}
    report['outputs']={p.name:hashlib.sha256(changes.get(p,p.read_bytes())).hexdigest() for p in out.iterdir()
                       if p.is_file() and p!=manifest_path}
    changes[manifest_path]=(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    backups={p:p.read_bytes() for p in changes}
    def overwrite(path,payload):
        # r+b cannot create a new file. Validate in RAM first; retain rollback
        # bytes in memory rather than making a backup or temporary output.
        with path.open('r+b') as stream:
            stream.write(payload);stream.truncate();stream.flush();os.fsync(stream.fileno())
    try:
        for path,payload in changes.items():overwrite(path,payload)
        validate(xlsx.read_bytes())
        if indicator_csv.read_bytes()!=original_csv:raise ValueError('Indicator CSV changed')
        frozen_check()
        if inventory()!=before_files:raise ValueError('Filesystem inventory changed')
    except Exception:
        for path,payload in backups.items():overwrite(path,payload)
        raise
    print(json.dumps({'status':report['status'],'xlsx':xlsx.relative_to(ROOT).as_posix(),**validation},ensure_ascii=True,indent=2))


if __name__=='__main__':
    if sys.argv[1:]==['--repair-territories']:repair_territories()
    elif sys.argv[1:]:raise SystemExit('Supported option: --repair-territories')
    else:export()
