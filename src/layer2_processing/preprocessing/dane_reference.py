"""Normalize the supplied DANE workbook without changing canonical Layer 1.

The inspected source uses three header rows and DD / MMM code components.
An unexpected workbook structure fails explicitly; it is never guessed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import unicodedata

from openpyxl import load_workbook
import pyarrow as pa
import pyarrow.parquet as pq

REFERENCE_VERSION = "DANE_REFERENCE_V1"
DEFAULT_SOURCE = Path("data/layer1_sources/reference/Codigos Dane/Tabla_Codigos_Dane.xlsx")
DEFAULT_OUTPUT = Path("outputs/layer2/reference")
HEADERS = ["codigo departamento", "nombre departamento", "codigo municipio", "nombre municipio"]
FIELDS = [
    "territory_id", "territory_type", "dane_code", "territory_name", "normalized_name",
    "department_code", "department_name", "municipality_code", "municipality_name",
    "parent_territory_id", "source_file", "source_sheet", "source_row", "territory_origin",
]
SCHEMA = pa.schema([(name, pa.int64() if name == "source_row" else pa.string()) for name in FIELDS])


def normalize_name(text: str) -> str:
    """Exact-match representation; original values are always retained separately."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in plain).split())


def file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _code(value, width: int, row: int, column: str) -> str:
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
    if not re.fullmatch(r"[0-9]{" + str(width) + r"}", text):
        raise ValueError(f"Invalid {column} at source row {row}: expected {width} digits")
    return text


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def inspect_catalog(source_path: Path, repo_root: Path):
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
            municipality = _code(values_row[2], 3, row_number, "municipality_code")
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


def _validate_output(output: Path, root: Path, source: Path):
    try:
        relative = output.relative_to(root)
    except ValueError as exc:
        raise ValueError("Reference output must remain inside repository root") from exc
    if output == source or output in source.parents:
        raise ValueError("Reference output must not contain the source workbook")
    allowed = [root / 'outputs/layer2/reference', root / 'outputs/layer2/preprocessing']
    if not any(output == p or output.is_relative_to(p) for p in allowed):
        raise ValueError("Reference output must use outputs/layer2/reference independently of canonical")


def build_reference(repo_root, source_path=None, output_dir=None):
    """Build independent current artifacts and immutable content-addressed versions."""
    root = Path(repo_root).resolve()
    source = Path(source_path) if source_path else root / DEFAULT_SOURCE
    output = Path(output_dir) if output_dir else root / DEFAULT_OUTPUT
    source = (root / source).resolve() if not source.is_absolute() else source.resolve()
    output = (root / output).resolve() if not output.is_absolute() else output.resolve()
    _validate_output(output, root, source)
    source_hash = file_hash(source)
    rows, audit, index = inspect_catalog(source, root)
    if file_hash(source) != source_hash:
        raise ValueError("DANE source changed during inspection")
    code_paths = [Path(__file__), Path(__file__).with_name("__init__.py")]
    cli = root / "scripts/build_dane_reference.py"
    if cli.exists():
        code_paths.append(cli)
    code_hashes = {_display_path(path, root): file_hash(path) for path in code_paths}
    logical_hash = sha256(_json_bytes(rows)).hexdigest()
    reference_id = sha256(_json_bytes({"version": REFERENCE_VERSION, "source": source_hash,
                                    "logical": logical_hash, "code": code_hashes})).hexdigest()
    version = output / "versions" / reference_id
    files = {"dane_reference_audit.json": _json_bytes(audit), "dane_ambiguity_index.json": _json_bytes(index),
             "dane_source.xlsx": source.read_bytes()}
    if sha256(files["dane_source.xlsx"]).hexdigest() != source_hash:
        raise ValueError("DANE source changed before versioned source snapshot")
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), sink, compression="zstd")
    files["dane_territories.parquet"] = sink.getvalue().to_pybytes()
    manifest = {"reference_version": REFERENCE_VERSION, "reference_id": reference_id,
        "status": "SUCCESS", "source_file": _display_path(source, root), "source_sheet": audit["source_sheet"],
        "source_sha256": source_hash, "header_rows": audit["header_rows"], "code_hashes": code_hashes,
        "logical_sha256": logical_hash, "department_count": audit["department_count"],
        "municipality_count": audit["municipality_count"], "territory_count": len(rows),
        "country_count": audit["country_count"], "country_extension": audit["country_extension"],
        "territory_origins": {"DANE": audit["department_count"] + audit["municipality_count"],
                              "USER_DEFINED_COUNTRY": audit["country_count"]},
        "outputs": {name: {"sha256": sha256(payload).hexdigest(), "bytes": len(payload)}
                    for name, payload in sorted(files.items())},
        "version_directory": _display_path(version, root),
        "validation": {"codes_are_strings": True, "department_code_width": 2,
                       "municipality_component_width": 3, "municipality_dane_code_width": 5,
                       "country_code": "000" if audit["country_count"] else None,
                       "duplicate_codes": 0, "null_required_values": 0},
        "canonical_layer1_modified": False}
    files["dane_reference_manifest.json"] = _json_bytes(manifest)
    # Existing snapshots are immutable: a mismatch is an error, never overwritten.
    version.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        destination = version / name
        if destination.exists() and destination.read_bytes() != payload:
            raise ValueError(f"Immutable reference version mismatch: {name}")
        if not destination.exists():
            destination.write_bytes(payload)
    # Manifest is the last current artifact written; readers verify its hashes.
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        destination = output / name
        if not destination.exists() or destination.read_bytes() != payload:
            temporary = output / ("." + name + ".pending")
            temporary.write_bytes(payload)
            temporary.replace(destination)
    return rows, manifest


def load_reference(directory):
    """Verify manifest, physical files, logical payload and schema before consuming."""
    directory = Path(directory)
    manifest_path = directory / "dane_reference_manifest.json"
    initial = manifest_path.read_bytes()
    manifest = json.loads(initial)
    if manifest.get("reference_version") != REFERENCE_VERSION or manifest.get("status") != "SUCCESS":
        raise ValueError("Unsupported or unsuccessful DANE reference manifest")
    for name, metadata in manifest["outputs"].items():
        if Path(name).name != name or file_hash(directory / name) != metadata["sha256"]:
            raise ValueError(f"DANE reference checksum mismatch: {name}")
    table = pq.read_table(directory / "dane_territories.parquet")
    if not table.schema.equals(SCHEMA):
        raise ValueError("DANE reference schema mismatch")
    rows = table.to_pylist()
    if sha256(_json_bytes(rows)).hexdigest() != manifest["logical_sha256"]:
        raise ValueError("DANE reference logical checksum mismatch")
    if manifest_path.read_bytes() != initial:
        raise ValueError("DANE reference manifest changed during reading; retry")
    return rows, manifest
