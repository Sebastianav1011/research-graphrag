"""Human review export; territorial decisions remain in matching.py."""
from collections import defaultdict
import json
import os
from pathlib import Path
import shutil
import subprocess


def _cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, str) and len(value) > 32000:
        return value[:31800] + ' [Vista abreviada. Consultar evidencia Parquet.]'
    return value


def review_spec(documents, territories, result, metadata):
    titles = {doc['source_id']: doc.get('title') for doc in documents}
    catalog = {(row['territory_type'], row['dane_code']): row for row in territories}
    grouped = defaultdict(list)
    for row in result['evidence']:
        grouped[row['project_id'], row['territory_type'], row['dane_code']].append(row)
    resolved = []
    for row in result['relationships']:
        key = row['project_id'], row['territory_type'], row['dane_code']
        evidence = grouped[key]
        territory = catalog[key[1:]]
        snippets = list(dict.fromkeys(e['field_name'] + ': ' + e.get('context_text', '') for e in evidence))
        review_evidence = '\n'.join(snippets[:3])
        if len(snippets) > 3:
            review_evidence += f'\n[Vista de 3 contextos; {len(evidence)} menciones completas en Parquet.]'
        resolved.append([*key, titles[key[0]], territory['territory_name'], territory['department_name'],
                         '; '.join(sorted({e['field_name'] for e in evidence})),
                         '; '.join(sorted({e['matched_text'] for e in evidence})),
                         '; '.join(sorted({e['resolution_method'] for e in evidence})),
                         len(evidence), review_evidence])
    ambiguous_columns = ['project_id', 'title', 'document_id', 'section_id', 'field_name',
                         'matched_text', 'normalized_match', 'territory_type_detected',
                         'candidate_count', 'candidate_dane_codes', 'candidate_names',
                         'candidate_departments', 'candidate_territory_types', 'context_text']
    ambiguous = [[titles[row['project_id']] if field == 'title' else row.get(field)
                  for field in ambiguous_columns] for row in result['ambiguous']]
    catalog_columns = list(territories[0]) if territories else []
    sheets = [
        {'name': 'RESUELTOS', 'columns': ['project_id', 'territory_type', 'dane_code', 'title',
            'territory_name', 'department_name', 'source_fields', 'matched_text',
            'resolution_method', 'mention_count', 'evidence'], 'rows': resolved,
            'widths': [29, 20, 14, 68, 29, 27, 33, 35, 38, 16, 100]},
        {'name': 'AMBIGUOS', 'columns': ambiguous_columns, 'rows': ambiguous,
            'widths': [29, 68, 30, 30, 22, 30, 30, 25, 18, 38, 45, 45, 38, 100]},
        {'name': 'CATALOGO_DANE', 'columns': catalog_columns,
            'rows': [[row[field] for field in catalog_columns] for row in territories]},
        {'name': 'METADATA', 'columns': ['campo', 'valor'],
            'rows': [[key, value] for key, value in metadata.items()], 'widths': [42, 110]},
    ]
    for sheet in sheets:
        sheet['rows'] = [[_cell(value) for value in row] for row in sheet['rows']]
    return {'sheets': sheets}


def _fallback(spec, output):
    """Portable offline fallback only when the artifact runtime is unavailable."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo
    wb = Workbook()
    wb.remove(wb.active)
    for tab in spec['sheets']:
        sheet = wb.create_sheet(tab['name'])
        sheet.append(tab['columns'])
        for row in tab['rows']:
            sheet.append(row)
        for row in sheet:
            for cell in row:
                cell.alignment = Alignment(vertical='top', wrap_text=True)
                cell.font = Font(name='Arial', size=10)
                if isinstance(cell.value, str):
                    cell.data_type = 's'
            sheet.row_dimensions[row[0].row].height = 60
        for cell in sheet[1]:
            cell.fill = PatternFill('solid', fgColor='173D57')
            cell.font = Font(name='Arial', size=10, color='FFFFFF', bold=True)
        sheet.row_dimensions[1].height = 30
        for index, column in enumerate(tab['columns'], start=1):
            sheet.column_dimensions[get_column_letter(index)].width = tab.get('widths', [23]*len(tab['columns']))[index-1]
            if 'code' in column or column.endswith('_id'):
                for row in sheet.iter_rows(min_col=index, max_col=index):
                    row[0].number_format = '@'
        sheet.freeze_panes = 'A2'
        sheet.sheet_view.showGridLines = False
        if tab['rows']:
            table = Table(displayName='Territory_' + tab['name'], ref=sheet.dimensions)
            table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2', showRowStripes=True)
            sheet.add_table(table)
    wb.save(output)
    return {'engine': 'openpyxl (artifact runtime unavailable)', 'sheets': [
        {'name': tab['name'], 'rows': len(tab['rows'])} for tab in spec['sheets']]}


def export_review(root, output_dir, documents, territories, result, metadata):
    spec = review_spec(documents, territories, result, metadata)
    output = output_dir / 'revision_territorios.xlsx'
    temporary = output_dir / '.review_spec.json'
    temporary.write_text(json.dumps(spec, ensure_ascii=True), encoding='utf-8')
    node = shutil.which('node')
    try:
        if node:
            command = [node, str(root / 'scripts/render_territory_workbook.mjs'),
                       str(temporary), str(output), str(output_dir / 'qa')]
            completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                       errors='replace', timeout=300, env=os.environ.copy())
            if completed.returncode == 0:
                report = json.loads(Path(str(output)+'.qa.json').read_text(encoding='utf-8'))
                Path(str(output)+'.qa.json').unlink()
                return report
            if completed.returncode != 3 or 'ARTIFACT_RUNTIME_UNAVAILABLE' not in completed.stderr:
                raise RuntimeError('Offline workbook export failed: ' + completed.stderr[-2000:])
        return _fallback(spec, output)
    finally:
        temporary.unlink(missing_ok=True)
