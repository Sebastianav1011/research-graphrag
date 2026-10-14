"""Local acceptance checks; reports only counts, never personal values."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
import pyarrow.parquet as pq
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from layer1_data.contracts import FIELDS, FINAL_FIELDS, KEYS, logical_schema
from layer1_data.provenance import file_hash
from layer1_data.pipeline import run


def snapshot(directory=None):
    directory = directory or ROOT / "data/canonical"
    result = {}
    for dataset in FIELDS:
        rows = pq.read_table(directory / (dataset + ".parquet")).to_pylist()
        result[dataset] = [{k: v for k, v in row.items() if k != "etl_run_id"} for row in rows]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing", action="store_true", help="Verify the active and immediately previous local publications without rerunning ETL")
    args = parser.parse_args()
    if args.existing:
        second = json.loads((ROOT / "data/canonical/_manifest.json").read_text(encoding="utf-8"))
        previous = ROOT / "outputs/layer1/runs" / second["run_id"] / "previous_canonical"
        first = json.loads((previous / "_manifest.json").read_text(encoding="utf-8"))
        assert first["run_id"] != second["run_id"]
        for publication in (first, second):
            assert publication["status"] == "SUCCESS"
            assert Path(publication["configuration"]["sources"]).is_relative_to(ROOT)
        before, after = snapshot(previous), snapshot()
    else:
        # Two full runs against configured originals establish reproducibility.
        first = run(ROOT)
        assert first["status"] == "SUCCESS", first["status"]
        before = snapshot()
        second = run(ROOT)
        assert second["status"] == "SUCCESS", second["status"]
        after = snapshot()
    assert before == after, "Canonical payloads changed beyond run ID"
    assert all(first[k] == second[k] for k in ("records_read", "records_staged", "records_accepted", "records_rejected", "records_canonical"))
    assert all(file_hash(Path(m["path"])) == m["sha256"] for m in second["input_files"])
    researchers = {r["researcher_id"] for r in after["investigadores"]}
    projects = {r["project_id"] for r in after["proyectos"]}
    articles = {r["article_id"] for r in after["articulos"]}
    for r in after["proyecto_investigador"]:
        assert r["project_id"] in projects and r["researcher_id"] in researchers
    for r in after["articulo_investigador"]:
        assert r["article_id"] in articles and r["researcher_id"] in researchers
    for dataset, rows in after.items():
        assert len({tuple(r[k] for k in KEYS[dataset]) for r in rows}) == len(rows)
        for row in rows:
            provenance = json.loads(row["provenance_json"])
            assert provenance and all("original_values" in p and "field_mapping" in p for p in provenance)
    book = load_workbook(ROOT / "templates/resultado_final_indicadores.xlsx", read_only=False)
    assert book.sheetnames == ["Proyectos", "Artículos"]
    preview = []
    for sheet in book:
        assert sheet.max_row == 1 and list(next(sheet.values)) == FINAL_FIELDS
        preview.append({"sheet": sheet.title, "height": sheet.row_dimensions[1].height,
                        "cells": [{"text": c.value, "width": sheet.column_dimensions[c.column_letter].width,
                                   "fill": c.fill.fgColor.rgb, "font": c.font.name,
                                   "font_size": c.font.sz, "bold": c.font.b, "color": c.font.color.rgb}
                                  for c in sheet[1]]})
    book.close()
    # The Windows sandbox can create .git under a different local account.
    # Trust only this project for these read-only checks; do not edit global Git config.
    git = ["git", "-c", "safe.directory=" + ROOT.as_posix()]
    root_ignore = []
    for rel in ["data/raw/proyectos/private.csv", "data/staging/proyectos/private.parquet",
                "data/canonical/proyectos.parquet", "outputs/layer1/quality/summary.json",
                "config/sources.local.yaml", ".env", ".venv/pyvenv.cfg"]:
        check = subprocess.run(git + ["check-ignore", "-q", "--", rel], cwd=ROOT, capture_output=True)
        assert check.returncode == 0, "Sensitive path not ignored: " + rel + ": " + check.stderr.decode(errors="replace")
        root_ignore.append(rel)
    tracked = subprocess.check_output(git + ["ls-files", "--", "data/raw", "data/staging", "data/canonical", "outputs"],
                                      cwd=ROOT, text=True).splitlines()
    assert not [p for p in tracked if not p.endswith((".gitkeep", "README.md"))]
    catalog_sha256 = "2f7185244e536c1d90568106a3c26d4d0520c0870cb80b91e777705316b1d1b0"
    assert catalog_sha256 == file_hash(ROOT / "data/reference/indicadores/catalogo_indicadores.xlsx")
    assert list((ROOT / "templates").glob("*.xlsx")) == [ROOT / "templates/resultado_final_indicadores.xlsx"]
    report = {
        "status": "PASS", "runs": [first["run_id"], second["run_id"]], "raw_unchanged": True,
        "idempotent": True, "foreign_keys": "PASS", "canonical_keys": "PASS",
        "template_sheets": ["Proyectos", "Artículos"], "template_columns": FINAL_FIELDS, "template_rows": 0,
        "catalog_sha256": catalog_sha256, "ignored_private_paths": root_ignore,
        "datasets": {d: {"rows": len(rows), "columns": list(pq.read_schema(ROOT / "data/canonical" / (d + ".parquet")).names),
                         "key": KEYS[d]} for d, rows in after.items()},
    }
    reports = ROOT / "outputs/layer1/reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (reports / "template_preview.json").write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "runs": report["runs"],
                      "datasets": {d: len(r) for d, r in after.items()}}, ensure_ascii=True))


if __name__ == "__main__":
    main()
