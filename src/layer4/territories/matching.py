"""Deterministic PROJECT territory mentions, independent of GraphRAG and models.

Names come exclusively from the supplied reference. Offsets refer to the original
section string; normalized text is a temporary matching representation only.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from bisect import bisect_left
import re
import unicodedata

from layer1_data.dane_reference import normalize_name

EXTRACTOR_VERSION = "1.0.0"
FIELDS = ("title", "keywords", "summary", "methodology", "objectives", "expected_results")
ACTIVE_RULES = ["exact_normalized_phrase_boundaries", "longest_nonoverlapping_names",
                "explicit_level", "unique_name", "same_sentence_department_context",
                "common_word_geographic_guard", "no_parent_inference",
                "bibliographic_context_guard", "institution_name_guard", "bounded_department_pairs",
                "single_department_context_max_250_characters",
                "no_region_expansion", "no_llm_no_fuzzy_no_external_services"]

# Exact lexical guards, applied equally to every project. These names are also
# common words, persons, countries, or concepts. A geographical syntactic cue is
# required; capitalization alone is never sufficient.
GUARDED_NAMES = frozenset(normalize_name(x) for x in (
    "Colombia", "Argentina", "Armenia", "Caldas", "Bolívar", "Córdoba", "Cesar",
    "Sucre", "Magdalena", "Meta", "Valencia", "Concordia", "Convención", "La Unión",
    "Unión", "El Banco", "El Paso", "El Retorno", "La Victoria", "Victoria",
    "La Esperanza", "La Paz", "La Gloria", "La Palma", "La Sierra", "La Tebaida",
    "El Paujil", "La Plata", "La Cruz", "La Florida", "Florida", "Los Andes",
    "El Carmen", "El Águila", "El Molino", "El Colegio", "El Dorado", "La Vega",
    "El Rosario", "La Argentina", "Salamina", "Santiago", "Providencia", "La Merced",
    "Sabanas de San Ángel", "Buenavista", "Vista Hermosa", "Tierra Alta", "La Apartada",
    "El Peñón", "El Roble", "El Tablón de Gómez", "La Belleza", "Socorro", "El Guamo",
    "El Cerrito", "El Dovio", "Puerto Rico", "San José", "Santa Rosa", "Santo Domingo",
))

# The real-corpus audit exposed citations and ordinary domain vocabulary that
# exactly equal municipal names. Even "en la pesca" or "en la fundación" is
# insufficient evidence; these require an explicit level or adjacent department.
STRICT_GUARDED_NAMES = frozenset(normalize_name(x) for x in (
    "Fundación", "López", "González", "Páramo", "Purificación", "Contratación", "Gama",
    "Gutiérrez", "Toro", "Rivera", "Retiro", "El Retiro", "Une", "Apartadó", "Pesca",
    "Medina", "Giraldo", "Murillo", "Salazar", "La Mesa", "La Peña", "Vélez", "Madrid",
    "Trujillo", "Garzón", "Ortega", "Distracción", "Fonseca", "Jardín", "Andes", "Bello",
    "Suárez", "Restrepo", "Cabrera", "Morales", "Colón", "Concepción", "Rosal", "El Rosal",
    "Rosas", "Plato", "La Cumbre", "Cumbre", "Toledo", "Sevilla", "Buenos Aires",
    "La Paz", "El Paso", "La Unión", "La Esperanza", "La Victoria", "El Banco", "La Plata",
    "El Colegio", "La Cruz", "El Retorno", "Convención", "La Belleza", "Salamina", "Santiago",
    "Colombia", "Argentina", "La Argentina", "Armenia", "Herrera", "Pizarro", "Uribe",
    "Pedraza", "Arboleda", "Ospina", "Leticia", "Beltrán", "Ulloa", "Piedras", "Miranda",
    "Dolores", "Acevedo", "Caicedo", "Hato", "Carolina", "Solano", "Soledad", "Jordán",
    "Vergara", "Arbeláez", "Elías", "Prado", "Turbo", "Olaya", "Almeida", "Alvarado",
    "Trinidad", "La Estrella", "Montenegro", "Cáceres", "Padilla", "Pacho", "Aldana",
    "Corrales", "Barbacoas", "Ginebra", "Saldaña", "Santuario", "Espinal", "Palermo",
    "Santana", "Zambrano", "Honda", "Margarita", "Gigante", "Cota", "Gamarra", "Girón",
    "Génova", "Valdivia", "Monterrey", "Chía", "Silos", "Calamar", "El Bagre", "Obando",
    "California", "San Diego", "La Chorrera", "Silvia", "La Sierra", "La Cumbre",
    "Ciénaga", "Pijao", "Ciudad Bolívar",
    "Abrego", "Ábrego", "Agrado", "Alcalá", "Alejandría", "Atlántico", "Almaguer", "Angostura", "Barbosa",
))

_LEVEL = re.compile(r"\b(municipios?|ciudad(?:es)?|departamentos?)\s+(?:(?:de|del)\s+)?$")
_SPATIAL = re.compile(r"\b(?:en|desde|hacia|hasta|entre|territorio de|region de|zona de|localidad de|poblacion de|habitantes de|rural de|urbana de|ubicad[oa] en)\s+(?:(?:el|la|los|las)\s+)?$")


def _normalized_offsets(text):
    """Return the exact reference normal form plus original character positions."""
    chars, starts, ends = [], [], []
    for pos, char in enumerate(text):
        plain = "".join(part for part in unicodedata.normalize("NFKD", char)
                        if not unicodedata.combining(part)).casefold()
        if not plain and ends:
            ends[-1] = pos + 1
        for part in plain:
            value = part if part.isalnum() else " "
            if value == " " and (not chars or chars[-1] == " "):
                if chars:
                    ends[-1] = pos + 1
                continue
            chars.append(value)
            starts.append(pos)
            ends.append(pos + 1)
    if chars and chars[-1] == " ":
        chars.pop(); starts.pop(); ends.pop()
    normalized = "".join(chars)
    if normalized != normalize_name(text):
        raise ValueError("Reference normalization and mention offsets disagree")
    return normalized, starts, ends


def _sentence_separators(text):
    # Never borrow context across a sentence, semicolon, or list/keyword line.
    return [hit.start() for hit in re.finditer(r"[.!?;\n\r]", text)
            if not (hit.group() == "." and hit.start() > 0 and text[hit.start() - 1].isalpha()
                    and (hit.start() < 2 or not text[hit.start() - 2].isalnum()))]


def _sentence_bounds(text, start, end, separators):
    # Preserve the supplied abbreviation N. DE SANTANDER as one context unit.
    before, after = bisect_left(separators, start), bisect_left(separators, end)
    left = separators[before - 1] + 1 if before else 0
    right = separators[after] if after < len(separators) else len(text)
    return left, right


def _candidates_payload(candidates):
    rows = sorted(candidates, key=lambda t: (t["territory_type"], t["dane_code"]))
    return {"candidate_count": len(rows),
            "candidate_dane_codes": [r["dane_code"] for r in rows],
            "candidate_names": [r["territory_name"] for r in rows],
            "candidate_departments": [r["department_name"] for r in rows],
            "candidate_territory_types": [r["territory_type"] for r in rows]}


def _name_pattern(names):
    # A prefix trie gives exact longest-first phrases without trying every DANE
    # name at every character of the complete project corpus.
    trie = {}
    for name in sorted(names):
        node = trie
        for character in name:
            node = node.setdefault(character, {})
        node[""] = None

    def branch(node):
        choices = [re.escape(char) + branch(child) for char, child in sorted(node.items()) if char]
        if "" in node:
            choices.append("")  # terminal last, so contained names are longest-first
        return choices[0] if len(choices) == 1 else "(?:" + "|".join(choices) + ")"

    return re.compile(r"(?<!\w)" + branch(trie) + r"(?!\w)")


def _mentions(text, index, pattern):
    normalized, starts, ends = _normalized_offsets(text)
    separators = _sentence_separators(text)
    mentions = []
    for hit in pattern.finditer(normalized):
        start, end = starts[hit.start()], ends[hit.end() - 1]
        name = hit.group()
        left, right = _sentence_bounds(text, start, end, separators)
        before = normalized[max(bisect_left(starts, left), hit.start() - 100):hit.start()]
        after = normalized[hit.end():hit.end() + 30]
        explicit_level = bool(_LEVEL.search(before))
        spatial = bool(_SPATIAL.search(before))
        original_after = text[end:min(right, end + 100)]
        sentence_prefix = normalize_name(text[max(left, start - 600):start])
        lower_markers = list(re.finditer(r"\b(?:corregimientos?|veredas?|barrios?|comunas?|localidad(?:es)?|caserios?|resguardos?|rios?|quebradas?|lagunas?|cuencas?|embalses?|cordilleras?|sierras?|parques?)\b", sentence_prefix))
        lower_list = False
        if lower_markers:
            tail = sentence_prefix[lower_markers[-1].end():]
            # Carry an explicitly lower-level list only inside this sentence;
            # a new administrative level or location clause ends the list.
            lower_list = not re.search(r"\b(?:municipios?|ciudades?|departamentos?|en|donde|que|para|desde|hacia|pertenec\w*|ubicad\w*|situad\w*|localizad\w*|aleda\w*)\b", tail)
        # Citation punctuation and author-year syntax do not assert geography.
        # Explicit geographical syntax takes precedence (e.g. en Medellín, 2020).
        citation = (not explicit_level and not spatial and (
            re.match(r"\s*,[^.;\n]{0,70}&[^.;\n]{0,50}\b[12][0-9]{3}\b", original_after)
            or
            re.match(r"\s*,?\s*(?:\(\s*[12][0-9]{3}[a-z]?\s*\)|[12][0-9]{3}\b|et\s+al\b)", original_after, re.I)
            or re.match(r"\s*,\s*[A-ZÁÉÍÓÚÑ]\s*\.", original_after)
            or re.match(r"\s+[A-ZÁÉÍÓÚÑ](?:\s*[A-ZÁÉÍÓÚÑ])?\s*\.\s*[,;]", original_after)
            or re.match(r"\s+(?:da|de|do|das|dos|van|von)\s+\w+\s+[A-Z]{1,3}\s*[,;.]", original_after)))
        hyphenated_author = (not explicit_level and not spatial
            and re.search(r"[^\W\d_]+[-–]$", text[max(left, start - 80):start])
            and re.search(r"(?:&|\by\b|\bet al\b).{0,70}\b[12][0-9]{3}\b", original_after, re.I))
        institution = (not explicit_level and not spatial and re.search(
            r"\b(?:universidad|universite|university|instituto|hospital|colegio|banco|corporacion)(?:\s+\w+){0,5}\s+$", before))
        postpositive_institution = re.match(r"\s+(?:(?:geographic|geographical|regional|national|research|medical|educational)\s+){0,3}(?:institute|university|hospital|college|bank)\b", after)
        postpositive_feature = re.match(r"\s+(?:knot|river|basin|lagoon|lake|mountains?|range|ridge|wetland|forest|park)\b", after)
        # Functional regions are not their contained names. Institution and
        # named-person references alone do not assert a territorial mention.
        if (citation or hyphenated_author or institution or postpositive_institution or postpositive_feature or lower_list
                or (name == "magdalena" and re.match(r"\s+medio\b", after))
                or (name == "choco" and re.match(r"\s+biogeografico\b", after))
                # The reference spells the distinct northern department
                # N. DE SANTANDER. Do not invent an alias or truncate its
                # unlisted expanded form to the different department Santander.
                or (name == "santander" and re.search(r"\bnorte de\s+$", before))
                or re.search(r"\b(?:rio|laguna|cienaga|cordillera|sierra|parque)(?:\s+\w+){0,3}\s+(?:de|del)\s+(?:la\s+)?$", before)
                or re.search(r"\b(?:pueblo(?: indigena)?|etnia|comunidad indigena|resguardo indigena)\s+(?:de\s+)?$", before)
                or re.search(r"\b(?:rios?|cuencas?|quebradas?|lagunas?|embalses?|cordilleras?|veredas?|barrios?|corregimientos?|comunas?|resguardos?|caserios?|haciendas?|localidad(?:es)?)\s+(?:(?:de|del|la|el|las|los)\s+){0,3}$", before)
                or re.search(r"\b(?:universidad|universite|university|instituto|hospital|colegio|banco)\s+(?:(?:de|del|la|el)\s+){0,3}$", before)
                or re.search(r"\b(?:universidad|universite|university|instituto|hospital|colegio|banco)(?:\s+\w+){0,5}\s+(?:de|del)\s+$", before)
                or (name == "bolivar" and re.search(r"\bsimon\s+$", before))):
            continue
        level_match = _LEVEL.search(before)
        explicit = None
        if level_match:
            explicit = "DEPARTMENT" if level_match[1].startswith("departamento") else "MUNICIPALITY"
            if name == "colombia" and level_match[1].endswith("s"):
                if not any(t["territory_type"] == "COUNTRY" for t in index[name]):
                    continue
                explicit = "COUNTRY"
        mentions.append({"name": name, "start": start, "end": end,
                         "matched_text": text[start:end], "candidates": index[name],
                         "explicit": explicit, "spatial": spatial,
                         "sentence": (left, right)})
    # X, Y and X (Y) are local geographical structures only when Y is a
    # department in the catalogue; no new candidate is ever generated.
    for item in mentions:
        item["paired"] = False
        item["pair_department_codes"] = set()
    for item in mentions:
        for other in mentions:
            if item is other or item["sentence"] != other["sentence"]:
                continue
            first, second = sorted((item, other), key=lambda m: m["start"])
            between = text[first["end"]:second["start"]]
            eligible = [t for t in second["candidates"] if t["territory_type"] == "DEPARTMENT"]
            if not re.fullmatch(r"\s*[,\(]\s*", between) or len(eligible) != 1 or second["explicit"] == "MUNICIPALITY":
                continue
            following = next((m for m in mentions if m["start"] > second["start"] and m["sentence"] == second["sentence"]), None)
            listed = following and re.fullmatch(r"\s*,\s*(?:y\s+)?", text[second["end"]:following["start"]])
            if listed and second["explicit"] != "DEPARTMENT":
                continue
            if "(" in between and not re.match(r"\s*\)", text[second["end"]:]):
                continue
            first["paired"] = second["paired"] = True
            first["pair_department_codes"].add(eligible[0]["department_code"])
    return [m for m in mentions
            if (m["name"] not in GUARDED_NAMES and m["name"] not in STRICT_GUARDED_NAMES)
            or any(t["territory_type"] == "COUNTRY" for t in m["candidates"])
            or m["explicit"] or m["paired"]
            or (m["spatial"] and m["name"] not in STRICT_GUARDED_NAMES)]


def _resolve(mention, mentions):
    all_candidates = mention["candidates"]
    candidates = [t for t in all_candidates if not mention["explicit"]
                  or t["territory_type"] == mention["explicit"]]
    department_codes = set()
    for other in mentions:
        if other is mention or other["sentence"] != mention["sentence"]:
            continue
        distance = max(0, max(mention["start"], other["start"]) - min(mention["end"], other["end"]))
        if distance > 250:
            continue
        eligible = [t for t in other["candidates"] if t["territory_type"] == "DEPARTMENT"]
        if len(eligible) == 1 and (other["explicit"] == "DEPARTMENT"
                                  or (other["explicit"] is None and len(other["candidates"]) == 1)):
            department_codes.add(eligible[0]["department_code"])
    if mention["pair_department_codes"]:
        department_codes = mention["pair_department_codes"]
    elif len(department_codes) != 1:
        # Tables/lists can contain many departments inside one unpunctuated
        # sentence. Only one local, unequivocal department may narrow candidates.
        department_codes = set()
    if len(candidates) == 1:
        candidate = candidates[0]
        if (candidate["territory_type"] == "MUNICIPALITY" and mention["paired"] and department_codes
                and candidate["department_code"] not in department_codes):
            return None, None, candidates
        return candidate, "EXPLICIT_LEVEL" if mention["explicit"] else "UNIQUE_NAME", candidates
    cross_level = len({t["territory_type"] for t in candidates}) > 1
    if (department_codes and candidates and mention["explicit"] != "DEPARTMENT"
            and (not cross_level or mention["explicit"] or mention["pair_department_codes"])):
        narrowed = [t for t in candidates if t["territory_type"] == "MUNICIPALITY"
                    and t["department_code"] in department_codes]
        if len(narrowed) == 1:
            method = "EXPLICIT_LEVEL_DEPARTMENT_CONTEXT" if mention["explicit"] else "MUNICIPALITY_DEPARTMENT_CONTEXT"
            return narrowed[0], method, narrowed
    if not mention["explicit"]:
        countries = [t for t in candidates if t["territory_type"] == "COUNTRY"]
        if len(countries) == 1:
            return countries[0], "EXPLICIT_COUNTRY_NAME", countries
    # Preserve every permissible original candidate when context is insufficient
    # or inconsistent; never rank or select the first.
    return None, None, candidates or all_candidates


def extract_territories(documents: list[dict], sections: list[dict], territories: list[dict]) -> dict:
    """Extract all PROJECT fields, retaining zero-match projects in coverage.

    Returns bridge rows, individual evidence, unresolved mentions and metrics.
    Inputs are not mutated; all result ordering is deterministic.
    """
    projects = {d["document_id"]: d for d in documents if d["source_type"] == "PROJECT"}
    if len(projects) != sum(d["source_type"] == "PROJECT" for d in documents):
        raise ValueError("Duplicate PROJECT document_id")
    index = defaultdict(list)
    for territory in territories:
        if not isinstance(territory["dane_code"], str):
            raise ValueError("DANE codes must be strings")
        index[territory["normalized_name"]].append(territory)
    if not index:
        raise ValueError("The authoritative territory catalogue must not be empty")
    pattern = _name_pattern(index)
    evidence, ambiguous, bridge = [], [], {}
    seen_sections = set()
    for section in sorted(sections, key=lambda s: (s["document_id"], FIELDS.index(s["field_name"]) if s["field_name"] in FIELDS else 99, s["section_id"])):
        doc = projects.get(section["document_id"])
        if doc is None or section["field_name"] not in FIELDS:
            continue
        if section["section_id"] in seen_sections:
            raise ValueError("Duplicate PROJECT section_id")
        seen_sections.add(section["section_id"])
        text = section.get("text_original")
        if text is None:
            text = section.get("text_normalized") or ""
        if not isinstance(text, str):
            raise ValueError("Section text must be string or NULL")
        mentions = _mentions(text, index, pattern)
        for mention in mentions:
            resolved, method, candidates = _resolve(mention, mentions)
            left, right = mention["sentence"]
            common = {"project_id": doc["source_id"], "document_id": doc["document_id"],
                      "section_id": section["section_id"], "field_name": section["field_name"],
                      "matched_text": mention["matched_text"], "normalized_match": mention["name"],
                      "start_char": mention["start"], "end_char": mention["end"],
                      "context_text": text[max(left, mention["start"] - 100):min(right, mention["end"] + 100)]}
            if resolved:
                evidence.append({**common, "territory_type": resolved["territory_type"],
                                 "dane_code": resolved["dane_code"], "territory_name": resolved["territory_name"],
                                 "resolution_method": method, "resolution_status": "RESOLVED"})
                key = (doc["source_id"], resolved["territory_type"], resolved["dane_code"])
                bridge[key] = {"project_id": key[0], "territory_type": key[1], "dane_code": key[2]}
            else:
                ambiguous.append({**common, "territory_type_detected": mention["explicit"],
                                  "dane_code": None, "resolution_status": "AMBIGUOUS",
                                  **_candidates_payload(candidates)})
    # A country mention expresses only national coverage when the project has
    # no resolved subnational territory. Keep suppressed mentions separately for
    # audit; this is never a fallback for projects with no territorial text.
    specific_projects = {key[0] for key in bridge if key[1] in {"DEPARTMENT", "MUNICIPALITY"}}
    national_mentions = [{**row, "publication_status": "SUPPRESSED_SPECIFIC_TERRITORY" if row["project_id"] in specific_projects else "PUBLISHED"}
                         for row in evidence if row["territory_type"] == "COUNTRY"]
    evidence = [row for row in evidence if row["territory_type"] != "COUNTRY" or row["project_id"] not in specific_projects]
    relationships = [bridge[k] for k in sorted(bridge) if k[1] != "COUNTRY" or k[0] not in specific_projects]
    resolved_projects = {r["project_id"] for r in relationships}
    ambiguous_projects = {r["project_id"] for r in ambiguous}
    counts = Counter(r["project_id"] for r in relationships)
    total_mentions = len(evidence) + len(ambiguous)
    suppressed_country = sum(r["publication_status"] != "PUBLISHED" for r in national_mentions)
    all_resolved_mentions = len(evidence) + suppressed_country
    all_detected_mentions = total_mentions + suppressed_country
    summary = {"total_projects": len(projects),
               "projects_with_resolved_territory": len(resolved_projects),
               "projects_without_resolved_territory": len(projects) - len(resolved_projects),
               "resolved_relationships": len(relationships),
               "resolved_municipality_relationships": sum(r["territory_type"] == "MUNICIPALITY" for r in relationships),
               "resolved_department_relationships": sum(r["territory_type"] == "DEPARTMENT" for r in relationships),
               "resolved_country_relationships": sum(r["territory_type"] == "COUNTRY" for r in relationships),
               "suppressed_national_mentions": suppressed_country,
               "national_mentions": len(national_mentions),
               "resolved_mentions": len(evidence), "ambiguous_mentions": len(ambiguous),
               "total_detected_mentions": total_mentions,
               "resolved_mention_percentage": 100 * len(evidence) / total_mentions if total_mentions else 0,
               "ambiguous_mention_percentage": 100 * len(ambiguous) / total_mentions if total_mentions else 0,
               "mention_percentage_denominator": "published_resolved_plus_ambiguous_excludes_suppressed_country",
               "all_detected_mentions": all_detected_mentions,
               "all_resolved_mentions": all_resolved_mentions,
               "all_resolved_mention_percentage": 100 * all_resolved_mentions / all_detected_mentions if all_detected_mentions else 0,
               "all_ambiguous_mention_percentage": 100 * len(ambiguous) / all_detected_mentions if all_detected_mentions else 0,
               "projects_with_ambiguous_mentions": len(ambiguous_projects),
               "projects_with_multiple_territories": sum(n > 1 for n in counts.values()),
               "unique_dane_codes_used": len({r["dane_code"] for r in relationships}),
               "resolution_methods": dict(sorted(Counter(e["resolution_method"] for e in evidence).items())),
               "top_ambiguous_names": [{"normalized_match": name, "mention_count": count}
                                       for name, count in sorted(Counter(r["normalized_match"] for r in ambiguous).items(), key=lambda x: (-x[1], x[0]))[:20]]}
    return {"relationships": relationships, "evidence": evidence, "ambiguous": ambiguous,
            "national_mentions": national_mentions, "summary": summary}
