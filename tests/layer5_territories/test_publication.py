"""Territorial contracts, fail-closed inputs and integration of real publications."""
import ast
import csv
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq
import pytest

from layer4_evaluation.territories.contracts import SCHEMAS, table
from layer4_evaluation.territories.inputs import load_projects
from layer4_evaluation.territories.pipeline import validate_result, logical_hash

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('name', SCHEMAS)
def test_typed_empty_outputs(name):
    result = table(name, [])
    assert result.num_rows == 0
    assert result.schema == SCHEMAS[name]
    assert str(result.schema.field('dane_code').type) == 'string'


def test_no_model_network_or_layer3_dependencies():
    forbidden = ('layer3_graphrag', 'openai', 'requests', 'httpx', 'urllib', 'socket',
                 'sentence_transformers', 'transformers', 'torch', 'geopy')
    for source in (ROOT / 'src/layer4_evaluation/territories').glob('*.py'):
        for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                assert all(not name.name.startswith(forbidden) for name in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden)


def test_quality_rejects_ambiguous_code():
    result = {'relationships': [], 'evidence': [], 'ambiguous': [{'dane_code': '05001', 'resolution_status': 'AMBIGUOUS'}],
              'summary': {'total_projects': 0, 'resolved_relationships': 0}}
    with pytest.raises(ValueError, match='Ambiguous'):
        validate_result([], [], [], result)


def test_quality_rejects_duplicate_bridge():
    row = {'project_id': 'P', 'territory_type': 'MUNICIPALITY', 'dane_code': '05001'}
    with pytest.raises(ValueError, match='Duplicate'):
        validate_result([], [], [], {'relationships': [row, row]})


def test_missing_or_unsuccessful_publication_rejected(tmp_path):
    directory = tmp_path / 'outputs/layer2/knowledge'
    directory.mkdir(parents=True)
    (directory / '_manifest.json').write_text(json.dumps({'status': 'FAILED', 'publication_kind': 'real'}))
    with pytest.raises(ValueError, match='SUCCESS'):
        load_projects(tmp_path)


def test_failed_build_preserves_previous_publication(tmp_path):
    from layer4_evaluation.territories.pipeline import build
    previous = tmp_path / 'outputs/layer4/territorios/publicacion'
    previous.mkdir(parents=True)
    (previous / 'user_note.txt').write_text('keep', encoding='utf-8')
    with pytest.raises(OSError):
        build(tmp_path)
    assert (previous / 'user_note.txt').read_text(encoding='utf-8') == 'keep'
    assert not (previous.parent / '.territories.lock').exists()
    assert list((tmp_path / 'outputs/layer4').glob('.territories-candidate-*/failure.json'))


def test_concurrent_writer_lock_is_preserved(tmp_path):
    from layer4_evaluation.territories.pipeline import build
    lock = tmp_path / 'outputs/layer4/.territories.lock'
    lock.parent.mkdir(parents=True)
    lock.write_text('existing writer', encoding='utf-8')
    with pytest.raises(FileExistsError):
        build(tmp_path)
    assert lock.read_text(encoding='utf-8') == 'existing writer'


@pytest.fixture
def real_publication():
    directory = ROOT / 'outputs/layer4/territorios/publicacion'
    if not (directory / 'territory_manifest.json').exists():
        pytest.skip('Run the explicit territorial build on authorized real snapshots first')
    return directory


def test_real_all_projects_and_fields(real_publication):
    documents, sections, upstream = load_projects(ROOT)
    manifest = json.loads((real_publication / 'territory_manifest.json').read_text(encoding='utf-8'))
    summary = manifest['summary']
    assert summary['total_projects'] == len(documents) == upstream['project_documents']
    assert {s['field_name'] for s in sections} == {'title', 'keywords', 'summary', 'methodology', 'objectives', 'expected_results'}
    assert manifest['layer2'] == upstream


def test_real_powerbi_resolved_only_and_codes_as_text(real_publication):
    resolved = pq.read_table(real_publication / 'project_territories.parquet').to_pylist()
    ambiguous = pq.read_table(real_publication / 'project_territory_ambiguous.parquet').to_pylist()
    with (real_publication / 'project_territories_powerbi.csv').open(encoding='utf-8-sig', newline='') as stream:
        powerbi = list(csv.DictReader(stream))
    assert powerbi == resolved
    assert all(row['dane_code'] is None for row in ambiguous)
    assert all(isinstance(row['dane_code'], str) for row in powerbi)
    assert any(row['dane_code'].startswith('0') for row in powerbi)


def test_real_country_only_without_specific(real_publication):
    resolved = pq.read_table(real_publication / 'project_territories.parquet').to_pylist()
    specific = {r['project_id'] for r in resolved if r['territory_type'] != 'COUNTRY'}
    countries = [r for r in resolved if r['territory_type'] == 'COUNTRY']
    assert countries
    assert all(r['dane_code'] == '000' and r['project_id'] not in specific for r in countries)
    evidence = pq.read_table(real_publication / 'project_territory_evidence.parquet').to_pylist()
    assert {r['project_id'] for r in countries} == {r['project_id'] for r in evidence if r['territory_type'] == 'COUNTRY'}


def test_real_idempotence(real_publication):
    report = json.loads((real_publication / 'idempotence.json').read_text(encoding='utf-8'))
    assert report['status'] == 'PASS'
    assert report['same_inputs_and_code']
    assert report['previous_build_id'] == report['current_build_id']
    manifest = json.loads((real_publication / 'territory_manifest.json').read_text(encoding='utf-8'))
    for key, name in [('relationships', 'project_territories'), ('evidence', 'project_territory_evidence'),
                      ('ambiguous', 'project_territory_ambiguous'), ('national_mentions', 'project_national_mentions')]:
        assert logical_hash(pq.read_table(real_publication / (name + '.parquet')).to_pylist()) == manifest['payload_hashes'][key]


def test_real_layer3_and_upstream_unchanged(real_publication):
    sys.path.insert(0, str(ROOT / 'scripts'))
    from territory_integrity import fingerprint
    before = json.loads((ROOT / 'outputs/layer4/territorios/aceptacion/integrity_before.json').read_text(encoding='utf-8-sig'))
    # The historical publication binds old source paths. Verify those exact
    # snapshots plus the separately recorded current relocation, never rebase it.
    from layer4_evaluation.paths import verify_expected
    for name, digest in before.items():
        verify_expected(ROOT, name, digest)
    assert fingerprint(ROOT)  # Current source/test paths are independently readable.


def test_real_country_amendment_preserves_original_sheets(real_publication):
    from zipfile import ZipFile
    from openpyxl import load_workbook
    original = ROOT / 'outputs/layer2/reference/versions/701a2468c65a5d86dcfa7823f66741ddc8e7289db0a0e841f292651ee84b0176/dane_source.xlsx'
    source = ROOT / 'data/layer1_sources/reference/Codigos Dane/Tabla_Codigos_Dane.xlsx'
    with ZipFile(original) as before, ZipFile(source) as after:
        # Only workbook registrations change; the source sheets/styles/data do not.
        changed = {'[Content_Types].xml', 'xl/workbook.xml', 'xl/_rels/workbook.xml.rels'}
        assert all(before.read(name) == after.read(name) for name in before.namelist() if name not in changed)
    wb = load_workbook(source, read_only=True)
    try:
        assert list(wb['ALCANCE_NACIONAL'].values) == [('code', 'name', 'type'), ('000', 'Colombia', 'COUNTRY')]
        assert wb['ALCANCE_NACIONAL']['A2'].data_type == 's'
    finally:
        wb.close()
