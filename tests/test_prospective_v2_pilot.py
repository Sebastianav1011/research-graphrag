"""Deterministic pilot/audit checks. Never start Ollama or execute real pairs."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import pilot_prospective_v2 as pilot
from layer4_evaluation.indicators import assessment_v3 as v3, prospective_v2 as p2
from layer4_evaluation.indicators import context_budget as cb
from layer4_evaluation import live_execution as live
from tests.test_prospective_v2 import prospective, case, make_na, confidence, errors


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    if not pilot.REFERENCE.exists():pytest.skip('Explicit reference run unavailable')
    old_base = live.BASE
    monkeypatch.setattr(pilot, 'checked_output', lambda p: Path(p).resolve())
    # Fail immediately if preparation attempts any provider/network interaction.
    monkeypatch.setattr(live, 'OllamaClient', lambda *a, **kw: pytest.fail('No Ollama during preparation'))
    destination = tmp_path / 'pilot'
    plan = pilot.prepare(destination)
    yield destination, plan
    live.BASE = old_base


def test_offline_preparation_seals_exact_two_pairs_without_inference(prepared):
    destination, plan = prepared
    pilot.validate_scope(plan)
    assert plan['maximum_calls'] == 4
    assert plan['pilot']['knowledge_ref']['version_id'] == pilot.KNOWLEDGE_ID
    assert not list(destination.rglob('provider.json'))
    assert not list(destination.rglob('authorization.json'))
    assert not list(destination.rglob('dispatch.claim.json'))
    assert not list(destination.rglob('native_response.json'))
    assert 'sin ejecutar' in (destination / 'comparacion.md').read_text(encoding='utf-8')
    for p in plan['projects']:
        request = plan['context_requests'][p['project_id']]['TEC-04']
        assert request['evaluation_mode'] == 'PROSPECTIVE_V2'
        assert request['context_mode'] == 'BASE_RETRIEVED_GRAPH_V1'
        assert request['context_budget']['fits']
        assert request['assessment_version'] == p2.VERSION
        assert 'El uso de tecnolog' not in request['prompt']  # Historical execution rationale absent.
    state = live.verify_run(destination / 'evaluation' / pilot.BATCH)
    assert state['new_calls'] == 0
    assert all(s['selected'] == ['TEC-04'] and not s['rows'] for s in state['projects'])


def test_preparation_is_idempotent_and_does_not_replace_sealed_files(prepared):
    destination, _ = prepared
    before = {p.relative_to(destination): p.read_bytes() for p in destination.rglob('*') if p.is_file()}
    pilot.prepare(destination)
    assert before == {p.relative_to(destination): p.read_bytes() for p in destination.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mutation', [
    lambda p:p.update(indicator_selection=['TEC-04', 'TEC-05']),
    lambda p:p['projects'].append(deepcopy(p['projects'][0])),
    lambda p:p.update(maximum_calls=6),
    lambda p:p['pilot']['knowledge_ref'].update(version_id='another-version'),
    lambda p:p['evaluation_policy'].update(evaluation_mode='PROSPECTIVE_V1'),
])
def test_scope_change_is_rejected_before_dispatch(prepared, mutation):
    _, plan = prepared
    mutation(plan)
    with pytest.raises(ValueError, match='alterados'):pilot.validate_scope(plan)


def test_report_without_calls_does_not_invent_semantic_decisions(prepared):
    destination, _ = prepared
    result = pilot.report(destination, execution_error='Synthetic metadata-only failure')
    assert result['native_calls'] == 0
    assert all(c['new'] is None and c['technical_status'] == 'PENDING' for c in result['comparisons'])
    assert all(c['documentary_correctness'] == 'PENDING_HUMAN_REVIEW' for c in result['comparisons'])
    states = json.loads((destination/'resultados/estado_indicadores.json').read_text(encoding='utf-8'))
    assert all(i['decision'] is None and i['confidence'] is None for i in states['indicators'])


def test_high_confidence_does_not_replace_an_incomplete_essential(prospective):
    x = prospective
    a = x['assessment']
    a.update(decision='INSUFFICIENT_EVIDENCE', support_strength=2)
    a['criterion_assessments'][0].update(support='PARTIAL', coverage=3,
        explanation='El mecanismo esta previsto; falta documentar una condicion esencial de su diseno.')
    a['strength_rubric'].update(dict.fromkeys(v3.STRENGTH_DIMENSIONS, 4))
    assert not errors(x)
    result = confidence(x)
    assert result['confidence_raw_score'] == 94.38
    assert a['decision'] == 'INSUFFICIENT_EVIDENCE'
    a.update(decision='SUPPORTED', support_strength=3)
    assert 'V3_SUPPORTED:REQUIRED_CRITERION_NOT_CLEAR' in errors(x)


def test_na_is_independent_of_a_compliance_score(prospective):
    x = make_na(prospective)
    assert not errors(x)
    assert confidence(x)['confidence_raw_score'] is None
    x['assessment']['applicability']['evidence_indices'] = []
    assert errors(x)


def test_all_48_prompts_have_no_global_execution_requirement():
    source = pilot.REFERENCE/'evaluation/batch_162fbf47e55a989c/plan.json'
    if not source.exists():pytest.skip('Explicit reference run unavailable')
    plan = json.loads(source.read_text(encoding='utf-8'))
    derived, _ = v3.catalog_for_mode(plan['profiles'], plan['rubrics'], p2.MODE)
    for iid, rubric in derived.items():
        fields = dict.fromkeys(v3.FIELDS, '')
        request = cb.make_request(dict(project_id='SYNTHETIC', fields=fields), plan['profiles'][iid], rubric, fields,
            evidence_references=True, assessment_version=p2.VERSION, evaluation_mode=p2.MODE, prompt_version=p2.PROMPT_CONCISE_V4)
        prompt = request['prompt']
        assert v3.SK_TEMPORAL_SCALE not in prompt and v3.DEMONSTRATED_STAGE_LINE not in prompt
        assert 'No exijas ejecucion, adopcion o impacto ya ocurrido.' in prompt
        assert all(c['temporal_requirement'] not in v3.PROSPECTIVE_TEMPORAL for c in rubric['criteria'])
        if iid not in p2.LIMITATIONS:
            assert request['payload']['indicators'][0]['prospective_limitation'] is None


def test_changed_decision_is_not_reported_as_automatically_correct(prospective):
    a = prospective['assessment']
    old = dict(decision='INSUFFICIENT_EVIDENCE', confidence_raw_score=80,
        criterion_assessments=deepcopy(a['criterion_assessments']))
    new = dict(old, decision='SUPPORTED', confidence_raw_score=96.56)
    result = pilot.compare(old, new, prospective['rubric'])
    assert result['documentary_correctness'] == 'PENDING_HUMAN_REVIEW'
    assert result['interpretation'].startswith('CAMBIO_DE_JUICIO')


def test_no_generic_cli_command_executes_the_pilot(monkeypatch, tmp_path):
    monkeypatch.setattr(pilot, 'checked_output', lambda p: Path(p))
    monkeypatch.setattr(pilot, 'prepare', lambda *a: {'prepared': True})
    monkeypatch.setattr(pilot, 'execute', lambda *a: pytest.fail('No inference on prepare'))
    assert pilot.main(['prepare', '--output', str(tmp_path)]) == 0


def test_prompt_revision_preserves_original_and_versions_contract_clarification(prospective):
    x = prospective
    project = dict(project_id='SYNTHETIC', fields=x['fields'])
    requests = [cb.make_request(project, x['profile'], x['rubric'], x['fields'],
        evidence_references=True, assessment_version=p2.VERSION, evaluation_mode=p2.MODE,
        prompt_version=version) for version in p2.PROMPTS]
    assert requests[0]['payload'] == requests[1]['payload']
    assert p2.CONTRACT_CLARIFICATION not in requests[0]['prompt']
    assert p2.CONTRACT_CLARIFICATION in requests[1]['prompt']
    assert p2.instructions_for(p2.PROMPT_V1) == p2.INSTRUCTIONS_V1
    policy = v3.evaluation_policy('prospective-v2', 'retrieved-graph', base=True)
    assert policy['instructions_version'] == p2.PROMPT
    assert not errors(x)  # Same assessment and unchanged gates/scoring.


def test_unsupported_with_refs_is_invalid_but_unknown_scope_is_not_na(prospective):
    x = make_na(prospective)
    a = x['assessment']
    a.update(decision='INSUFFICIENT_EVIDENCE')
    a['applicability'].update(status='UNDETERMINED', basis='UNKNOWN',
        evidence_indices=[], explanation='No hay respaldo suficiente para establecer pertinencia ni exclusion.')
    assert not errors(x)
    assert confidence(x)['confidence_raw_score'] == 0
    a['criterion_assessments'][0]['evidence_indices'] = [0]
    assert 'V3_CRITERION:UNSUPPORTED_CANNOT_CLAIM_EVIDENCE' in errors(x)
