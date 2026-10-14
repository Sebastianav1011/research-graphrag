"""Accept two real publications: hashes, IDs, payloads, privacy and upstream immutability."""
import json
import sys
from pathlib import Path
from collections import Counter
import pyarrow.parquet as pq
from jsonschema import Draft202012Validator
from openpyxl import load_workbook
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from layer2_knowledge.contracts import SCHEMAS, arrow_schema, manifest_schema
from layer2_knowledge.provenance import file_hash, payload_hash, serialize
from layer2_knowledge.validate_inputs import load_config, validate_inputs, assert_unchanged
from layer2_knowledge.security import scan_package_structure


def main():
    config, config_hash = load_config(ROOT, 'config/layer2.yaml')
    snapshot = validate_inputs(ROOT, config)
    folder = ROOT / 'outputs/layer2/reports'
    baseline = json.loads((folder / 'upstream_before.json').read_text(encoding='utf-8'))
    assert snapshot['manifest_hash'] == baseline['layer1_manifest_hash'], 'Snapshot changed; repeat approval and synchronization'
    assert snapshot['hashes'] == baseline['canonical_hashes'], 'Canonical hashes changed'
    protected = {relative: file_hash(ROOT / relative) for relative in baseline['protected_file_hashes']}
    assert protected == baseline['protected_file_hashes'], 'Protected Layer 1/template files changed'
    assert not (ROOT / 'outputs/layer2/.publish.lock').exists()
    assert not (ROOT / 'outputs/layer2/publication_pending.json').exists()
    manifests = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((ROOT/'outputs/layer2/manifests').glob('run_*.json'))]
    successes = [m for m in manifests if m.get('status') == 'SUCCESS']
    assert len(successes) >= 2
    first, final = successes[-2:]
    published = json.loads((ROOT/'data/knowledge/_manifest.json').read_text(encoding='utf-8'))
    assert published == final
    Draft202012Validator(manifest_schema()).validate(final)
    assert first['layer1_manifest_hash'] == final['layer1_manifest_hash'] == snapshot['manifest_hash']
    assert first['layer2_config_hash'] == final['layer2_config_hash'] == config_hash
    previous_dir = ROOT/'outputs/layer2/runs'/final['layer2_run_id']/'previous_knowledge'
    assert json.loads((previous_dir/'_manifest.json').read_text(encoding='utf-8')) == first
    idempotence, outputs, package = {}, {}, {}
    for name in SCHEMAS:
        path = ROOT / final['output_files'][name]
        assert file_hash(path) == final['output_hashes'][name]
        table = pq.read_table(path)
        assert table.schema == arrow_schema(name)
        rows = table.to_pylist()
        previous = pq.read_table(previous_dir/(name+'.parquet')).to_pylist()
        id_field = next(iter(SCHEMAS[name]))
        assert [r[id_field] for r in rows] == [r[id_field] for r in previous]
        assert payload_hash(rows) == payload_hash(previous) == final['payload_hashes'][name] == first['payload_hashes'][name]
        assert len(rows) == final[name+'_created']
        idempotence[name] = {'ids': 'PASS', 'payloads': 'PASS'}
        outputs[path.name] = {'rows': len(rows), 'sha256': file_hash(path)}
        package[name] = rows
    issues = scan_package_structure(package, snapshot['datasets'], config)
    assert not issues, 'Source/reference privacy structure issues'
    assert not final['quality_summary']['failures']
    assert sum(final['quality_summary']['entities'].values()) == sum(len(snapshot['datasets'][name]) for name in config['datasets'])
    assert len(package['relations']) == sum(len(snapshot['datasets'][name]) for name in config['relations'])
    ids = {r['entity_id'] for r in package['entities']}
    assert all(r['source_entity_id'] in ids and r['target_entity_id'] in ids for r in package['relations'])
    assert {r['relation_type'] for r in package['relations']} <= {'PROJECT_HAS_RESEARCHER','ARTICLE_HAS_RESEARCHER'}
    workbook = load_workbook(ROOT/'templates/resultado_final_indicadores.xlsx', read_only=True, data_only=False)
    template = {}
    for sheet in workbook:
        headers = next(sheet.iter_rows(min_row=1,max_row=1,values_only=True))
        row_count = sum(any(value is not None for value in row) for row in sheet.iter_rows(min_row=2,values_only=True))
        assert len(headers) == 16 and row_count == 0
        template[sheet.title] = {'columns':len(headers),'data_rows':row_count}
    assert len(template) == 2
    workbook.close()
    functional_paths = list((ROOT/'src/layer2_knowledge').glob('*.py')) + list((ROOT/'tests/layer2').glob('*.py'))
    functional_paths += [ROOT/'config/layer2.yaml'] + [p for p in (ROOT/'scripts').glob('*layer2*.py')]
    legacy = ['Pruebas\\Prueba GraphRag', 'Pruebas/Prueba GraphRag', 'data_canonical', 'audit_datos_graphrag', '.graphml']
    assert all(not any(token in p.read_text(encoding='utf-8') for token in legacy) for p in functional_paths if p.name != 'verify_layer2.py')
    assert_unchanged(ROOT, snapshot['hashes'], snapshot['manifest_hash'])
    outputs['_manifest.json'] = {'rows': None, 'sha256':file_hash(ROOT/'data/knowledge/_manifest.json')}
    result = {'status':'PASS', 'layer1_run_id':snapshot['layer1_run_id'], 'layer1_manifest_hash':snapshot['manifest_hash'],
        'layer2_runs':[first['layer2_run_id'], final['layer2_run_id']], 'canonical_unchanged': True,
        'protected_files_unchanged':True, 'input_counts':{n:len(r) for n,r in snapshot['datasets'].items()},
        'idempotence':idempotence, 'outputs':outputs, 'quality': final['quality_summary'],
        'source_sections_by_type':dict(Counter(r['source_type'] for r in package['source_sections'])),
        'researcher_identity_statuses':dict(Counter(r['identity_status'] for r in snapshot['datasets']['investigadores'])),
        'template':template, 'functional_legacy_references':0}
    (folder/'acceptance.json').write_text(serialize(result),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['status','layer1_run_id','layer2_runs','canonical_unchanged','outputs']},indent=2))


if __name__ == '__main__':
    main()
