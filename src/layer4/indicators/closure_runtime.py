"""Verify frozen machine results and mutable human opinions without rebasing hashes."""
from collections import Counter
import json
from pathlib import Path
import statistics

from . import experiment
from .experiment_inputs import read, sha256, verify_hashes

REVIEW_FILE = 'reviews/revision_humana_v2.xlsx'


def check_source_display(actual, expected):
    """Excel may trim display-cell edges; canonical text/coordinates stay frozen."""
    actual, expected = Counter(map(tuple,actual)), Counter(map(tuple,expected))
    if actual == expected:
        return 0
    def display(row):
        if len(row)!=5 or (row[3] is not None and not isinstance(row[3],str)):
            raise ValueError('Invalid source display row')
        return (*row[:3],row[3].strip() if row[3] else row[3],row[4])
    if Counter({}) == expected and actual:
        raise ValueError('Unexpected source display')
    a = Counter(); b = Counter()
    for row,n in actual.items():a[display(row)]+=n
    for row,n in expected.items():b[display(row)]+=n
    if a != b:
        raise ValueError('Original project text changed in the human workbook')
    return sum((actual-expected).values())


def human_opinions(rows, expected):
    """Validate unaltered machine columns; grades express agreement, never labels."""
    found = set(); opinions = []
    for values in rows:
        if not any(value is not None for value in values):
            continue
        if len(values) != 8:
            raise ValueError('Human workbook must use the eight-column review layout')
        siap, title, indicator, source_link, decision, explanation, grade, notes = values
        if not isinstance(indicator, str) or ' — ' not in indicator:
            raise ValueError('Missing indicator identity in review')
        key = siap, indicator.split(' — ', 1)[0]
        if key in found or key not in expected:
            raise ValueError('Duplicate or unassessed human-review pair')
        found.add(key)
        if list(values[:6]) != expected[key]:
            raise ValueError('Machine content changed in human review: ' + str(key))
        if grade is not None and (type(grade) is not int or not 1 <= grade <= 5):
            raise ValueError('Agreement must be a whole number from 1 to 5 or NULL')
        if notes is not None and not isinstance(notes, str):
            raise ValueError('Human notes must be text or NULL')
        opinions.append({'siap_id': siap, 'indicator_id': key[1], 'codex_decision': decision,
                         'agreement_1_to_5': grade, 'notes': notes})
    if found != set(expected):
        raise ValueError('Human workbook does not match the assessed pairs')
    grades = [r['agreement_1_to_5'] for r in opinions if r['agreement_1_to_5'] is not None]
    return {'status': 'OPINIONS_RECORDED' if grades else 'PENDING_HUMAN_OPINIONS',
            'opinions': opinions, 'rated_pairs': len(grades), 'assessed_pairs': len(expected),
            'mean_agreement': statistics.mean(grades) if grades else None,
            'median_agreement': statistics.median(grades) if grades else None,
            'grade_distribution': dict(Counter(str(v) for v in grades)),
            'low_agreement_pairs': [r for r in opinions if r['agreement_1_to_5'] in (1, 2)],
            'semantic_human_labels': None, 'academic_acceptance': False,
            'independent_review_verified': False, 'classification_metrics': None}


def inspect_review(out, selected, profiles, rows, expected_hash):
    """Read the reviewed workbook without editing it or its registered checksum."""
    import openpyxl
    from .assessment_v2 import rubric
    path = Path(out) / REVIEW_FILE
    if not path.exists():
        raise ValueError('Current human-review workbook is missing')
    actual_hash = sha256(path)
    book = openpyxl.load_workbook(path, read_only=False, data_only=False)
    try:
        expected = {}
        projects = {p['project_id']: p for p in selected}
        for row in rows:
            p, iid = projects[row['project_id']], row['indicator_id']
            profile = profiles[iid]
            expected[p['siap_id'], iid] = [p['siap_id'], p['title'],
                f"{iid} — {profile['indicator_name']}\n\nQué evalúa: {profile['descripcion_ampliada']}",
                'Leer texto completo', row['decision'], row['evidence_explanation']]
        main = book['ETIQUETADO']
        if main.max_column != 8:
            raise ValueError('Expected the current simplified human-review workbook')
        result = human_opinions(list(main.values)[1:], expected)
        field_names = {'title': 'Título', 'keywords': 'Palabras clave', 'summary': 'Resumen',
                       'methodology': 'Metodología', 'objectives': 'Objetivos',
                       'expected_results': 'Resultados esperados'}
        source_rows = []
        for p in selected:
            for field in ('title','keywords','summary','methodology','objectives','expected_results'):
                text = p['fields'][field] or ''
                for start in range(0, max(1, len(text)), 800):
                    fragment = text[start:start+800] or None
                    section = p['field_provenance'].get(field, {}).get('section_id')
                    location = (f'{field}; {section}; caracteres [{start},{start+len(fragment or "")})'
                                if fragment else f'{field}; campo sin texto en la fuente')
                    source_rows.append((p['siap_id'], p['title'], field_names[field], fragment, location))
        actual_sources = [tuple(r) for r in list(book['FUENTES'].values)[1:]]
        display_whitespace_rows=check_source_display(actual_sources,source_rows)
        diagnostic_sheet = list(book['DIAGNOSTICOS'].values)
        diagnostics = [dict(zip(diagnostic_sheet[0], v)) for v in diagnostic_sheet[1:]]
        by_pair = {(r['project_id'], r['indicator_id']): r for r in rows}
        if len(diagnostics) != len(rows):
            raise ValueError('Diagnostic rows changed in the human workbook')
        seen = set()
        for value in diagnostics:
            key = value['project_id'], value['indicator_id']
            if key in seen or key not in by_pair:
                raise ValueError('Diagnostic identity mismatch')
            seen.add(key); r = by_pair[key]
            expected_values = {'decision': r['decision'], 'strength': r['support_strength'],
                'coverage': r['conceptual_coverage'], 'confidence_v1': r.get('v1_comparison_score'),
                'confidence_v2': r['confidence_raw_score'], 'explanation': r['evidence_explanation'],
                'quotes': '\n\n'.join(r['evidence_texts']) or None}
            if any(value[k] != v for k,v in expected_values.items()):
                raise ValueError('Machine diagnostics changed in the human workbook')
            if json.loads(value['criteria']) != r['criterion_assessments']:
                raise ValueError('Criterion judgements changed in the human workbook')
        criterion_sheet = list(book['CRITERIOS'].values)
        expected_criteria = {}
        for iid in {c['indicator_id'] for p in selected for c in p['candidates']}:
            profile = profiles[iid]
            for c in rubric(profile)['criteria']:
                expected_criteria[iid,c['criterion_id']] = (c['criterion'], c['weight'],
                    profile['descripcion_ampliada'], profile['favorable_evidence'], profile['insufficient_evidence'])
        actual_criteria = {}
        for values in criterion_sheet[1:]:
            value = dict(zip(criterion_sheet[0], values)); key = value['indicator_id'], value['criterion_id']
            if key in actual_criteria:
                raise ValueError('Duplicate review criterion')
            actual_criteria[key] = tuple(value[k] for k in ('criterion','weight','definition','favorable_evidence','insufficient_evidence'))
        if actual_criteria != expected_criteria:
            raise ValueError('Published rubric changed in the human workbook')
        for index in range(2, main.max_row+1):
            link = main.cell(index,4).hyperlink
            if not link or not link.location or not link.location.startswith("'FUENTES'!A"):
                raise ValueError('Missing/invalid internal source hyperlink')
            source_index = int(link.location.rsplit('!A',1)[1])
            if book['FUENTES'].cell(source_index,1).value != main.cell(index,1).value:
                raise ValueError('Human-review link points to another project')
        result.update(workbook=str(path), registered_workbook_sha256=expected_hash,
                      current_workbook_sha256=actual_hash,
                      artifact_hash_status='MATCH' if actual_hash==expected_hash else 'HUMAN_INPUT_CHANGED_MACHINE_CONTENT_VERIFIED',
                      original_text_and_machine_content='PASS', registered_hash_rewritten=False,
                      source_display_edge_whitespace_differences=display_whitespace_rows,
                      source_coordinates_refer_to='CANONICAL_ORIGINAL_SELECTION_TEXT_NOT_TRIMMED_DISPLAY')
        return result
    finally:
        book.close()


def verify_current(root, config_path='config/layer4_final.yaml'):
    """Frozen pipeline validation plus a separate, explicit mutable human input."""
    import pyarrow.parquet as pq
    root = Path(root).resolve()
    verified = experiment.verify_prepared(root, config_path)
    config, out, manifest, data, selected, requests, runtime = verified
    verify_hashes(out, {k:v for k,v in manifest.get('result_hashes',{}).items() if k != REVIEW_FILE})
    records = {f.stem:read(f) for f in (out/'records').glob('*.json')}
    if set(records)-{p['project_id'] for p in selected}:
        raise ValueError('Unselected project in records')
    request_map = {r['project_id']:r for r in requests}; rows = []
    for p in selected:
        if p['project_id'] in records:
            rows.extend(experiment.validate_record(records[p['project_id']],p,data['profiles'],manifest,
                                                   request_map[p['project_id']],out)['rows'])
    if rows != experiment.read_jsonl(out/'technical_results.jsonl'):
        raise ValueError('Original Codex responses and technical results differ')
    if rows != pq.read_table(out/'project_indicator_diagnostics.parquet').to_pylist():
        raise ValueError('Technical parquet differs from original assessments')
    review = inspect_review(out,selected,data['profiles'],rows,manifest['result_hashes'][REVIEW_FILE])
    verification = {'status':'PASS','verification_scope':'IMMUTABLE_MACHINE_ARTIFACTS_AND_MUTABLE_HUMAN_OPINIONS',
        'selected_projects':len(selected),'processed_projects':len(records),'valid_assessments':sum(r['assessment_validation_status']=='VALID' for r in rows),
        'invalid_assessments':sum(r['assessment_validation_status']!='VALID' for r in rows),
        'requested_assessments':manifest['assessments_requested'],'protected_files':len(read(out/'protected_inputs.json')),
        'decisions':dict(Counter(r['decision'] for r in rows)),
        'human_artifact_status':review['artifact_hash_status'],'academic_acceptance':False,
        'real_execution_complete':len(records)==len(selected) and all(r['status']=='VALID' for r in records.values())}
    return {'verified':verified,'verification':verification,'human_review':review}
