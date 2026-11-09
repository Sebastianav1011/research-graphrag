"""Versioned local configuration; no dependency on upstream pipeline modules."""

from collections.abc import Mapping
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
import yaml
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
import unicodedata
from .selection import substantive_fields

VERSION = "RAW_CONFIDENCE_V1"
ORIENTATION = frozenset(("title", "keywords"))
SUBSTANTIVE = frozenset(("summary", "methodology", "objectives", "expected_results"))
DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config/layer4_confidence.yaml"
NUMERIC_KEYS = {
    "weights": ("key_element_coverage", "field_relevance", "corroboration", "support_strength"),
    "field_relevance": ("preferred", "substantive_non_preferred",
                        "substantive_without_preferences", "orientation"),
    "corroboration": ("zero_substantive_fields", "one_substantive_field",
                      "two_or_more_substantive_fields"),
}


class _DecimalLoader(yaml.SafeLoader):
    """Retain YAML decimal spelling rather than converting through binary float."""


def _decimal_scalar(loader, node):
    try:
        return Decimal(loader.construct_scalar(node))
    except InvalidOperation:
        raise ValueError("Invalid YAML decimal scalar") from None


def _unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str) or key in result:
            raise ValueError("Configuration keys must be unique strings")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_DecimalLoader.add_constructor("tag:yaml.org,2002:float", _decimal_scalar)
_DecimalLoader.add_constructor("tag:yaml.org,2002:map", _unique_mapping)


def validate_confidence_config(config):
    """Return a fresh Decimal configuration or raise ValueError (configuration error)."""
    if not isinstance(config, Mapping) or config.get("version") != VERSION:
        raise ValueError("config.version must be RAW_CONFIDENCE_V1")
    if set(config) != {"version", "allowed_fields", *NUMERIC_KEYS}:
        raise ValueError("Unexpected or missing confidence configuration keys")
    result = {"version": VERSION}
    for section, keys in NUMERIC_KEYS.items():
        values = config.get(section)
        if not isinstance(values, Mapping) or set(values) != set(keys):
            raise ValueError(f"Invalid configuration section: {section}")
        result[section] = {}
        for key in keys:
            value = values[key]
            # Float/string scalars supplied by a caller have explicit decimal spelling.
            if isinstance(value, bool):
                raise ValueError(f"Invalid numeric value: {section}.{key}")
            try:
                number = Decimal(str(value))
            except (InvalidOperation, ValueError):
                raise ValueError(f"Invalid numeric value: {section}.{key}") from None
            if not number.is_finite() or not Decimal(0) <= number <= Decimal(1):
                raise ValueError(f"Out of range: {section}.{key}")
            result[section][key] = number
    # Use enough precision to check the actual decimal sum, independent of caller context.
    weights = result["weights"].values()
    precision = max(50, max(-v.as_tuple().exponent for v in weights) + 10)
    with localcontext(Context(prec=precision, rounding=ROUND_HALF_UP)):
        if sum(result["weights"].values(), Decimal(0)) != Decimal(1):
            raise ValueError("Confidence weights must sum exactly to 1.0")
    fields = config.get("allowed_fields")
    if not isinstance(fields, Mapping) or set(fields) != {"orientation", "substantive"}:
        raise ValueError("Invalid allowed_fields")
    for role, expected in (("orientation", ORIENTATION), ("substantive", SUBSTANTIVE)):
        values = fields.get(role)
        if (not isinstance(values, list) or any(not isinstance(v, str) for v in values)
                or len(values) != len(expected) or set(values) != expected):
            raise ValueError(f"RAW_CONFIDENCE_V1 requires exact {role} fields")
    result["allowed_fields"] = {role: list(fields[role]) for role in fields}
    return result


def load_confidence_config(path=DEFAULT_CONFIG):
    """Read only the local versioned YAML; never open project or retrieval outputs."""
    with Path(path).open(encoding="utf-8") as stream:
        return validate_confidence_config(yaml.load(stream, Loader=_DecimalLoader))



DECISION_STRENGTHS = {
    "NOT_SUPPORTED": (0,),
    "INSUFFICIENT_EVIDENCE": (1, 2),
    "SUPPORTED": (3, 4),
}
COMPONENT_KEYS = ("key_element_coverage", "field_relevance_score",
                  "corroboration_score", "support_strength_score")


def _normalize(text):
    # Preserve case, accents and punctuation; only NFC and whitespace collapse.
    return " ".join(unicodedata.normalize("NFC", text).split())


def _text_list(value):
    return (isinstance(value, list)
            and all(isinstance(v, str) and bool(_normalize(v)) for v in value))


def _settings(config):
    return load_confidence_config() if config is None else validate_confidence_config(config)


def validate_assessment(project_fields, indicator_profile, assessment):
    """Return ordered error codes; never mutate inputs or coerce narrative values.

    Missing/null/empty key_elements means unavailable catalog, not invented K.
    Catalog membership and the nonempty supported-elements gate are deferred in
    that case; all other gates still apply before NOT_COMPUTABLE can be returned.
    """
    errors = []
    if not isinstance(project_fields, Mapping):
        errors.append("project_fields:EXPECTED_OBJECT")
        project_fields = {}
    if not isinstance(indicator_profile, Mapping):
        errors.append("indicator_profile:EXPECTED_OBJECT")
        indicator_profile = {}
    catalog = indicator_profile.get("key_elements")
    if catalog is None:
        catalog = []
    if not _text_list(catalog):
        errors.append("indicator_profile.key_elements:EXPECTED_NONEMPTY_STRINGS")
        catalog = []
    catalog_set = {_normalize(v) for v in catalog}
    preferred = indicator_profile.get("preferred_evidence_fields")
    if preferred is not None and (
        not isinstance(preferred, list)
        or any(not isinstance(v, str) or v not in ORIENTATION | SUBSTANTIVE for v in preferred)
    ):
        errors.append("indicator_profile.preferred_evidence_fields:INVALID_FIELDS")

    if not isinstance(assessment, Mapping):
        return errors + ["assessment:EXPECTED_OBJECT"]
    decision = assessment.get("decision")
    if not isinstance(decision, str) or decision not in DECISION_STRENGTHS:
        errors.append("decision:INVALID_DECISION")
    strength = assessment.get("support_strength")
    if type(strength) is not int:
        errors.append("support_strength:EXPECTED_INTEGER")
    elif isinstance(decision, str) and decision in DECISION_STRENGTHS:
        if strength not in DECISION_STRENGTHS[decision]:
            errors.append("support_strength:INCONSISTENT_DECISION")

    supported = assessment.get("supported_key_elements")
    if not _text_list(supported):
        errors.append("supported_key_elements:EXPECTED_NONEMPTY_STRINGS")
    else:
        if catalog_set:
            if any(_normalize(v) not in catalog_set for v in supported):
                errors.append("supported_key_elements:UNKNOWN_ELEMENT")
            if decision == "SUPPORTED" and not supported:
                errors.append("supported_key_elements:REQUIRED_FOR_SUPPORTED")

    explanation = assessment.get("explanation")
    if not isinstance(explanation, str) or not _normalize(explanation):
        errors.append("explanation:EXPECTED_NONEMPTY_STRING")
    evidence = assessment.get("evidence")
    valid_fields = set()
    if not isinstance(evidence, list):
        errors.append("evidence:EXPECTED_ARRAY")
        evidence = []
    if decision == "SUPPORTED" and not evidence:
        errors.append("evidence:REQUIRED_FOR_SUPPORTED")
    for index, item in enumerate(evidence):
        prefix = f"evidence[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{prefix}:EXPECTED_OBJECT")
            continue
        field, text = item.get("field"), item.get("text")
        field_allowed = isinstance(field, str) and field in ORIENTATION | substantive_fields(project_fields)
        if not field_allowed:
            errors.append(f"{prefix}.field:FIELD_NOT_ALLOWED")
        if not isinstance(field, str) or field not in project_fields:
            errors.append(f"{prefix}.field:FIELD_NOT_IN_PROJECT")
            continue
        if not field_allowed:
            continue
        if not isinstance(text, str) or not _normalize(text):
            errors.append(f"{prefix}.text:EXPECTED_NONEMPTY_STRING")
            continue
        value = project_fields[field]
        # Canonical keywords is a list; a quote must occur in one real item.
        values = value if field == "keywords" and isinstance(value, list) else [value]
        if not values or any(not isinstance(v, str) for v in values):
            errors.append(f"{prefix}.field:INVALID_PROJECT_TEXT")
        elif not any(_normalize(text) in _normalize(v) for v in values):
            errors.append(f"{prefix}.text:QUOTE_NOT_FOUND")
        else:
            valid_fields.add(field)
    if decision == "SUPPORTED" and not valid_fields & substantive_fields(project_fields):
        errors.append("evidence:SUBSTANTIVE_FIELD_REQUIRED")
    return errors


def _field_relevance(field, preferred, config):
    relevance = config["field_relevance"]
    if field in ORIENTATION:
        return relevance["orientation"]
    if not preferred:
        return relevance["substantive_without_preferences"]
    return relevance["preferred"] if field in preferred else relevance["substantive_non_preferred"]


def _corroboration(fields, config):
    count = len(set(fields) & SUBSTANTIVE)
    key = ("zero_substantive_fields" if count == 0 else
           "one_substantive_field" if count == 1 else "two_or_more_substantive_fields")
    return config["corroboration"][key]


def _components(indicator_profile, assessment, config):
    # This function is only entered after validation and the applicability gates.
    with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
        catalog = {_normalize(v) for v in indicator_profile["key_elements"]}
        supported = {_normalize(v) for v in assessment["supported_key_elements"]}
        fields = {item["field"] for item in assessment["evidence"]}
        preferred = indicator_profile.get("preferred_evidence_fields") or []
        field_scores = [_field_relevance(field, preferred, config) for field in fields]
        return {
            "key_element_coverage": Decimal(len(supported)) / Decimal(len(catalog)),
            "field_relevance_score": max(field_scores),
            "corroboration_score": _corroboration(fields, config),
            "support_strength_score": Decimal(assessment["support_strength"]) / Decimal(4),
        }


def calculate_confidence_components(project_fields, indicator_profile, assessment, *, config=None):
    """Return Decimal K/F/C/S for a valid computable SUPPORTED assessment.

    Raise ValueError for invalid, inapplicable or uncomputable input. Use
    calculate_raw_confidence for the structured four-status interface.
    """
    settings = _settings(config)
    errors = validate_assessment(project_fields, indicator_profile, assessment)
    if errors:
        raise ValueError("; ".join(errors))
    if assessment["decision"] != "SUPPORTED":
        raise ValueError("Confidence components are NOT_APPLICABLE")
    if not indicator_profile.get("key_elements"):
        raise ValueError("Confidence components are NOT_COMPUTABLE")
    return _components(indicator_profile, assessment, settings)


def calculate_raw_confidence(project_fields, indicator_profile, assessment, *, config=None):
    """Validate -> applicability -> components -> Decimal score, without inference."""
    settings = _settings(config)
    errors = validate_assessment(project_fields, indicator_profile, assessment)
    result = {
        "confidence_version": VERSION,
        "confidence_status": "INVALID_ASSESSMENT",
        **dict.fromkeys(COMPONENT_KEYS),
        "confidence_raw_score": None,
        "confidence_probability": None,
        "confidence_level": None,
        "validation_errors": errors,
    }
    if errors:
        return result
    if assessment["decision"] != "SUPPORTED":
        result["confidence_status"] = "NOT_APPLICABLE"
        return result
    if not indicator_profile.get("key_elements"):
        result["confidence_status"] = "NOT_COMPUTABLE"
        return result
    components = _components(indicator_profile, assessment, settings)
    weights = settings["weights"]
    with localcontext(Context(prec=50, rounding=ROUND_HALF_UP)):
        score = Decimal(100) * (
            weights["key_element_coverage"] * components["key_element_coverage"]
            + weights["field_relevance"] * components["field_relevance_score"]
            + weights["corroboration"] * components["corroboration_score"]
            + weights["support_strength"] * components["support_strength_score"]
        )
        result["confidence_raw_score"] = score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    result.update(components)
    result["confidence_status"] = "COMPUTED"
    return result
