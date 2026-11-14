"""Title-only CLEAR rule on synthetic evidence: no institutional data, no real Qwen answers.

Covers the rule previously verified only by replaying the compacted run
run_institutional_minimal_3x3_20261102 (now an opt-in historical test): a CLEAR
criterion supported only by the title is rejected; adding substantive evidence
from the same project removes that specific rejection. Python never relabels.
"""
from copy import deepcopy
import hashlib

from jsonschema import Draft202012Validator

from autonomous_execution import minimal as m
from layer4_evaluation.indicators import assessment_v3 as v3
from tests.layer5_experiment.test_assessment_v3 import case  # noqa: F401  (synthetic catalog fixture)

RULE = 'V3_CRITERION:CLEAR_REQUIRES_COMPATIBLE_SUBSTANTIVE_EVIDENCE'


def synthetic_registry(project):
    registry = {}
    for eid, field in (('E_TITLE', 'title'), ('E_BODY', 'methodology')):
        text = project['fields'][field]
        registry[eid] = dict(project_id=project['project_id'], field=field, start=0, end=len(text), text=text,
            original_field_sha256=hashlib.sha256(text.encode()).hexdigest(), chunk_ids=['CHUNK_' + field])
    return registry


def answer(evidence_ids, conclusion):
    stage = 'CLEAR__DESIGN_DOCUMENTED'
    return dict(criteria={
        'C01': dict(judgment=stage, evidence_ids=list(evidence_ids), why='Juicio sintetico de prueba.'),
        'C02': dict(judgment=stage, evidence_ids=list(evidence_ids), why='Juicio sintetico de prueba.'),
        'C03': dict(judgment='NOT_DEMONSTRATED', evidence_ids=[], why='Sin respaldo sintetico.'),
        'C04': dict(judgment='NOT_DEMONSTRATED', evidence_ids=[], why='Sin respaldo sintetico.')},
        conclusion=conclusion, why='Conclusion sintetica; no es etiqueta humana.')


def validate(project, profile, rubric, registry, value):
    wrapper = m.assemble(project, profile['indicator_id'], rubric, registry, value)
    assessment = {k: v for k, v in wrapper['assessments'][0].items() if k != 'indicator_id'}
    return v3.validate(project['fields'], profile, assessment, rubric)


def test_title_only_clear_rule_is_enforced_on_synthetic_evidence(case):
    profile, rubric = case['profile'], case['rubric']
    fields = deepcopy(case['fields'])
    fields['title'] = 'Mecanismo compartido sintetico'
    project = dict(project_id='SYNTH_PROJECT', fields=fields)
    registry = synthetic_registry(project)
    transport = m.schema(rubric, registry)

    title_only = answer(['E_TITLE'], 'SUPPORTED__3')
    assert not list(Draft202012Validator(transport).iter_errors(title_only))  # Schema accepts; the rule is semantic.
    errors = validate(project, profile, rubric, registry, title_only)
    assert errors.count(RULE) == 2  # Both CLEAR criteria cite only the title.

    with_body = answer(['E_TITLE', 'E_BODY'], 'SUPPORTED__3')
    assert not list(Draft202012Validator(transport).iter_errors(with_body))
    assert RULE not in validate(project, profile, rubric, registry, with_body)
    assert validate(project, profile, rubric, registry, answer(['E_BODY'], 'SUPPORTED__3')) == []
