import json
from pathlib import Path
import pyarrow.parquet as pq
import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError
from openpyxl import load_workbook

from layer2_processing.preprocessing.pipeline import run
from layer2_processing.preprocessing.contracts import FIELDS, FINAL_FIELDS, logical_schema
from layer2_processing.preprocessing.provenance import file_hash
from .conftest import ROOT


def table(root, domain):
    return pq.read_table(root / "outputs/layer2/canonical" / (domain + ".parquet")).to_pylist()


def test_end_to_end_and_idempotency(workspace):
    before = {str(p): file_hash(p) for p in (workspace / "tests/fixtures/synthetic").glob("*.csv")}
    first = run(workspace)
    assert first["status"] == "SUCCESS"
    first_tables = {}
    for domain in FIELDS:
        rows = table(workspace, domain)
        assert rows
        for row in rows:
            Draft202012Validator(logical_schema(domain)).validate(row)
            assert json.loads(row["provenance_json"])[0]["original_values"]
        first_tables[domain] = [{k: v for k, v in r.items() if k != "etl_run_id"} for r in rows]
    second = run(workspace)
    assert second["status"] == "SUCCESS" and first["run_id"] != second["run_id"]
    for domain in FIELDS:
        assert first_tables[domain] == [{k: v for k, v in r.items() if k != "etl_run_id"} for r in table(workspace, domain)]
    assert before == {str(p): file_hash(p) for p in (workspace / "tests/fixtures/synthetic").glob("*.csv")}
    assert len(list((workspace / "outputs/layer2/preprocessing/manifests").glob("*.json"))) == 2
    assert (workspace / "outputs/layer2/preprocessing/audit/anomalies.csv").is_file()
    for file in ("summary.json", "completeness.csv", "duplicate_records.csv", "invalid_records.csv", "identity_conflicts.csv", "unresolved_entities.csv"):
        assert (workspace / "outputs/layer2/preprocessing/quality" / file).is_file()
    assert len(table(workspace, "proyectos")) == 2
    assert len(table(workspace, "articulos")) == 2
    assert len(table(workspace, "investigadores")) == 5
    assert len(table(workspace, "proyecto_investigador")) == 5
    assert len(table(workspace, "articulo_investigador")) == 2
    assert list((workspace / "outputs/layer2/staging/proyectos").rglob("*.parquet"))


def test_critical_failure_keeps_last_successful_canonical(workspace):
    good = run(workspace)
    before = file_hash(workspace / "outputs/layer2/canonical/proyectos.parquet")
    config = workspace / "config/sources.yaml"
    settings = yaml.safe_load(config.read_text(encoding="utf-8"))
    settings["proyectos"]["path"] = "missing.csv"
    config.write_text(yaml.safe_dump(settings), encoding="utf-8")
    failed = run(workspace)
    assert failed["status"] == "FAILED"
    assert "FILE_NOT_FOUND" in failed["anomalies"]
    assert file_hash(workspace / "outputs/layer2/canonical/proyectos.parquet") == before
    canonical_manifest = json.loads((workspace / "outputs/layer2/canonical/_manifest.json").read_text(encoding="utf-8"))
    assert canonical_manifest["run_id"] == good["run_id"]
    assert (workspace / ("outputs/layer2/preprocessing/manifests/" + failed["run_id"] + ".json")).exists()


def test_strict_error_policy_blocks_publication(workspace):
    path = workspace / "config/layer1.yaml"
    settings = yaml.safe_load(path.read_text(encoding="utf-8"))
    settings["errors"]["fail_on_error"] = True
    path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    result = run(workspace)
    assert result["status"] == "FAILED"
    assert not list((workspace / "outputs/layer2/canonical").glob("*.parquet"))


def test_output_cannot_overwrite_raw(workspace):
    config = workspace / "config/layer1.yaml"
    settings = yaml.safe_load(config.read_text(encoding="utf-8"))
    settings["directories"]["canonical"] = "tests/fixtures"
    config.write_text(yaml.safe_dump(settings), encoding="utf-8")
    before = file_hash(workspace / "tests/fixtures/synthetic/proyectos.csv")
    assert run(workspace)["status"] == "FAILED"
    assert file_hash(workspace / "tests/fixtures/synthetic/proyectos.csv") == before


def test_empty_domains_have_typed_parquet(workspace):
    config = workspace / "config/sources.yaml"
    settings = yaml.safe_load(config.read_text(encoding="utf-8"))
    settings["investigadores"]["enabled"] = False
    settings["articulos"].pop("researcher_mapping")
    config.write_text(yaml.safe_dump(settings), encoding="utf-8")
    assert run(workspace)["status"] == "SUCCESS"
    result = pq.read_table(workspace / "outputs/layer2/canonical/investigadores.parquet")
    assert result.num_rows == 0
    assert str(result.schema.field("researcher_id").type) == "string"


def test_fresh_template_has_exact_contract():
    from autonomous_execution.final_output import load_template,SHEETS
    book = load_template(ROOT)
    assert book.sheetnames == list(SHEETS)
    for sheet in book:
        assert list(next(sheet.values)) == SHEETS[sheet.title]
        assert not any(c.value is not None for row in sheet.iter_rows(min_row=2) for c in row)
    book.close()


def test_final_schema_rejects_mechanism_as_evidence_source():
    schema = json.loads((ROOT / "schemas/final_output.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    validator.validate({"Proyectos": [], "Artículos": []})
    row = {f: "value" for f in FINAL_FIELDS}
    row.update(source_type="PROJECT", source_id="PROJ_1", confidence_score=None, evidence_source_field="GraphRAG")
    with pytest.raises(ValidationError):
        validator.validate({"Proyectos": [row], "Artículos": []})
    row["evidence_source_field"] = "resumen"
    validator.validate({"Proyectos": [row], "Artículos": []})


def test_publication_failure_is_audited_and_keeps_previous(workspace, monkeypatch):
    import layer2_processing.preprocessing.pipeline as pipeline
    assert run(workspace)["status"] == "SUCCESS"
    previous = file_hash(workspace / "outputs/layer2/canonical/proyectos.parquet")

    def fail_write(*args, **kwargs):
        raise OSError("Synthetic write failure")

    monkeypatch.setattr(pipeline, "write_parquet", fail_write)
    failed = run(workspace)
    assert failed["status"] == "FAILED"
    assert "PUBLICATION_FAILURE" in failed["anomalies"]
    assert file_hash(workspace / "outputs/layer2/canonical/proyectos.parquet") == previous
    assert (workspace / ("outputs/layer2/preprocessing/manifests/" + failed["run_id"] + ".json")).exists()
    assert not (workspace / ".layer1.lock").exists()


def test_concurrent_writer_is_blocked(workspace):
    lock = workspace / ".layer1.lock"
    lock.write_text("active-run", encoding="utf-8")
    result = run(workspace)
    assert result["status"] == "FAILED"
    assert lock.read_text(encoding="utf-8") == "active-run"


def test_configured_empty_paths_fails(workspace):
    config = workspace / "config/sources.yaml"
    spec = yaml.safe_load(config.read_text(encoding="utf-8"))
    spec["investigadores"]["paths"] = []
    config.write_text(yaml.safe_dump(spec), encoding="utf-8")
    assert run(workspace)["status"] == "FAILED"


def test_input_mutation_is_detected(workspace, monkeypatch):
    import layer2_processing.preprocessing.pipeline as pipeline
    real_ingest = pipeline.ingest

    def changed_ingest(path, *args):
        result = real_ingest(path, *args)
        if path.name == "proyectos.csv":
            with path.open("a", encoding="utf-8") as stream:
                stream.write("\\n")
        return result

    monkeypatch.setattr(pipeline, "ingest", changed_ingest)
    result = run(workspace)
    assert result["status"] == "FAILED"
    assert result["raw_unchanged"] is False
    assert "INPUT_CHANGED" in result["anomalies"]


def test_maximum_anomalies_blocks_run(workspace):
    path = workspace / "config/layer1.yaml"
    settings = yaml.safe_load(path.read_text(encoding="utf-8"))
    settings["errors"]["max_anomalies"] = 0
    path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    assert run(workspace)["status"] == "FAILED"
