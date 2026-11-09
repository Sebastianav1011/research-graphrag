import csv
import json
from copy import deepcopy

import pyarrow.parquet as pq
import pytest
import yaml

from layer2_processing.preprocessing.canonicalize import canonical_entities, enrich_project_titles
from layer2_processing.preprocessing.identity import resolve
from layer2_processing.preprocessing.normalize import normalize_record
from layer2_processing.preprocessing.pipeline import run
from layer2_processing.preprocessing.quality import production_conflicts
from layer2_processing.preprocessing.ingestion import map_rows, validate_columns, validate_rows
from .conftest import record


def mapped(values, number=2, mapping=None):
    spec = {"mapping": mapping or {"institutional_id": ["id_empleado", "id_investigador"],
                                   "document_number": "cedula", "full_name": "nombre"},
            "unwrap_quoted_fields": ["institutional_id", "document_number"]}
    raw = record(number, **values)
    return normalize_record(map_rows([raw], spec)[0], {})


def title_case(titles):
    projects, _, _, _ = canonical_entities([record(source_project_id="001", convocatoria_nombre="Not a title")], "proyectos", "test")
    members = []
    for number, title in enumerate(titles, 2):
        row = record(number, id_actividad="001", titulo=title)
        row["_file"] = "miembros-doc-limpio.csv"
        members.append(normalize_record(map_rows([row], {"mapping": {
            "source_project_id": "id_actividad", "project_title": "titulo"}})[0], {}))
    events, stats = enrich_project_titles(projects, members, "test")
    return projects[0], events, stats


@pytest.mark.parametrize("titles", [["Real title", "Real title"],
    ['  "Café   regional"  ', "cafe\u0301 regional", "CAFÉ regional"]])
def test_consistent_title_preserves_original_and_all_support(titles):
    project, events, stats = title_case(titles)
    assert project["title"] == titles[0]
    assert project["project_id"] == "PROJ_001" and not events
    assert stats["titles_from_members"] == 1
    refs = json.loads(project["provenance_json"])
    assert refs[0]["record_source"] == "synthetic.csv"
    support = [r for r in refs if "enrichment" in r]
    assert len(support) == len(titles)
    assert all(r["record_source"] == "miembros-doc-limpio.csv" and
               r["field_mapping"]["title"] == "titulo" and
               r["enrichment"]["join_value"] == "001" for r in support)
    assert [r["original_values"]["titulo"] for r in support] == titles


def test_different_titles_are_not_selected():
    project, events, stats = title_case(["First title", "Second title"])
    assert project["title"] is None
    assert events[0]["anomaly_code"] == "PROJECT_TITLE_CONFLICT"
    assert "First title" in events[0]["description"] and "Second title" in events[0]["description"]
    assert stats["conflicts"] == 1
    assert len(json.loads(project["provenance_json"])) == 3


@pytest.mark.parametrize("titles", [[], [None, "", '"  "'], ["NULL", "N/A"]])
def test_absent_title_stays_null_without_convocatoria_fallback(titles):
    project, events, stats = title_case(titles)
    assert project["title"] is None and not events and stats["without_title"] == 1


def test_titles_do_not_leak_across_project_ids():
    project, _, _ = title_case(["Source title"])
    project["title"] = None
    row = mapped({"id_actividad": "OTHER", "titulo": "Wrong title"}, mapping={"source_project_id": "id_actividad", "project_title": "titulo"})
    events, stats = enrich_project_titles([project], [row], "test")
    assert project["title"] is None and stats["titles_from_members"] == 0


def test_employee_and_researcher_aliases_resolve_same_person():
    rows = [mapped({"id_empleado": '"001"', "nombre": "Persona"}),
            mapped({"id_investigador": "001", "nombre": "Persona"}, 3)]
    entities, _, _ = resolve(rows, "test")
    assert len(entities) == 1
    assert entities[0]["institutional_id"] == "001"
    assert entities[0]["identity_rule"] == "exact_institutional_id"
    assert rows[0]["_raw"]["id_empleado"] == '"001"'


@pytest.mark.parametrize("column", ["cedula", "documento", "id_documento", "numero_documento"])
def test_explicit_personal_document_mappings_are_equivalent(column):
    rows = [mapped({column: "002"}, mapping={"document_number": column}),
            mapped({"cedula": "002"}, 3, mapping={"document_number": "cedula"})]
    entities, _, _ = resolve(rows, "test")
    assert len(entities) == 1 and entities[0]["document_number"] == "002"
    assert entities[0]["institutional_id"] is None
    assert entities[0]["identity_rule"] == "exact_document_number"


@pytest.mark.parametrize("rows, field", [
    ([record(institutional_id="I1", document_number="D1"), record(3, institutional_id="I1", document_number="D2")], "document_number"),
    ([record(institutional_id="I1", document_number="D1"), record(3, institutional_id="I2", document_number="D1")], "institutional_id")])
def test_contradictory_identifiers_block_entire_component(rows, field):
    entities, _, events = resolve(deepcopy(rows), "test")
    assert len(entities) == 2 and all(e["identity_status"] == "ambiguous" for e in entities)
    assert all(field in e["_conflict_fields"] for e in entities)
    assert all(field in event["description"] for event in events)


def test_contradictory_aliases_in_same_row_are_not_silently_selected():
    rows = [mapped({"id_empleado": "I1", "id_investigador": "I2"}),
            mapped({"id_empleado": "I1"}, 3), mapped({"id_investigador": "I2"}, 4)]
    entities, assignments, events = resolve(rows, "test")
    assert len(entities) == 3 and all(e["identity_status"] == "ambiguous" for e in entities)
    assert rows[0]["institutional_id"] is None
    assert all(e["_conflict_fields"] == ["institutional_id"] for e in entities)
    reverse, _, _ = resolve(list(reversed(deepcopy(rows))), "test2")
    assert [e["researcher_id"] for e in entities] == [e["researcher_id"] for e in reverse]


def test_document_aliases_keep_intra_row_contradictions():
    row = mapped({"cedula": "D1", "documento": "D2"}, mapping={"document_number": ["cedula", "documento"]})
    entities, _, _ = resolve([row], "test")
    assert entities[0]["document_number"] is None and entities[0]["identity_status"] == "ambiguous"


def test_institutional_and_document_namespaces_do_not_intersect():
    entities, _, _ = resolve([record(institutional_id="123"), record(3, document_number="123")], "test")
    assert len(entities) == 2


def test_invalid_alias_does_not_escape_validation(settings):
    rows = [mapped({"id_empleado": "I1", "id_investigador": "invalid value"})]
    good, rejected, events = validate_rows(rows, "investigadores", settings, "test")
    assert not good and len(rejected) == 1
    assert any(e["anomaly_code"] == "INVALID_IDENTIFIER" for e in events)


def test_all_configured_alias_columns_must_exist(settings):
    events = validate_columns(["id_empleado"], {"mapping": {"institutional_id": ["id_empleado", "id_investigador"]}}, "optional", settings, "test", "members")
    assert events[0]["severity"] == "CRITICAL"


def test_production_conflict_report_projects_existing_quarantine():
    rows = [record(source_article_id="P1", title="A", publication_year=2020),
            record(3, source_article_id="P1", title="B", publication_year=2021)]
    for row in rows:
        row["_source_id"] = "P1"
    canonical, accepted, rejected, events = canonical_entities(rows, "articulos", "test")
    report = production_conflicts(events, rejected)
    assert not canonical and not accepted and len(report) == 2
    assert {r["conflict_group"] for r in report} == {"ART_SRC_P1"}
    assert all(r["resolution_status"] == "UNRESOLVED" for r in report)
    assert {r["title"] for r in report} == {"A", "B"}


def test_new_domain_rules_through_pipeline(workspace):
    config_path = workspace / "config/sources.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for domain in config:
        config[domain]["enabled"] = False
    config["proyectos"] = {"enabled": True, "path": "projects.csv", "type": "csv",
                            "mapping": {"source_project_id": "id_actividad"}}
    config["investigadores"] = {"enabled": True, "path": "members.csv", "type": "csv",
        "mapping": {"source_project_id": "id_actividad", "project_title": "titulo",
                    "institutional_id": ["id_empleado", "id_investigador"],
                    "document_number": "documento", "full_name": "nombre"}}
    (workspace / "projects.csv").write_text("id_actividad,convocatoria_nombre\n1,Not a title\n2,Also not\n3,Never\n", encoding="utf-8")
    (workspace / "members.csv").write_text("id_actividad,titulo,id_empleado,id_investigador,documento,nombre\n1,Project one,I1,,D1,Person A\n1,Project one,,I1,D1,Person A\n2,First,I2,,D2,Person B\n2,Second,I2,,D2,Person B\n", encoding="utf-8")
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    first = run(workspace)
    assert first["status"] == "SUCCESS"
    def tables():
        return {p.stem: [{k: v for k, v in row.items() if k != "etl_run_id"} for row in pq.read_table(p).to_pylist()]
                for p in (workspace / "outputs/layer2/canonical").glob("*.parquet")}
    before = tables()
    assert [p["title"] for p in before["proyectos"]] == ["Project one", None, None]
    assert first["anomalies"]["PROJECT_TITLE_CONFLICT"] == 1
    assert len(before["investigadores"]) == 2
    assert len(before["proyecto_investigador"]) == 2
    refs = json.loads(before["proyectos"][0]["provenance_json"])
    assert refs[0]["record_source"].endswith("projects.csv")
    assert len([r for r in refs if r["record_source"].endswith("members.csv")]) == 2
    quality = workspace / "outputs/layer2/preprocessing/quality"
    with (quality / "production_conflicts.csv").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        assert "resolution_status" in reader.fieldnames and not list(reader)
    assert run(workspace)["status"] == "SUCCESS"
    assert before == tables()
