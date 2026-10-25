"""V3 rubric and assessment contracts with generic synthetic catalog/project data."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from layer4.indicators import assessment_v2 as v2, assessment_v3 as v3
from layer4.indicators.selection import canonical_hash


@pytest.fixture
def case():
    profile=dict(indicator_id='SYNTH_I',indicator_name='Mecanismo con una vía válida.',
        indicator_category='SYNTHETIC',indicator_dimension=None,
        descripcion_ampliada='Existe un mecanismo vigente con una vía de actuación; el detalle administrativo es complementario.',
        key_elements=['Mecanismo','Vía A','Vía B','Detalle administrativo'],preferred_evidence_fields=[],
        favorable_evidence='Diseño operativo documentado o mecanismo establecido.',
        insufficient_evidence='Una intención futura no demuestra un mecanismo existente.',relational_context='Vínculo del mecanismo con el propósito.',
        source_record_json='{"forma_evaluacion":"PRESENCIA"}')
    candidate=dict(indicator_id=profile['indicator_id'],profile_sha256=canonical_hash(profile),
        indicator_evidence_type='MECHANISM_OR_COLLABORATION',
        indicator_type_basis=[dict(profile_field='descripcion_ampliada',text=profile['descripcion_ampliada'])],
        indicator_type_rationale='Naturaleza del mecanismo en este catálogo sintético.',
        criteria=[dict(criterion_id='C'+str(i).zfill(2),role=role,alternative_group=group,
            temporal_requirement='DESIGN_OR_EXECUTION',basis=[dict(profile_field='descripcion_ampliada',
            text=profile['descripcion_ampliada'])],rationale='Propuesta de rol sintética, no revisión humana.')
            for i,role,group in [(1,'REQUIRED',None),(2,'ALTERNATIVE','G1'),(3,'ALTERNATIVE','G1'),(4,'COMPLEMENTARY',None)]])
    wrapper=dict(project_id=v3.CATALOG_ID,assessments=[dict(indicator_id=v3.CATALOG_ID,rubrics=[candidate])])
    rubric=v3.validate_rubric_wrapper(wrapper,[profile])[profile['indicator_id']]
    fields=dict.fromkeys(v2.FIELDS,None)
    fields['methodology']='El diseño vigente integra un mecanismo compartido mediante la vía A.'
    assessment=dict(assessment_version=v3.VERSION,decision='SUPPORTED',support_strength=4,
        criterion_assessments=[dict(criterion_id='C'+str(i).zfill(2),support=support,
            evidence_indices=[0] if support!='NOT_DEMONSTRATED' else [],explanation='Juicio sintético del transporte simulado.')
            for i,support in [(1,'CLEAR'),(2,'CLEAR'),(3,'NOT_DEMONSTRATED'),(4,'NOT_DEMONSTRATED')]],
        evidence=[dict(field='methodology',text=fields['methodology'],stage='DESIGN_DOCUMENTED')],
        explanation='Diseño documentado, sin afirmar ejecución o impacto.')
    return dict(profile=profile,rubric=rubric,wrapper=wrapper,fields=fields,assessment=assessment)


def test_catalog_model_roles_are_frozen_not_assigned_by_python(case):
    r=case['rubric']; p=case['profile']
    assert r['acceptance']=='PENDING_HUMAN_REVIEW'
    assert r['derived_by']=='CODEX_CLI_CATALOG_LEVEL'
    assert v3.check_rubric(p,r)==r
    changed=deepcopy(r); changed['criteria'][0]['role']='COMPLEMENTARY'
    with pytest.raises(ValueError,match='drift'):
        v3.check_rubric(p,changed)
    request=v3.make_rubric_input([p])
    assert 'project' not in request['payload'] and request['project_id']==v3.CATALOG_ID
    assert 'role' not in request['payload']['catalog'][0]['criteria'][0]


@pytest.mark.parametrize('mutation',[
    lambda w:w['assessments'][0]['rubrics'][0].update(profile_sha256='wrong'),
    lambda w:w['assessments'][0]['rubrics'][0]['criteria'].pop(),
    lambda w:w['assessments'][0]['rubrics'][0]['criteria'][0].update(alternative_group='G1'),
    lambda w:w['assessments'][0]['rubrics'][0]['criteria'][1].update(alternative_group=None),
    lambda w:w['assessments'][0]['rubrics'][0]['criteria'][0]['basis'][0].update(text='Un texto no publicado.'),
    lambda w:w['assessments'][0]['rubrics'][0]['criteria'][0]['basis'][0].update(text='   '),
    lambda w:w['assessments'][0]['rubrics'][0]['criteria'][0].update(rationale=' '),
    lambda w:w['assessments'][0]['rubrics'][0].update(indicator_type_rationale=' '),
    lambda w:w['assessments'][0]['rubrics'][0].update(indicator_evidence_type='CAMBIO'),
    lambda w:w['assessments'][0]['rubrics'][0]['criteria'][0].update(basis=[dict(profile_field='key_elements',text='Mecanismo')]),
    lambda w:w['assessments'][0]['rubrics'].append(deepcopy(w['assessments'][0]['rubrics'][0])),
])
def test_catalog_integrity_requires_complete_literal_provenance(case,mutation):
    mutation(case['wrapper'])
    with pytest.raises(Exception):
        v3.validate_rubric_wrapper(case['wrapper'],[case['profile']])


def test_all_complementary_has_no_fabricated_coverage(case):
    for c in case['wrapper']['assessments'][0]['rubrics'][0]['criteria']:
        c.update(role='COMPLEMENTARY',alternative_group=None)
    with pytest.raises(ValueError,match='no essential'):
        v3.validate_rubric_wrapper(case['wrapper'],[case['profile']])


def test_catalog_subsets_exact_for_bounded_transport(case):
    profiles=[]; rubrics=[]
    for i in range(16):
        p=deepcopy(case['profile']); p['indicator_id']='SYNTH_'+str(i)
        r=deepcopy(case['wrapper']['assessments'][0]['rubrics'][0]); r.update(indicator_id=p['indicator_id'],profile_sha256=canonical_hash(p))
        profiles.append(p);rubrics.append(r)
    wrapper=dict(project_id=v3.CATALOG_ID,assessments=[dict(indicator_id=v3.CATALOG_ID,rubrics=rubrics)])
    assert len(v3.validate_rubric_wrapper(wrapper,profiles))==16
    assert len(v3.make_rubric_input(profiles)['payload']['catalog'])==16
    with pytest.raises(ValueError,match='exactly once'):
        v3.validate_rubric_wrapper(wrapper,profiles[:-1])


def test_design_is_not_execution_and_one_alternative_is_enough(case):
    p,r,f,a=[case[k] for k in ('profile','rubric','fields','assessment')]
    assert not v3.validate(f,p,a,r)
    result=v3.confidence(f,p,a,r)
    assert result['conceptual_coverage']==1 and result['confidence_raw_score']==100
    assert result['confidence_probability'] is None
    Draft202012Validator(v3.schemas()['confidence_result']).validate(result)
    assert a['evidence'][0]['stage']=='DESIGN_DOCUMENTED'
    assert a['criterion_assessments'][2]['support']=='NOT_DEMONSTRATED'


def test_partial_and_complementary_do_not_inflate_coverage(case):
    p,r,f,a=[case[k] for k in ('profile','rubric','fields','assessment')]
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=2)
    a['criterion_assessments'][1]['support']='PARTIAL'
    a['criterion_assessments'][3].update(support='CLEAR',evidence_indices=[0])
    result=v3.confidence(f,p,a,r)
    assert result['conceptual_coverage']==.75 and result['confidence_raw_score']==61.25
    a['criterion_assessments'][3].update(support='NOT_DEMONSTRATED',evidence_indices=[])
    assert v3.confidence(f,p,a,r)['confidence_raw_score']==61.25
    a['criterion_assessments'][2].update(support='PARTIAL',evidence_indices=[0])
    assert v3.confidence(f,p,a,r)['conceptual_coverage']==.75  # max, not sum


def test_not_supported_zero_and_invalid_null(case):
    p,r,f,a=[case[k] for k in ('profile','rubric','fields','assessment')]
    a.update(decision='NOT_SUPPORTED',support_strength=0,evidence=[])
    for c in a['criterion_assessments']:
        c.update(support='NOT_DEMONSTRATED',evidence_indices=[])
    assert v3.confidence(f,p,a,r)['confidence_raw_score']==0
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=1)
    result=v3.confidence(f,p,a,r)
    assert result['confidence_raw_score'] is None and result['confidence_status']=='INVALID_ASSESSMENT'


@pytest.mark.parametrize('mutation',[
    lambda a:a['evidence'][0].update(text='Cita inventada.'),
    lambda a:a['evidence'][0].update(stage='ACTIVITY_PROPOSED'),
    lambda a:a['evidence'][0].update(stage='RESULT_EXPECTED'),
    lambda a:a['criterion_assessments'][0].update(support='PARTIAL'),
    lambda a:a['criterion_assessments'][1].update(support='PARTIAL'),
    lambda a:a['criterion_assessments'][0].update(evidence_indices=[0,0]),
    lambda a:a['criterion_assessments'][0].update(evidence_indices=[10]),
    lambda a:a['criterion_assessments'][0].update(required_stage='CONTEXT'),
    lambda a:a.update(confidence=100),
])
def test_invalid_does_not_relabel_or_repair(case,mutation):
    p,r,f,a=[case[k] for k in ('profile','rubric','fields','assessment')]
    mutation(a); original=deepcopy(a)
    assert v3.confidence(f,p,a,r)['confidence_raw_score'] is None
    assert a==original and a['decision']=='SUPPORTED'


@pytest.mark.parametrize('requirement,stage',[
    ('DEMONSTRATED_RESULT','DESIGN_DOCUMENTED'),('DEMONSTRATED_RESULT','ACTIVITY_EXECUTED'),
    ('ESTABLISHED_OR_EXECUTED','DESIGN_DOCUMENTED'),('EXECUTED_ACTIVITY','MECHANISM_ESTABLISHED')])
def test_temporal_policy_fixed_before_project(case,requirement,stage):
    candidate=case['wrapper']['assessments'][0]['rubrics'][0]
    candidate['criteria'][0]['temporal_requirement']=requirement
    r=v3.validate_rubric_wrapper(case['wrapper'],[case['profile']])[case['profile']['indicator_id']]
    case['assessment']['evidence'][0]['stage']=stage
    assert v3.confidence(case['fields'],case['profile'],case['assessment'],r)['confidence_raw_score'] is None


def test_project_input_includes_frozen_rubric_and_all_six_fields(case):
    p,r=case['profile'],case['rubric']
    project=dict(project_id='SYNTH_PROJECT',fields=case['fields'])
    request=v3.make_input(project,[p],[],{p['indicator_id']:r})
    assert request['payload']['project']==project
    assert request['payload']['indicators'][0]['rubric']==r
    assert request['input_version']==v3.VERSION
    row=v3.indicator_row(project,p,case['assessment'],r)
    assert row['assessment_validation_status']=='VALID' and row['assessment_version']=='ASSESSMENT_V3'
    assert row['conceptual_coverage_version']==v3.K_VERSION


def test_schema_transport_subset_and_wrapper_ids(case):
    for schema in v3.schemas().values():
        Draft202012Validator.check_schema(schema)
    assert 'uniqueItems' not in json.dumps(v3.schemas()['assessment_batch'])
    assessment=dict(indicator_id=case['profile']['indicator_id'],**case['assessment'])
    wrapper=dict(project_id='SYNTH_PROJECT',assessments=[assessment])
    v3.validate_wrapper(wrapper,'SYNTH_PROJECT',[case['profile']['indicator_id']])
    with pytest.raises(ValueError):
        v3.validate_wrapper(wrapper,'OTHER',[case['profile']['indicator_id']])


def test_formula_weights_preserved_but_k_version_difference_explicit(case):
    p,r,f,a=[case[k] for k in ('profile','rubric','fields','assessment')]
    a['evidence'][0]['stage']='ACTIVITY_EXECUTED'
    historical=deepcopy(a);historical['assessment_version']=v2.VERSION
    for c in historical['criterion_assessments']:
        c['required_stage']='ACTIVITY_EXECUTED'
    assert v2.confidence(f,p,historical)['confidence_raw_score']==77.5
    assert v3.confidence(f,p,a,r)['confidence_raw_score']==100
    # This proves changed K operationalization, not semantic quality superiority.


def test_versioned_schema_files_match_contract_authority():
    v3.write_contracts(Path(__file__).resolve().parents[2],check=True)


def test_schema_drift_is_detected_without_rewriting(tmp_path):
    v3.write_contracts(tmp_path)
    path=tmp_path/'schemas/layer4_assessment_v3/assessment.schema.json'
    value=json.loads(path.read_text(encoding='utf-8'))
    value['properties']['assessment_version']['const']='ASSESSMENT_V2'
    path.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValueError,match='schema drift'):
        v3.write_contracts(tmp_path,check=True)
    assert json.loads(path.read_text(encoding='utf-8'))['properties']['assessment_version']['const']=='ASSESSMENT_V2'
