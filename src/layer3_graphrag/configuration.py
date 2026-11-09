"""Configuration validation and closed-by-default execution approval."""
import copy
import math
from pathlib import Path

import yaml
from .contracts import ENTITY_TYPES, RELATION_ENDPOINTS
from .provenance import digest
from layer2_processing.checkpoints import resolve, destination


def inside(root, relative, allowed):
    root = Path(root).resolve()
    raw = Path(relative)
    if raw.is_absolute():
        raise ValueError('Layer 3 paths must be project-relative')
    path = destination(root, raw).resolve()
    allowed = tuple(destination(root, base).relative_to(root).as_posix() for base in allowed)
    if not any(path == root / base or path.is_relative_to(root / base) for base in allowed):
        raise ValueError('Path outside Layer 3 boundary')
    return path


def validate_config(config):
    config = copy.deepcopy(config)
    for section in ('readiness', 'execution', 'input', 'embeddings', 'vector_index', 'graph', 'hybrid', 'context', 'evaluation', 'quality', 'outputs'):
        if not isinstance(config.get(section), dict):
            raise ValueError('Missing configuration section: ' + section)
    if config['input']['knowledge_manifest'].replace('\\', '/') != 'outputs/layer2/knowledge/_manifest.json':
        raise ValueError('Only the official knowledge manifest may be configured')
    if config['vector_index']['backend'] != 'numpy_exact' or config['graph']['backend'] != 'local_json':
        raise ValueError('Unsupported local backend')
    positive = [(config['embeddings'], 'batch_size'), (config['vector_index'], 'top_k'), (config['hybrid'], 'candidate_pool')]
    positive += [(config['graph'], k) for k in ('max_neighbors', 'max_total_nodes')]
    positive += [(config['context'], k) for k in ('max_chunks', 'max_documents', 'max_entities', 'max_relations', 'max_reference_chunks', 'max_characters')]
    if 'max_package_characters' in config['context']:
        positive.append((config['context'], 'max_package_characters'))
    for section, key in positive:
        if type(section.get(key)) is not int or section[key] < 1:
            raise ValueError('Positive integer required: ' + key)
    if type(config['graph'].get('max_hops')) is not int or config['graph']['max_hops'] < 0:
        raise ValueError('max_hops must be a nonnegative integer')
    for key, valid in (('allowed_relation_types', RELATION_ENDPOINTS), ('allowed_entity_types', ENTITY_TYPES)):
        if not isinstance(config['graph'].get(key), list) or not set(config['graph'][key]) <= set(valid):
            raise ValueError('Unknown graph filter: ' + key)
    for key in ('vector_weight', 'graph_weight', 'structured_relation_weight', 'diversity_weight'):
        value = config['hybrid'].get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid retrieval weight: ' + key)
    if sum(config['hybrid'][k] for k in ('vector_weight', 'graph_weight', 'structured_relation_weight')) == 0:
        raise ValueError('At least one base ranking weight must be positive')
    for section, key in ((config['execution'], 'allow_real_build'), (config['embeddings'], 'normalize_embeddings'),
                         (config['embeddings'], 'allow_model_download'), (config['graph'], 'expand_ambiguous_researchers'),
                         (config['quality'], 'fail_on_orphan_relation'), (config['quality'], 'fail_on_missing_provenance')):
        if type(section.get(key)) is not bool:
            raise ValueError('Boolean required: ' + key)
    dimensions = config['embeddings'].get('dimensions')
    if dimensions is not None and (type(dimensions) is not int or dimensions < 1):
        raise ValueError('Invalid embedding dimensions')
    if config['graph'].get('researcher_bridge_policy', 'resolved_only') != 'resolved_only':
        raise ValueError('Researcher bridge policy must be resolved_only')
    if config.get('retrieval', {}).get('enabled'):
        if config['graph']['expand_ambiguous_researchers']:
            raise ValueError('Real indicator retrieval prohibits ambiguous researcher bridges')
        for key in ('vector_top_k_per_reference_chunk', 'max_chunks_per_source', 'final_candidates_per_indicator'):
            if type(config['retrieval'].get(key)) is not int or config['retrieval'][key] < 1:
                raise ValueError('Positive retrieval integer required: ' + key)
        if config['hybrid']['vector_weight'] + config['hybrid']['graph_weight'] != 1:
            raise ValueError('Real hybrid weights must sum to one')
    ks = config['evaluation'].get('k_values')
    if not isinstance(ks, list) or not ks or any(type(k) is not int or k < 1 for k in ks):
        raise ValueError('Invalid evaluation K values')
    modes = config['evaluation'].get('compare_modes')
    if not isinstance(modes, list) or not modes or not set(modes) <= {'vector', 'graph', 'hybrid'} or len(modes) != len(set(modes)):
        raise ValueError('Invalid evaluation mode')
    return config


def load_config(root, path='config/layer3.yaml'):
    location = inside(root, path, ('config',))
    with location.open(encoding='utf-8-sig') as stream:
        config = validate_config(yaml.safe_load(stream))
    inside(root, config['embeddings']['cache'], ('outputs/layer3',))
    if config['embeddings'].get('local_model_path'):
        inside(root, config['embeddings']['local_model_path'], ('outputs/layer3/models',))
    if config['outputs']['publication'].replace('\\', '/') != 'outputs/layer3/publication':
        raise ValueError('Official Layer 3 destination must be outputs/layer3/publication')
    for key in ('base', 'quality', 'manifests', 'reports'):
        inside(root, config['outputs'][key], ('outputs/layer3',))
    return config, digest(config)


def require_approval(config, building=False):
    if config['readiness'].get('layer2_status') != 'FINAL_PROJECT_LAYER_2_READY':
        raise RuntimeError('WAITING_FOR_FINAL_PROJECT_LAYER_2_READY')
    sha = config['readiness'].get('approved_layer2_manifest_sha256')
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
        raise RuntimeError('Explicit approved Layer 2 manifest SHA-256 is required')
    if building and not config['execution'].get('allow_real_build'):
        raise RuntimeError('Real build is disabled in configuration')
