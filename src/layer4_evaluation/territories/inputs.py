"""Read only the two Layer 2 publications used by territorial characterization."""
import hashlib
import json
from layer2_processing.checkpoints import resolve
from pathlib import Path

import pyarrow.parquet as pq


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_projects(root):
    root = Path(root).resolve()
    directory = resolve(root, 'outputs/layer2/knowledge')
    for sentinel in (root / 'outputs/layer2/knowledge_artifacts/.publish.lock',
                     root / 'outputs/layer2/knowledge_artifacts/publication_pending.json'):
        if sentinel.exists():
            raise ValueError('Layer 2 publication has an active or interrupted writer')
    manifest_path = directory / '_manifest.json'
    original_hash = sha256(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if manifest.get('status') != 'SUCCESS' or manifest.get('publication_kind') != 'real':
        raise ValueError('Territories require a SUCCESS real Layer 2 publication')
    rows = {}
    input_hashes = {}
    from layer2_processing.knowledge.contracts import arrow_schema
    for name in ('source_documents', 'source_sections'):
        path = directory / (name + '.parquet')
        expected_path = Path(str(manifest['output_files'][name]).replace('\\', '/'))
        if resolve(root, expected_path) != path:
            raise ValueError(f'Unexpected Layer 2 output location: {name}')
        input_hashes[name] = sha256(path)
        if input_hashes[name] != manifest['output_hashes'][name]:
            raise ValueError(f'Layer 2 checksum mismatch: {name}')
        data = pq.read_table(path)
        if not data.schema.equals(arrow_schema(name), check_metadata=False):
            raise ValueError(f'Layer 2 schema mismatch: {name}')
        if data.num_rows != manifest[name + '_created']:
            raise ValueError(f'Layer 2 row count mismatch: {name}')
        rows[name] = data.to_pylist()
        if any(row['layer2_run_id'] != manifest['layer2_run_id'] for row in rows[name]):
            raise ValueError(f'Mixed Layer 2 run IDs: {name}')
    documents = [d for d in rows['source_documents'] if d['source_type'] == 'PROJECT']
    by_id = {d['document_id']: d for d in documents}
    if len(by_id) != len(documents) or len({d['source_id'] for d in documents}) != len(documents):
        raise ValueError('Duplicate PROJECT document/source IDs')
    sections = [s for s in rows['source_sections'] if s['source_type'] == 'PROJECT']
    if len({s['section_id'] for s in sections}) != len(sections):
        raise ValueError('Duplicate PROJECT section IDs')
    for section in sections:
        doc = by_id.get(section['document_id'])
        if doc is None or doc['source_id'] != section['source_id']:
            raise ValueError('Orphan PROJECT section or source mismatch')
    if sha256(manifest_path) != original_hash:
        raise ValueError('Layer 2 manifest changed while reading')
    return documents, sections, {
        'manifest_path': str(Path(str(manifest['output_files']['source_documents']).replace('\\', '/')).parent / '_manifest.json').replace('\\', '/'),
        'manifest_sha256': original_hash, 'layer2_run_id': manifest['layer2_run_id'],
        'input_hashes': input_hashes, 'project_documents': len(documents),
        'project_sections': len(sections),
    }


def check_unchanged(root, snapshot):
    directory = Path(root) / 'outputs/layer2/knowledge'
    if any((Path(root) / path).exists() for path in
           ('outputs/layer2/knowledge_artifacts/.publish.lock', 'outputs/layer2/knowledge_artifacts/publication_pending.json')):
        raise ValueError('Layer 2 writer became active during territorial build')
    if sha256(directory / '_manifest.json') != snapshot['manifest_sha256']:
        raise ValueError('Layer 2 changed during territorial build')
    for name, expected in snapshot['input_hashes'].items():
        if sha256(directory / (name + '.parquet')) != expected:
            raise ValueError(f'Layer 2 input changed: {name}')
