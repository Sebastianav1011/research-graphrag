"""BALANCED_CRITERIA_DECISION_V2: final accreditation decision over a verified V5 assessment.

Deterministic Python over the model's stored criterion judgments; no model call, no new
state (SUPPORTED, INSUFFICIENT_EVIDENCE, NOT_APPLICABLE). It replaces only the rule
"every REQUIRED criterion must be CLEAR" of VALIDATED_CRITERIA_DECISION_V1, which treated a
PARTIAL judgment (relevant, cited, incomplete evidence) exactly like an absent element.

SUPPORTED requires all of:
  1. applicability APPLICABLE (substantive, non-context evidence of the source itself);
  2. no REQUIRED criterion NOT_DEMONSTRATED: every indispensable catalog element has
     cited literal evidence (CLEAR or PARTIAL);
  3. a strict majority of REQUIRED criteria CLEAR;
  4. at least one CLEAR REQUIRED criterion that is a contribution of the project
     (temporal requirement other than CONTEXT_ONLY), so context alone (a territory, a
     population) never accredits;
  5. unchanged V1 gates: every alternative group with a CLEAR member and external-record
     criteria (EXTERNAL_RECORD_CRITERIA) CLEAR with executed/demonstrated evidence.
A V1 SUPPORTED is always kept SUPPORTED (V2 only relaxes rule 1 of V1). NOT_APPLICABLE is
kept. The numeric confidence is never used. A prospective accreditation (only proposed or
expected evidence) is labeled as a planned contribution, never as an observed impact.
"""
VERSION = 'BALANCED_CRITERIA_DECISION_V2'
# An explained mechanism is not an observed impact: only executed activities or demonstrated
# results make an accreditation OBSERVADA (everything else stays PROSPECTIVA).
OBSERVED_STAGES = {'ACTIVITY_EXECUTED', 'RESULT_DEMONSTRATED'}


def evidence_nature(assessment):
    stages = {assessment['evidence_stages'][i] for c in assessment['criterion_assessments']
              if c['support'] in ('CLEAR', 'PARTIAL') for i in c.get('evidence_indices') or []
              if i < len(assessment.get('evidence_stages') or [])}
    if not stages:
        return 'SIN_EVIDENCIA'
    return 'OBSERVADA' if stages & OBSERVED_STAGES else 'PROSPECTIVA'


def final_decision(assessment, rubric, external_record_criteria=()):
    """(decision, receipt) for a verified V5 row/assessment and its sealed rubric."""
    criteria = rubric['criteria']
    judgments = {c['criterion_id']: c for c in assessment['criterion_assessments']}
    required = [c for c in criteria if c['role'] == 'REQUIRED']
    support = {c['criterion_id']: judgments[c['criterion_id']]['support'] for c in required}
    absent = sorted(cid for cid, s in support.items() if s == 'NOT_DEMONSTRATED')
    partial = sorted(cid for cid, s in support.items() if s == 'PARTIAL')
    clear = [c for c in required if support[c['criterion_id']] == 'CLEAR']
    contribution = [c['criterion_id'] for c in clear if c.get('temporal_requirement') != 'CONTEXT_ONLY']
    original = assessment['decision']
    applicability = (assessment.get('applicability') or {}).get('status')
    groups = {c.get('alternative_group') for c in criteria if c['role'] == 'ALTERNATIVE'}
    groups_ok = all(any(c.get('alternative_group') == g and judgments[c['criterion_id']]['support'] == 'CLEAR' for c in criteria)
                    for g in groups)
    if original == 'NOT_APPLICABLE':
        decision, rule = 'NOT_APPLICABLE', 'V1_NOT_APPLICABLE'
    elif original == 'SUPPORTED':
        decision, rule = 'SUPPORTED', 'V1_SUPPORTED'
    elif original != 'INSUFFICIENT_EVIDENCE':
        raise ValueError('Decision V5 no prevista: ' + str(original))
    elif applicability != 'APPLICABLE':
        decision, rule = 'INSUFFICIENT_EVIDENCE', 'R1_SIN_EVIDENCIA_SUSTANTIVA_PROPIA'
    elif absent:
        decision, rule = 'INSUFFICIENT_EVIDENCE', 'R2_ELEMENTO_INDISPENSABLE_AUSENTE'
    elif not len(clear) * 2 > len(required):
        decision, rule = 'INSUFFICIENT_EVIDENCE', 'R3_SIN_MAYORIA_CLARA'
    elif not contribution:
        decision, rule = 'INSUFFICIENT_EVIDENCE', 'R4_SOLO_CONTEXTO_CLARO'
    elif not groups_ok:
        decision, rule = 'INSUFFICIENT_EVIDENCE', 'R5_GRUPO_ALTERNATIVO_SIN_CLARO'
    elif external_record_criteria:
        # External-record indicators keep the strict V1 gate: an executed/demonstrated
        # record cannot be replaced by a partial judgment. V1 already decided.
        decision, rule = 'INSUFFICIENT_EVIDENCE', 'R5_REGISTRO_EXTERNO_V1'
    else:
        decision, rule = 'SUPPORTED', 'V2_MAYORIA_CLARA_SIN_ELEMENTOS_AUSENTES'
    nature = evidence_nature(assessment)
    meaning = None
    if decision == 'SUPPORTED':
        meaning = ('Acreditacion prospectiva: contribucion prevista por el proyecto, no impacto observado'
                   if nature == 'PROSPECTIVA' else 'Acreditacion con evidencia de actividad o resultado realizado')
    receipt = dict(version=VERSION, decision_v5=original, decision=decision, rule=rule, changed=decision != original,
                   required=len(required), required_clear=len(clear), required_partial=partial, required_absent=absent,
                   contribution_clear=contribution, evidence_nature=nature, meaning=meaning,
                   confidence_raw_score=assessment.get('confidence_raw_score'))
    return decision, receipt


def explanation(receipt, original_text=''):
    text = (f"Decision final {VERSION}: {receipt['decision']} (regla {receipt['rule']}; V5 {receipt['decision_v5']}); "
            f"esenciales claros {receipt['required_clear']}/{receipt['required']}, parciales {receipt['required_partial']}, "
            f"ausentes {receipt['required_absent']}.")
    if receipt['meaning']:
        text += ' ' + receipt['meaning'] + '.'
    return text + (' ' + original_text if original_text else '')
