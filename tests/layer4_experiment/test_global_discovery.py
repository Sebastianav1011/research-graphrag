from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError, Draft202012Validator

from layer4.indicators import global_discovery as gd


@pytest.fixture
def case():
    profiles = [dict(indicator_id=f'I{i:02d}', indicator_name='Concepto ' + str(i),
        indicator_category='CAT' + str(i % 4), indicator_dimension=None,
        descripcion_ampliada='Definición publicada completa', key_elements=['Criterio conceptual'],
        source_record_json=json.dumps({'forma_evaluacion': 'PRESENCIA'})) for i in range(48)]
    fields = dict.fromkeys(gd.FIELDS, '')
    fields['summary'] = 'Se estableció un mecanismo comunitario de diálogo.'
    project = dict(project_id='SYNTH_P', fields=fields,
        field_provenance={'summary': {'section_id': 'SYNTH_SECTION'}},
        eligible_candidates=[dict(indicator_id='I00', candidate_id='SYNTH_CANDIDATE')])
    candidates = [dict(indicator_id=p['indicator_id'], indicator_category=p['indicator_category'],
        priority='ASSESS' if i < 6 else 'BACKLOG', rank=i+1,
        reason='La evidencia del mecanismo corresponde conceptualmente a la definición.',
        evidence=[dict(field='summary', text=fields['summary'], stage='ACTIVITY_EXECUTED')])
        for i, p in enumerate(profiles[:8])]
    rejected = [dict(indicator_id=p['indicator_id'], indicator_category=p['indicator_category'],
                      reason='El proyecto no documenta el concepto del perfil para priorizar su evaluación.') for p in profiles[8:]]
    wrapper = dict(project_id=project['project_id'], assessments=[dict(indicator_id=gd.MARKER,
                    candidates=candidates, rejected=rejected)])
    return project, profiles, wrapper


def test_global_input_has_all_48_six_fields_and_no_retrieval_bias(case):
    project, profiles, wrapper = case
    request = gd.make_input(project, profiles, [{'id_regla': 'RULE', 'descripcion': 'Texto orientativo'}])
    assert request['payload']['project']['fields'] == project['fields']
    assert len(request['payload']['catalog']) == 48
    assert request['payload']['transport'] == dict(envelope_count=1, marker=gd.MARKER,
                                                  marker_is_indicator=False, profiles_in_prompt=48)
    assert 'eligible_candidates' not in request['prompt']
    assert 'hybrid_retrieval_score' not in request['prompt']
    assert 'SYNTH_CANDIDATE' not in request['prompt']
    assert gd.make_input(project, list(reversed(profiles)), [])['prompt'] == gd.make_input(project, profiles, [])['prompt']


def test_complete_catalog_has_6_prioritized_and_untruncated_backlog(case):
    project, profiles, wrapper = case
    result = gd.validate_selection(wrapper, project, profiles)
    assert result['prioritized_ids'] == [f'I{i:02d}' for i in range(6)]
    assert result['backlog_ids'] == ['I06', 'I07']
    assert result['candidates'][0]['candidate_source'] == 'LAYER3_RETRIEVAL'
    assert result['candidates'][1]['candidate_source'] == 'LAYER4_GLOBAL_DISCOVERY'
    assert result['candidates'][0]['evidence_locations'][0]['match_valid']
    assert result['profiles_considered'] == 48 and not result['compliance_decided']
    assert all(c['semantic_assessment_status'] == 'NOT_EVALUATED' for c in result['candidates'])


def test_zero_candidates_is_valid_and_does_not_force_supported(case):
    project, profiles, wrapper = case
    wrapper['assessments'][0]['candidates'] = []
    wrapper['assessments'][0]['rejected'] = [dict(indicator_id=p['indicator_id'],
        indicator_category=p['indicator_category'], reason='Sin evidencia sustantiva.') for p in profiles]
    result = gd.validate_selection(wrapper, project, profiles)
    assert result['prioritized_ids'] == result['backlog_ids'] == []


@pytest.mark.parametrize('change', [
    lambda w: w.update(project_id='OTHER'),
    lambda w: w['assessments'][0].update(indicator_id='I00'),
    lambda w: w['assessments'][0]['rejected'].pop(),
    lambda w: w['assessments'][0]['rejected'][0].update(indicator_id='I00'),
    lambda w: w['assessments'][0]['rejected'][0].update(indicator_id='UNKNOWN'),
    lambda w: w['assessments'][0]['candidates'][0].update(indicator_category='OTHER'),
    lambda w: w['assessments'][0]['candidates'][0].update(reason='   '),
    lambda w: w['assessments'][0]['candidates'][0].update(rank=3),
    lambda w: w['assessments'][0]['candidates'][0].update(rank=True),
    lambda w: w['assessments'][0]['candidates'][0].update(priority='BACKLOG'),
    lambda w: w['assessments'][0]['candidates'][6].update(priority='ASSESS'),
    lambda w: w['assessments'][0]['candidates'][0].update(decision='SUPPORTED'),
    lambda w: w['assessments'][0]['candidates'][0]['evidence'][0].update(text='Cita inventada'),
    lambda w: w['assessments'][0]['candidates'][0]['evidence'][0].update(field='title'),
    lambda w: w['assessments'][0]['candidates'][0]['evidence'][0].update(stage='IMPACT_CONFIRMED'),
])
def test_invalid_discovery_rejected_without_semantic_reclassification(case, change):
    project, profiles, wrapper = case
    change(wrapper)
    with pytest.raises((ValueError, ValidationError)):
        gd.validate_selection(wrapper, project, profiles)


@pytest.mark.parametrize('change', [
    lambda ps: ps.pop(),
    lambda ps: ps.append(deepcopy(ps[0])),
    lambda ps: ps[0].update(rule_status='RULE_TEXT'),
    lambda ps: ps[0].update(enabled=False),
    lambda ps: ps[0].update(source_record_json='{}'),
])
def test_wrong_or_disabled_catalog_not_silently_treated_as_48(case, change):
    project, profiles, wrapper = case
    change(profiles)
    with pytest.raises(ValueError):
        gd.make_input(project, profiles, [])


def test_same_category_is_not_selection_evidence(case):
    project, profiles, wrapper = case
    wrapper['assessments'][0]['candidates'][0]['evidence'] = []
    with pytest.raises(ValidationError):
        gd.validate_selection(wrapper, project, profiles)


def test_literal_nfc_whitespace_tolerance_keeps_coordinate_system(case):
    project, profiles, wrapper = case
    wrapper['assessments'][0]['candidates'][0]['evidence'][0]['text'] = project['fields']['summary'].replace(' ', '\n  ')
    result = gd.validate_selection(wrapper, project, profiles)
    assert result['candidates'][0]['evidence_locations'][0]['coordinate_system'].startswith('NFC_whitespace_collapsed')


@pytest.mark.parametrize('stage', ['DESIGN_DOCUMENTED', 'MECHANISM_ESTABLISHED', 'RESULT_EXPECTED', 'ACTIVITY_PROPOSED'])
def test_v3_discovery_preserves_design_or_proposal_stage_without_deciding_compliance(case, stage):
    project, profiles, wrapper = case
    wrapper['assessments'][0]['candidates'][0]['evidence'][0]['stage'] = stage
    result = gd.validate_selection(wrapper, project, profiles)
    assert result['candidates'][0]['evidence'][0]['stage'] == stage
    assert result['candidates'][0]['semantic_assessment_status'] == 'NOT_EVALUATED'


def test_existing_provider_uses_one_envelope_and_validates_all_48(case, tmp_path):
    project, profiles, wrapper = case
    schema = tmp_path / 'schema.json'
    schema.write_text(json.dumps(gd.selection_schema()), encoding='utf-8')
    Draft202012Validator.check_schema(gd.selection_schema())
    calls = []
    def runner(args, **kwargs):
        calls.append(kwargs['input'])
        assert len(json.loads(kwargs['input'].split('INPUT_JSON:\n')[1])['catalog']) == 48
        response = Path(args[args.index('--output-last-message') + 1])
        response.write_text(json.dumps(wrapper), encoding='utf-8')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    provider = gd.make_provider(tmp_path / 'calls', schema, project, profiles, [],
        command=['SYNTHETIC_NOT_EXECUTED'], runner=runner, max_retries=0)
    assert calls == []
    values = provider.evaluate(project, [{'indicator_id': gd.MARKER}])
    assert len(calls) == len(values) == 1
    assert values[0]['indicator_id'] == gd.MARKER
    assert len(values[0]['assessment']['candidates']) + len(values[0]['assessment']['rejected']) == 48


def test_all_48_can_be_plausible_without_discarding_backlog(case):
    project, profiles, wrapper = case
    template = wrapper['assessments'][0]['candidates'][0]
    wrapper['assessments'][0]['candidates'] = [{**deepcopy(template), 'indicator_id': p['indicator_id'],
        'indicator_category': p['indicator_category'], 'rank': i+1,
        'priority': 'ASSESS' if i < 6 else 'BACKLOG'} for i, p in enumerate(profiles)]
    wrapper['assessments'][0]['rejected'] = []
    result = gd.validate_selection(wrapper, project, profiles)
    assert len(result['backlog_ids']) == 42
