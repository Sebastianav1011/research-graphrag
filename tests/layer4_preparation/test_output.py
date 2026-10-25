from copy import deepcopy
import json
from pathlib import Path
import pytest
from jsonschema import ValidationError
from openpyxl import load_workbook
from layer4.indicators.export import workbook_data,workbook_spec,validate_workbook_data,export_workbook
from layer4.indicators.assessment import AssessmentProvider

ROOT=Path(__file__).resolve().parents[2]


def data(fixture):
    p,i,t,m,profiles=fixture
    return workbook_data(p,i,t,m,profiles=profiles),profiles


def test_exact_workbook_structure(workbook_fixture):
    package,profiles=data(workbook_fixture)
    spec=workbook_spec(package,profiles)
    assert [s['name'] for s in spec['sheets']]==['PROYECTOS','INDICADORES','TERRITORIOS','METADATA']
    assert len(spec['sheets'][0]['rows'])==2 and len(spec['sheets'][1]['rows'])==1
    assert 'retrieval_score' not in spec['sheets'][1]['columns']
    assert json.dumps(package,sort_keys=True)==json.dumps(workbook_data(*workbook_fixture[:4],profiles=profiles),sort_keys=True)


@pytest.mark.parametrize('kind',['master_duplicate','unknown_project','indicator_duplicate','territory_duplicate',
    'unknown_indicator','tampered_confidence','fake_evidence','non_probability','confidence_level','retrieval_column','country_duplicate'])
def test_output_fail_closed(workbook_fixture,kind):
    package,profiles=data(workbook_fixture)
    if kind=='master_duplicate':package['projects'].append(deepcopy(package['projects'][0]))
    if kind=='unknown_project':package['indicators'][0]['project_id']='UNKNOWN'
    if kind=='indicator_duplicate':package['indicators'].append(deepcopy(package['indicators'][0]))
    if kind=='territory_duplicate':package['territories'].append(deepcopy(package['territories'][0]))
    if kind=='unknown_indicator':package['indicators'][0]['indicator_id']='UNKNOWN'
    if kind=='tampered_confidence':package['indicators'][0]['confidence_raw_score']=99
    if kind=='fake_evidence':package['indicators'][0]['evidence_texts'][0]='Frase inexistente'
    if kind=='non_probability':package['indicators'][0]['confidence_probability']=0.99
    if kind=='confidence_level':package['indicators'][0]['confidence_level']='HIGH'
    if kind=='retrieval_column':package['indicators'][0]['retrieval_score']=0.99
    if kind=='country_duplicate':package['territories'][1]['project_id']='SYNTH_P1'
    with pytest.raises((ValueError,ValidationError)):validate_workbook_data(package,profiles)


def test_aligned_evidence_arrays_required(workbook_fixture):
    package,profiles=data(workbook_fixture);package['indicators'][0]['evidence_texts'].pop()
    with pytest.raises(ValueError,match='aligned'):validate_workbook_data(package,profiles)


def test_synthetic_four_sheet_xlsx_only(workbook_fixture,tmp_path):
    package,profiles=data(workbook_fixture)
    target=tmp_path/'synthetic_fixture.xlsx'
    export_workbook(package,profiles,target)
    wb=load_workbook(target,data_only=False)
    try:
        assert wb.sheetnames==['PROYECTOS','INDICADORES','TERRITORIOS','METADATA']
        header=[c.value for c in wb['TERRITORIOS'][1]]
        codes=[row[header.index('territory_code')] for row in wb['TERRITORIOS'].iter_rows(min_row=2)]
        assert [(cell.value,cell.data_type) for cell in codes]==[('05001','s'),('000','s')]
        fields=[c.value for c in wb['INDICADORES'][1]]
        score=wb['INDICADORES'].cell(2,fields.index('confidence_raw_score')+1)
        assert score.value==87.5 and score.number_format=='0.00'
        assert wb['INDICADORES'].cell(2,fields.index('confidence_probability')+1).value is None
        assert wb['PROYECTOS'].max_row==3
        assert all(c.data_type!='f' for s in wb for row in s for c in row)
    finally:wb.close()
    with pytest.raises(FileExistsError):export_workbook(package,profiles,target)


def test_fake_provider_compatible_without_production_implementation(example):
    fields,profile,assessment=example
    class FakeProvider:
        def evaluate(self,project,indicators):
            return [{'indicator_id':i['indicator_id'],'assessment':deepcopy(assessment)} for i in indicators]
    provider:AssessmentProvider=FakeProvider()
    response=provider.evaluate({'project_id':'SYNTH','fields':fields},[profile])
    assert response[0]['indicator_id']=='TEST-01'


def test_prepared_metadata_has_no_selected_projects_or_execution():
    prepared=json.loads((ROOT/'outputs/layer4/auditoria/historicos/preparacion_inicial/prepared_inputs.json').read_text(encoding='utf-8'))
    assert prepared['selected_project_ids']==[] and prepared['assessment_rows_created']==0
    assert prepared['real_workbooks_created']==0 and prepared['provider_implementations']==[]
    assert prepared['metadata']['project_count']==0 and prepared['metadata']['planned_project_count']==20
    assert prepared['metadata']['assessment_engine_status']=='NOT_EXECUTED'
    assert prepared['metadata']['country_internal_code']=='000'
    assert prepared['metadata']['country_internal_code_system']=='INTERNAL'
    assert not prepared['retrieval_executed'] and not prepared['llm_executed'] and not prepared['external_api_used']
