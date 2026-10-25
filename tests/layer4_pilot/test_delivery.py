"""Synthetic presentation tests; never invokes Codex or territorial detection."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from layer4.indicators.preliminary_output import indicator_row

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('pilot_delivery',ROOT/'scripts/export_layer4_pilot.py')
delivery=importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


@pytest.fixture
def example():
    fields={'title':'Proyecto sintético','keywords':'bosque','summary':'Conservar bosques.',
            'objectives':'Participación comunitaria.','methodology':'','expected_results':''}
    project={'project_id':'SYNTH_P1','siap_id':'00042','fields':fields,
             'field_provenance':{k:{'section_id':'SYNTH_SEC_'+k} for k in fields},
             'candidates':[{'indicator_id':'SYNTH_I1'}]}
    profile={'indicator_id':'SYNTH_I1','indicator_name':'Indicador sintético','indicator_category':'TEST',
             'indicator_dimension':None,'key_elements':['Conservación','Participación','Recuperación','Seguimiento'],
             'preferred_evidence_fields':[]}
    assessment={'decision':'SUPPORTED','support_strength':3,'supported_key_elements':profile['key_elements'][:3],
                'evidence':[{'field':'summary','text':'Conservar bosques.'},
                            {'field':'objectives','text':'Participación comunitaria.'}],
                'explanation':'Explicación sintética para probar la presentación sin inventar resultados reales.'}
    row=indicator_row(project,profile,assessment)
    record={'project_id':project['project_id'],'status':'VALID','rows':[row],
            'wrapper':{'project_id':project['project_id'],'assessments':[{'indicator_id':profile['indicator_id'],**assessment}]}}
    return project,profile,assessment,record


def test_explanation_quotes_fields_and_offsets_preserved(example):
    project,profile,assessment,record=example
    original=deepcopy(record)
    rows,audit=delivery.indicator_projection([project],{profile['indicator_id']:profile},{project['project_id']:record})
    assert list(rows[0])==delivery.COLUMNS and rows[0]['siap_id']=='00042'
    assert rows[0]['confianza']==87.50
    assert assessment['explanation'] in rows[0]['parrafo_evidencia']
    assert all(e['text'] in rows[0]['parrafo_evidencia'] for e in assessment['evidence'])
    assert 'summary (Resumen)' in rows[0]['fuente_evidencia']
    assert 'Resumen; caracteres [0,18)' in rows[0]['ubicacion_evidencia']
    assert 'texto original' in rows[0]['ubicacion_evidencia']
    assert audit[0]['locations'][0]['section_id']=='SYNTH_SEC_summary'
    assert all(e['match_valid'] for e in audit[0]['locations'])
    assert record==original


def test_invalid_decision_not_published(example):
    project,profile,assessment,record=example
    assessment['evidence'][0]['text']='Cita inexistente.'
    record['rows']=[indicator_row(project,profile,assessment)]
    record['wrapper']['assessments']=[{'indicator_id':profile['indicator_id'],**assessment}]
    rows,audit=delivery.indicator_projection([project],{profile['indicator_id']:profile},{project['project_id']:record})
    assert rows==audit==[]


def test_non_supported_keeps_explanation_and_nulls(example):
    project,profile,assessment,record=example
    assessment.update(decision='NOT_SUPPORTED',support_strength=0,supported_key_elements=[],evidence=[])
    record['rows']=[indicator_row(project,profile,assessment)]
    record['wrapper']['assessments']=[{'indicator_id':profile['indicator_id'],**assessment}]
    rows,_=delivery.indicator_projection([project],{profile['indicator_id']:profile},{project['project_id']:record})
    assert rows[0]['confianza'] is rows[0]['fuente_evidencia'] is rows[0]['ubicacion_evidencia'] is None
    assert rows[0]['parrafo_evidencia']==assessment['explanation']


def test_territories_survive_pending_llm_and_counts_differ(example):
    project,profile,assessment,record=example
    territories=[{'siap_id':'00042','territory_type':'MUNICIPALITY','territory_code':'05001'},
                 {'siap_id':'00042','territory_type':'DEPARTMENT','territory_code':'05'}]
    result=delivery.statistics([project],{},territories,[])
    assert result['assessments_expected']==1 and result['assessments_returned']==0
    assert result['projects_with_resolved_territory']==1 and result['territory_relationships']==2
    assert result['confidence_min'] is result['confidence_mean'] is result['confidence_max'] is None
    assert result['decisions']==dict.fromkeys(('SUPPORTED','INSUFFICIENT_EVIDENCE','NOT_SUPPORTED'),0)


def test_summary_counts_project_and_confidence_correctly(example):
    project,profile,assessment,record=example
    rows,_=delivery.indicator_projection([project],{profile['indicator_id']:profile},{project['project_id']:record})
    stats=delivery.statistics([project],{project['project_id']:record},[],[{'project_id':project['project_id'],'retry':0}])
    text=delivery.summary_markdown([project],stats,rows,[],[],[],'Prueba sintética')
    assert '87.50 / 87.50 / 87.50' in text and 'no es probabilidad' in text
    assert '0 MUNICIPALITY, 0 DEPARTMENT y 0 COUNTRY' in text
    assert len(text.split())<=1000


def test_real_pilot_ids_and_budget_cannot_be_changed():
    selected=[{'project_id':pid,'candidates':[{}]*(1 if i in (0,3) else 2)} for i,pid in enumerate(delivery.EXPECTED_IDS)]
    assert len(delivery.pilot_projects(selected,{'pilot_project_count':5,'project_count':50},{'assessments_requested':77}))==5
    selected[0]['project_id']='SYNTH_CHANGED'
    with pytest.raises(ValueError,match='exact 5/8'):delivery.pilot_projects(selected,{'pilot_project_count':5,'project_count':50},{'assessments_requested':77})


def test_two_sheet_artifact_export_preserves_string_codes(example,tmp_path):
    project,profile,assessment,record=example
    rows,_=delivery.indicator_projection([project],{profile['indicator_id']:profile},{project['project_id']:record})
    territories=[{'siap_id':'00042','territory_type':'COUNTRY','territory_code':'000','territory_name':'Colombia',
                  'department_code':None,'department_name':None,'code_system':'INTERNAL'}]
    workbook={'sheets':[delivery.sheet('RESULTADO_INDICADORES',delivery.COLUMNS,rows),
                        delivery.sheet('TERRITORIOS',delivery.TERRITORY_COLUMNS,territories)]}
    qa=delivery.export_delivery_spec(ROOT,workbook,tmp_path/'synthetic_pilot.xlsx')
    assert qa['sheet_rows']=={'RESULTADO_INDICADORES':1,'TERRITORIOS':1} and qa['all_values_preserved']
