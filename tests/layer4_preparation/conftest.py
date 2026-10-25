from copy import deepcopy
import pytest
from layer4.indicators.assessment import build_indicator_row


@pytest.fixture
def example():
    fields={'title':'Proyecto sintético','keywords':['bosques','territorio'],
        'summary':'Estudio en Colombia.','methodology':'Medición participativa.',
        'objectives':'Conservar bosques y fortalecer capacidades.',
        'expected_results':'Recuperación ecológica verificable.'}
    profile={'indicator_id':'TEST-01','indicator_name':'Indicador de fixture',
        'indicator_category':'TEST','indicator_dimension':None,
        'key_elements':['Conservación','Capacidades','Recuperación','Participación'],
        'preferred_evidence_fields':['objectives','expected_results']}
    assessment={'decision':'SUPPORTED','support_strength':3,
        'supported_key_elements':profile['key_elements'][:3],
        'evidence':[{'field':'objectives','text':'Conservar bosques'},
                    {'field':'expected_results','text':'Recuperación ecológica'}],
        'explanation':'Explicación sintética, no assessment de datos reales.'}
    return deepcopy((fields,profile,assessment))


@pytest.fixture
def metadata():
    return {'output_status':'SYNTHETIC_TEST','project_count':2,'candidate_limit_per_project':2,
        'layer3_run':'SYNTHETIC_FIXTURE','retrieval_indicator_version':'FIXTURE_V1',
        'assessment_indicator_version':'FIXTURE_V2','assessment_indicator_sha256':'a'*64,
        'assessment_engine':'SYNTHETIC_TEST_PROVIDER','assessment_engine_status':'SYNTHETIC_TEST',
        'confidence_version':'RAW_CONFIDENCE_V1','confidence_is_probability':False,
        'territory_version':'PROJECT_TERRITORY_V1','dane_reference_sha256':'b'*64,
        'country_internal_code':'000','country_internal_code_system':'INTERNAL',
        'generated_at':'2026-10-16T12:00:00Z'}


@pytest.fixture
def workbook_fixture(example,metadata):
    fields,profile,assessment=example
    projects=[{'project_id':'SYNTH_P1',**fields},{'project_id':'SYNTH_P2',**fields}]
    indicator=build_indicator_row('SYNTH_P1',fields,profile,assessment,
        engine=metadata['assessment_engine'],engine_status=metadata['assessment_engine_status'])
    territories=[{'project_id':'SYNTH_P1','territory_type':'MUNICIPALITY','territory_code':'05001',
        'territory_name':'Medellín','department_code':'05','department_name':'Antioquia','code_system':'DANE'},
        {'project_id':'SYNTH_P2','territory_type':'COUNTRY','territory_code':'000','territory_name':'Colombia',
         'department_code':None,'department_name':None,'code_system':'INTERNAL'}]
    return projects,[indicator],territories,metadata,{'TEST-01':profile}
