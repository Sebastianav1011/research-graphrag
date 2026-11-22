"""DANE workbook reading for the territorial export (evaluation side).

Same reader as layer2_processing.preprocessing.dane_reference.inspect_catalog plus the
optional zero-padding of numeric municipal components (column C stored as a number,
e.g. 1 -> "001") used by the territorial catalog. It lives outside the Knowledge code
(src/layer2_processing/ is part of the sealed Knowledge fingerprint), so the export can
use it without invalidating the active Knowledge version. With
normalize_numeric_components=False the result is identical to the Layer 2 reader.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math
from pathlib import Path
import re

from openpyxl import load_workbook

from layer2_processing.preprocessing.dane_reference import (FIELDS, HEADERS, REFERENCE_VERSION, _display_path,
                                                            file_hash, normalize_name)


def _code(value, width: int, row: int, column: str, *, pad_numeric=False) -> str:
    # Numeric XLSX cells are converted only to their textual digit representation.
    # No code ever becomes a numeric canonical identifier.
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Invalid {column} at source row {row}: code required")
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
        text = format(value, ".0f")
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise ValueError(f"Invalid {column} type at source row {row}")
    if pad_numeric and isinstance(value, (int, float)):
        text = text.zfill(width)
    if not re.fullmatch(r"[0-9]{" + str(width) + r"}", text):
        raise ValueError(f"Invalid {column} at source row {row}: expected {width} digits")
    return text


def inspect_catalog(source_path: Path, repo_root: Path, *, normalize_numeric_components=False):
    """Return normalized rows, a full workbook audit and an ambiguity index."""
    workbook = load_workbook(source_path, read_only=True, data_only=False)
    try:
        sheets = []
        populated = []
        for sheet in workbook:
            values = list(sheet.iter_rows(values_only=True))
            nonempty = [(i, row) for i, row in enumerate(values, 1) if any(x is not None for x in row)]
            sheets.append({"sheet": sheet.title, "max_row": sheet.max_row, "max_column": sheet.max_column,
                           "nonempty_rows": len(nonempty)})
            if nonempty:
                populated.append((sheet, values))
        national_sheets = [(s, v) for s, v in populated if s.title == "ALCANCE_NACIONAL"]
        populated = [(s, v) for s, v in populated if s.title != "ALCANCE_NACIONAL"]
        if len(populated) != 1:
            raise ValueError("Expected exactly one nonempty DANE worksheet; inspect changed workbook")
        sheet, values = populated[0]
        if sheet.max_column != 4 or len(values) < 4:
            raise ValueError("DANE workbook must have the inspected four-column structure")
        header_rows = values[:3]
        actual_headers = [normalize_name(" ".join(str(row[i]) for row in header_rows if row[i] is not None))
                          for i in range(4)]
        if actual_headers != HEADERS:
            raise ValueError(f"Unrecognized DANE headers: {actual_headers!r}")
        source_file = _display_path(source_path, repo_root)
        rows = []
        departments = {}
        municipality_codes = set()
        empty_rows = []
        types = [Counter() for _ in HEADERS]
        nulls = [0] * 4
        lengths = {"department_code": Counter(), "municipality_code": Counter()}
        for row_number, values_row in enumerate(values[3:], 4):
            if all(value is None for value in values_row):
                empty_rows.append(row_number)
                continue
            for i, value in enumerate(values_row):
                types[i][type(value).__name__] += 1
                nulls[i] += value is None
            department = _code(values_row[0], 2, row_number, "department_code")
            municipality = _code(values_row[2], 3, row_number, "municipality_code",
                                 pad_numeric=normalize_numeric_components)
            lengths["department_code"][len(department)] += 1
            lengths["municipality_code"][len(municipality)] += 1
            department_name, municipality_name = values_row[1], values_row[3]
            if any(not isinstance(value, str) or not value.strip() for value in (department_name, municipality_name)):
                raise ValueError(f"Missing/invalid territory name at source row {row_number}")
            if department in departments and departments[department]["territory_name"] != department_name:
                raise ValueError(f"Conflicting department names for code {department}")
            department_id = f"DANE:DEPARTMENT:{department}"
            if department not in departments:
                departments[department] = dict(zip(FIELDS, [department_id, "DEPARTMENT", department,
                    department_name, normalize_name(department_name), department, department_name,
                    None, None, None, source_file, sheet.title, row_number, "DANE"]))
            full_code = department + municipality
            if full_code in municipality_codes:
                raise ValueError(f"Duplicate municipality DANE code {full_code} at source row {row_number}")
            municipality_codes.add(full_code)
            rows.append(dict(zip(FIELDS, [f"DANE:MUNICIPALITY:{full_code}", "MUNICIPALITY", full_code,
                municipality_name, normalize_name(municipality_name), department, department_name,
                municipality, municipality_name, department_id, source_file, sheet.title, row_number, "DANE"])))
        if not rows:
            raise ValueError("DANE reference contains no municipalities")
        rows.extend(departments.values())
        country_count = 0
        if national_sheets:
            national_sheet, national_values = national_sheets[0]
            national_rows = [(i, r) for i, r in enumerate(national_values, 1) if any(v is not None for v in r)]
            if national_sheet.max_column != 3 or len(national_rows) != 2:
                raise ValueError("ALCANCE_NACIONAL must contain exactly a header and the authorized COUNTRY row")
            if list(national_rows[0][1]) != ["code", "name", "type"]:
                raise ValueError("Unrecognized ALCANCE_NACIONAL headers")
            if list(national_rows[1][1]) != ["000", "Colombia", "COUNTRY"]:
                raise ValueError("Only the explicit user-defined COUNTRY Colombia code '000' is authorized")
            rows.append(dict(zip(FIELDS, ["USER_DEFINED:COUNTRY:000", "COUNTRY", "000", "Colombia", "colombia",
                None, None, None, None, None, source_file, national_sheet.title, national_rows[1][0],
                "USER_DEFINED_COUNTRY"])))
            country_count = 1
        rows.sort(key=lambda row: (row["territory_type"], row["dane_code"]))
        grouped = defaultdict(list)
        by_name = defaultdict(list)
        for row in rows:
            grouped[(row["normalized_name"], row["territory_type"])].append(row)
            by_name[row["normalized_name"]].append(row)
        index = []
        for (name, kind), candidates in sorted(grouped.items()):
            index.append({"normalized_name": name, "territory_type": kind, "candidate_count": len(candidates),
                "candidate_dane_codes": [x["dane_code"] for x in candidates],
                "candidate_names": [x["territory_name"] for x in candidates],
                "candidate_departments": [x["department_name"] for x in candidates]})
        duplicates = [entry for entry in index if entry["candidate_count"] > 1]
        cross_level = [{"normalized_name": name, "candidates": [
            {"territory_type": x["territory_type"], "dane_code": x["dane_code"],
             "territory_name": x["territory_name"], "department_name": x["department_name"]} for x in candidates]}
            for name, candidates in sorted(by_name.items()) if len({x["territory_type"] for x in candidates}) > 1]
        anomalies = []
        if empty_rows:
            anomalies.append({"kind": "EMPTY_SOURCE_ROWS", "source_rows": empty_rows,
                              "action": "Excluded wholly empty rows; source unchanged"})
        if any(types[i].get("int", 0) or types[i].get("float", 0) for i in (0, 2)):
            anomalies.append({"kind": "MIXED_XLSX_CODE_STORAGE_TYPES",
                              "action": "Validated DD/MMM digit widths and represented all codes as strings"})
        audit = {"reference_version": REFERENCE_VERSION, "source_file": source_file,
            "source_sha256": file_hash(source_path), "sheets": sheets, "source_sheet": sheet.title,
            "header_rows": [1, 2, 3], "header_values": [list(row) for row in header_rows],
            "mapped_columns": dict(zip(HEADERS, ["A", "B", "C", "D"])),
            "observed_types": dict(zip(HEADERS, [dict(value) for value in types])),
            "null_counts_nonempty_rows": dict(zip(HEADERS, nulls)),
            "code_lengths": {key: {str(k): v for k, v in value.items()} for key, value in lengths.items()},
            "data_row_count": len(municipality_codes), "department_count": len(departments),
            "municipality_count": len(municipality_codes), "territory_count": len(rows),
            "country_count": country_count,
            "duplicate_code_count": 0, "duplicate_normalized_name_groups": len(duplicates),
            "duplicate_names_by_type": duplicates, "cross_level_name_count": len(cross_level),
            "cross_level_names": cross_level, "anomalies": anomalies,
            "catalog_policy": "User XLSX authoritative; no aliases, Internet corrections or invented territories",
            "country_extension": "USER_DEFINED_COUNTRY" if country_count else None}
        return rows, audit, index
    finally:
        workbook.close()
