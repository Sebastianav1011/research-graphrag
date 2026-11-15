"""Closure regressions: local fixtures and existing pilot only, no inference."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts import pilot_prospective_v2 as pilot
from layer4_evaluation import live_execution as live
from layer4_evaluation.indicators import prospective_v2 as p2, assessment_v3 as v3
from layer4_evaluation.indicators import context_budget as cb, evidence_references as refs
from tests.test_prospective_v2 import prospective, case, make_na


def transport_case(x, revision=None):
    request = cb.make_request(dict(project_id='P', fields=x['fields']), x['profile'], x['rubric'], x['fields'],
        evidence_references=True, assessment_version=p2.VERSION, evaluation_mode=p2.MODE,
        prompt_version=revision or p2.PROMPT)
    a = deepcopy(x['assessment'])
    a.pop('coverage_policy'); a.pop('evidence')
    for c in [*a['criterion_assessments'], a['strength_rubric'], a['applicability']]:
        c['evidence_refs'] = [dict(fragment_id='F000', stage='ACTIVITY_PROPOSED') for _ in c.pop('evidence_indices')]
    wrapper = dict(project_id='P', assessments=[dict(indicator_id=x['profile']['indicator_id'], **a)])
    return request, wrapper, refs.response_schema(request, x['fields'])


@pytest.mark.parametrize('status,basis,decision,valid', [
    ('APPLICABLE','RELEVANT_SCOPE','SUPPORTED',True),
    ('APPLICABLE','RELEVANT_SCOPE','INSUFFICIENT_EVIDENCE',True),
    ('APPLICABLE','RELEVANT_SCOPE','NOT_APPLICABLE',False),
    ('UNDETERMINED','UNKNOWN','INSUFFICIENT_EVIDENCE',True),
    ('UNDETERMINED','UNKNOWN','NOT_APPLICABLE',False),
    ('UNDETERMINED','UNKNOWN','SUPPORTED',False),
    ('UNDETERMINED','RELEVANT_SCOPE','INSUFFICIENT_EVIDENCE',False),
])
def test_decoding_schema_rejects_incoherent_combinations(prospective,status,basis,decision,valid):
    _, wrapper, schema = transport_case(prospective, p2.PROMPT_V3)
    a = wrapper['assessments'][0]
    a['applicability'].update(status=status, basis=basis)
    a['decision'] = decision
    assert Draft202012Validator(schema).is_valid(wrapper) == valid


def test_documented_na_branch_retains_zero_support_and_scope_gates(prospective):
    _, wrapper, schema = transport_case(make_na(prospective), p2.PROMPT_V3)
    validator = Draft202012Validator(schema)
    assert validator.is_valid(wrapper)
    a = wrapper['assessments'][0]
    a['support_strength'] = 2
    assert not validator.is_valid(wrapper)
    a['support_strength'] = 0
    a['applicability']['evidence_refs'] = []
    assert not validator.is_valid(wrapper)


def test_previous_prompt_schemas_remain_independent(prospective):
    for revision in (p2.PROMPT_V1, p2.PROMPT_V2):
        request, _, schema = transport_case(prospective, revision)
        assert 'applicability_protocol' not in request
        assert 'anyOf' not in schema['properties']['assessments']['items']


def test_existing_positive_still_valid_without_repeating_inference():
    directory = pilot.ROOT/'outputs/pilotos/prospective_v2_tec04_r2'
    plan = json.loads((directory/'evaluation'/pilot.BATCH/'plan.json').read_text(encoding='utf-8'))
    data = json.loads((directory/'resultados/evaluaciones_validas.json').read_text(encoding='utf-8'))
    row = next(r for r in data['assessments'] if r['siap_id'] == '21869')
    project = next(p for p in plan['projects'] if p['siap_id'] == '21869')
    assessment = live.assessment_from_row(row)
    assert not v3.validate(project['fields'], plan['profiles']['TEC-04'], assessment, plan['rubrics']['TEC-04'])
    assert v3.confidence(project['fields'], plan['profiles']['TEC-04'], assessment,
        plan['rubrics']['TEC-04'])['confidence_raw_score'] == row['confidence_raw_score'] == 100
    assert row['decision'] == 'SUPPORTED'


def test_closure_is_only_negative_with_two_calls_and_no_client(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, 'checked_output', lambda p: Path(p).resolve())
    monkeypatch.setattr(live, 'OllamaClient', lambda *a, **k: pytest.fail('No inference during preparation'))
    monkeypatch.setattr(live, 'BASE', tmp_path)
    plan = pilot.prepare_closure(tmp_path/'closure')
    assert [p['siap_id'] for p in plan['projects']] == ['21844']
    assert plan['maximum_calls'] == 2
    pilot.validate_scope(plan)
    plan['projects'][0]['siap_id'] = '21869'
    with pytest.raises(ValueError):
        pilot.validate_scope(plan)
