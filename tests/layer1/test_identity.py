from copy import deepcopy
from layer1_data.identity import resolve
from conftest import record


def test_institutional_match():
    rows = [record(institutional_id="EMP1", full_name="Persona A"), record(3, institutional_id="EMP1", full_name="Persona A.")]
    entities, assignments, events = resolve(rows, "run")
    assert len(entities) == 1 and not events
    assert entities[0]["identity_rule"] == "exact_institutional_id"


def test_document_match_and_institutional_priority():
    rows = [record(institutional_id="EMP1", document_number="DOC1"),
            record(3, document_number="DOC1", full_name="Persona A")]
    entities, _, _ = resolve(rows, "run")
    assert len(entities) == 1 and entities[0]["institutional_id"] == "EMP1"


def test_external_match():
    entities, _, _ = resolve([record(external_id="EXT1"), record(3, external_id="EXT1")], "run")
    assert len(entities) == 1 and entities[0]["identity_rule"] == "exact_external_id"


def test_name_with_structured_evidence():
    rows = [record(full_name="Persona A", email="a@example.invalid"), record(3, full_name="Persona A", email="a@example.invalid")]
    entities, _, _ = resolve(rows, "run")
    assert len(entities) == 1 and entities[0]["identity_rule"] == "exact_name_and_email"


def test_names_alone_are_not_merged():
    entities, _, events = resolve([record(full_name="Persona A"), record(3, full_name="Persona A")], "run")
    assert len(entities) == 2
    assert {r["identity_status"] for r in entities} == {"ambiguous"}
    assert len(events) == 2


def test_unresolved():
    entities, _, _ = resolve([record(full_name="Persona A")], "run")
    assert entities[0]["identity_status"] == "unresolved"


def test_conflicting_bridge_never_merges():
    rows = [record(institutional_id="EMP1", document_number="D1"),
            record(3, institutional_id="EMP2", document_number="D1"),
            record(4, institutional_id="EMP2")]
    entities, _, _ = resolve(rows, "run")
    assert len(entities) == 3
    assert {r["identity_status"] for r in entities} == {"ambiguous"}


def test_deterministic_and_order_independent():
    rows = [record(institutional_id="EMP1", document_number="D1"), record(3, document_number="D1")]
    first, _, _ = resolve(deepcopy(rows), "run1")
    second, _, _ = resolve(list(reversed(deepcopy(rows))), "run2")
    assert [r["researcher_id"] for r in first] == [r["researcher_id"] for r in second]


def test_homonyms_with_distinct_ids_stay_distinct():
    rows = [record(institutional_id="EMP1", full_name="Persona A"), record(3, institutional_id="EMP2", full_name="Persona A")]
    entities, _, _ = resolve(rows, "run")
    assert len(entities) == 2

