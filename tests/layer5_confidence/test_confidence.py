"""Synthetic in-memory contracts only: no corpus, provider, API or upstream pipeline."""
from copy import deepcopy
from decimal import Decimal, ROUND_DOWN, localcontext
from itertools import combinations
import json
from pathlib import Path
import unicodedata

import pytest
from jsonschema import Draft202012Validator

from layer4_evaluation.indicators.confidence import (
    calculate_confidence_components, calculate_raw_confidence,
    load_confidence_config, validate_assessment, validate_confidence_config,
)
from layer4_evaluation.indicators.confidence import _corroboration, _field_relevance

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def inputs():
    project = {
        "title": "Restauración regional",
        "keywords": ["bosques", "territorio"],
        "summary": "Restauración de bosques.",
        "methodology": "Medición participativa.",
        "objectives": "Conservar bosques y fortalecer capacidades.",
        "expected_results": "Recuperación ecológica verificable.",
    }
    indicator = {
        "key_elements": ["Conservación", "Capacidades", "Recuperación", "Participación"],
        "preferred_evidence_fields": ["objectives", "expected_results"],
    }
    assessment = {
        "decision": "SUPPORTED", "support_strength": 3,
        "supported_key_elements": indicator["key_elements"][:3],
        "evidence": [
            {"field": "objectives", "text": "Conservar bosques"},
            {"field": "expected_results", "text": "Recuperación ecológica"},
        ],
        "explanation": "Los fragmentos sustentan la asignación propuesta.",
    }
    return project, indicator, assessment


def quote(project, *fields):
    return [{"field": f, "text": project[f][0] if isinstance(project[f], list) else project[f]}
            for f in fields]


def test_reference_exactly_87_50(inputs):
    result = calculate_raw_confidence(*inputs)
    assert result == {
        "confidence_version": "RAW_CONFIDENCE_V1", "confidence_status": "COMPUTED",
        "key_element_coverage": Decimal("0.75"),
        "field_relevance_score": Decimal("1.00"),
        "corroboration_score": Decimal("1.00"),
        "support_strength_score": Decimal("0.75"),
        "confidence_raw_score": Decimal("87.50"),
        "confidence_probability": None, "confidence_level": None, "validation_errors": [],
    }
    assert str(result["confidence_raw_score"]) == "87.50"
    assert calculate_confidence_components(*inputs) == {
        key: result[key] for key in (
            "key_element_coverage", "field_relevance_score",
            "corroboration_score", "support_strength_score")
    }


@pytest.mark.parametrize("decision,strength,valid", [
    ("SUPPORTED", 3, True), ("SUPPORTED", 4, True), ("SUPPORTED", 2, False),
    ("INSUFFICIENT_EVIDENCE", 1, True), ("INSUFFICIENT_EVIDENCE", 2, True),
    ("INSUFFICIENT_EVIDENCE", 3, False),
    ("NOT_SUPPORTED", 0, True), ("NOT_SUPPORTED", 1, False),
    ("UNKNOWN", 0, False),
])
def test_decision_strength_contract(inputs, decision, strength, valid):
    p, i, a = inputs
    a.update(decision=decision, support_strength=strength)
    result = calculate_raw_confidence(p, i, a)
    assert (not validate_assessment(p, i, a)) is valid
    expected = "COMPUTED" if decision == "SUPPORTED" else "NOT_APPLICABLE"
    assert result["confidence_status"] == (expected if valid else "INVALID_ASSESSMENT")
    if not valid or decision != "SUPPORTED":
        assert result["confidence_raw_score"] is None


@pytest.mark.parametrize("strength", [True, False, 3.0, "3", None, [], {}, -1, 5])
def test_strength_never_coerced(inputs, strength):
    inputs[2]["support_strength"] = strength
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "INVALID_ASSESSMENT"


@pytest.mark.parametrize("decision,strength", [("NOT_SUPPORTED", 0), ("INSUFFICIENT_EVIDENCE", 1),
                                             ("INSUFFICIENT_EVIDENCE", 2)])
def test_non_assignment_can_have_no_evidence_or_elements(inputs, decision, strength):
    inputs[2].update(decision=decision, support_strength=strength,
                     evidence=[], supported_key_elements=[])
    result = calculate_raw_confidence(*inputs)
    assert result["confidence_status"] == "NOT_APPLICABLE"
    assert result["confidence_raw_score"] is None
    assert result["key_element_coverage"] is None


def test_unknown_key_element_rejected(inputs):
    inputs[2]["supported_key_elements"].append("Inventado")
    result = calculate_raw_confidence(*inputs)
    assert result["confidence_status"] == "INVALID_ASSESSMENT"
    assert "supported_key_elements:UNKNOWN_ELEMENT" in result["validation_errors"]


def test_duplicate_elements_never_inflate_coverage(inputs):
    baseline = calculate_raw_confidence(*inputs)
    inputs[2]["supported_key_elements"] *= 4
    inputs[1]["key_elements"] *= 3
    assert calculate_raw_confidence(*inputs) == baseline


def test_supported_requires_key_element(inputs):
    inputs[2]["supported_key_elements"] = []
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "INVALID_ASSESSMENT"


@pytest.mark.parametrize("catalog", [None, []])
@pytest.mark.parametrize("supported", [[], ["Conservación"]])
def test_missing_catalog_not_computable(inputs, catalog, supported):
    inputs[1]["key_elements"] = catalog
    inputs[2]["supported_key_elements"] = supported
    result = calculate_raw_confidence(*inputs)
    assert result["confidence_status"] == "NOT_COMPUTABLE"
    assert result["confidence_raw_score"] is None
    assert result["key_element_coverage"] is None
    assert result["validation_errors"] == []


def test_absent_catalog_not_computable(inputs):
    del inputs[1]["key_elements"]
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "NOT_COMPUTABLE"


def test_missing_catalog_never_hides_bad_citation(inputs):
    inputs[1]["key_elements"] = []
    inputs[2]["evidence"][0]["text"] = "Inventado"
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "INVALID_ASSESSMENT"


@pytest.mark.parametrize("location,value", [
    ("key_elements", "Conservación"), ("key_elements", [""]),
    ("key_elements", [3]), ("preferred_evidence_fields", "objectives"),
    ("preferred_evidence_fields", ["abstract"]), ("preferred_evidence_fields", [3]),
])
def test_malformed_indicator_profile_rejected(inputs, location, value):
    inputs[1][location] = value
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "INVALID_ASSESSMENT"


@pytest.mark.parametrize("field", ["abstract", "missing", None, [], {}])
def test_disallowed_or_malformed_field_rejected(inputs, field):
    inputs[2]["evidence"][0]["field"] = field
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "INVALID_ASSESSMENT"


def test_allowed_but_absent_project_field_rejected(inputs):
    del inputs[0]["objectives"]
    result = calculate_raw_confidence(*inputs)
    assert result["confidence_status"] == "INVALID_ASSESSMENT"
    assert "evidence[0].field:FIELD_NOT_IN_PROJECT" in result["validation_errors"]


def test_existing_unrecognized_project_field_rejected(inputs):
    inputs[0]["abstract"] = "Real text"
    inputs[2]["evidence"].append({"field": "abstract", "text": "Real text"})
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "INVALID_ASSESSMENT"


@pytest.mark.parametrize("text", ["No existe", "", " \n\t ", None, 123, [], {}])
def test_invented_empty_or_malformed_quote_rejected(inputs, text):
    inputs[2]["evidence"][0]["text"] = text
    result = calculate_raw_confidence(*inputs)
    assert result["confidence_status"] == "INVALID_ASSESSMENT"
    assert result["confidence_raw_score"] is None


@pytest.mark.parametrize("value", [None, 42, [], {"text": "Conservar bosques"}])
def test_nontext_project_value_rejected(inputs, value):
    inputs[0]["objectives"] = value
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "INVALID_ASSESSMENT"


@pytest.mark.parametrize("fields", [("title",), ("keywords",), ("title", "keywords")])
def test_orientation_only_never_supported(inputs, fields):
    p, i, a = inputs
    a["evidence"] = quote(p, *fields)
    result = calculate_raw_confidence(p, i, a)
    assert result["confidence_status"] == "INVALID_ASSESSMENT"
    assert "evidence:SUBSTANTIVE_FIELD_REQUIRED" in result["validation_errors"]


def test_orientation_and_substantive_supported(inputs):
    p, i, a = inputs
    a["evidence"] = quote(p, "title", "keywords", "objectives")
    result = calculate_raw_confidence(p, i, a)
    assert result["confidence_status"] == "COMPUTED"
    assert result["field_relevance_score"] == Decimal("1.00")
    assert result["corroboration_score"] == Decimal("0.70")


@pytest.mark.parametrize("fields,expected", [
    (["objectives"], "0.70"), (["summary"], "0.70"),
    (["objectives", "expected_results"], "1.00"),
    (["objectives", "objectives", "objectives"], "0.70"),
    (["title", "keywords", "objectives"], "0.70"),
])
def test_corroboration_distinct_substantive_fields(inputs, fields, expected):
    inputs[2]["evidence"] = quote(inputs[0], *fields)
    assert calculate_raw_confidence(*inputs)["corroboration_score"] == Decimal(expected)


def test_distinct_quotes_same_field_not_independent(inputs):
    inputs[2]["evidence"] = [
        {"field": "objectives", "text": "Conservar bosques"},
        {"field": "objectives", "text": "fortalecer capacidades"},
    ]
    assert calculate_raw_confidence(*inputs)["corroboration_score"] == Decimal("0.70")


@pytest.mark.parametrize("preferred,field,expected", [
    (["objectives"], "objectives", "1.00"),
    (["expected_results"], "objectives", "0.75"),
    (None, "objectives", "1.00"), ([], "summary", "1.00"),
])
def test_field_relevance(inputs, preferred, field, expected):
    inputs[1]["preferred_evidence_fields"] = preferred
    inputs[2]["evidence"] = quote(inputs[0], field)
    assert calculate_raw_confidence(*inputs)["field_relevance_score"] == Decimal(expected)


def test_absent_preferences(inputs):
    del inputs[1]["preferred_evidence_fields"]
    assert calculate_raw_confidence(*inputs)["field_relevance_score"] == Decimal("1.00")


@pytest.mark.parametrize("field", ["title", "keywords"])
def test_orientation_relevance_always_025(field):
    cfg = load_confidence_config()
    assert _field_relevance(field, [], cfg) == Decimal("0.25")
    assert _field_relevance(field, [field], cfg) == Decimal("0.25")
    assert _corroboration([field], cfg) == Decimal("0.00")


def test_max_field_relevance_not_average(inputs):
    inputs[2]["evidence"] = quote(inputs[0], "title", "summary", "objectives")
    assert calculate_raw_confidence(*inputs)["field_relevance_score"] == Decimal("1.00")


def test_all_computable_combinations_stay_in_bounds(inputs):
    p, i, a = inputs
    fields = ("summary", "methodology", "objectives", "expected_results")
    for strength in (3, 4):
        a["support_strength"] = strength
        for size in range(1, 5):
            a["supported_key_elements"] = i["key_elements"][:size]
            for count in range(1, 5):
                for selected in combinations(fields, count):
                    a["evidence"] = quote(p, "title", "keywords", *selected)
                    result = calculate_raw_confidence(p, i, a)
                    assert result["confidence_status"] == "COMPUTED"
                    assert all(Decimal(0) <= result[key] <= Decimal(1) for key in (
                        "key_element_coverage", "field_relevance_score",
                        "corroboration_score", "support_strength_score"))
                    assert Decimal(0) <= result["confidence_raw_score"] <= Decimal(100)
                    assert result["confidence_raw_score"].as_tuple().exponent == -2


def test_retrieval_metadata_has_no_effect(inputs):
    baseline = calculate_raw_confidence(*inputs)
    for value in (-1000000, 0, 1000000):
        changed = deepcopy(inputs)
        for mapping in (*changed, *changed[2]["evidence"]):
            for key in ("vector_score", "cosine_score", "graph_score", "hybrid_score",
                        "rank", "retrieval_score", "bge_m3_similarity"):
                mapping[key] = value
            mapping["confidence_raw_score"] = value
            mapping["confidence_probability"] = value
            mapping["confidence_level"] = "HIGH"
        assert calculate_raw_confidence(*changed) == baseline


@pytest.mark.parametrize("status", ["COMPUTED", "NOT_APPLICABLE", "NOT_COMPUTABLE", "INVALID_ASSESSMENT"])
def test_probability_and_level_always_null_and_result_schema(inputs, status):
    if status == "NOT_APPLICABLE":
        inputs[2].update(decision="NOT_SUPPORTED", support_strength=0)
    elif status == "NOT_COMPUTABLE":
        inputs[1]["key_elements"] = []
    elif status == "INVALID_ASSESSMENT":
        inputs[2]["support_strength"] = 2
    result = calculate_raw_confidence(*inputs)
    assert result["confidence_status"] == status
    assert result["confidence_probability"] is None
    assert result["confidence_level"] is None
    schema = json.loads((ROOT / "schemas/layer4_confidence/confidence_result.schema.json").read_text())
    Draft202012Validator(schema).validate(result)


def test_repeatability_and_input_immutability(inputs):
    original = deepcopy(inputs)
    baseline = calculate_raw_confidence(*inputs)
    for _ in range(10):
        assert calculate_raw_confidence(*inputs) == baseline
    assert inputs == original


def test_caller_decimal_context_does_not_change_score(inputs):
    baseline = calculate_raw_confidence(*inputs)
    with localcontext() as ctx:
        ctx.prec = 3
        ctx.rounding = ROUND_DOWN
        assert calculate_raw_confidence(*inputs) == baseline


def test_half_up_rounding_at_exact_half_cent(inputs):
    inputs[1].update(key_elements=[str(n) for n in range(8)],
                     preferred_evidence_fields=["expected_results"])
    inputs[2].update(supported_key_elements=["0"], evidence=quote(inputs[0], "objectives"))
    assert str(calculate_raw_confidence(*inputs)["confidence_raw_score"]) == "52.13"


def test_weights_sum_exactly_one_and_version():
    cfg = load_confidence_config()
    assert cfg["version"] == "RAW_CONFIDENCE_V1"
    assert sum(cfg["weights"].values()) == Decimal("1.0")
    assert cfg["weights"] == dict(zip(
        ("key_element_coverage", "field_relevance", "corroboration", "support_strength"),
        map(Decimal, ("0.35", "0.30", "0.20", "0.15"))))


@pytest.mark.parametrize("value", ["0.34", "0.350000000000000000000000000000000000000000000000001"])
def test_weights_must_sum_exactly_one(value):
    cfg = load_confidence_config()
    cfg["weights"]["key_element_coverage"] = value
    with pytest.raises(ValueError, match="sum exactly"):
        validate_confidence_config(cfg)


@pytest.mark.parametrize("value", [-1, "NaN", "Infinity", True, "invalid", "1.01"])
def test_invalid_config_values_rejected(value):
    cfg = load_confidence_config()
    cfg["weights"]["key_element_coverage"] = value
    with pytest.raises(ValueError):
        validate_confidence_config(cfg)


def test_invalid_config_version_rejected():
    cfg = load_confidence_config()
    cfg["version"] = "OTHER"
    with pytest.raises(ValueError, match="version"):
        validate_confidence_config(cfg)


def test_config_cannot_reclassify_orientation_as_substantive():
    cfg = load_confidence_config()
    cfg["allowed_fields"]["substantive"].append("title")
    with pytest.raises(ValueError, match="exact substantive fields"):
        validate_confidence_config(cfg)


def test_weights_are_read_from_config_and_config_is_not_mutated(inputs):
    cfg = load_confidence_config()
    cfg["weights"] = dict(zip(cfg["weights"], map(Decimal, ("1", "0", "0", "0"))))
    original = deepcopy(cfg)
    assert calculate_raw_confidence(*inputs, config=cfg)["confidence_raw_score"] == Decimal("75.00")
    assert cfg == original


def test_nfc_and_whitespace_quotes_without_mutation(inputs):
    p, i, a = inputs
    p["objectives"] = "  La conservación\r\n\t de\u00a0bosques. "
    a["evidence"] = [{"field": "objectives",
                       "text": unicodedata.normalize("NFD", "conservación   de bosques")}]
    original = deepcopy(inputs)
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "COMPUTED"
    assert inputs == original


@pytest.mark.parametrize("text", ["conservacion", "CONSERVACIÓN", "conser\u200bvación",
                                 "conservación-bosques"])
def test_no_accent_case_fuzzy_or_punctuation_matching(inputs, text):
    inputs[0]["objectives"] = "conservación de bosques"
    inputs[2]["evidence"] = [{"field": "objectives", "text": text}]
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "INVALID_ASSESSMENT"


def test_key_element_conservative_normalization_and_duplicates(inputs):
    inputs[1]["key_elements"][0] = "Conservación  local"
    inputs[2]["supported_key_elements"] = [
        unicodedata.normalize("NFD", "Conservación\nlocal"), "Conservación local"]
    assert calculate_raw_confidence(*inputs)["key_element_coverage"] == Decimal("0.25")


@pytest.mark.parametrize("text", ["conservación", "Conservacion"])
def test_key_elements_do_not_drop_case_or_accents(inputs, text):
    inputs[2]["supported_key_elements"] = [text]
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "INVALID_ASSESSMENT"


def test_keyword_quote_cannot_cross_list_items(inputs):
    inputs[2]["evidence"].append({"field": "keywords", "text": "bosques territorio"})
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "INVALID_ASSESSMENT"


@pytest.mark.parametrize("key", ["decision", "support_strength", "supported_key_elements",
                               "evidence", "explanation"])
def test_required_assessment_fields(inputs, key):
    del inputs[2][key]
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "INVALID_ASSESSMENT"


@pytest.mark.parametrize("value", [None, [], "", 123])
def test_malformed_assessment_is_structured_invalid(inputs, value):
    assert calculate_raw_confidence(inputs[0], inputs[1], value)["confidence_status"] == "INVALID_ASSESSMENT"


@pytest.mark.parametrize("key,value", [
    ("evidence", None), ("evidence", []), ("evidence", [None]),
    ("supported_key_elements", "Conservación"), ("supported_key_elements", [None]),
    ("explanation", ""), ("decision", []),
])
def test_malformed_payloads_rejected(inputs, key, value):
    inputs[2][key] = value
    assert calculate_raw_confidence(*inputs)["confidence_status"] == "INVALID_ASSESSMENT"


@pytest.mark.parametrize("kind", ["invalid", "not_applicable", "not_computable"])
def test_components_guarded_before_computation(inputs, kind):
    if kind == "invalid":
        inputs[2]["evidence"][0]["text"] = "Inventado"
    elif kind == "not_applicable":
        inputs[2].update(decision="NOT_SUPPORTED", support_strength=0)
    else:
        inputs[1]["key_elements"] = []
    with pytest.raises(ValueError):
        calculate_confidence_components(*inputs)


def test_all_schemas_are_valid_and_input_contracts_match(inputs):
    for path in sorted((ROOT / "schemas/layer4_confidence").glob("*.schema.json")):
        Draft202012Validator.check_schema(json.loads(path.read_text()))
    for name, value in (("assessment", inputs[2]), ("indicator_profile", inputs[1])):
        schema = json.loads((ROOT / f"schemas/layer4_confidence/{name}.schema.json").read_text())
        Draft202012Validator(schema).validate(value)


def test_decimal_traps_do_not_leak_into_scoring(inputs):
    from decimal import Inexact, Rounded
    inputs[1]["key_elements"] = inputs[1]["key_elements"][:3]
    inputs[2]["supported_key_elements"] = inputs[1]["key_elements"][:1]
    baseline = calculate_raw_confidence(*inputs)
    with localcontext() as ctx:
        ctx.traps[Inexact] = True
        ctx.traps[Rounded] = True
        assert calculate_raw_confidence(*inputs) == baseline


def test_yaml_duplicate_configuration_keys_rejected(tmp_path):
    original = (ROOT / "config/layer4_confidence.yaml").read_text(encoding="utf-8")
    path = tmp_path / "duplicate.yaml"
    path.write_text(original + "\nversion: RAW_CONFIDENCE_V1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_confidence_config(path)


@pytest.mark.parametrize("scalar", [".nan", ".inf", "-.inf"])
def test_yaml_nonfinite_configuration_values_rejected(tmp_path, scalar):
    original = (ROOT / "config/layer4_confidence.yaml").read_text(encoding="utf-8")
    path = tmp_path / "nonfinite.yaml"
    path.write_text(original.replace("key_element_coverage: 0.35",
                                    "key_element_coverage: " + scalar), encoding="utf-8")
    with pytest.raises(ValueError):
        load_confidence_config(path)
