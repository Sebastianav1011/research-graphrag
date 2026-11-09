"""Read-only integrity and acceptance checks for the territorial publication."""
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from layer2_processing.preprocessing.dane_reference import load_reference
from layer4_evaluation.history import verify_historical_files
from layer4_evaluation.paths import verify_expected, resolve
from layer4_evaluation.territories.contracts import SCHEMAS
from layer4_evaluation.territories.inputs import check_unchanged, load_projects, sha256
from layer4_evaluation.territories.pipeline import OUTPUT_NAMES, json_bytes, logical_hash, validate_result, _verify_workbook
from territory_integrity import fingerprint
import pyarrow.parquet as pq


def verify(root=ROOT):
    directory = root / 'outputs/layer4/territorios/publicacion'
    manifest = json.loads((directory / 'territory_manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'SUCCESS' or manifest['architecture'] != 'PROJECT_TERRITORY_V1':
        raise ValueError('Unsuccessful territorial publication')
    for name, metadata in manifest['outputs'].items():
        if sha256(directory / name) != metadata['sha256']:
            raise ValueError(f'Published checksum mismatch: {name}')
    historical = any(name.startswith('src/layer4_territories/') for name in manifest['code_hashes'])
    if historical:
        source_integrity = verify_historical_files(root, manifest['code_hashes'])
    else:
        for name, expected in manifest['code_hashes'].items():
            verify_expected(root,name,expected)
        source_integrity = {'verification_scope': 'CURRENT_PUBLICATION_CODE', 'status': 'PASS'}
    documents, sections, upstream = load_projects(root)
    if upstream != manifest['layer2']:
        raise ValueError('Layer 2 input snapshot changed')
    territories, reference = load_reference(root / 'outputs/layer2/reference')
    if reference != manifest['reference_manifest']:
        raise ValueError('Reference snapshot changed')
    if sha256(resolve(root,reference['source_file'])) != reference['source_sha256']:
        raise ValueError('Reference workbook changed since normalization')
    result = {}
    for key, name in OUTPUT_NAMES.items():
        data = pq.read_table(directory / (name + '.parquet'))
        if not data.schema.equals(SCHEMAS[name]):
            raise ValueError(f'Territorial schema mismatch: {name}')
        result[key] = data.to_pylist()
    result['national_mentions'] = pq.read_table(directory / 'project_national_mentions.parquet').to_pylist()
    result['summary'] = json.loads((directory / 'territory_summary.json').read_text(encoding='utf-8'))
    quality = validate_result(documents, sections, territories, result)
    if {key: logical_hash(rows) for key, rows in result.items()} != manifest['payload_hashes']:
        raise ValueError('Published logical hashes do not match')
    with (directory / 'project_territories_powerbi.csv').open(encoding='utf-8-sig', newline='') as stream:
        if list(csv.DictReader(stream)) != result['relationships']:
            raise ValueError('Power BI contains data other than the resolved bridge')
    _verify_workbook(directory / 'revision_territorios.xlsx', result, len(territories))
    idempotence = json.loads((directory / 'idempotence.json').read_text(encoding='utf-8'))
    if idempotence['status'] != 'PASS' or not idempotence['same_inputs_and_code']:
        raise ValueError('Two identical territorial builds are required')
    before_path = root / 'outputs/layer4/territorios/aceptacion/integrity_before.json'
    before = json.loads(before_path.read_text(encoding='utf-8-sig'))
    after = fingerprint(root)
    # Frozen path keys predate namespace migrations. Verify their exact original
    # bytes and the separately fingerprinted current implementation, never rebase.
    for name, expected in before.items():
        verify_expected(root, name, expected)
    source_relocated = before != after
    check_unchanged(root, upstream)
    report = {'status': 'PASS', 'build_id': manifest['build_id'], 'protected_files': len(before),
              'protected_files_unchanged': True, 'idempotence': 'PASS', 'quality': quality,
              'layer1_canonical_altered': False, 'layer2_publication_altered': False,
              'layer3_code_altered': source_relocated, 'layer3_publication_altered': False,
              'source_layout_migrated': source_relocated,
              'integrity_scope': 'ORIGINAL_BYTES_AND_BOUND_CURRENT_RELOCATION',
              'embeddings_recalculated': False, 'llm_used': False, 'external_api_used': False}
    # A read-only historical check must not rewrite the acceptance record.
    report['source_integrity'] = source_integrity
    return report


if __name__ == '__main__':
    try:
        print(json.dumps(verify(), ensure_ascii=True))
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': str(exc)}))
        raise SystemExit(2)
