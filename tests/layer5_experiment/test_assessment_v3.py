"""V3 rubric and assessment contracts with generic synthetic catalog/project data."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from layer4_evaluation.indicators import assessment_v2 as v2, assessment_v3 as v3
from layer4_evaluation.indicators.selection import canonical_hash


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


@pytest.mark.parametrize('requirement,stage,valid,criterion',[
    ('CONTEXT_ONLY','CONTEXT',True,'Actor relacionado con el proyecto.'),
    ('EXECUTED_ACTIVITY','ACTIVITY_PROPOSED',False,'Talleres realizados.'),
    ('EXECUTED_ACTIVITY','ACTIVITY_EXECUTED',True,'Talleres realizados.'),
    ('DEMONSTRATED_RESULT','RESULT_EXPECTED',False,'Resultado alcanzado.'),
    ('DEMONSTRATED_RESULT','RESULT_DEMONSTRATED',True,'Resultado alcanzado.'),
    ('DEMONSTRATED_RESULT','RESULT_EXPECTED',False,'Impacto atribuible al proyecto.'),
    ('DEMONSTRATED_RESULT','RESULT_DEMONSTRATED',True,'Impacto atribuible al proyecto.'),
    ('DEMONSTRATED_RESULT','DESIGN_DOCUMENTED',False,'Resultado alcanzado.'),
    ('ESTABLISHED_OR_EXECUTED','DESIGN_DOCUMENTED',False,'Mecanismo establecido.'),
    ('EXECUTED_ACTIVITY','MECHANISM_ESTABLISHED',False,'Talleres realizados.')])
def test_temporal_policy_fixed_before_project(case,requirement,stage,valid,criterion):
    profile=case['profile'];profile['key_elements'][0]=criterion
    candidate=case['wrapper']['assessments'][0]['rubrics'][0]
    candidate['profile_sha256']=canonical_hash(profile)
    candidate['criteria'][0]['temporal_requirement']=requirement
    r=v3.validate_rubric_wrapper(case['wrapper'],[profile])[profile['indicator_id']]
    text={
        'CONTEXT':'La asociación Vecinal está vinculada al proyecto.',
        'ACTIVITY_PROPOSED':'El proyecto propone realizar talleres.',
        'ACTIVITY_EXECUTED':'El proyecto realizó tres talleres.',
        'RESULT_EXPECTED':'El proyecto espera mejorar el bienestar.',
        'RESULT_DEMONSTRATED':'El seguimiento documentó una mejora del bienestar atribuible al proyecto.',
        'DESIGN_DOCUMENTED':'El diseño operativo del mecanismo está documentado.',
        'MECHANISM_ESTABLISHED':'El mecanismo de intercambio está establecido.'}[stage]
    case['fields']['methodology']+=' '+text
    a=case['assessment'];a['evidence'].append(dict(field='methodology',text=text,stage=stage))
    a['criterion_assessments'][0]['evidence_indices']=[1]
    score=v3.confidence(case['fields'],profile,a,r)['confidence_raw_score']
    assert (score is not None)==valid


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


@pytest.fixture
def sk_case(case):
    a = case['assessment']
    a['assessment_version'] = v3.SK_VERSION
    a['strength_rubric'] = dict(directness=3, specificity=2, clarity=4, temporal_alignment=3,
        evidence_indices=[0], explanation='Vinculo directo; falta detalle; texto claro; etapa con salvedad.')
    for c in a['criterion_assessments']:
        c['coverage'] = 4 if c['support'] == 'CLEAR' else 0
    return case


@pytest.mark.parametrize('requirement,stage',[
    ('DESIGN_OR_EXECUTION','ACTIVITY_PROPOSED'),('ESTABLISHED_OR_EXECUTED','ACTIVITY_PROPOSED'),
    ('EXECUTED_ACTIVITY','ACTIVITY_PROPOSED'),('DEMONSTRATED_RESULT','RESULT_EXPECTED')])
def test_prospective_sk_accepts_concrete_plans_without_changing_confidence(sk_case,requirement,stage):
    p,r,f,a=[sk_case[k] for k in ('profile','rubric','fields','assessment')]
    for c in r['criteria']:c['temporal_requirement']=requirement
    r['rubric_sha256']=canonical_hash({k:v for k,v in r.items() if k!='rubric_sha256'})
    original=deepcopy(r)
    f['methodology']='El proyecto desarrollara un mecanismo compartido mediante la via A para la comunidad.'
    a['evidence'][0].update(text=f['methodology'],stage=stage)
    assert v3.confidence(f,p,a,r)['confidence_raw_score'] is None
    derived,receipt=v3.catalog_for_mode({p['indicator_id']:p},{p['indicator_id']:r},v3.PROSPECTIVE)
    effective=derived[p['indicator_id']]
    result=v3.confidence(f,p,a,effective)
    assert result['confidence_raw_score']==86.25 and result['support_strength_score']==.75
    assert result['conceptual_coverage']==1 and r==original
    for old,new in zip(r['criteria'],effective['criteria']):
        assert {k:v for k,v in old.items() if k!='temporal_requirement'}=={k:v for k,v in new.items() if k!='temporal_requirement'}
    assert receipt['original_catalog_sha256']!=receipt['effective_catalog_sha256']
    demonstrated,_=v3.catalog_for_mode({p['indicator_id']:p},{p['indicator_id']:r},v3.DEMONSTRATED)
    assert demonstrated[p['indicator_id']]==original
    a['evidence'][0]['stage']='RESULT_DEMONSTRATED'
    assert not v3.validate(f,p,a,r)  # Actual results still work in demonstrated mode.


def test_prospective_vague_intention_and_context_do_not_satisfy_required(sk_case):
    p,r,f,a=[sk_case[k] for k in ('profile','rubric','fields','assessment')]
    r=v3.prospective_rubric(r)
    # Mock semantic judgment: vague intention is partial, never silently promoted.
    a['criterion_assessments'][0].update(support='PARTIAL',coverage=1)
    a['evidence'][0]['stage']='ACTIVITY_PROPOSED'
    assert 'V3_SUPPORTED:REQUIRED_CRITERION_NOT_CLEAR' in v3.validate(f,p,a,r)
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=1)
    result=v3.confidence(f,p,a,r)
    assert result['confidence_status']=='COMPUTED' and result['conceptual_coverage']==.25
    # A contextual citation cannot be relabelled as a planned intervention.
    a.update(decision='SUPPORTED',support_strength=3)
    a['criterion_assessments'][0].update(support='CLEAR',coverage=4)
    a['evidence'][0]['stage']='CONTEXT'
    assert 'V3_SUPPORTED:REQUIRED_CRITERION_NOT_CLEAR' in v3.validate(f,p,a,r)


def test_prospective_context_preserved_and_activity_not_a_result(sk_case):
    p,r,f,a=[sk_case[k] for k in ('profile','rubric','fields','assessment')]
    r['criteria'][0]['temporal_requirement']='CONTEXT_ONLY'
    r['criteria'][1]['temporal_requirement']='DEMONSTRATED_RESULT'
    r['rubric_sha256']=canonical_hash({k:v for k,v in r.items() if k!='rubric_sha256'})
    derived=v3.prospective_rubric(r)
    assert derived['criteria'][0]==r['criteria'][0]
    assert v3.prospective_rubric(derived)==derived
    a['evidence'][0]['stage']='ACTIVITY_PROPOSED'
    assert 'V3_SUPPORTED:ALTERNATIVE_GROUP_NOT_CLEAR' in v3.validate(f,p,a,derived)
    a['evidence'][0]['stage']='RESULT_EXPECTED'
    assert not v3.validate(f,p,a,derived)


def test_sk_formula_uses_only_documented_strength_and_essential_coverage(sk_case):
    p,r,f,a = [sk_case[k] for k in ('profile','rubric','fields','assessment')]
    result = v3.confidence(f,p,a,r)
    assert result['confidence_version'] == v3.SK_CONFIDENCE_VERSION
    assert result['conceptual_coverage_version'] == v3.SK_K_VERSION
    assert result['support_strength_score'] == .75 and result['conceptual_coverage'] == 1
    assert result['confidence_raw_score'] == 86.25
    assert result['confidence_probability'] is None
    Draft202012Validator(v3.schemas(version=v3.SK_VERSION)['confidence_result']).validate(result)
    # The historical anchor no longer makes scores constant for new assessments.
    a['support_strength'] = 3
    a['strength_rubric']['specificity'] = 3
    assert v3.confidence(f,p,a,r)['confidence_raw_score'] == 89.69
    a['strength_rubric']['directness'] = 2
    assert v3.confidence(f,p,a,r)['confidence_raw_score'] == 86.25
    project = dict(project_id='SYNTH_PROJECT', fields=f)
    before = v3.indicator_row(project,p,a,r)
    project.update(vector_score=.9999, semantic_similarity=1)
    assert v3.indicator_row(project,p,a,r) == before


@pytest.mark.parametrize('grade,expected_k', [(0,0),(1,.25),(2,.5),(3,.75)])
def test_sk_required_gate_cannot_be_compensated_by_other_criteria(sk_case,grade,expected_k):
    p,r,f,a = [sk_case[k] for k in ('profile','rubric','fields','assessment')]
    a.update(decision='INSUFFICIENT_EVIDENCE', support_strength=2)
    a['criterion_assessments'][0].update(support='PARTIAL' if grade else 'NOT_DEMONSTRATED',
        coverage=grade,evidence_indices=[0] if grade else [])
    a['criterion_assessments'][3].update(support='CLEAR', coverage=4, evidence_indices=[0])
    result = v3.confidence(f,p,a,r)
    assert result['conceptual_coverage'] == expected_k
    assert result['confidence_raw_score'] == round(100*(.55*.75+.45*expected_k),2)
    a['criterion_assessments'][3].update(support='NOT_DEMONSTRATED', coverage=0, evidence_indices=[])
    assert v3.confidence(f,p,a,r) == result


def test_partial_coverage_mean_preserves_evidence_without_satisfying_required(sk_case):
    p,r,f,a=[sk_case[k] for k in ('profile','rubric','fields','assessment')]
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=2)
    a['criterion_assessments'][0].update(support='NOT_DEMONSTRATED',coverage=0,evidence_indices=[])
    old=v3.confidence(f,p,a,r)
    assert old['conceptual_coverage']==0 and old['support_strength_score']==.75
    a['coverage_policy']=v3.PARTIAL_COVERAGE
    current=v3.confidence(f,p,a,r)
    assert current['conceptual_coverage']==.5 and current['support_strength_score']==.75
    assert current['confidence_raw_score']==63.75
    assert current['conceptual_coverage_version']==v3.PARTIAL_COVERAGE
    a['decision']='SUPPORTED'
    assert 'V3_SUPPORTED:REQUIRED_CRITERION_NOT_CLEAR' in v3.validate(f,p,a,r)


def test_partial_coverage_does_not_force_positive_score_without_evidence(sk_case):
    p,r,f,a=[sk_case[k] for k in ('profile','rubric','fields','assessment')]
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=0,evidence=[],coverage_policy=v3.PARTIAL_COVERAGE)
    for c in a['criterion_assessments']:c.update(support='NOT_DEMONSTRATED',coverage=0,evidence_indices=[])
    a['strength_rubric'].update({key:0 for key in v3.STRENGTH_DIMENSIONS},evidence_indices=[])
    assert v3.confidence(f,p,a,r)['confidence_raw_score']==0


def test_sk_alternatives_use_best_route_without_summing(sk_case):
    p,r,f,a = [sk_case[k] for k in ('profile','rubric','fields','assessment')]
    a.update(decision='INSUFFICIENT_EVIDENCE', support_strength=2)
    a['criterion_assessments'][1].update(support='PARTIAL', coverage=1)
    a['criterion_assessments'][2].update(support='PARTIAL', coverage=3, evidence_indices=[0])
    assert v3.confidence(f,p,a,r)['conceptual_coverage'] == .875


def test_sk_zero_maximum_and_original_state_gates_are_preserved(sk_case):
    p,r,f,a = [sk_case[k] for k in ('profile','rubric','fields','assessment')]
    for key in v3.STRENGTH_DIMENSIONS:
        a['strength_rubric'][key] = 4
    assert v3.confidence(f,p,a,r)['confidence_raw_score'] == 100
    a.update(decision='NOT_SUPPORTED', support_strength=0, evidence=[])
    for c in a['criterion_assessments']:
        c.update(support='NOT_DEMONSTRATED', coverage=0, evidence_indices=[])
    a['strength_rubric'].update({key:0 for key in v3.STRENGTH_DIMENSIONS})
    a['strength_rubric']['evidence_indices'] = []
    assert v3.confidence(f,p,a,r)['confidence_raw_score'] == 0
    # A completed evaluation without support now has the main insufficient state.
    a['decision'] = 'INSUFFICIENT_EVIDENCE'
    result = v3.confidence(f,p,a,r)
    assert result['confidence_status'] == 'COMPUTED' and result['confidence_raw_score'] == 0


@pytest.mark.parametrize('decision', ['NOT_SUPPORTED', 'INSUFFICIENT_EVIDENCE'])
def test_sk_no_support_preserves_raw_alias_and_zero_components(sk_case,decision):
    p,r,f,a = [sk_case[k] for k in ('profile','rubric','fields','assessment')]
    a.update(decision=decision,support_strength=0,evidence=[])
    for c in a['criterion_assessments']:
        c.update(support='NOT_DEMONSTRATED',coverage=0,evidence_indices=[])
    a['strength_rubric'].update({name:0 for name in v3.STRENGTH_DIMENSIONS},evidence_indices=[])
    original=deepcopy(a)
    row=v3.indicator_row(dict(project_id='SYNTH',fields=f),p,a,r)
    assert row['decision']=='INSUFFICIENT_EVIDENCE' and row['assessment_validation_status']=='VALID'
    assert row['confidence_raw_score']==row['conceptual_coverage']==row['support_strength_score']==0
    assert row['confidence_status']=='COMPUTED' and a==original


def test_sk_zero_cannot_hide_positive_criteria(sk_case):
    p,r,f,a = [sk_case[k] for k in ('profile','rubric','fields','assessment')]
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=0)
    a['strength_rubric'].update({name:0 for name in v3.STRENGTH_DIMENSIONS},evidence_indices=[])
    result=v3.confidence(f,p,a,r)
    assert result['confidence_raw_score'] is None
    assert 'SK_ZERO_SUPPORT:CANNOT_CLAIM_POSITIVE_CONCEPTUAL_SUPPORT' in result['validation_errors']


def test_sk_verified_context_does_not_become_positive_support(sk_case):
    p,r,f,a = [sk_case[k] for k in ('profile','rubric','fields','assessment')]
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=0)
    for c in a['criterion_assessments']:c.update(support='NOT_DEMONSTRATED',coverage=0,evidence_indices=[])
    a['strength_rubric'].update({name:0 for name in v3.STRENGTH_DIMENSIONS},evidence_indices=[])
    result=v3.confidence(f,p,a,r)
    assert result['confidence_status']=='COMPUTED' and result['confidence_raw_score']==0
    # A contextual citation is still subject to the literal gate.
    a['evidence'][0]['text']='Inventado.'
    assert v3.confidence(f,p,a,r)['confidence_raw_score'] is None


@pytest.mark.parametrize('strength,grade', [(1,1),(2,2),(2,3)])
def test_sk_weak_and_partial_valid_assessments_receive_confidence(sk_case,strength,grade):
    p,r,f,a = [sk_case[k] for k in ('profile','rubric','fields','assessment')]
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=strength)
    for c in a['criterion_assessments']:
        if c['support']!='NOT_DEMONSTRATED':c.update(support='PARTIAL',coverage=grade)
    result=v3.confidence(f,p,a,r)
    assert result['confidence_status']=='COMPUTED'
    assert result['conceptual_coverage']==grade/4 and result['support_strength_score']==.75
    assert result['confidence_raw_score']==pytest.approx(100*(.55*.75+.45*grade/4))


@pytest.mark.parametrize('mutation', [
    lambda a:a['strength_rubric'].update(directness=5),
    lambda a:a['strength_rubric'].update(directness=True),
    lambda a:a['strength_rubric'].update(specificity=.5),
    lambda a:a['strength_rubric'].update(evidence_indices=[99]),
    lambda a:a['strength_rubric'].update(evidence_indices=[0,0]),
    lambda a:a['strength_rubric'].update(evidence_indices=[]),
    lambda a:a['strength_rubric'].update(explanation=' '),
    lambda a:a['criterion_assessments'][0].update(coverage=3),
    lambda a:a['criterion_assessments'][0].update(explanation=' '),
    lambda a:a['evidence'][0].update(text='Inventado.'),
    lambda a:a['evidence'][0].update(stage='RESULT_EXPECTED'),
    lambda a:a.pop('strength_rubric'),
])
def test_sk_invalid_data_has_null_confidence_and_is_never_repaired(sk_case,mutation):
    p,r,f,a = [sk_case[k] for k in ('profile','rubric','fields','assessment')]
    mutation(a)
    original = deepcopy(a)
    result = v3.confidence(f,p,a,r)
    assert result['confidence_status'] == 'INVALID_ASSESSMENT'
    assert all(result[k] is None for k in ('confidence_raw_score','support_strength_score','conceptual_coverage'))
    assert a == original


def test_sk_version_cannot_silently_reinterpret_legacy_assessment(case):
    p,r,f,a = [case[k] for k in ('profile','rubric','fields','assessment')]
    assert v3.confidence(f,p,a,r)['confidence_version'] == v3.CONFIDENCE_VERSION
    assert v3.confidence(f,p,a,r)['confidence_raw_score'] == 100
    a['assessment_version'] = v3.SK_VERSION
    assert v3.confidence(f,p,a,r)['confidence_raw_score'] is None


@pytest.mark.parametrize('assessment',[None,[],{},False,{'assessment_version':'UNKNOWN'}])
def test_malformed_confidence_input_returns_null_without_imputation(case,assessment):
    result = v3.confidence(case['fields'],case['profile'],assessment,case['rubric'])
    assert result['confidence_status'] == 'INVALID_ASSESSMENT' and result['confidence_raw_score'] is None


def test_sk_decimal_result_is_independent_of_caller_precision(sk_case):
    from decimal import localcontext
    p,r,f,a = [sk_case[k] for k in ('profile','rubric','fields','assessment')]
    expected = v3.confidence(f,p,a,r)
    with localcontext() as context:
        context.prec = 1
        assert v3.confidence(f,p,a,r) == expected
