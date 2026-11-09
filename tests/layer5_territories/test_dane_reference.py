"""Reference integrity and real-catalog collision tests; no external calls."""
from pathlib import Path

from openpyxl import Workbook
import pytest

from layer2_processing.preprocessing.dane_reference import build_reference, inspect_catalog, load_reference, normalize_name

ROOT = Path(__file__).resolve().parents[2]


def workbook_at(root, rows):
    source = root / "data/reference/input.xlsx"
    source.parent.mkdir(parents=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    for row in [("Código", "Nombre", "Código", None), (None, None, None, "Nombre Municipio"),
                ("Departamento", "Departamento", "Municipio", None), *rows]:
        sheet.append(row)
    workbook.save(source)
    return source


def test_leading_zeros_and_construction(tmp_path):
    source = workbook_at(tmp_path, [("05", "ANTIOQUIA", "001", "MEDELLÍN"),
                                    (13, "BOLIVAR", 100, "FIRST")])
    rows, manifest = build_reference(tmp_path, source)
    assert manifest["validation"]["codes_are_strings"]
    municipality = next(row for row in rows if row["dane_code"] == "05001")
    assert municipality["municipality_code"] == "001"
    assert municipality["department_code"] == "05"
    assert municipality["parent_territory_id"] == "DANE:DEPARTMENT:05"
    assert municipality["territory_name"] == "MEDELLÍN"
    assert municipality["source_row"] == 4
    assert all(isinstance(row["dane_code"], str) for row in rows)
    assert next(row for row in rows if row["dane_code"] == "05")["municipality_code"] is None
    assert load_reference(tmp_path / "outputs/layer2/reference") == (rows, manifest)


def test_normalization():
    assert normalize_name("  San  ANDRÉS,  ") == "san andres"
    assert normalize_name("N. DE SANTANDER") == "n de santander"
    assert normalize_name("Meta") != normalize_name("metas")


@pytest.mark.parametrize("row", [("5", "A", "001", "B"), ("05", "A", 1, "B"),
                                  ("05", "A", "0001", "B"), ("05", "A", "001", None),
                                  (True, "A", "001", "B"), ("05", "A", "=1", "B")])
def test_invalid_codes_names_fail_closed(tmp_path, row):
    source = workbook_at(tmp_path, [row])
    with pytest.raises(ValueError):
        build_reference(tmp_path, source)


def test_duplicate_codes_fail(tmp_path):
    source = workbook_at(tmp_path, [("05", "A", "001", "B"), ("05", "A", "001", "C")])
    with pytest.raises(ValueError, match="Duplicate municipality"):
        build_reference(tmp_path, source)


def test_conflicting_department_names_fail(tmp_path):
    source = workbook_at(tmp_path, [("05", "A", "001", "B"), ("05", "C", "002", "D")])
    with pytest.raises(ValueError, match="Conflicting department"):
        build_reference(tmp_path, source)


def test_repeated_and_cross_level_names_are_indexed(tmp_path):
    source = workbook_at(tmp_path, [("05", "CALDAS", "001", "GRANADA"),
                                    ("13", "B", "001", "GRANADA"), ("05", "CALDAS", "002", "CALDAS")])
    _, audit, index = inspect_catalog(source, tmp_path)
    assert audit["duplicate_normalized_name_groups"] == 1
    assert audit["cross_level_name_count"] == 1
    assert next(x for x in index if x["normalized_name"] == "granada")["candidate_count"] == 2


def test_user_defined_country_is_separate_from_dane(tmp_path):
    source = workbook_at(tmp_path, [("41", "HUILA", "206", "COLOMBIA")])
    from openpyxl import load_workbook
    workbook = load_workbook(source)
    sheet = workbook.create_sheet("ALCANCE_NACIONAL")
    sheet.append(["code", "name", "type"])
    sheet.append(["000", "Colombia", "COUNTRY"])
    workbook.save(source)
    rows, manifest = build_reference(tmp_path, source)
    assert manifest["country_count"] == 1
    assert manifest["department_count"] == manifest["municipality_count"] == 1
    country = next(row for row in rows if row["territory_type"] == "COUNTRY")
    assert country["dane_code"] == "000"
    assert country["territory_origin"] == "USER_DEFINED_COUNTRY"
    assert country["department_code"] is country["municipality_code"] is country["parent_territory_id"] is None
    assert len([row for row in rows if row["normalized_name"] == "colombia"]) == 2
    assert (tmp_path / "outputs/layer2/reference/dane_source.xlsx").read_bytes() == source.read_bytes()


def test_deterministic_version_and_tamper_detection(tmp_path):
    source = workbook_at(tmp_path, [("05", "A", "001", "B")])
    first = build_reference(tmp_path, source)
    second = build_reference(tmp_path, source)
    assert first == second
    output = tmp_path / "outputs/layer2/reference"
    path = output / "dane_ambiguity_index.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_reference(output)


def test_header_change_is_not_guessed(tmp_path):
    source = workbook_at(tmp_path, [("05", "A", "001", "B")])
    from openpyxl import load_workbook
    workbook = load_workbook(source)
    workbook.active.cell(1, 1, "OTHER")
    workbook.save(source)
    with pytest.raises(ValueError, match="headers"):
        build_reference(tmp_path, source)


def test_output_cannot_modify_canonical_or_source(tmp_path):
    source = workbook_at(tmp_path, [("05", "A", "001", "B")])
    with pytest.raises(ValueError, match="independently"):
        build_reference(tmp_path, source, tmp_path / "outputs/layer2/canonical")
    with pytest.raises(ValueError, match="source workbook"):
        build_reference(tmp_path, source, source.parent)


def test_real_catalog_schema_counts_and_automatically_detected_duplicates():
    source = ROOT / "data/layer1_sources/reference/Codigos Dane/Tabla_Codigos_Dane.xlsx"
    if not source.exists():
        pytest.fail("Required supplied real DANE workbook is missing")
    rows, audit, index = inspect_catalog(source, ROOT)
    assert audit["department_count"] == 33
    assert audit["municipality_count"] == 1120
    assert audit["header_rows"] == [1, 2, 3]
    assert all(value == 0 for value in audit["null_counts_nonempty_rows"].values())
    duplicates = [entry for entry in index if entry["candidate_count"] > 1]
    assert duplicates
    for entry in duplicates:
        candidates = [row for row in rows if row["normalized_name"] == entry["normalized_name"]
                      and row["territory_type"] == entry["territory_type"]]
        assert len(candidates) == entry["candidate_count"]
        assert len({candidate["dane_code"] for candidate in candidates}) == len(candidates)
    assert len({row["territory_id"] for row in rows}) == len(rows)
    widths = {"DEPARTMENT": 2, "MUNICIPALITY": 5, "COUNTRY": 3}
    assert all(len(row["dane_code"]) == widths[row["territory_type"]] for row in rows)
