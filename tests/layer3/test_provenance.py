"""Lineage contains hashes and inherited references without upstream reads."""
import copy
import json

import pytest

from layer3_graphrag.provenance import digest, lineage, serialize, stable_id, text_hash


def test_stable_ids_use_unambiguous_parts_and_stable_serialization():
    assert stable_id('QUERY', 'ab', 'c') != stable_id('QUERY', 'a', 'bc')
    assert digest({'a': 1, 'b': 2}) == digest({'b': 2, 'a': 1})
    assert stable_id('QUERY', 'consulta') == stable_id('QUERY', 'consulta')
    assert stable_id('QUERY', 'consulta') != stable_id('EMB', 'consulta')
    assert text_hash('é') != text_hash('e')
    assert json.loads(serialize({'title': 'Español'})) == {'title': 'Español'}


def test_nonfinite_metadata_is_not_serializable():
    with pytest.raises(ValueError):
        serialize({'value': float('nan')})


def test_lineage_composes_exact_snapshot_and_never_reads_layer1(snapshot, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Provenance must not open RAW/canonical')
    monkeypatch.setattr('pathlib.Path.open', forbidden)
    chunk = snapshot.tables['source_chunks'][0]
    result = lineage(snapshot, chunk)
    assert result['chunk_id'] == chunk['chunk_id']
    assert result['section_id'] == chunk['section_id']
    assert result['document_id'] == chunk['document_id']
    assert result['source_id'] == chunk['source_id']
    assert result['layer2_manifest_hash'] == snapshot.manifest_hash
    assert result['layer1_manifest_hash'] == snapshot.manifest['layer1_manifest_hash']
    assert result['layer2_run_id'] == snapshot.manifest['layer2_run_id']
    assert result['layer1_run_id'] == snapshot.manifest['layer1_run_id']
    assert result['upstream'] == json.loads(chunk['provenance_json'])


@pytest.mark.parametrize('key', ['layer1_run_id', 'layer2_run_id'])
def test_lineage_rejects_mixed_snapshots(snapshot, key):
    chunk = copy.deepcopy(snapshot.tables['source_chunks'][0])
    provenance = json.loads(chunk['provenance_json'])
    provenance[key] = 'other-run'
    chunk['provenance_json'] = json.dumps(provenance)
    with pytest.raises(ValueError, match='lineage mismatch'):
        lineage(snapshot, chunk)
