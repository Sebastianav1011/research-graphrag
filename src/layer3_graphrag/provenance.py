"""Identifiers and retrieval lineage, without following upstream filesystem paths."""
import hashlib
import json
from pathlib import Path


def serialize(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(serialize(value).encode('utf-8')).hexdigest()


def text_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def file_hash(path):
    from layer2_processing.checkpoints import locate
    path=locate(path)
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def stable_id(prefix, *parts):
    return prefix + '_' + digest(parts)


def lineage(snapshot, chunk):
    """Carry inherited L1 provenance; never open canonical or raw."""
    upstream = json.loads(chunk['provenance_json'])
    if upstream.get('layer1_run_id') != snapshot.manifest['layer1_run_id']:
        raise ValueError('Chunk Layer 1 lineage mismatch')
    if upstream.get('layer2_run_id') != snapshot.manifest['layer2_run_id']:
        raise ValueError('Chunk Layer 2 lineage mismatch')
    return {'chunk_id': chunk['chunk_id'], 'section_id': chunk['section_id'],
            'document_id': chunk['document_id'], 'source_id': chunk['source_id'],
            'source_type': chunk['source_type'], 'field_name': chunk['field_name'],
            'layer2_run_id': snapshot.manifest['layer2_run_id'], 'layer2_manifest_hash': snapshot.manifest_hash,
            'layer1_run_id': snapshot.manifest['layer1_run_id'],
            'layer1_manifest_hash': snapshot.manifest['layer1_manifest_hash'], 'upstream': upstream}
