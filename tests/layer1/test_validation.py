from layer1_data.ingestion import validate_columns, validate_rows
from conftest import record


def test_required_columns(settings):
    errors = validate_columns(["title"], {"mapping": {"title": "title"}}, "proyectos", settings, "test", "source")
    assert errors[0]["anomaly_code"] == "MISSING_REQUIRED_COLUMN"


def test_required_id(settings):
    good, bad, events = validate_rows([record(title="Synthetic")], "proyectos", settings, "test")
    assert not good and len(bad) == 1
    assert events[0]["anomaly_code"] == "MISSING_REQUIRED_FIELD"


def test_duplicates_are_audited_not_silently_discarded(settings):
    good, bad, events = validate_rows([record(source_project_id="1"), record(3, source_project_id="1")], "proyectos", settings, "test")
    assert len(good) == 2 and not bad
    assert events[0]["anomaly_code"] == "DUPLICATE_SOURCE_ID"


def test_invalid_date(settings):
    good, bad, events = validate_rows([record(source_project_id="1", start_date="2025-02-30")], "proyectos", settings, "test")
    assert not good and len(bad) == 1
    assert events[0]["anomaly_code"] == "INVALID_DATE"


def test_bad_optional_doi_excluded_but_original_preserved(settings):
    good, _, events = validate_rows([record(title="Test", doi="not-a-doi")], "articulos", settings, "test")
    assert good[0]["doi"] is None
    assert good[0]["_raw"]["doi"] == "not-a-doi"
    assert events[0]["severity"] == "WARNING"


def test_impossible_year_and_type(settings):
    for year, code in [("future", "INVALID_TYPE"), ("-10", "IMPOSSIBLE_VALUE")]:
        good, bad, events = validate_rows([record(title="Test", publication_year=year)], "articulos", settings, "test")
        assert bad and not good
        assert any(e["anomaly_code"] == code for e in events)


def test_personal_identifier_not_exposed_in_anomaly(settings):
    _, _, events = validate_rows([record(institutional_id="SECRET NUMBER")], "investigadores", settings, "test")
    assert events and all(e["source_object_id"] is None for e in events)
    assert "SECRET NUMBER" not in str(events)

