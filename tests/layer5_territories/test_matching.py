"""Deterministic rule tests plus the supplied real DANE reference."""
from copy import deepcopy
from pathlib import Path

import pytest

from layer2_processing.preprocessing.dane_reference import normalize_name
from layer2_processing.preprocessing.dane_reference import inspect_catalog
from layer4_evaluation.territories.matching import extract_territories

ROOT = Path(__file__).resolve().parents[2]


def territory(name, code, kind="MUNICIPALITY", dept="05", department="Antioquia"):
    return {"territory_id": f"DANE:{kind}:{code}", "territory_type": kind,
            "dane_code": code, "territory_name": name, "normalized_name": normalize_name(name),
            "department_code": dept, "department_name": department}


@pytest.fixture
def catalogue():
    return [territory("Antioquia", "05", "DEPARTMENT"),
            territory("Meta", "50", "DEPARTMENT", "50", "Meta"),
            territory("Caldas", "17", "DEPARTMENT", "17", "Caldas"),
            territory("Medellín", "05001"), territory("Caldas", "05129"),
            territory("Granada", "05313"), territory("Granada", "50313", dept="50", department="Meta"),
            territory("Barranquilla", "08001", dept="08", department="Atlántico")]


def extract(catalogue, **fields):
    documents = [{"document_id": "D1", "source_id": "P1", "source_type": "PROJECT", "title": "Test"},
                 {"document_id": "D2", "source_id": "P2", "source_type": "PROJECT", "title": None},
                 {"document_id": "A1", "source_id": "A1", "source_type": "ARTICLE", "title": None}]
    sections = [{"document_id": "D1", "section_id": f"S-{field}", "field_name": field,
                 "text_original": text, "text_normalized": text} for field, text in fields.items()]
    sections += [{"document_id": "A1", "section_id": "AS", "field_name": "title", "text_original": "Medellín"}]
    return extract_territories(documents, sections, catalogue)


def test_unique_department(catalogue):
    result = extract(catalogue, summary="Trabajo en Antioquia.")
    assert result["relationships"] == [{"project_id": "P1", "territory_type": "DEPARTMENT", "dane_code": "05"}]
    assert result["summary"]["total_projects"] == 2


def test_unique_municipality_preserves_zero_and_no_parent(catalogue):
    result = extract(catalogue, summary="Medellín")
    assert result["relationships"] == [{"project_id": "P1", "territory_type": "MUNICIPALITY", "dane_code": "05001"}]


def test_duplicate_municipality_is_ambiguous(catalogue):
    result = extract(catalogue, summary="Actividades desarrolladas en Granada.")
    assert not result["relationships"]
    row, = result["ambiguous"]
    assert row["dane_code"] is None
    assert row["candidate_dane_codes"] == ["05313", "50313"]
    assert row["candidate_count"] == 2


@pytest.mark.parametrize("text", ["municipio de Granada, Meta", "Granada (Meta)", "En el departamento del Meta se estudia Granada."])
def test_duplicate_department_context(catalogue, text):
    result = extract(catalogue, summary=text)
    assert {r["dane_code"] for r in result["relationships"]} == {"50", "50313"}
    assert not result["ambiguous"]


def test_cross_level_ambiguity(catalogue):
    result = extract(catalogue, summary="En Caldas")
    assert not result["relationships"]
    assert result["ambiguous"][0]["candidate_dane_codes"] == ["17", "05129"]


def test_explicit_level(catalogue):
    result = extract(catalogue, summary="Departamento de Caldas.")
    assert result["relationships"][0]["dane_code"] == "17"
    result = extract(catalogue, summary="Municipio de Caldas, Antioquia.")
    assert {r["dane_code"] for r in result["relationships"]} == {"05129", "05"}


@pytest.mark.parametrize("text", ["MEDELLIN", "Medelli\u0301n", "(Medellín),", "Medellín: datos"])
def test_accents_punctuation_and_original_offsets(catalogue, text):
    result = extract(catalogue, summary=text)
    row, = result["evidence"]
    assert row["normalized_match"] == "medellin"
    assert text[row["start_char"]:row["end_char"]] == row["matched_text"]


@pytest.mark.parametrize("text", ["metas del proyecto", "Medellincito", "premedellin", "Medellínx", "Medellon", "Meta del proyecto"])
def test_no_substring_fuzzy_or_common_word(catalogue, text):
    result = extract(catalogue, summary=text)
    assert not result["evidence"] and not result["ambiguous"]


def test_multiple_mentions_fields_deduplicate_bridge(catalogue):
    result = extract(catalogue, summary="Medellín, Medellín.", objectives="Medellín", methodology="Medellín")
    assert len(result["relationships"]) == 1
    assert len(result["evidence"]) == 4
    assert {e["field_name"] for e in result["evidence"]} == {"summary", "objectives", "methodology"}


def test_many_municipalities_and_explicit_distinct_department(catalogue):
    result = extract(catalogue, summary="Medellín y Barranquilla y el departamento de Caldas.")
    assert {r["dane_code"] for r in result["relationships"]} == {"05001", "08001", "17"}
    assert result["summary"]["projects_with_multiple_territories"] == 1


def test_no_cross_field_or_sentence_context(catalogue):
    result = extract(catalogue, summary="Granada. Antioquia.", title="Antioquia", objectives="Granada")
    assert len(result["ambiguous"]) == 2
    assert {r["dane_code"] for r in result["relationships"]} == {"05"}


def test_conflicting_department_does_not_resolve_unique_city(catalogue):
    result = extract(catalogue, summary="Municipio de Medellín, Meta")
    assert not any(r["dane_code"] == "05001" for r in result["relationships"])
    assert result["ambiguous"][0]["candidate_dane_codes"] == ["05001"]


def test_no_broad_region_or_institution_inference(catalogue):
    data = catalogue + [territory("Magdalena", "47", "DEPARTMENT", "47", "Magdalena"),
                        territory("Colombia", "41206", dept="41", department="Huila")]
    result = extract(data, summary="Región Caribe, Amazonía, Orinoquía, Pacífico y Magdalena Medio. Universidad de Antioquia. Colombia.")
    assert not result["relationships"] and not result["ambiguous"]


def test_longest_name_wins(catalogue):
    data = catalogue + [territory("Cauca", "19", "DEPARTMENT", "19", "Cauca"),
                        territory("Valle del Cauca", "76", "DEPARTMENT", "76", "Valle del Cauca")]
    result = extract(data, summary="Valle del Cauca")
    assert [r["dane_code"] for r in result["relationships"]] == ["76"]


def test_repeated_execution_same_logical_output_and_no_mutation(catalogue):
    original = deepcopy(catalogue)
    first = extract(catalogue, title="Medellín", summary="Granada, Meta")
    assert first == extract(list(reversed(catalogue)), title="Medellín", summary="Granada, Meta")
    assert catalogue == original


@pytest.fixture(scope="module")
def real_catalogue():
    return inspect_catalog(ROOT / "data/layer1_sources/reference/Codigos Dane/Tabla_Codigos_Dane.xlsx", ROOT)[0]


def test_real_automatically_detected_duplicate_names(real_catalogue):
    from collections import defaultdict
    names = defaultdict(list)
    for row in real_catalogue:
        if row["territory_type"] == "MUNICIPALITY":
            names[row["normalized_name"]].append(row)
    duplicates = {name: rows for name, rows in names.items() if len(rows) > 1}
    assert duplicates
    for rows in duplicates.values():
        result = extract(real_catalogue, summary=f"municipio de {rows[0]['territory_name']}")
        assert not result["relationships"], rows[0]["territory_name"]
        assert result["ambiguous"][0]["candidate_count"] == len(rows)
        assert set(result["ambiguous"][0]["candidate_dane_codes"]) == {r["dane_code"] for r in rows}


def test_real_duplicate_resolves_with_explicit_parent(real_catalogue):
    from collections import defaultdict
    names = defaultdict(list)
    for row in real_catalogue:
        if row["territory_type"] == "MUNICIPALITY":
            names[row["normalized_name"]].append(row)
    for rows in names.values():
        if len(rows) > 1:
            for row in rows:
                result = extract(real_catalogue, summary=f"municipio de {row['territory_name']}, departamento de {row['department_name']}")
                assert row["dane_code"] in {r["dane_code"] for r in result["relationships"]}, row


def test_real_all_project_fields_coverage_and_determinism(real_catalogue):
    import pyarrow.parquet as pq
    documents = pq.read_table(ROOT / "outputs/layer2/knowledge/source_documents.parquet").to_pylist()
    sections = pq.read_table(ROOT / "outputs/layer2/knowledge/source_sections.parquet").to_pylist()
    result = extract_territories(documents, sections, real_catalogue)
    assert result["summary"]["total_projects"] == sum(d["source_type"] == "PROJECT" for d in documents)
    assert result["summary"]["total_projects"] > 464
    assert result == extract_territories(documents, sections, real_catalogue)
    assert all(r["dane_code"] is None for r in result["ambiguous"])
    assert len(result["relationships"]) == len({(r["project_id"], r["territory_type"], r["dane_code"]) for r in result["relationships"]})


@pytest.fixture
def country_catalogue(catalogue):
    return catalogue + [territory("Colombia", "41206", dept="41", department="Huila"),
                        territory("Huila", "41", "DEPARTMENT", "41", "Huila"),
                        territory("Colombia", "000", "COUNTRY", None, None)]


@pytest.mark.parametrize("text", ["Colombia", "Estudio realizado en Colombia."])
def test_country_only_when_explicitly_mentioned(country_catalogue, text):
    result = extract(country_catalogue, summary=text)
    assert [r["dane_code"] for r in result["relationships"]] == ["000"]
    assert result["evidence"][0]["resolution_method"] == "EXPLICIT_COUNTRY_NAME"


def test_country_not_a_fallback(country_catalogue):
    assert not extract(country_catalogue, summary="Investigación sin localización.")["relationships"]


def test_country_suppressed_by_specific_resolved_territory(country_catalogue):
    result = extract(country_catalogue, summary="Colombia. Medellín.")
    assert [r["dane_code"] for r in result["relationships"]] == ["05001"]
    assert [r["dane_code"] for r in result["evidence"]] == ["05001"]
    assert result["national_mentions"][0]["publication_status"] == "SUPPRESSED_SPECIFIC_TERRITORY"


@pytest.mark.parametrize("text", ["municipio de Colombia", "Colombia (Huila)"])
def test_colombia_municipality_not_country(country_catalogue, text):
    result = extract(country_catalogue, summary=text)
    assert "41206" in {r["dane_code"] for r in result["relationships"]}
    assert "000" not in {r["dane_code"] for r in result["relationships"]}


def test_institution_colombia_not_national_scope(country_catalogue):
    result = extract(country_catalogue, summary="Universidad Nacional de Colombia. Banco de la República de Colombia.")
    assert not result["relationships"] and not result["ambiguous"]


def test_real_corpus_common_nouns_and_citation_surnames_guarded(real_catalogue):
    result = extract(real_catalogue, summary="La fundación realizará la purificación. Amplia gama de tratamientos. López y González, 2020. Se une a la proteína. Actividades en la pesca y la contratación.")
    assert not result["relationships"] and not result["ambiguous"]
    result = extract(real_catalogue, summary="Municipio de Fundación, departamento de Magdalena.")
    assert "47288" in {r["dane_code"] for r in result["relationships"]}


def test_rivers_and_lower_administrative_levels_not_municipality_or_department(catalogue):
    result = extract(catalogue, summary="río Antioquia. barrio Medellín. localidad de Caldas. vereda Granada.")
    assert not result["relationships"] and not result["ambiguous"]


def test_explicit_type_does_not_cross_sentence(catalogue):
    result = extract(catalogue, summary="Municipio de. Caldas.")
    assert not result["relationships"]


@pytest.mark.parametrize("text", ["ciudades de Colombia", "municipios de Colombia", "departamentos de Colombia"])
def test_plural_country_subdivisions_are_country(country_catalogue, text):
    result = extract(country_catalogue, summary=text)
    assert [r["dane_code"] for r in result["relationships"]] == ["000"]


def test_natural_features_ethnic_groups_and_districts_not_municipalities(real_catalogue):
    result = extract(real_catalogue, summary="Pueblo Pijao. Ciénaga Grande de Santa Marta. Sierra Nevada de Santa Marta. Localidad de Ciudad Bolívar. Parque Nacional Natural de La Macarena.")
    assert not result["relationships"] and not result["ambiguous"]


def test_unlisted_expanded_name_not_truncated_to_another_department(real_catalogue):
    result = extract(real_catalogue, summary="Norte de Santander. Cuenca del Cauca. Chocó biogeográfico.")
    assert not result["relationships"] and not result["ambiguous"]
    result = extract(real_catalogue, summary="Departamento de N. de Santander.")
    assert "54" in {r["dane_code"] for r in result["relationships"]}


@pytest.mark.parametrize("text", [
    "Menjívar y Abrego (2012) denominan el concepto.",
    "El nivel de confort, confianza y agrado general.",
    "Instituto Geográfico Agustín Codazzi (IGAC).",
    "Pilar Riaño-Alcalá y Erin Baines (2011).",
    "Orígenes de Alejandría y Agustín de Hipona.",
    "La región Pacífico está mejor monitoreada que el Atlántico.",
    "Alonso,D. Barbosa,H. Duque y otros autores.",
])
def test_real_review_false_positive_patterns_suppressed(real_catalogue, text):
    result = extract(real_catalogue, summary=text)
    assert not result["relationships"] and not result["ambiguous"]


def test_institution_geographic_placement_preserved(catalogue):
    result = extract(catalogue, summary="El instituto ubicado en Medellín desarrolla el trabajo.")
    assert [r["dane_code"] for r in result["relationships"]] == ["05001"]


def test_city_list_is_not_an_incompatible_department_pair(real_catalogue):
    result = extract(real_catalogue, summary="Barranquilla, Bogotá, Bucaramanga, Cali, Medellín.")
    names = {row["territory_name"] for row in result["evidence"]}
    assert {"BARRANQUILLA", "BUCARAMANGA", "CALI", "MEDELLIN"} <= names
    assert not any(r["normalized_match"] in {"barranquilla", "bucaramanga", "cali", "medellin"}
                   for r in result["ambiguous"])


def test_geographic_name_with_year_is_preserved(catalogue):
    result = extract(catalogue, summary="El trabajo se realizó en Medellín (2020).")
    assert [r["dane_code"] for r in result["relationships"]] == ["05001"]


def test_hyphenated_bibliographic_surname_not_municipality(real_catalogue):
    result = extract(real_catalogue, summary='Castillo-Briceño & Navarrete-Mier, 2015.')
    assert not result['relationships'] and not result['ambiguous']


def test_comma_separated_author_list_not_territorial_list(real_catalogue):
    result = extract(real_catalogue, summary='Briceño, Enciso, & Yepes, 2018.')
    assert not result['relationships'] and not result['ambiguous']


def test_author_surname_followed_by_initials_not_territory(real_catalogue):
    result = extract(real_catalogue, summary='[6] Briceño L., Torres M., Córdoba A., Le Blanc J.')
    assert not result['relationships'] and not result['ambiguous']


def test_mention_summary_reconciles_suppressed_country(country_catalogue):
    result = extract(country_catalogue, summary="Colombia. Medellín. Granada.")
    summary = result["summary"]
    assert summary["resolved_mentions"] == 1
    assert summary["ambiguous_mentions"] == 1
    assert summary["suppressed_national_mentions"] == 1
    assert summary["total_detected_mentions"] == 2
    assert summary["all_detected_mentions"] == 3
    assert summary["all_resolved_mentions"] == 2
    assert summary["resolved_mention_percentage"] == 50
    assert summary["all_resolved_mention_percentage"] == pytest.approx(200 / 3)
    assert summary["all_ambiguous_mention_percentage"] == pytest.approx(100 / 3)
    assert summary["mention_percentage_denominator"] == "published_resolved_plus_ambiguous_excludes_suppressed_country"


@pytest.mark.parametrize("text", [
    "the Agustin Codazzi Geographic Institute (IGAC)",
    "Corporación Autónoma Regional del Cauca (CRC)",
    "the fluvial star or Almaguer Knot contains hydrographic basins",
    "corregimientos de Carmen de Pijiño y/o Peñoncito y/o Puerto Arturo y/o Cabrera y/o Angostura, aledaños al río",
    "Schneider MC, Aguilera XP, Smith RM, Moynihan MJ, Barbosa da Silva J, Aldighieri A, Almiron M,2011",
    "(Colombia,2022)",
])
def test_additional_real_review_patterns_general_guards(real_catalogue, text):
    result = extract(real_catalogue, summary=text)
    assert not result["relationships"] and not result["ambiguous"]


def test_lower_level_list_context_ends_at_new_clause(catalogue):
    result = extract(catalogue, summary="Veredas de una localidad, situadas en Medellín. Municipio de Caldas.")
    assert {r["dane_code"] for r in result["relationships"]} == {"05001", "05129"}


def test_country_geographic_cue_with_year_preserved(country_catalogue):
    result = extract(country_catalogue, summary="Trabajo realizado en Colombia,2022.")
    assert [r["dane_code"] for r in result["relationships"]] == ["000"]


def test_multiple_department_context_does_not_pick_one_municipality(catalogue):
    result = extract(catalogue, summary="Municipio de Granada con actividades en Antioquia y en Meta")
    assert not any(r["territory_type"] == "MUNICIPALITY" for r in result["relationships"])
    assert result["ambiguous"][0]["candidate_count"] == 2


def test_distant_department_context_not_used(catalogue):
    text = "Municipio de Granada " + ("actividad " * 40) + "en Antioquia"
    result = extract(catalogue, summary=text)
    assert not any(r["territory_type"] == "MUNICIPALITY" for r in result["relationships"])
    assert result["ambiguous"][0]["candidate_count"] == 2


def test_explicit_pair_has_priority_over_other_local_departments(catalogue):
    result = extract(catalogue, summary="Granada (Meta) realiza actividades y en Antioquia se evalúan otras acciones")
    assert "50313" in {r["dane_code"] for r in result["relationships"]}


def test_real_cross_level_name_in_long_department_list_is_not_municipality(real_catalogue):
    result = extract(real_catalogue, summary="En Córdoba se evalúan actividades en Quindío y en Cauca y en Huila y en Tolima")
    assert not any(row["normalized_match"] == "cordoba" and row["territory_type"] == "MUNICIPALITY" for row in result["evidence"])


def test_river_list_not_department_or_municipality(real_catalogue):
    result = extract(real_catalogue, summary="Los ríos Guaviare, Apaporis, Caquetá, Putumayo y Amazonas se estudian")
    assert not result["relationships"] and not result["ambiguous"]
