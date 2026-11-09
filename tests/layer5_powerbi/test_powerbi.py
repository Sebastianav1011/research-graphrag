from copy import deepcopy
import pytest
from layer4_evaluation.indicators.powerbi import COLUMNS,consumption_rows
from layer4_evaluation.indicators.powerbi import TERRITORY_COLUMNS,territory_rows,territorial_workbook_bytes


@pytest.fixture
def row():
    return {'project_id':'PROJ_INTERNAL','indicator_id':'IND-01','decision':'SUPPORTED',
        'assessment_validation_status':'VALID','validation_errors':[],
        'evidence_source_fields':['summary','objectives'],
        'evidence_texts':['Cita original con acentos.','Otra cita\ncon salto.'],
        'confidence_raw_score':87.5,'confidence_status':'COMPUTED','confidence_version':'RAW_CONFIDENCE_V1',
        'confidence_probability':None,'confidence_level':None,'retrieval_score':.99}


def test_exact_columns_original_id_all_quotes(row):
    result=consumption_rows([row],{'PROJ_INTERNAL':'00042'})[0]
    assert list(result)==COLUMNS and result['siap_id']=='00042'
    assert result['confianza']==87.5 and result['estado_cumplimiento']=='SUPPORTED'
    assert all(t in result['parrafo_evidencia'] for t in row['evidence_texts'])
    assert result['ubicacion_evidencia']=='[1] Resumen\n[2] Objetivos'
    assert result['fuente_evidencia']=='SIAP'


@pytest.mark.parametrize('decision',['INSUFFICIENT_EVIDENCE','NOT_SUPPORTED'])
def test_no_invented_zero_confidence_or_evidence(row,decision):
    row.update(decision=decision,confidence_status='NOT_APPLICABLE',confidence_raw_score=None,
               evidence_source_fields=[],evidence_texts=[])
    result=consumption_rows([row],{'PROJ_INTERNAL':'42'})[0]
    assert result['confianza'] is None
    assert all(result[c] is None for c in ('parrafo_evidencia','fuente_evidencia','ubicacion_evidencia'))


@pytest.mark.parametrize('case',['missing_id','duplicate','invalid','unaligned','unknown_field','bad_score','probability'])
def test_consumer_fail_closed(row,case):
    rows=[row];mapping={'PROJ_INTERNAL':'42'}
    if case=='missing_id':mapping={}
    if case=='duplicate':rows.append(deepcopy(row))
    if case=='invalid':row['assessment_validation_status']='INVALID_ASSESSMENT'
    if case=='unaligned':row['evidence_texts'].pop()
    if case=='unknown_field':row['evidence_source_fields'][0]='invented'
    if case=='bad_score':row['decision']='NOT_SUPPORTED'
    if case=='probability':row['confidence_probability']=.87
    with pytest.raises(ValueError):consumption_rows(rows,mapping)


def test_projection_does_not_mutate_or_recompute(row):
    original=deepcopy(row)
    first=consumption_rows([row],{'PROJ_INTERNAL':'42'})
    row['retrieval_score']=0
    assert first==consumption_rows([row],{'PROJ_INTERNAL':'42'})
    row['retrieval_score']=original['retrieval_score']
    assert row==original


@pytest.fixture
def territories():
    relationships=[{'project_id':'P1','territory_type':'MUNICIPALITY','dane_code':'05001'},
                   {'project_id':'P2','territory_type':'DEPARTMENT','dane_code':'05'},
                   {'project_id':'P3','territory_type':'COUNTRY','dane_code':'000'}]
    dimension=[{'territory_type':'MUNICIPALITY','dane_code':'05001','territory_name':'MEDELLÍN',
                'department_code':'05','department_name':'ANTIOQUIA'},
               {'territory_type':'DEPARTMENT','dane_code':'05','territory_name':'ANTIOQUIA',
                'department_code':'05','department_name':'ANTIOQUIA'},
               {'territory_type':'COUNTRY','dane_code':'000','territory_name':'Colombia',
                'department_code':None,'department_name':None,'territory_origin':'USER_DEFINED_COUNTRY'}]
    return relationships,dimension,{'P1':'00001','P2':'00002','P3':'00003','P4':'00004'}


def test_territorial_projection_exact_columns_and_all_published(territories):
    rows=territory_rows(*territories)
    assert len(rows)==3 and all(list(r)==TERRITORY_COLUMNS for r in rows)
    assert {r['siap_id'] for r in rows}=={'00001','00002','00003'}
    assert all(isinstance(r['territory_code'],str) for r in rows)
    assert all(r['department_code'] is None or isinstance(r['department_code'],str) for r in rows)
    assert {r['territory_code'] for r in rows}=={'05001','05','000'}
    country=next(r for r in rows if r['territory_type']=='COUNTRY')
    assert country['code_system']=='INTERNAL' and country['territory_code']=='000'
    assert country['department_code'] is None
    assert all(r['code_system']=='DANE' for r in rows if r['territory_type']!='COUNTRY')


def test_territorial_ambiguous_never_exported(territories):
    relationships,dimension,mapping=territories
    relationships[0]['resolution_status']='AMBIGUOUS'
    with pytest.raises(ValueError,match='AMBIGUOUS'):territory_rows(relationships,dimension,mapping)


def test_territorial_no_duplicate_country_or_relationship(territories):
    relationships,dimension,mapping=territories
    relationships.append(deepcopy(relationships[0]))
    with pytest.raises(ValueError,match='Duplicate'):territory_rows(relationships,dimension,mapping)


def test_in_memory_two_sheet_repair_preserves_indicators_and_csv_equivalence(territories):
    import csv
    from io import BytesIO,StringIO
    from pathlib import Path
    import zipfile
    from contextlib import closing
    from openpyxl import load_workbook
    root=Path(__file__).resolve().parents[2]
    from layer4_evaluation.paths import resolve
    folder=resolve(root, root/'outputs/layer4/powerbi_preliminary_20')
    files_before={p.name for p in folder.iterdir()}
    original=(folder/'resultado_indicadores_powerbi.xlsx').read_bytes()
    indicator_csv=(folder/'resultado_indicadores_powerbi.csv').read_bytes()
    rows=territory_rows(*territories)
    result=territorial_workbook_bytes(original,rows)
    with closing(load_workbook(BytesIO(original))) as before,closing(load_workbook(BytesIO(result))) as after:
        assert after.sheetnames==['RESULTADO_INDICADORES','TERRITORIOS']
        assert list(before['RESULTADO_INDICADORES'].values)==list(after['RESULTADO_INDICADORES'].values)
        assert list(next(after['RESULTADO_INDICADORES'].values))==COLUMNS
        assert after['RESULTADO_INDICADORES'].max_row==32
        sheet=after['TERRITORIOS']
        assert list(next(sheet.values))==TERRITORY_COLUMNS
        assert all(sheet.cell(i,3).data_type=='s' for i in range(2,5))
        assert all(sheet.cell(i,5).value is None or sheet.cell(i,5).data_type=='s' for i in range(2,5))
        text=StringIO(newline='');writer=csv.DictWriter(text,fieldnames=TERRITORY_COLUMNS)
        writer.writeheader();writer.writerows(rows)
        parsed=list(csv.DictReader(StringIO(text.getvalue())))
        assert parsed==[dict(zip(TERRITORY_COLUMNS,['' if v is None else v for v in values])) for values in list(sheet.values)[1:]]
    with zipfile.ZipFile(BytesIO(original)) as before,zipfile.ZipFile(BytesIO(result)) as after:
        for name in ('xl/worksheets/sheet1.xml','xl/tables/table1.xml','xl/sharedStrings.xml','xl/styles.xml'):
            assert before.read(name)==after.read(name)
    # A repeated correction updates the second sheet, without duplicating it.
    with closing(load_workbook(BytesIO(territorial_workbook_bytes(result,rows)))) as repeat:
        assert repeat.sheetnames==['RESULTADO_INDICADORES','TERRITORIOS']
    assert {p.name for p in folder.iterdir()}==files_before
    assert (folder/'resultado_indicadores_powerbi.xlsx').read_bytes()==original
    assert (folder/'resultado_indicadores_powerbi.csv').read_bytes()==indicator_csv
