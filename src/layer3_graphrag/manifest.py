"""Manifest creation and complete artifact checksum verification."""
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from . import PIPELINE_VERSION
from .contracts import layer3_manifest_schema
from .provenance import file_hash, serialize


def now():
    return datetime.now(timezone.utc).isoformat()


def output_hashes(directory):
    directory = Path(directory)
    return {p.relative_to(directory).as_posix(): file_hash(p) for p in sorted(directory.rglob('*'))
            if p.is_file() and p.name != '_manifest.json'}


def create_manifest(root, snapshot, config_hash, run_id, started, bundles, indexes, graph, directory):
    manifest = {'layer3_run_id': run_id, 'pipeline_version': PIPELINE_VERSION, 'status': 'SUCCESS',
                'started_at': started, 'finished_at': now(), 'layer3_config_hash': config_hash,
                'layer2_run_id': snapshot.manifest['layer2_run_id'], 'layer2_manifest_hash': snapshot.manifest_hash,
                'layer1_run_id': snapshot.manifest['layer1_run_id'], 'layer1_manifest_hash': snapshot.manifest['layer1_manifest_hash'],
                'embedding_config_hash': bundles['SOURCE'].metadata['embedding_config_hash'],
                'embedding_model': {k: bundles['SOURCE'].metadata[k] for k in ('model', 'model_version', 'dimensions')},
                'vector_indexes': {space: indexes[space].validate() for space in indexes},
                'graph': graph.validate(), 'counts': {'entities': len(graph.nodes), 'relations': len(graph.relations),
                    'embeddings': {space: len(bundle.records) for space, bundle in bundles.items()}},
                'evaluation': {'status': 'PENDING_LABELED_REAL_EVALUATION', 'results': None},
                'output_hashes': output_hashes(directory),
                'code_hashes': {p.name: file_hash(p) for p in sorted((Path(root) / 'src/layer3_graphrag').glob('*.py'))},
                'runtime': {p: importlib.metadata.version(p) for p in ('numpy', 'pyarrow', 'PyYAML', 'jsonschema')}}
    Draft202012Validator(layer3_manifest_schema()).validate(manifest)
    (Path(directory) / '_manifest.json').write_text(serialize(manifest), encoding='utf-8')
    return manifest


def validate_publication(directory, expected_layer2_hash=None):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / '_manifest.json').read_text(encoding='utf-8'))
    Draft202012Validator(layer3_manifest_schema()).validate(manifest)
    if expected_layer2_hash is not None and manifest['layer2_manifest_hash'] != expected_layer2_hash:
        raise ValueError('Layer 3 publication belongs to another knowledge snapshot')
    if not manifest['output_hashes']:
        raise ValueError('Empty Layer 3 artifact manifest')
    for relative, sha in manifest['output_hashes'].items():
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory) or file_hash(path) != sha:
            raise ValueError('Layer 3 artifact hash/path mismatch')
    if output_hashes(directory) != manifest['output_hashes']:
        raise ValueError('Unregistered Layer 3 artifacts')
    if manifest.get('candidate_architecture')=='SOURCE_INDICATOR_V1' and manifest.get('retrieval_parameters',{}).get('enabled'):
        required={'retrieval/source_indicator_candidates.parquet','retrieval/source_context_packages.parquet'}
        obsolete={'retrieval/indicator_candidates.parquet','retrieval/context_packages.parquet'}
        if not required<=manifest['output_hashes'].keys() or obsolete & manifest['output_hashes'].keys():
            raise ValueError('Invalid SOURCE-only publication outputs')
    return manifest
