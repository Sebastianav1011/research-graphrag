import pytest
from layer1_data.normalize import text, name, header, identifier, doi, eid, issn_isbn, email, date_value, keywords


def test_strings_unicode_invisible():
    assert text("  Investigacio\u0301n\u200b   regional\n") == "Investigación regional"
    assert text("") is None
    assert text("NULL") is None


def test_names():
    assert name("  PERSONA   ÁLFA ") == "persona álfa"
    assert name("María") != name("Maria")


def test_headers():
    assert header(" Área Conocimiento ") == "area_conocimiento"


def test_identifiers_preserve_leading_zeros():
    assert identifier("00123.0") == "00123"


def test_doi_eid():
    assert doi("https://doi.org/10.1234/ABC") == "10.1234/abc"
    assert eid("2-s2.0-123456") == "2-s2.0-123456"


def test_serials_emails_keywords():
    assert issn_isbn("1234-567X") == "1234567X"
    assert email(" Example@Example.invalid ") == "example@example.invalid"
    assert keywords("agua; aire ;agua") == ["agua", "aire"]


def test_dates():
    assert date_value("29/02/2024") == "2024-02-29"
    assert date_value("2024-02-29", ["%d/%m/%Y"]) == "2024-02-29"
    with pytest.raises(ValueError):
        date_value("29/02/2025")


def test_source_configured_quote_unwrapping_preserves_original():
    from layer1_data.normalize import normalize_record
    row = {"institutional_id": '"00123"', "_raw": {"id": '"00123"'},
           "_spec": {"unwrap_quoted_fields": ["institutional_id"]}}
    result = normalize_record(row, {})
    assert result["institutional_id"] == "00123"
    assert result["_raw"]["id"] == '"00123"'
