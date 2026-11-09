from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator,ValidationError
from layer4_evaluation.indicators.contracts import check_contracts,load_schema
from layer4_evaluation.indicators.assessment import build_indicator_row,validate_structured_assessment
from layer4_evaluation.indicators.confidence import calculate_raw_confidence

ROOT=Path(__file__).resolve().parents[2]


def test_all_schemas_in_sync():assert check_contracts(ROOT)==6


def test_contractual_87_50(example):
    fields,profile,assessment=example
    result=calculate_raw_confidence(fields,profile,assessment)
    assert result['confidence_raw_score']==Decimal('87.50')
    assert tuple(result[k] for k in ('key_element_coverage','field_relevance_score','corroboration_score','support_strength_score'))==(
        Decimal('0.75'),Decimal('1.00'),Decimal('1.00'),Decimal('0.75'))
    row=build_indicator_row('SYNTH',fields,profile,assessment,engine='SYNTHETIC_TEST_PROVIDER',engine_status='SYNTHETIC_TEST')
    assert row['confidence_raw_score']==87.5 and row['confidence_probability'] is row['confidence_level'] is None


@pytest.mark.parametrize('decision,strength',[('SUPPORTED',3),('SUPPORTED',4),('INSUFFICIENT_EVIDENCE',1),
    ('INSUFFICIENT_EVIDENCE',2),('NOT_SUPPORTED',0)])
def test_decision_strength_and_no_explicit_contradiction_required(example,decision,strength):
    fields,profile,assessment=example
    assessment.update(decision=decision,support_strength=strength)
    if decision!='SUPPORTED':assessment.update(supported_key_elements=[],evidence=[])
    assert not validate_structured_assessment(fields,profile,assessment)
    result=calculate_raw_confidence(fields,profile,assessment)
    if decision!='SUPPORTED':assert result['confidence_raw_score'] is None


@pytest.mark.parametrize('decision,strength',[('SUPPORTED',0),('SUPPORTED',2),('INSUFFICIENT_EVIDENCE',3),('NOT_SUPPORTED',1)])
def test_inconsistent_strength_invalid(example,decision,strength):
    fields,profile,assessment=example;assessment.update(decision=decision,support_strength=strength)
    assert validate_structured_assessment(fields,profile,assessment)


@pytest.mark.parametrize('quote',['conservar bosques','Conservar bosque','Conservar árboles'])
def test_no_case_fuzzy_semantic_or_substring_correction(example,quote):
    # The plural truncation 'Conservar bosque' is a literal substring, so use
    # non-substring changes in this gate test rather than prohibiting valid quotes.
    if quote=='Conservar bosque':quote='Conservar  los bosques'
    fields,profile,assessment=example;assessment['evidence'][0]['text']=quote
    assert validate_structured_assessment(fields,profile,assessment)
    assert calculate_raw_confidence(fields,profile,assessment)['confidence_raw_score'] is None


def test_nfc_and_whitespace_only(example):
    fields,profile,assessment=example
    fields['objectives']='Cafe\u0301\n  local y bosque'
    assessment['evidence'][0]['text']='Café local'
    assert not validate_structured_assessment(fields,profile,assessment)
    assessment['evidence'][0]['text']='Cafe local'
    assert validate_structured_assessment(fields,profile,assessment)


def test_unknown_field_invalid(example):
    fields,profile,assessment=example;assessment['evidence'][0]['field']='abstract'
    assert validate_structured_assessment(fields,profile,assessment)


@pytest.mark.parametrize('key',['confidence_raw_score','confidence_probability','confidence_level','retrieval_score'])
def test_provider_never_supplies_confidence_or_retrieval(example,key):
    fields,profile,assessment=example;assessment[key]=99
    assert validate_structured_assessment(fields,profile,assessment)


def test_retrieval_cannot_affect_raw_confidence(example):
    fields,profile,assessment=example;before=calculate_raw_confidence(fields,profile,assessment)
    for target in (fields,profile,assessment):target.update(retrieval_score=10**20,graph_score=-100,rank=1)
    assert calculate_raw_confidence(fields,profile,assessment)==before


def test_invalid_assessment_not_exportable(example):
    fields,profile,assessment=example;assessment['evidence'][0]['text']='Texto inventado'
    with pytest.raises(ValueError,match='INVALID_ASSESSMENT'):
        build_indicator_row('SYNTH',fields,profile,assessment,engine='FIXTURE',engine_status='SYNTHETIC_TEST')


def test_supported_without_elements_not_computable(example):
    fields,profile,assessment=example;profile['key_elements']=[]
    row=build_indicator_row('SYNTH',fields,profile,assessment,engine='FIXTURE',engine_status='SYNTHETIC_TEST')
    assert row['confidence_status']=='NOT_COMPUTABLE' and row['confidence_raw_score'] is None


def test_provider_protocol_is_interface_only():
    from layer4_evaluation.indicators.assessment import AssessmentProvider
    assert AssessmentProvider._is_protocol
    with pytest.raises(TypeError):AssessmentProvider()
