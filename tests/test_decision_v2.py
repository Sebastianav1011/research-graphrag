"""BALANCED_CRITERIA_DECISION_V2: balanced final accreditation over verified V5 judgments."""
import pytest

from layer4_evaluation.indicators import decision_v2 as d2

# C01/C02 context, C03-C05 contribution, C06 complementary.
RUBRIC = dict(criteria=[dict(criterion_id='C01', role='REQUIRED', temporal_requirement='CONTEXT_ONLY'),
                        dict(criterion_id='C02', role='REQUIRED', temporal_requirement='CONTEXT_ONLY'),
                        dict(criterion_id='C03', role='REQUIRED', temporal_requirement='PROPOSAL_OR_HIGHER'),
                        dict(criterion_id='C04', role='REQUIRED', temporal_requirement='EXPECTED_OR_DEMONSTRATED'),
                        dict(criterion_id='C05', role='REQUIRED', temporal_requirement='EXPECTED_OR_DEMONSTRATED'),
                        dict(criterion_id='C06', role='COMPLEMENTARY', temporal_requirement='CONTEXT_ONLY')])


def row(supports, decision='INSUFFICIENT_EVIDENCE', applicability='APPLICABLE', stage='RESULT_EXPECTED', confidence=60.0):
    return dict(decision=decision, applicability=dict(status=applicability), confidence_raw_score=confidence,
                evidence_stages=[stage], criterion_assessments=[
                    dict(criterion_id=f'C0{n}', support=s, evidence_indices=[] if s == 'NOT_DEMONSTRATED' else [0])
                    for n, s in enumerate(supports, 1)])


def test_high_confidence_with_an_absent_element_is_not_supported():
    decision, receipt = d2.final_decision(row(['CLEAR', 'CLEAR', 'CLEAR', 'CLEAR', 'NOT_DEMONSTRATED', 'CLEAR'], confidence=99.0), RUBRIC)
    assert decision == 'INSUFFICIENT_EVIDENCE' and receipt['rule'] == 'R2_ELEMENTO_INDISPENSABLE_AUSENTE'


def test_majority_clear_with_partial_minority_is_supported_and_labeled_prospective():
    decision, receipt = d2.final_decision(row(['CLEAR', 'PARTIAL', 'CLEAR', 'CLEAR', 'PARTIAL', 'NOT_DEMONSTRATED']), RUBRIC)
    assert decision == 'SUPPORTED' and receipt['required_partial'] == ['C02', 'C05']
    assert receipt['evidence_nature'] == 'PROSPECTIVA' and 'no impacto observado' in receipt['meaning']
    assert 'no impacto observado' in d2.explanation(receipt)
    _, observed = d2.final_decision(row(['CLEAR', 'PARTIAL', 'CLEAR', 'CLEAR', 'PARTIAL', 'CLEAR'], stage='RESULT_DEMONSTRATED'), RUBRIC)
    assert observed['evidence_nature'] == 'OBSERVADA' and 'realizado' in observed['meaning']


def test_minority_clear_or_context_only_clear_stays_insufficient():
    assert d2.final_decision(row(['CLEAR', 'CLEAR', 'PARTIAL', 'PARTIAL', 'PARTIAL', 'CLEAR']), RUBRIC)[1]['rule'] == 'R3_SIN_MAYORIA_CLARA'
    # PREDICOL SOC-01 pattern: the improvement itself is only partial; context alone never accredits.
    context = dict(criteria=[dict(c, temporal_requirement='CONTEXT_ONLY') if c['criterion_id'] in ('C03',) else c
                             for c in RUBRIC['criteria']])
    decision, receipt = d2.final_decision(row(['CLEAR', 'CLEAR', 'CLEAR', 'PARTIAL', 'PARTIAL', 'CLEAR']), context)
    assert decision == 'INSUFFICIENT_EVIDENCE' and receipt['rule'] == 'R4_SOLO_CONTEXTO_CLARO'


def test_no_substantive_evidence_or_negative_control_stays_insufficient():
    assert d2.final_decision(row(['CLEAR'] * 6, applicability='UNDETERMINED'), RUBRIC)[0] == 'INSUFFICIENT_EVIDENCE'
    # SAL-03 / CUL-02 pattern: two indispensable elements absent despite high confidence.
    assert d2.final_decision(row(['NOT_DEMONSTRATED', 'CLEAR', 'CLEAR', 'NOT_DEMONSTRATED', 'CLEAR', 'CLEAR'], confidence=70.6), RUBRIC)[0] == 'INSUFFICIENT_EVIDENCE'


def test_v1_supported_and_not_applicable_are_kept_and_external_records_stay_strict():
    assert d2.final_decision(row(['CLEAR'] * 6, decision='SUPPORTED'), RUBRIC)[0] == 'SUPPORTED'
    assert d2.final_decision(row(['NOT_DEMONSTRATED'] * 6, decision='NOT_APPLICABLE', applicability='NOT_APPLICABLE'), RUBRIC)[0] == 'NOT_APPLICABLE'
    decision, receipt = d2.final_decision(row(['CLEAR', 'PARTIAL', 'CLEAR', 'CLEAR', 'PARTIAL', 'CLEAR']), RUBRIC, ('C04',))
    assert decision == 'INSUFFICIENT_EVIDENCE' and receipt['rule'] == 'R5_REGISTRO_EXTERNO_V1'
    with pytest.raises(ValueError):
        d2.final_decision(row(['CLEAR'] * 6, decision='OTHER'), RUBRIC)


def test_alternative_groups_still_need_a_clear_member():
    rubric = dict(criteria=RUBRIC['criteria'][:5] + [dict(criterion_id='C06', role='ALTERNATIVE', alternative_group='G', temporal_requirement='CONTEXT_ONLY')])
    assert d2.final_decision(row(['CLEAR', 'CLEAR', 'CLEAR', 'PARTIAL', 'PARTIAL', 'PARTIAL']), rubric)[1]['rule'] == 'R5_GRUPO_ALTERNATIVO_SIN_CLARO'


def test_an_explained_mechanism_is_not_an_observed_impact():
    decision, receipt = d2.final_decision(row(['CLEAR', 'PARTIAL', 'CLEAR', 'CLEAR', 'PARTIAL', 'CLEAR'], stage='MECHANISM_ESTABLISHED'), RUBRIC)
    assert decision == 'SUPPORTED' and receipt['evidence_nature'] == 'PROSPECTIVA' and 'no impacto observado' in receipt['meaning']
