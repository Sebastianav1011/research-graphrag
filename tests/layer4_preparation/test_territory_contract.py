from copy import deepcopy
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator,ValidationError
from layer1_data.dane_reference import normalize_name
from layer4.territories.matching import extract_territories
from layer4.territories.contracts import consumption_rows
from layer4.indicators.contracts import load_schema
from layer4.indicators.export import workbook_data

ROOT=Path(__file__).resolve().parents[2]


def dimension():
    rows=[('Colombia','COUNTRY','000',None,None),('Medellín','MUNICIPALITY','05001','05','Antioquia'),
          ('Granada','MUNICIPALITY','05313','05','Antioquia'),('Granada','MUNICIPALITY','50313','50','Meta')]
    return [{'territory_name':name,'normalized_name':normalize_name(name),'territory_type':kind,
             'dane_code':code,'department_code':dept,'department_name':parent,
             'territory_origin':'USER_DEFINED_COUNTRY' if kind=='COUNTRY' else 'DANE'}
             for name,kind,code,dept,parent in rows]


def extract(text):
    return extract_territories([{'document_id':'D','source_id':'SYNTH_P','source_type':'PROJECT'}],
        [{'document_id':'D','section_id':'S','field_name':'summary','text_original':text}],dimension())


def test_country_case_a_no_duplicate_subnational():
    result=extract('Colombia. Medellín.')
    assert [(r['territory_type'],r['dane_code']) for r in result['relationships']]==[('MUNICIPALITY','05001')]
    assert result['national_mentions'][0]['publication_status']=='SUPPRESSED_SPECIFIC_TERRITORY'


def test_country_case_b_explicit_national():
    result=extract('Estudio en Colombia.')
    rows=consumption_rows(result['relationships'],dimension())
    assert rows[0]['territory_code']=='000' and rows[0]['code_system']=='INTERNAL'


def test_country_case_c_never_replaces_ambiguous():
    result=extract('Trabajo en Granada.')
    assert not result['relationships']
    assert result['ambiguous'][0]['dane_code'] is None
    assert result['ambiguous'][0]['candidate_count']==2
    with_country=extract('Colombia. Trabajo en Granada.')
    assert with_country['relationships']==[{'project_id':'SYNTH_P','territory_type':'COUNTRY','dane_code':'000'}]
    assert with_country['ambiguous'][0]['resolution_status']=='AMBIGUOUS'
    assert with_country['ambiguous'][0]['dane_code'] is None


def test_country_case_d_no_territorial_mention():assert not extract('Investigación sin localización.')['relationships']


def test_000_is_never_official_dane():
    row=consumption_rows(extract('Colombia.')['relationships'],dimension())[0]
    row['code_system']='DANE'
    with pytest.raises(ValidationError):Draft202012Validator(load_schema(ROOT,'project_territory')).validate(row)


def test_ambiguous_cannot_enter_consumer_projection():
    with pytest.raises(ValueError,match='AMBIGUOUS'):
        consumption_rows([{'project_id':'SYNTH_P','resolution_status':'AMBIGUOUS','dane_code':None}],dimension())


def test_country_subnational_duplicate_rejected():
    rows=extract('Colombia.')['relationships']+extract('Medellín.')['relationships']
    with pytest.raises(ValueError,match='COUNTRY'):consumption_rows(rows,dimension())


def test_ambiguity_remains_visible_in_metadata(workbook_fixture):
    projects,indicators,territories,metadata,profiles=workbook_fixture
    ambiguous=[{'project_id':'SYNTH_P2','dane_code':None,'resolution_status':'AMBIGUOUS'}]
    before=deepcopy(ambiguous)
    package=workbook_data(projects,indicators,territories,metadata,profiles=profiles,ambiguous_mentions=ambiguous)
    assert package['metadata']['territory_ambiguous_mentions']==1
    assert package['metadata']['territory_ambiguous_projects']==1
    assert ambiguous==before
    assert all(r['territory_code'] is not None for r in package['territories'])
