"""Synthetic relevance declarations; these tests do not measure LLM semantics."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError, Draft202012Validator

from layer4_evaluation.indicators import global_discovery_v3_3 as gd


@pytest.fixture
def case():
    profiles = [dict(indicator_id=f'I{i:02d}', indicator_name='Intercambio documentado',
        indicator_category='CAT', indicator_dimension=None,
        descripcion_ampliada='Mecanismo de intercambio con la comunidad.',
        key_elements=['Mecanismo de intercambio documentado.'],
        source_record_json='{"forma_evaluacion":"PRESENCIA"}') for i in range(48)]
    fields = dict.fromkeys(gd.historical.FIELDS, '')
    fields['summary'] = 'Se estableció un mecanismo comunitario de diálogo.'
    fields['title'] = 'Diálogo'
    project = dict(project_id='SYNTH', fields=fields, eligible_candidates=[
        dict(indicator_id='I00', candidate_id='GRAPH_CANDIDATE', source_id='SYNTH')])
    def response(count, backlog=0):
        candidates = [dict(indicator_id=p['indicator_id'], indicator_category='CAT',
            priority='ASSESS' if i < count else 'BACKLOG', rank=i+1,
            reason='La cita describe un mecanismo de intercambio.',
            relevance_class='DIRECT_EVIDENCE' if i % 2 == 0 else 'PARTIAL_RELEVANT',
            evidence=[dict(field='summary', text=fields['summary'], stage='MECHANISM_ESTABLISHED')],
            criterion_links=[dict(criterion_id='C01', criterion_text=p['key_elements'][0],
                evidence_indices=[0], correspondence='El diálogo establecido corresponde al mecanismo; falta describir sus participantes.')])
            for i,p in enumerate(profiles[:count+backlog])]
        rejected = [dict(indicator_id=p['indicator_id'], indicator_category='CAT',
            relevance_class='NO_RELATION', reason='No se describe relación concreta con este criterio.')
            for p in profiles[count+backlog:]]
        return dict(project_id='SYNTH', selection_version=gd.VERSION,
            assessments=[dict(indicator_id=gd.MARKER, candidates=candidates, rejected=rejected)])
    return project, profiles, response


@pytest.mark.parametrize('count', range(7))
def test_zero_through_six_do_not_fill_budget(case, count):
    project, profiles, response = case
    wrapper = response(count)
    result = gd.validate_selection(wrapper, project, profiles)
    assert len(result['prioritized_ids']) == count
    batches = gd.assessment_batches(wrapper, project, profiles)
    assert [iid for batch in batches for iid in batch] == result['prioritized_ids']
    assert all(len(batch) <= 3 for batch in batches)
    assert not result['semantic_correctness_verified_by_python']
    if count == 0:
        assert batches == []  # GraphRAG's I00 does not force a candidate.


@pytest.mark.parametrize('origin', ['retrieval', 'global'])
@pytest.mark.parametrize('classification', ['THEMATIC_SIMILARITY', 'SPECULATIVE_RELATION', 'NO_RELATION'])
def test_weak_classifications_cannot_reach_assessment_for_either_origin(case, origin, classification):
    project, profiles, response = deepcopy(case)
    if origin == 'global':
        project['eligible_candidates'] = []
    wrapper = response(1)
    wrapper['assessments'][0]['candidates'][0]['relevance_class'] = classification
    with pytest.raises(ValidationError):
        gd.assessment_batches(wrapper, project, profiles)


@pytest.mark.parametrize('classification', ['DIRECT_EVIDENCE', 'PARTIAL_RELEVANT'])
def test_direct_and_partial_accepted_without_confidence_or_supported(case, classification):
    project, profiles, response = case
    wrapper = response(1)
    item = wrapper['assessments'][0]['candidates'][0]
    item['relevance_class'] = classification
    item['evidence'][0]['stage'] = 'ACTIVITY_PROPOSED'
    result = gd.validate_selection(wrapper, project, profiles)
    assert result['candidates'][0]['candidate_source'] == 'LAYER3_RETRIEVAL'
    assert result['candidates'][0]['evidence'][0]['stage'] == 'ACTIVITY_PROPOSED'
    assert result['candidates'][0]['semantic_assessment_status'] == 'NOT_EVALUATED'


@pytest.mark.parametrize('change', [
    lambda x:x.update(relevance_class='THEMATIC_SIMILARITY'),
    lambda x:x.update(criterion_links=[]),
    lambda x:x['criterion_links'][0].update(criterion_id='C99'),
    lambda x:x['criterion_links'][0].update(criterion_text='Otro criterio'),
    lambda x:x['criterion_links'][0].update(evidence_indices=[99]),
    lambda x:x['criterion_links'][0].update(evidence_indices=[True]),
    lambda x:x['criterion_links'][0].update(evidence_indices=[0,0]),
    lambda x:x['criterion_links'][0].update(correspondence='  '),
    lambda x:x['evidence'][0].update(text='Cita inventada'),
    lambda x:x.update(confidence=90),
    lambda x:x.update(decision='SUPPORTED'),
])
def test_invalid_links_and_unsupported_fields_block_assessment(case, change):
    project, profiles, response = case
    wrapper = response(1)
    change(wrapper['assessments'][0]['candidates'][0])
    with pytest.raises((ValueError, ValidationError)):
        gd.assessment_batches(wrapper, project, profiles)


def test_link_must_reference_substantive_quote_not_only_title(case):
    project, profiles, response = case
    wrapper = response(1)
    candidate = wrapper['assessments'][0]['candidates'][0]
    candidate['evidence'].append(dict(field='title', text=project['fields']['title'], stage='CONTEXT'))
    candidate['criterion_links'][0]['evidence_indices'] = [1]
    with pytest.raises(ValueError, match='substantive'):
        gd.validate_selection(wrapper, project, profiles)


def test_all_48_accounted_for_and_backlog_also_requires_relevance(case):
    project, profiles, response = case
    wrapper = response(2, backlog=3)
    result = gd.validate_selection(wrapper, project, profiles)
    assert len(result['prioritized_ids']) == 2 and len(result['backlog_ids']) == 3
    wrapper['assessments'][0]['candidates'][-1]['relevance_class'] = 'SPECULATIVE_RELATION'
    with pytest.raises(ValidationError):
        gd.validate_selection(wrapper, project, profiles)


def test_input_version_no_retrieval_bias_and_no_confidence(case):
    project, profiles, response = case
    request = gd.make_input(project, profiles, [])
    assert request['input_version'] == gd.VERSION
    assert len(request['payload']['catalog']) == 48
    assert all(p['selection_criteria'][0]['criterion_id'] == 'C01' for p in request['payload']['catalog'])
    assert request['payload']['project']['fields'] == project['fields']
    assert 'GRAPH_CANDIDATE' not in request['prompt']
    assert request == gd.make_input(project, list(reversed(profiles)), [])
    Draft202012Validator.check_schema(gd.selection_schema())
    old = gd.historical.make_input(project, profiles, [])
    assert old['input_version'] == 'GLOBAL_DISCOVERY_V3'
    with pytest.raises(ValidationError):
        legacy = response(0); legacy.pop('selection_version')
        gd.validate_selection(legacy, project, profiles)


def test_provider_and_coordinator_handoff_use_only_declared_candidates(case, tmp_path):
    project, profiles, response = case
    schema = tmp_path/'schema.json'
    schema.write_text(json.dumps(gd.selection_schema()), encoding='utf-8')
    invoked = []
    wrapper = response(1)
    def runner(args, **kwargs):
        invoked.append(args)
        payload = json.loads(kwargs['input'].split('INPUT_JSON:\n',1)[1])
        assert payload['selection_version'] == gd.VERSION and len(payload['catalog']) == 48
        Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(wrapper), encoding='utf-8')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    provider = gd.make_provider(tmp_path/'runs', schema, project, profiles, [],
        command=['SYNTHETIC_ONLY'], runner=runner, max_retries=0)
    assert invoked == []
    provider.evaluate(project, [dict(indicator_id=gd.MARKER)])
    assert len(invoked) == 1
    assert gd.assessment_batches(provider.last_output, project, profiles) == [['I00']]
