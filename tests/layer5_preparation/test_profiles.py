from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from openpyxl import Workbook
from layer4_evaluation.indicators.profiles import COLUMNS,SHEET,build_profiles,inspect_catalog,key_elements,load_profiles,preferred_fields

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('raw,expected,method',[
    (None,[],'EMPTY'),('  ',[],'EMPTY'),('[]',[],'JSON_ARRAY'),
    ('["A", "B"]',['A','B'],'JSON_ARRAY'),
    ('- Actor\n- Acción',['Actor','Acción'],'MARKED_LIST'),
    ('Actor; Acción',['Actor','Acción'],'SEMICOLON_LIST'),
    ('Actor identificado. Acción documentada.',['Actor identificado.','Acción documentada.'],'PERIOD_LIST'),
    ('Actor y acción sin delimitación inequívoca',['Actor y acción sin delimitación inequívoca'],'WHOLE_VALUE'),
    ('Valor 2.5. Actor presente.',['Valor 2.5. Actor presente.'],'WHOLE_VALUE'),
    ('Institución S. Actor presente.',['Institución S. Actor presente.'],'WHOLE_VALUE')])
def test_lossless_deterministic_elements(raw,expected,method):
    assert key_elements(raw)==(expected,method)
    assert key_elements(raw)==key_elements(raw)


def test_invalid_key_type_not_invented():
    with pytest.raises(ValueError):key_elements(42)


@pytest.mark.parametrize('raw,expected,status,mapped',[
    ('Objetivos',['objectives'],'MAPPED',['objectives']),
    ('Resultados esperados',['expected_results'],'MAPPED',['expected_results']),
    ('Metodología; Resumen',['methodology','summary'],'MAPPED',['methodology','summary']),
    ('title, keywords y objectives',['title','keywords','objectives'],'MAPPED',['title','keywords','objectives']),
    ('Resumen; informes de ejecución',[],'PARTIALLY_MAPPED',['summary']),
    ('Contexto: resumen. Evidencia: metodología detallada.',[],'UNMAPPED',[]),
    ('Abstracts de artículos',[],'UNMAPPED',[]),
    ('',[],'EMPTY',[]),(None,[],'EMPTY',[])])
def test_preferred_mapping_closed_dictionary(raw,expected,status,mapped):
    assert preferred_fields(raw)==(expected,status,mapped)


def make_catalog(root,*,missing=False,duplicate=False):
    path=root/'data/layer1_sources/reference/indicadores/catalogo_indicadores_v2.xlsx';path.parent.mkdir(parents=True)
    wb=Workbook();sheet=wb.active;sheet.title=SHEET;sheet.append(COLUMNS)
    row=['TEST-01','TEST',None,'Nombre literal','CUALITATIVO','PRESENCIA',None,
        'Descripción literal',None if missing else 'Actor identificado. Acción documentada.',
        'Favorable literal','Insuficiente literal','Términos literales','Contexto literal','Objetivos']
    sheet.append(row)
    if duplicate:sheet.append(row)
    rules=wb.create_sheet('Reglas_generales');rules.append(['id_regla','nombre_regla','descripcion','aplicacion','ejemplo_ilustrativo'])
    rules.append(['R1','Regla','Descripción sin implementación','Guía humana','Ejemplo'])
    wb.save(path)
    return path


def test_profile_publication_determinism_and_originals(tmp_path):
    source=make_catalog(tmp_path)
    rows,manifest=build_profiles(tmp_path)
    assert build_profiles(tmp_path)==(rows,manifest)
    assert load_profiles(tmp_path)==(rows,manifest)
    row=rows[0]
    assert row['source_hash']==hashlib.sha256(source.read_bytes()).hexdigest()
    assert row['source_row']==2 and row['key_elements_original']=='Actor identificado. Acción documentada.'
    assert row['preferred_evidence_fields']==['objectives']
    assert json.loads(row['source_record_json'])['unidad'] is None
    rules=json.loads((tmp_path/'outputs/layer4/indicator_profiles/indicator_assessment_rules.json').read_text(encoding='utf-8'))
    assert rules['rules'][0]['rule_status']=='RULE_TEXT' and not rules['rules'][0]['implemented_rule']
    assert (tmp_path/manifest['source_snapshot']).read_bytes()==source.read_bytes()


def test_missing_key_elements_explicit_and_uncomputable(tmp_path,example):
    make_catalog(tmp_path,missing=True)
    rows,manifest=build_profiles(tmp_path)
    assert rows[0]['key_elements']==[] and rows[0]['key_elements_status']=='MISSING'
    assert manifest['metrics']['indicators_without_key_elements']==1
    from layer4_evaluation.indicators.confidence import calculate_raw_confidence
    fields,_,assessment=example
    assert calculate_raw_confidence(fields,rows[0],assessment)['confidence_status']=='NOT_COMPUTABLE'


def test_duplicate_indicator_ids_fail_closed(tmp_path):
    make_catalog(tmp_path,duplicate=True)
    with pytest.raises(ValueError,match='duplicate'):build_profiles(tmp_path)


def test_profile_tampering_rejected(tmp_path):
    make_catalog(tmp_path);build_profiles(tmp_path)
    path=tmp_path/'outputs/layer4/indicator_profiles/indicator_assessment_rules.json'
    path.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='checksum'):load_profiles(tmp_path)


def test_real_v2_profiles_no_project_assessment():
    rows,rules,mappings,audit=inspect_catalog(ROOT)
    assert len(rows)==48 and len(rules['rules'])==12
    assert audit['indicators_with_key_elements']==48 and audit['indicators_without_key_elements']==0
    assert audit['key_elements_count']=={'min':4,'median':5.0,'max':7}
    assert audit['preferred_field_mapping_counts']=={'MAPPED':0,'PARTIALLY_MAPPED':0,'UNMAPPED':48,'EMPTY':0}
    assert all(p['preferred_evidence_fields']==[] for p in rows)
    assert all(p['key_elements_original']==' '.join(p['key_elements']) for p in rows)
    assert all(p['source_hash']==audit['source_hash'] for p in rows)
    assert all(r['rule_status']=='RULE_TEXT' and not r['implemented_rule'] for r in rules['rules'])
    assert all('project_id' not in p for p in rows)
