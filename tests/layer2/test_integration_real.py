"""Opt-in real integration only; no fixture generation, no RAW, no publication."""
import json
import os
from pathlib import Path
import pytest
from layer2_knowledge.pipeline import build_package, context_for, run
from layer2_knowledge.validate_inputs import load_config, validate_inputs, WaitingForLayer1, ConfigurationPending
from layer2_knowledge.provenance import payload_hash
from layer2_knowledge.quality import evaluate
from layer2_knowledge.security import excluded

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.environ.get('LAYER2_REAL_INTEGRATION') != '1',
    reason='PENDING_LAYER_1_REAL: explicit opt-in and approved real manifest required')


@pytest.fixture(scope='module')
def real_package():
    config, digest = load_config(ROOT, os.environ.get('LAYER2_CONFIG', 'config/layer2.yaml'))
    try:
        snapshot = validate_inputs(ROOT, config)
    except (WaitingForLayer1, ConfigurationPending) as exc:
        pytest.skip('PENDING_LAYER_1_REAL: ' + str(exc))
    context = context_for(snapshot, config, digest, 'INTEGRATION_READ_ONLY')
    package = build_package(snapshot, config, context)
    return package, snapshot, config, context, digest


def test_real_documents_one_per_source(real_package):
    package, snapshot, *_ = real_package
    assert len(package['source_documents']) == len(snapshot['datasets']['proyectos']) + len(snapshot['datasets']['articulos'])
    assert all(d['source_type'] in {'PROJECT', 'ARTICLE'} for d in package['source_documents'])


def test_real_input_contract_snapshot(real_package):
    _, snapshot, config, *_ = real_package
    assert snapshot['manifest']['status'] == 'SUCCESS'
    assert set(snapshot['datasets']) == set(config['datasets']) | set(config['relations'])
    for name, inspection in snapshot['inspection'].items():
        assert inspection['rows'] == len(snapshot['datasets'][name])
        assert snapshot['hashes'][name] == snapshot['manifest']['canonical_files'][name]['sha256']


def test_real_canonical_unchanged_after_building(real_package):
    from layer2_knowledge.validate_inputs import assert_unchanged
    _, snapshot, *_ = real_package
    assert_unchanged(ROOT, snapshot['hashes'], snapshot['manifest_hash'])


def test_real_sections_keep_fields_and_original(real_package):
    from layer2_knowledge.text_normalization import as_text
    from layer2_knowledge.security import apply_email_privacy
    from layer2_knowledge.provenance import text_hash
    package, snapshot, config, *_ = real_package
    documents = {d['document_id']: d for d in package['source_documents']}
    upstream_index = {name: {r[config['datasets'][name]['id_field']]: r for r in rows}
                      for name, rows in snapshot['datasets'].items() if name in config['datasets']}
    for s in package['source_sections']:
        d = documents[s['document_id']]
        assert s['field_name'] in config['datasets'][d['canonical_dataset']]['text_fields']
        assert not excluded(s['field_name'], config)
        dataset = d['canonical_dataset']
        id_field = config['datasets'][dataset]['id_field']
        upstream = upstream_index[dataset][s['source_id']]
        original = as_text(upstream[s['field_name']])
        expected, count = apply_email_privacy(original, config.get('privacy',{}).get('email_policy','reject'))
        assert s['text_original'] == expected
        provenance = json.loads(s['provenance_json'])
        assert provenance['email_redactions'] == count
        assert provenance['text_hash_input'] == text_hash(original if original is not None else '')


def test_real_chunks_offsets_and_boundaries(real_package):
    package, _, config, *_ = real_package
    for prefix in ('source', 'reference'):
        sections = {s['section_id']: s for s in package[prefix + '_sections']}
        for c in package[prefix + '_chunks']:
            s = sections[c['section_id']]
            assert c['text'] == s['text_normalized'][c['char_start']:c['char_end']]
            assert all(c[k] == s[k] for k in ('source_id', 'source_type', 'field_name', 'document_id'))
            assert c['word_count'] <= config['chunking']['max_words']


def test_real_reference_separation(real_package):
    package, snapshot, *_ = real_package
    assert len(package['reference_documents']) == len(snapshot['datasets']['indicadores'])
    assert all(c['source_type'] == 'INDICATOR_REFERENCE' for c in package['reference_chunks'])
    assert not ({d['document_id'] for d in package['source_documents']} & {d['document_id'] for d in package['reference_documents']})


def test_real_entities_canonical_ids(real_package):
    package, snapshot, config, *_ = real_package
    canonical_ids = {name: {r[spec['id_field']] for r in snapshot['datasets'][name]}
                     for name, spec in config['datasets'].items()}
    for e in package['entities']:
        p = json.loads(e['provenance_json'])
        spec = config['datasets'][p['canonical_dataset']]
        assert e['entity_id'] == e['entity_type'] + ':' + e['canonical_id']
        assert e['canonical_id'] in canonical_ids[p['canonical_dataset']]


def test_real_explicit_relations_only(real_package):
    package, snapshot, config, *_ = real_package
    allowed = {r['relation_type'] for r in config['relations'].values()}
    ids = {e['entity_id'] for e in package['entities']}
    assert len(package['relations']) == sum(len(snapshot['datasets'][n]) for n in config['relations'])
    for r in package['relations']:
        assert r['relation_type'] in allowed
        assert r['source_entity_id'] in ids and r['target_entity_id'] in ids
        assert r['evidence_type'] == 'STRUCTURED_CANONICAL'


def test_real_provenance_quality_privacy(real_package):
    package, snapshot, config, context, _ = real_package
    summary, reports = evaluate(package, snapshot['datasets'], config, context)
    assert summary['status'] == 'PASS'
    assert not reports['provenance_issues']
    assert not reports['pii_findings']
    assert not reports['privacy_structure_issues']
    assert not reports['orphan_entities'] and not reports['orphan_relations']


def test_real_idempotent_ids_and_payloads(real_package):
    package, snapshot, config, context, digest = real_package
    second = build_package(snapshot, config, context_for(snapshot, config, digest, 'SECOND_READ_ONLY'))
    for name in package:
        id_field = next(iter(package[name][0])) if package[name] else None
        if id_field:
            assert [r[id_field] for r in package[name]] == [r[id_field] for r in second[name]]
        assert payload_hash(package[name]) == payload_hash(second[name])


def test_real_end_to_end_validation_without_publication(real_package):
    result = run(ROOT, os.environ.get('LAYER2_CONFIG', 'config/layer2.yaml'), mode='validate')
    assert result['status'] == 'PASS'


@pytest.mark.skipif(os.environ.get('LAYER2_VERIFY_PUBLICATION') != '1', reason='PENDING_REAL_PUBLICATION: verify after two approved CLI runs')
def test_real_published_manifest_hashes_and_idempotence():
    from layer2_knowledge.provenance import file_hash
    from layer2_knowledge.contracts import manifest_schema
    from jsonschema import Draft202012Validator
    manifests = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((ROOT / 'outputs/layer2/manifests').glob('run_*.json'))]
    successes = [m for m in manifests if m.get('status') == 'SUCCESS']
    assert len(successes) >= 2
    previous, latest = successes[-2:]
    Draft202012Validator(manifest_schema()).validate(latest)
    assert latest['layer1_manifest_hash'] == previous['layer1_manifest_hash']
    assert latest['layer2_config_hash'] == previous['layer2_config_hash']
    assert latest['payload_hashes'] == previous['payload_hashes']
    published = json.loads((ROOT / 'data/knowledge/_manifest.json').read_text(encoding='utf-8'))
    assert published == latest
    for name, relative in latest['output_files'].items():
        assert file_hash(ROOT / relative) == latest['output_hashes'][name]
