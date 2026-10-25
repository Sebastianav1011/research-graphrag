"""Reusable future four-sheet export. No project selection, provider or real-data reads."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import re
import zipfile
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator, FormatChecker
from .contracts import FIELDS, PROJECT_COLUMNS, INDICATOR_COLUMNS, TERRITORY_COLUMNS, load_schema
from .assessment import build_indicator_row

ROOT=Path(__file__).resolve().parents[3]


def _preserve_iso_strings(output,spec):
    """Repair an artifact-tool export coercion, without reauthoring the workbook.

    The native exporter coerces literal ISO strings into date cells even with a
    text number format, losing timezone and microseconds. Restore only those
    explicitly declared string cells as OOXML inline strings. All workbook
    design, tables, styles, other cells and previews remain artifact-authored.
    """
    namespace='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    def tag(name):return '{'+namespace+'}'+name
    changes={}
    with zipfile.ZipFile(output) as source:
        for index,sheet in enumerate(spec['sheets'],1):
            dates=[(r+2,c+1,value) for r,row in enumerate(sheet['rows']) for c,value in enumerate(row)
                   if isinstance(value,str) and re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',value)]
            if not dates:continue
            name=f'xl/worksheets/sheet{index}.xml';xml=ET.fromstring(source.read(name))
            for row,column,value in dates:
                from openpyxl.utils import get_column_letter
                address=get_column_letter(column)+str(row)
                cell=next((c for c in xml.iter(tag('c')) if c.attrib.get('r')==address),None)
                if cell is None:raise ValueError('Missing serialized ISO cell: '+address)
                for child in list(cell):cell.remove(child)
                cell.set('t','inlineStr')
                text=ET.SubElement(ET.SubElement(cell,tag('is')),tag('t'))
                text.set('{http://www.w3.org/XML/1998/namespace}space','preserve');text.text=value
            changes[name]=ET.tostring(xml,encoding='utf-8',xml_declaration=True)
        if not changes:return
        replacement=Path(str(output)+'.literal-timestamps.tmp')
        with zipfile.ZipFile(replacement,'w') as target:
            for entry in source.infolist():target.writestr(entry,changes.get(entry.filename,source.read(entry.filename)))
    replacement.replace(output)


def _finite(value):
    if isinstance(value, dict):
        for item in value.values():_finite(item)
    elif isinstance(value,list):
        for item in value:_finite(item)
    elif isinstance(value,(float,Decimal)) and not math.isfinite(value):
        raise ValueError('Nonfinite value in output')


def validate_workbook_data(data, profiles):
    _finite(data)
    Draft202012Validator(load_schema(ROOT,'workbook_data'),format_checker=FormatChecker()).validate(data)
    projects={row['project_id']:row for row in data['projects']}
    if len(projects)!=len(data['projects']):raise ValueError('Duplicate master PROJECT')
    if len(projects)!=data['metadata']['project_count']:raise ValueError('Metadata project count mismatch')
    indicators=set();counts=Counter()
    for row in data['indicators']:
        project=projects.get(row['project_id'])
        if project is None:raise ValueError('Indicator refers to unknown PROJECT')
        key=row['project_id'],row['indicator_id']
        if key in indicators:raise ValueError('Duplicate PROJECT+INDICATOR')
        indicators.add(key);counts[row['project_id']]+=1
        if row['indicator_id'] not in profiles:raise ValueError('Unknown indicator profile')
        if len(row['evidence_source_fields'])!=len(row['evidence_texts']):raise ValueError('Evidence arrays not aligned')
        if row['confidence_status']=='INVALID_ASSESSMENT':raise ValueError('Invalid assessment remains in technical diagnostics')
        assessment={'decision':row['decision'],'support_strength':row['support_strength'],
            'supported_key_elements':row['supported_key_elements'],
            'evidence':[{'field':field,'text':text} for field,text in zip(row['evidence_source_fields'],row['evidence_texts'])],
            'explanation':row['evidence_explanation']}
        expected=build_indicator_row(row['project_id'],{f:project[f] for f in FIELDS},profiles[row['indicator_id']],assessment,
            engine=row['assessment_engine'],engine_status=row['assessment_engine_status'])
        if expected!=row:raise ValueError('Output differs from validated assessment/profile/confidence')
        if any(row[k]!=data['metadata'][k] for k in ('assessment_engine','assessment_engine_status')):
            raise ValueError('Assessment engine metadata mismatch')
        if row['assessment_engine_status']=='NOT_EXECUTED':raise ValueError('Assessment rows cannot claim NOT_EXECUTED')
    if any(n>data['metadata']['candidate_limit_per_project'] for n in counts.values()):
        raise ValueError('Candidate limit per PROJECT exceeded')
    territories=set();specific=set();countries=set()
    for row in data['territories']:
        if row['project_id'] not in projects:raise ValueError('Territory refers to unknown PROJECT')
        key=row['project_id'],row['territory_type'],row['territory_code']
        if key in territories:raise ValueError('Duplicate PROJECT+TERRITORY')
        territories.add(key)
        if row['territory_type']=='COUNTRY':countries.add(row['project_id'])
        else:
            specific.add(row['project_id'])
            if not row['territory_code'].startswith(row['department_code']):raise ValueError('Territory parent code mismatch')
    if countries & specific:raise ValueError('COUNTRY duplicates resolved subnational territory')
    return True


def workbook_data(projects, indicators, territories, metadata, *, profiles, ambiguous_mentions=()):
    """Create flat sheets with one master row per PROJECT, preserving diagnostics separately."""
    metadata=deepcopy(metadata)
    ids={p['project_id'] for p in projects}
    if any(row['project_id'] not in ids for row in ambiguous_mentions):
        raise ValueError('Ambiguity diagnostics must belong to the supplied PROJECT set')
    metadata['territory_ambiguous_mentions']=len(ambiguous_mentions)
    metadata['territory_ambiguous_projects']=len({r['project_id'] for r in ambiguous_mentions})
    result=deepcopy({'projects':projects,'indicators':indicators,'territories':territories,'metadata':metadata})
    validate_workbook_data(result,profiles)
    return result


def workbook_spec(data, profiles):
    validate_workbook_data(data,profiles)
    tabs=[]
    for name,key,columns in [('PROYECTOS','projects',PROJECT_COLUMNS),('INDICADORES','indicators',INDICATOR_COLUMNS),
                             ('TERRITORIOS','territories',TERRITORY_COLUMNS)]:
        rows=[]
        for record in data[key]:
            rows.append([json.dumps(record[c],ensure_ascii=False) if isinstance(record[c],list) else record[c] for c in columns])
        tabs.append({'name':name,'columns':columns,'rows':rows})
    tabs.append({'name':'METADATA','columns':['key','value'],'rows':[[k,v] for k,v in data['metadata'].items()]})
    return {'sheets':tabs}


def export_workbook(data, profiles, output):
    """Explicit future exporter. Current preparation calls it only with synthetic fixtures."""
    spec=workbook_spec(data,profiles)
    return export_workbook_spec(spec,output)


def export_workbook_spec(spec, output):
    """Render an already validated four-sheet spec using the prepared renderer.

    The preliminary runner supplies its separately validated diagnostic schema;
    ordinary final exports continue to reject invalid assessments above.
    """
    if [s['name'] for s in spec['sheets']]!=['PROYECTOS','INDICADORES','TERRITORIOS','METADATA']:
        raise ValueError('Expected the four contractual sheets')
    for sheet in spec['sheets']:
        for row in sheet['rows']:
            if len(row)!=len(sheet['columns']):raise ValueError('Workbook row width mismatch')
            if any(isinstance(v,str) and len(v)>32767 for v in row):
                raise ValueError('Excel cell limit exceeded; refusing to truncate required text')
    output=Path(output).resolve()
    if output.suffix.lower()!='.xlsx':raise ValueError('Expected .xlsx output')
    if output.exists():raise FileExistsError('Preserve existing workbook; choose a new output path')
    output.parent.mkdir(parents=True,exist_ok=True)
    node=shutil.which('node')
    with tempfile.TemporaryDirectory(prefix='layer4-export-',dir=output.parent) as scratch:
        spec_path=Path(scratch)/'spec.json'
        spec_path.write_text(json.dumps(spec,ensure_ascii=True),encoding='utf-8')
        if node:
            completed=subprocess.run([node,str(ROOT/'scripts/render_layer4_workbook.mjs'),str(spec_path),str(output)],
                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
            if completed.returncode==0:
                _preserve_iso_strings(output,spec)
                return output
            if completed.returncode!=3 or 'ARTIFACT_RUNTIME_UNAVAILABLE' not in completed.stderr:
                raise RuntimeError('Workbook export failed: '+completed.stderr[-1500:])
        # Offline fallback is used only if the artifact runtime is unavailable.
        from openpyxl import Workbook
        from openpyxl.styles import Alignment,Font,PatternFill
        from openpyxl.utils import get_column_letter
        wb=Workbook();wb.remove(wb.active)
        for tab in spec['sheets']:
            sheet=wb.create_sheet(tab['name']);sheet.append(tab['columns'])
            for row in tab['rows']:sheet.append(row)
            for row in sheet:
                for cell in row:
                    if isinstance(cell.value,str):cell.data_type='s'
                    cell.font=Font(name='Arial',size=10)
                    cell.alignment=Alignment(wrap_text=True,vertical='top')
            for cell in sheet[1]:
                cell.fill=PatternFill('solid',fgColor='173D57');cell.font=Font(name='Arial',size=10,color='FFFFFF',bold=True)
            for i,name in enumerate(tab['columns'],1):
                sheet.column_dimensions[get_column_letter(i)].width=36
                for row in sheet.iter_rows(min_col=i,max_col=i,min_row=2):
                    if name=='territory_code' or name.endswith('_id') or name.endswith('_code'):row[0].number_format='@'
                    elif name.endswith('_score') or name=='key_element_coverage':row[0].number_format='0.00'
            sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
        wb.save(output)
        return output
