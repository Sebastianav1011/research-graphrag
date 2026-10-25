"""Provider-neutral contracts and deterministic validation. No assessment engine."""

from .contracts import load_schema
from typing import Mapping, Protocol, Sequence, TypedDict
from decimal import Decimal
from pathlib import Path
from jsonschema import Draft202012Validator
from layer4.indicators.confidence import calculate_raw_confidence, validate_assessment

class ProjectInput(TypedDict):
    project_id: str
    fields: Mapping[str, object]


class IndicatorAssessment(TypedDict):
    indicator_id: str
    assessment: Mapping[str, object]


class AssessmentProvider(Protocol):
    def evaluate(self, project: ProjectInput, indicators: Sequence[Mapping[str, object]]) -> Sequence[IndicatorAssessment]:
        """Return structured assessments; never compute confidence or resolve territory."""
        ...

__all__ = ['validate_structured_assessment', 'build_indicator_row', 'AssessmentProvider']


ROOT=Path(__file__).resolve().parents[3]


def validate_structured_assessment(project_fields, profile, assessment):
    errors = [f'SCHEMA:{list(e.absolute_path)}:{e.validator}' for e in
              Draft202012Validator(load_schema(ROOT,'assessment')).iter_errors(assessment)]
    errors += validate_assessment(project_fields, profile, assessment)
    return errors


def build_indicator_row(project_id, project_fields, profile, assessment, *, engine, engine_status):
    """Pure transformation for future callers/fixtures; never invokes a provider."""
    errors=validate_structured_assessment(project_fields,profile,assessment)
    if errors:
        raise ValueError('INVALID_ASSESSMENT: '+'; '.join(errors))
    confidence=calculate_raw_confidence(project_fields,profile,assessment)
    result={'project_id':project_id,**{field:profile[field] for field in
        ('indicator_id','indicator_name','indicator_category','indicator_dimension')},
        'decision':assessment['decision'],'support_strength':assessment['support_strength'],
        'supported_key_elements':list(assessment['supported_key_elements']),
        'evidence_source_fields':[e['field'] for e in assessment['evidence']],
        'evidence_texts':[e['text'] for e in assessment['evidence']],
        'evidence_explanation':assessment['explanation'],'assessment_engine':engine,
        'assessment_engine_status':engine_status,
        **{key:float(value) if isinstance(value,Decimal) else value for key,value in confidence.items()
           if key!='validation_errors'}}
    Draft202012Validator(load_schema(ROOT,'project_indicator')).validate(result)
    return result
