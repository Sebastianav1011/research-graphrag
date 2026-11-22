"""Minimal checks for the independent diagnostic recommendations (C1-C3, C5-C9).

Offline and deterministic: no Ollama, API, retrieval or Knowledge access.
"""
from copy import deepcopy
from decimal import Decimal

import pytest
from jsonschema import Draft202012Validator

from layer4_evaluation.indicators import assessment_v3 as v3, prospective_v2 as p2
from layer4_evaluation.indicators import context_budget as cb, evidence_references as refs
from layer4_evaluation.indicators import ollama_provider as transport, retry_review, semantic_verification as sv
from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError
from tests.layer5_experiment.test_assessment_v3 import case  # noqa: F401  (fixture)
from tests.test_prospective_v2 import prospective  # noqa: F401  (fixture)

SETTINGS = dict(num_ctx=16384, num_predict=4096, context_margin_tokens=1024)


def v5(x, title='Proyecto sintetico de mecanismos'):
    fields = dict(x['fields'], title=title)
    request = cb.make_request(dict(project_id='P', fields=fields), x['profile'], x['rubric'], fields,
        evidence_references=True, assessment_version=p2.VERSION, evaluation_mode=p2.MODE, prompt_version=p2.PROMPT)
    return fields, request, refs.response_schema(request, fields)


def selection(request, supports, stage='ACTIVITY_PROPOSED', claimed=False, dims=(4, 3, 4, 4)):
    fid = next(f['fragment_id'] for f in request['payload']['project']['fragments'] if f['field'] == 'methodology')
    criteria = []
    for c in request['payload']['indicators'][0]['rubric']['criteria']:
        support = supports.get(c['criterion_id'], 'NOT_DEMONSTRATED')
        criteria.append(dict(criterion_id=c['criterion_id'], explanation='Conclusion sintetica del criterio.',
            support=support, coverage=dict(CLEAR=4, PARTIAL=2, NOT_DEMONSTRATED=0)[support],
            evidence_refs=[] if support == 'NOT_DEMONSTRATED' else [dict(fragment_id=fid, stage=stage)]))
    scope = (dict(explanation='Frase que delimita un alcance incompatible.', claimed=True, basis='EXPLICIT_EXCLUSION',
                  evidence_refs=[dict(fragment_id=fid, stage='CONTEXT')]) if claimed else
             dict(explanation='No se reclama exclusion de alcance.', claimed=False, basis='NONE', evidence_refs=[]))
    item = dict(indicator_id=request['payload']['indicators'][0]['indicator_id'], assessment_version=p2.VERSION,
        criterion_assessments=criteria, scope_exclusion=scope,
        strength_rubric=dict(explanation='Valoracion sintetica.', **dict(zip(v3.STRENGTH_DIMENSIONS, dims))))
    return dict(project_id='P', assessments=[item])


def resolve(x, fields, request, wrapper):
    w = refs.materialize(request, wrapper)
    item = {k: v for k, v in w['assessments'][0].items() if k != 'indicator_id'}
    return p2.resolve_decision(fields, x['profile'], item, x['rubric'])[0]


SUPPORTED = {'C01': 'CLEAR', 'C02': 'CLEAR'}


def test_v5_is_the_default_policy_and_sends_catalog_meaning(prospective):
    assert v3.evaluation_policy(base=True)['instructions_version'] == p2.PROMPT
    fields, request, schema = v5(prospective)
    indicator = request['payload']['indicators'][0]
    assert request['component_protocol'] == p2.DERIVED_PROTOCOL
    assert indicator['insufficient_evidence'] == prospective['profile']['insufficient_evidence']
    assert 'favorable_evidence' not in indicator
    for criterion in indicator['rubric']['criteria']:
        assert 'rationale' not in criterion  # generic text replaced by literal catalog basis
        assert criterion['referencias_catalogo'] == [prospective['profile']['descripcion_ampliada']]
        assert criterion['etapa_admitida'] == p2.STAGE_MEANING[criterion['temporal_requirement']]
    assert v3.SK_TEMPORAL_SCALE not in request['prompt'] and 'segun las reglas anteriores' not in request['prompt']
    item = schema['properties']['assessments']['items']['properties']
    assert set(item) == {'indicator_id', 'assessment_version', 'criterion_assessments', 'strength_rubric', 'scope_exclusion'}


def test_derived_fields_follow_model_judgments(prospective):
    fields, request, schema = v5(prospective)
    wrapper = selection(request, SUPPORTED)
    Draft202012Validator(schema).validate(wrapper)
    item = refs.materialize(request, wrapper)['assessments'][0]
    assert [c['support'] for c in item['criterion_assessments']] == ['CLEAR', 'CLEAR', 'NOT_DEMONSTRATED', 'NOT_DEMONSTRATED']
    assert [c['evidence_relation'] for c in item['criterion_assessments']] == [
        'PROJECT_CONTRIBUTION', 'PROJECT_CONTRIBUTION', 'NO_SUPPORT', 'NO_SUPPORT']
    assert item['strength_rubric']['evidence_indices'] == [0]
    assert item['applicability'] == dict(status='APPLICABLE', basis='RELEVANT_SCOPE',
        explanation='No se reclama exclusion de alcance.', evidence_indices=[0])
    assert (item['decision'], item['support_strength']) == ('SUPPORTED', 3)
    assert resolve(prospective, fields, request, wrapper)['decision'] == 'SUPPORTED'
    # Without positive criteria: S dimensions are 0 by definition, IE, undetermined scope.
    empty = refs.materialize(request, selection(request, {}))['assessments'][0]
    assert (empty['decision'], empty['support_strength'], empty['applicability']['status']) == (
        'INSUFFICIENT_EVIDENCE', 0, 'UNDETERMINED')
    assert all(empty['strength_rubric'][d] == 0 for d in v3.STRENGTH_DIMENSIONS)


def test_irrelevant_or_orientation_citation_is_not_substantive(prospective):
    fields, request, schema = v5(prospective)
    assert all(f['field'] not in p2.ORIENTATION_FIELDS for f in request['payload']['project']['fragments'])
    # A CONTEXT-stage citation for an action criterion is not relabelled by Python: still rejected.
    with pytest.raises(AssessmentValidationError) as error:
        resolve(prospective, fields, request, selection(request, SUPPORTED, stage='CONTEXT'))
    assert 'P2_CRITERION:CONTEXT_ONLY_REFERENCES' in {i['rule'] for i in error.value.issues}
    # Positive criteria with all S dimensions 0 remain a semantic contradiction, not repaired.
    with pytest.raises(AssessmentValidationError):
        resolve(prospective, fields, request, selection(request, SUPPORTED, dims=(0, 0, 0, 0)))
    # Title evidence never supports a criterion, even if injected.
    item = refs.materialize(request, selection(request, {}))['assessments'][0]
    raw = dict(item, scope_exclusion=dict(explanation='x', claimed=False, basis='NONE', evidence_indices=[]),
               evidence=[dict(field='title', text=fields['title'], stage='CONTEXT')])
    raw['criterion_assessments'][0].update(support='PARTIAL', coverage=2, evidence_indices=[0])
    with pytest.raises(AssessmentValidationError, match='ORIENTATION_FIELD_NOT_CITABLE'):
        p2.derive_components(raw, request['payload']['indicators'][0]['rubric']['criteria'])


def test_not_applicable_is_distinct_from_insufficient_evidence(prospective):
    fields, request, _ = v5(prospective)
    assert resolve(prospective, fields, request, selection(request, {}))['decision'] == 'INSUFFICIENT_EVIDENCE'
    na = resolve(prospective, fields, request, selection(request, {}, claimed=True))
    assert (na['decision'], na['applicability']['status']) == ('NOT_APPLICABLE', 'NOT_APPLICABLE')
    with pytest.raises(AssessmentValidationError) as error:  # exclusion claimed with positive support
        resolve(prospective, fields, request, selection(request, SUPPORTED, claimed=True))
    assert 'P2_APPLICABILITY:NOT_A_SUPPORT_ASSESSMENT' in {i['rule'] for i in error.value.issues}


def test_retry_is_localized_and_keeps_unflagged_criteria(prospective):
    fields, request, schema = v5(prospective)
    baseline = selection(request, SUPPORTED)
    baseline['assessments'][0]['criterion_assessments'][1]['evidence_refs'][0]['stage'] = 'CONTEXT'  # C02 invalid
    with pytest.raises(AssessmentValidationError) as error:
        resolve(prospective, fields, request, baseline)
    issues = retry_review.diagnostic_details(error.value.issues, baseline, request)
    assert {(i['rule'], i.get('criterion_id')) for i in issues} >= {('P2_CRITERION:CONTEXT_ONLY_REFERENCES', 'C02')}
    assert transport.correction_scope(baseline, issues) == ['C02']
    revised = transport.corrective_request(request, schema, SETTINGS, issues, baseline, transport.P2_TARGETED_VERSION)
    tail = revised['prompt'].split('CORRECCION_LOCALIZADA_V1:', 1)[1]
    assert 'Criterio C02' in tail and 'Tu juicio anterior' in tail and 'Criterio C01' not in tail
    correction = selection(request, {'C02': 'CLEAR'})  # fixes C02 but drifts C01 to ND
    def validator(materialized):  # same contract as the provider: resolve an already materialized wrapper
        item = {k: v for k, v in materialized['assessments'][0].items() if k != 'indicator_id'}
        p2.resolve_decision(fields, prospective['profile'], item, prospective['rubric'])
    merged, provenance = transport.merged_attempt(baseline, ['C02'], False, correction, request, validator)
    supports = {c['criterion_id']: c['support'] for c in merged['assessments'][0]['criterion_assessments']}
    assert supports['C01'] == 'CLEAR' and provenance['criteria_origin']['C01'] == 'first_judgment'
    assert merged['assessments'][0]['evidence'][0]['stage'] == 'ACTIVITY_PROPOSED'
    accepted = transport.merged_selection(baseline, ['C02'], False, correction, provenance)
    assert accepted['assessments'][0]['criterion_assessments'][0]['support'] == 'CLEAR'


def test_unjustified_promotion_stays_blocked(prospective):
    fields, request, schema = v5(prospective)
    baseline = selection(request, {'C01': 'CLEAR'})
    baseline['assessments'][0]['criterion_assessments'][1].update(support='NOT_DEMONSTRATED', coverage=0,
        evidence_refs=list(baseline['assessments'][0]['criterion_assessments'][0]['evidence_refs']))  # C02 ND with refs
    promoted = selection(request, SUPPORTED)  # C02 ND -> CLEAR in the correction
    with pytest.raises(AssessmentValidationError, match='FLAGGED_CRITERION_INCREASED'):
        transport.merged_attempt(baseline, ['C02'], False, promoted, request, lambda w: None)
    # Withdrawing a claimed exclusion is an applicability promotion requiring review.
    claimed = selection(request, SUPPORTED, claimed=True)
    receipt = retry_review.compare(claimed, selection(request, SUPPORTED), request, request, schema, schema, 'SUPPORTED')
    assert receipt['review_required'] and 'applicability' in receipt['promoted_global_fields']


def test_confidence_formula_is_unchanged(prospective):
    fields, request, _ = v5(prospective)
    result = resolve(prospective, fields, request, selection(request, SUPPORTED, dims=(4, 3, 4, 4)))
    computed = v3.confidence(fields, prospective['profile'], result, prospective['rubric'])
    s = Decimal(4 + 3 + 4 + 4) / 16
    k = (Decimal(4) / 4 + Decimal(4) / 4) / 2  # C01 REQUIRED + best of alternative group G1
    assert computed['confidence_raw_score'] == float((100 * (Decimal('.55') * s + Decimal('.45') * k)).quantize(Decimal('.01')))


def test_fragments_v2_keep_quoted_scope_together():
    text = 'Contexto inicial. La atribucion fue negada: «Se implemento un control. Los costos bajaron.» Fin.'
    old = [f['text'] for f in refs.fragments(dict(methodology=text))]
    new = [f['text'] for f in refs.fragments_v2(dict(methodology=text))]
    assert any(f.endswith('control. ') for f in old)  # historical cut inside the quotation
    assert ''.join(new) == text and not any(f.endswith('control. ') for f in new)
    assert any('«Se implemento un control. Los costos bajaron.»' in f for f in new)
    unbalanced = 'Abre (sin cerrar. Otra frase.'
    assert refs.fragments_v2(dict(methodology=unbalanced)) == refs.fragments(dict(methodology=unbalanced))


def test_semantic_verifier_is_prepared_but_inactive(prospective):
    assert sv.ENABLED is False
    fields, request, _ = v5(prospective)
    result = resolve(prospective, fields, request, selection(request, SUPPORTED))
    verification = sv.build_request(result, request)
    assert [c['criterion_id'] for c in verification['payload']['criteria']] == ['C01', 'C02']
    text = verification['payload']['criteria'][0]['fragments'][0]
    good = dict(verifications=[dict(criterion_id=c, fragment_id=text['fragment_id'], object_span='una plataforma web',
        action_span='implementara', reason='Afirmado.', verdict='ENTAILED') for c in ('C01', 'C02')])
    Draft202012Validator(sv.response_schema(verification)).validate(good)
    assert sv.gate('SUPPORTED', sv.validate_response(verification, good))[0] == 'SUPPORTED'
    rejected = deepcopy(good); rejected['verifications'][1]['verdict'] = 'NOT_ENTAILED'
    assert sv.gate('SUPPORTED', sv.validate_response(verification, rejected))[0] == 'INSUFFICIENT_EVIDENCE'
    ungrounded = deepcopy(good); ungrounded['verifications'][0]['action_span'] = ''  # a citation alone is not enough
    assert sv.gate('SUPPORTED', sv.validate_response(verification, ungrounded))[0] == 'INSUFFICIENT_EVIDENCE'
    bad = deepcopy(good); bad['verifications'][1]['object_span'] = 'texto inventado'
    with pytest.raises(AssessmentValidationError, match='SPAN_NOT_IN_CITED_FRAGMENT'):
        sv.validate_response(verification, bad)
    assert sv.build_request(dict(result, decision='INSUFFICIENT_EVIDENCE'), request) is None


def provider_run(tmp_path, x, answers):
    """OllamaAssessmentProvider end to end with a simulated client (no inference)."""
    import json
    from pathlib import Path
    from unittest.mock import Mock
    runtime = json.loads((Path(__file__).resolve().parents[1] / 'outputs/audits/validacion_real_corregida_v1/'
                          'inferencia_local/baseline_v1/preflight.json').read_text(encoding='utf-8'))['runtime']
    fields, request, schema = v5(x)
    project = dict(project_id='P', fields=fields)
    schema_path = tmp_path / 'schema.json'
    schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding='utf-8')
    natives = [dict(model=runtime['configuration']['model'], done=True, done_reason='stop', prompt_eval_count=500,
                    eval_count=400, message=dict(content=json.dumps(a, ensure_ascii=False))) for a in answers]
    client = Mock(spec=transport.OllamaClient)
    client.inspect.return_value = runtime
    client.request.side_effect = natives

    def resolver(wrapper):
        resolved, receipts = [], []
        for item in wrapper['assessments']:
            a, receipt = p2.resolve_decision(fields, x['profile'], {k: v for k, v in item.items() if k != 'indicator_id'}, x['rubric'])
            resolved.append(dict(indicator_id=item['indicator_id'], **a)); receipts.append(receipt)
        return dict(wrapper, assessments=resolved), receipts

    def validator(wrapper, pid, ids):
        for item in wrapper['assessments']:
            errors = v3.validate(fields, x['profile'], {k: v for k, v in item.items() if k != 'indicator_id'}, x['rubric'])
            if errors:
                raise AssessmentValidationError([dict(category='INVALID_FIELD_VALUE', path='$', rule=e) for e in errors])
    provider = transport.OllamaAssessmentProvider(tmp_path / 'runs', schema_path, lambda p, ids: deepcopy(request),
        settings=runtime['configuration'], runtime=runtime, client=client, max_indicators=1, corrective_retries=1,
        correction_version=transport.P2_TARGETED_VERSION, wrapper_validator=validator, wrapper_resolver=resolver)
    return provider, project, client


def test_provider_merges_localized_retry_and_keeps_v1_protection(tmp_path, prospective):
    _, request, _ = v5(prospective)
    first = selection(request, SUPPORTED)
    first['assessments'][0]['criterion_assessments'][1]['evidence_refs'][0]['stage'] = 'CONTEXT'
    drift = selection(request, {'C02': 'CLEAR'})  # corrects C02, drifts the unflagged C01 to ND
    provider, project, client = provider_run(tmp_path, prospective, [first, drift])
    provider.evaluate(project, [prospective['profile']])
    result = provider.last_output['assessments'][0]
    assert result['decision'] == 'SUPPORTED' and client.request.call_count == 2
    assert [c['support'] for c in result['criterion_assessments']][:2] == ['CLEAR', 'CLEAR']
    attempt = next((tmp_path / 'runs').rglob('attempt_2'))
    assert 'CORRECCION_LOCALIZADA_V1' in (attempt / 'prompt.txt').read_text(encoding='utf-8')
    assert (attempt / 'repair.json').exists() and (attempt / 'decision.json').exists()


def test_provider_rejects_promotion_in_localized_retry(tmp_path, prospective):
    _, request, _ = v5(prospective)
    first = selection(request, {'C01': 'CLEAR'})
    c01, c02 = first['assessments'][0]['criterion_assessments'][:2]
    c02.update(support='NOT_DEMONSTRATED', coverage=0, evidence_refs=list(c01['evidence_refs']))  # ND with refs
    promoted = selection(request, SUPPORTED)  # the correction turns the flagged C02 into CLEAR
    provider, project, client = provider_run(tmp_path, prospective, [first, promoted])
    with pytest.raises(transport.OllamaError, match='FLAGGED_CRITERION_INCREASED'):
        provider.evaluate(project, [prospective['profile']])
    assert provider.last_output is None and client.request.call_count == 2


def test_provider_merge_keeps_unflagged_strength_dimensions(tmp_path, prospective):
    _, request, _ = v5(prospective)
    first = selection(request, SUPPORTED, dims=(3, 3, 3, 3))
    first['assessments'][0]['criterion_assessments'][1]['evidence_refs'][0]['stage'] = 'CONTEXT'
    inflated = selection(request, SUPPORTED, dims=(4, 4, 4, 4))
    provider, project, _ = provider_run(tmp_path, prospective, [first, inflated])
    provider.evaluate(project, [prospective['profile']])
    strength = provider.last_output['assessments'][0]['strength_rubric']
    assert [strength[d] for d in v3.STRENGTH_DIMENSIONS] == [3, 3, 3, 3]  # not taken from the retry


def test_article_source_uses_the_same_v5_evaluation(prospective):
    """ARTICLE: abstract via the existing text__ mechanism; type declared; project bytes unchanged."""
    from layer4_evaluation.indicators.selection import substantive_fields, authorized_fields
    fields = dict(prospective['fields'], title='Titulo del articulo', keywords='a | b',
                  text__abstract=prospective['fields']['methodology'], methodology='')
    assert authorized_fields(fields) and 'text__abstract' in substantive_fields(fields)
    assert not authorized_fields(dict(prospective['fields'], abstract='x'))  # unrecognized field still rejected
    article = dict(project_id='ART_2-s2.0-1', source_type='ARTICLE', fields=fields)
    request = cb.make_request(article, prospective['profile'], prospective['rubric'], fields, evidence_references=True,
        assessment_version=p2.VERSION, evaluation_mode=p2.MODE, prompt_version=p2.PROMPT)
    project = request['payload']['project']
    assert project['source_type'] == 'ARTICLE' and p2.ARTICLE_SOURCE_NOTE in request['prompt']
    assert [f['field'] for f in project['fragments']] == ['text__abstract']
    _, plain, _ = v5(prospective)
    assert 'source_type' not in plain['payload']['project'] and p2.ARTICLE_SOURCE_NOTE not in plain['prompt']
