"""Lossless input serialization checks; no model calls or quality claims."""
import json

import pytest

from layer4_evaluation.indicators import global_discovery_v3_3 as base
from layer4_evaluation.indicators import global_discovery_v3_3_compact as compact


@pytest.fixture
def inputs():
    profiles = [dict(indicator_id=f'S{i:02d}', indicator_name='Integrated mechanism',
        indicator_category='TEST', indicator_dimension=None,
        descripcion_ampliada='A specific relationship, including literal spaces.',
        key_elements=['One original criterion.'], favorable_evidence='A documented mechanism.',
        insufficient_evidence='A label without a mechanism.', related_terms='Related concepts.',
        relational_context='Shared decisions.', fuentes_relevantes_original='Project methodology.',
        source_record_json='{"forma_evaluacion":"PRESENCIA"}') for i in range(48)]
    fields = dict.fromkeys(base.historical.FIELDS, None)
    fields['summary'] = 'Literal  double spaces, accents: áéí; quotes "A".\nSecond line.'
    fields['objectives'] = ''
    project = dict(project_id='SYNTHETIC', fields=fields, eligible_candidates=[])
    rules = [dict(id_regla='R',nombre_regla='Rule',descripcion='Do not infer execution.',
        aplicacion='Separate future and present.',ejemplo_ilustrativo='A literal example.')]
    return project, profiles, rules


def test_every_payload_field_and_instruction_is_identical(inputs):
    old, new = base.make_input(*inputs), compact.make_input(*inputs)
    assert new['payload'] == old['payload']
    old_instruction, old_json = old['prompt'].split(compact.DELIMITER,1)
    new_instruction, new_json = new['prompt'].split(compact.DELIMITER,1)
    assert old_instruction == new_instruction
    assert json.loads(old_json) == json.loads(new_json) == old['payload']
    assert len(new['prompt']) < len(old['prompt'])
    assert new['input_version'] == compact.INPUT_VERSION
    assert new['payload']['selection_version'] == base.VERSION
    assert old['input_version'] == base.VERSION


def test_all_48_profiles_and_original_criteria_survive(inputs):
    project, profiles, rules = inputs
    payload = compact.make_input(*inputs)['payload']
    assert payload['catalog_count'] == len(payload['catalog']) == 48
    assert payload['project']['fields'] == project['fields']
    assert len(payload['project']['fields']) == 6
    for old,new in zip(base.make_input(*inputs)['payload']['catalog'],payload['catalog']):
        assert old == new  # No dropped descriptions, criteria, evidence or examples.
        assert new['key_elements'][0] == new['selection_criteria'][0]['criterion_text']


def test_zero_candidates_still_valid_and_no_assessment_dispatch(inputs):
    project, profiles, rules = inputs
    wrapper = dict(project_id=project['project_id'], selection_version=base.VERSION,
        assessments=[dict(indicator_id=base.MARKER,candidates=[],rejected=[
            dict(indicator_id=p['indicator_id'],indicator_category=p['indicator_category'],
                 relevance_class='NO_RELATION',reason='Synthetic empty relation.') for p in profiles])])
    assert base.validate_selection(wrapper,project,profiles)['prioritized_ids'] == []
    assert base.assessment_batches(wrapper,project,profiles) == []
    assert not hasattr(compact,'make_provider')  # Cannot silently activate a runner.


@pytest.mark.parametrize('cap',[1,3,6])
def test_cap_and_deterministic_order_are_preserved(inputs,cap):
    project,profiles,rules = inputs
    request = compact.make_input(project,profiles,rules,max_assessments=cap)
    assert request['payload']['max_assessments'] == cap
    assert request == compact.make_input(project,list(reversed(profiles)),rules,max_assessments=cap)


def test_invalid_catalog_and_seventh_prioritized_limit_not_relaxed(inputs):
    project,profiles,rules = inputs
    with pytest.raises(ValueError):
        compact.make_input(project,profiles[:-1],rules)
    with pytest.raises(ValueError):
        compact.make_input(project,profiles,rules,max_assessments=7)
