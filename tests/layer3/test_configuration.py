"""Configuration and approval tests do not inspect the institutional corpus."""
import copy

import pytest
import yaml

from layer3_graphrag.configuration import inside, load_config, require_approval, validate_config
from layer3_graphrag.validate_inputs import validate_inputs


def test_default_configuration_blocks_corpus_reads(layer3_config, monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError('Corpus access before explicit snapshot approval')

    monkeypatch.setattr('pathlib.Path.read_bytes', forbidden)
    with pytest.raises(RuntimeError, match='WAITING'):
        validate_inputs(tmp_path, layer3_config)


def test_approval_requires_status_hash_and_build_flag(layer3_config):
    config = copy.deepcopy(layer3_config)
    config['readiness']['layer2_status'] = 'FINAL_PROJECT_LAYER_2_READY'
    with pytest.raises(RuntimeError, match='SHA-256'):
        require_approval(config)
    config['readiness']['approved_layer2_manifest_sha256'] = 'a' * 64
    require_approval(config)
    with pytest.raises(RuntimeError, match='disabled'):
        require_approval(config, building=True)
    config['execution']['allow_real_build'] = True
    require_approval(config, building=True)


@pytest.mark.parametrize('sha', ['x' * 64, 'A' * 64, 'a' * 63, None, 12])
def test_approval_rejects_non_sha256(layer3_config, sha):
    config = copy.deepcopy(layer3_config)
    config['readiness'].update(layer2_status='FINAL_PROJECT_LAYER_2_READY', approved_layer2_manifest_sha256=sha)
    with pytest.raises(RuntimeError):
        require_approval(config)


@pytest.mark.parametrize('section,key,value', [
    ('graph', 'max_hops', -1), ('graph', 'max_hops', True),
    ('graph', 'max_neighbors', 0), ('graph', 'max_total_nodes', 0),
    ('vector_index', 'top_k', '10'), ('embeddings', 'batch_size', False),
    ('embeddings', 'dimensions', 0), ('embeddings', 'normalize_embeddings', 1),
    ('execution', 'allow_real_build', 'false'), ('context', 'max_chunks', 0),
    ('context', 'max_package_characters', 0),
    ('graph', 'allowed_relation_types', ['INVENTED']),
    ('graph', 'allowed_entity_types', ['PERSON_ALIAS']),
    ('hybrid', 'vector_weight', float('nan')), ('hybrid', 'graph_weight', -1),
    ('hybrid', 'structured_relation_weight', True), ('hybrid', 'diversity_weight', float('inf')),
    ('evaluation', 'k_values', [1, 0]), ('evaluation', 'compare_modes', ['llm']),
    ('evaluation', 'compare_modes', []), ('evaluation', 'compare_modes', 'vector'),
    ('evaluation', 'compare_modes', ['vector', 'vector']),
    ('input', 'knowledge_manifest', 'data/canonical/_manifest.json'),
])
def test_invalid_configuration_rejected(layer3_config, section, key, value):
    config = copy.deepcopy(layer3_config)
    config[section][key] = value
    with pytest.raises(ValueError):
        validate_config(config)


def test_zero_base_ranking_weights_rejected(layer3_config):
    config = copy.deepcopy(layer3_config)
    for key in ('vector_weight', 'graph_weight', 'structured_relation_weight'):
        config['hybrid'][key] = 0
    with pytest.raises(ValueError, match='positive'):
        validate_config(config)


@pytest.mark.parametrize('path', ['data/canonical/cache', 'data/raw/cache', 'data/staging/cache',
                                 'outputs/layer2/cache', '../outside', '/absolute'])
def test_output_boundary_rejects_other_layers(tmp_path, path):
    with pytest.raises(ValueError):
        inside(tmp_path, path, ('outputs/layer3',))


@pytest.mark.parametrize('section,key,bad', [('embeddings', 'cache', 'outputs/layer2/cache'),
                                          ('outputs', 'quality', 'data/canonical'),
                                          ('outputs', 'publication', 'data/knowledge')])
def test_loader_enforces_path_boundary(tmp_path, layer3_config, section, key, bad):
    config = copy.deepcopy(layer3_config)
    config[section][key] = bad
    folder = tmp_path / 'config'
    folder.mkdir()
    (folder / 'layer3.yaml').write_text(yaml.safe_dump(config), encoding='utf-8')
    with pytest.raises(ValueError):
        load_config(tmp_path)


def test_config_hash_is_stable_and_input_not_mutated(tmp_path, layer3_config):
    original = copy.deepcopy(layer3_config)
    folder = tmp_path / 'config'
    folder.mkdir()
    (folder / 'layer3.yaml').write_text(yaml.safe_dump(layer3_config), encoding='utf-8')
    loaded, sha = load_config(tmp_path)
    assert load_config(tmp_path)[1] == sha
    loaded['graph']['max_hops'] += 1
    assert layer3_config == original
