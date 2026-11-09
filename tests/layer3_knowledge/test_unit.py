"""Pure technical tests: no fictional domain records or persistent Parquet datasets."""
import copy
import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from jsonschema import Draft202012Validator
from layer2_processing.knowledge.chunking import spans
from layer2_processing.knowledge.contracts import SCHEMAS, arrow_schema, logical_schema, manifest_schema
from layer2_processing.knowledge.pipeline import publish_directory
from layer2_processing.knowledge.provenance import stable_id, text_hash, payload_hash, serialize
from layer2_processing.knowledge.quality import statistics, field_traceable
from layer2_processing.knowledge.security import excluded
from layer2_processing.knowledge.text_normalization import normalize, words, as_text
from layer2_processing.knowledge.validate_inputs import load_config, validate_config, require_approval, WaitingForLayer1, ConfigurationPending

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config():
    # Negative readiness cases use an unapproved copy; no datasets or publication created.
    config = load_config(ROOT, 'config/layer2.yaml')[0]
    config['readiness'] = {'publication_kind': 'unverified', 'approved_layer1_manifest_sha256': None,
                           'mappings_verified': False, 'chunking_calibrated': False}
    return config


def test_unicode_original_untouched(config):
    original = '  investigacio\u0301n\u00a0  reproducible\r\n\r\n\ufeffTexto\u200b.  '
    assert normalize(original, config['normalization']) == 'investigación reproducible\n\nTexto.'
    assert '\u0301' in original and '\r' in original


def test_normalization_preserves_language(config):
    text = 'Método / Method: “resultado”; A\u200dB\u200cC — β.'
    assert normalize(text, config['normalization']) == text


@pytest.mark.parametrize('value,expected', [(None, None), ('', ''), (['uno', 'dos'], 'uno\ndos')])
def test_text_representation(value, expected):
    assert as_text(value) == expected


def test_invalid_text_type():
    with pytest.raises(ValueError, match='UPSTREAM_DATA_ISSUE'):
        as_text(42)


def test_ids_escape_without_collision():
    assert stable_id('TECH', 'a_b', 'c') != stable_id('TECH', 'a', 'b_c')
    assert stable_id('TECH', 'a/b') == stable_id('TECH', 'a/b')


def test_sha256_and_payload_operational_fields():
    assert len(text_hash('texto')) == 64
    assert text_hash('Texto') != text_hash('texto')
    a = [{'value': 'texto', 'layer2_run_id': 'one', 'provenance_json': serialize({'layer2_run_id': 'one', 'layer1_run_id': 'fixed'})}]
    b = [{'value': 'texto', 'layer2_run_id': 'two', 'provenance_json': serialize({'layer2_run_id': 'two', 'layer1_run_id': 'fixed'})}]
    assert payload_hash(a) == payload_hash(b)
    b[0]['value'] = 'cambio'
    assert payload_hash(a) != payload_hash(b)


def test_config_provisional(config):
    assert not config['readiness']['mappings_verified']
    assert not config['readiness']['chunking_calibrated']
    assert config['readiness']['approved_layer1_manifest_sha256'] is None


@pytest.mark.parametrize('mutation', ['raw_input', 'escaping_output', 'overlap', 'sensitive', 'inference', 'overlapping_outputs'])
def test_config_rejects_unsafe_decisions(config, mutation):
    if mutation == 'raw_input': config['input']['canonical'] = 'data/layer1_sources'
    elif mutation == 'escaping_output': config['outputs']['quality'] = 'outputs/layer2/preprocessing/quality'
    elif mutation == 'overlap': config['chunking']['overlap_words'] = config['chunking']['target_words']
    elif mutation == 'sensitive': config['datasets']['proyectos']['text_fields'].append('email')
    elif mutation == 'inference': config['relations']['proyecto_investigador']['relation_type'] = 'PROJECT_HAS_INDICATOR'
    else: config['outputs']['reports'] = config['outputs']['quality']
    with pytest.raises(ValueError): validate_config(ROOT, config)


@pytest.mark.parametrize('field', ['email', 'document_number', 'cédula', 'birth_date', 'marital_status', 'sex', 'doi', 'institutional_id'])
def test_sensitive_and_technical_exclusion(config, field):
    assert excluded(field, config)
    assert not excluded('summary', config)


def test_missing_manifest_waits_without_outputs(tmp_path, config):
    with pytest.raises(WaitingForLayer1, match='LAYER_2_WAITING_FOR_LAYER_1'):
        require_approval(tmp_path, config)
    assert not list(tmp_path.iterdir())


def test_unverified_manifest_is_never_opened(config):
    root = MagicMock()
    root.__truediv__.return_value.exists.return_value = False
    root.__truediv__.return_value.is_file.return_value = True
    with pytest.raises(ConfigurationPending): require_approval(root, config)
    root.__truediv__.return_value.open.assert_not_called()
    root.__truediv__.return_value.read_text.assert_not_called()


def test_short_section_single(config):
    text = 'Una sección corta. Conserva cada palabra.'
    assert spans(text, config['chunking']) == [(0, len(text), 0)]
    assert spans('', config['chunking']) == []


def test_paragraph_preferred(config):
    chunk = config['chunking'] | {'target_words': 6, 'max_words': 8, 'overlap_words': 0}
    text = 'uno dos tres cuatro cinco seis\n\nsiete ocho nueve diez once doce trece catorce'
    result = spans(text, chunk)
    assert text[result[0][0]:result[0][1]] == 'uno dos tres cuatro cinco seis'


def test_sentence_fallback(config):
    chunk = config['chunking'] | {'target_words': 4, 'max_words': 6, 'overlap_words': 0}
    text = 'Uno dos tres cuatro. Cinco seis siete ocho. Nueve diez once doce.'
    result = spans(text, chunk)
    assert text[result[0][0]:result[0][1]] == 'Uno dos tres cuatro.'


@pytest.mark.parametrize('overlap', [0, 1, 3])
def test_long_sentence_offsets_overlap_coverage(config, overlap):
    chunk = config['chunking'] | {'target_words': 7, 'max_words': 10, 'overlap_words': overlap}
    text = ' '.join('palabra' + str(i) for i in range(47))
    result = spans(text, chunk)
    assert result == spans(text, chunk)
    assert result[0][0] == 0 and result[-1][1] == len(text)
    original_tokens = words(text)
    covered = set()
    for index, (start, end, actual_overlap) in enumerate(result):
        assert len(words(text[start:end])) <= 10
        covered.update(i for i, token in enumerate(original_tokens) if start <= token.start() and token.end() <= end)
        assert actual_overlap == (overlap if index else 0)
        if index and overlap:
            prior = text[result[index-1][0]:result[index-1][1]].split()
            assert prior[-overlap:] == text[start:end].split()[:overlap]
    assert covered == set(range(47))


def test_statistics_empty_and_interpolated():
    assert statistics([])['p95'] is None
    assert statistics([0, 10])['median'] == 5
    assert statistics([0, 10])['p90'] == 9


def test_field_lineage_requires_original_column():
    # Metadata structure only; no domain fixture and no original data file opened.
    p = {'layer1': [{'field_mapping': {'field': 'column'}, 'original_values': {'column': None}}]}
    assert field_traceable(p, 'field')
    assert not field_traceable(p, 'absent')


@pytest.mark.parametrize('name', list(SCHEMAS))
def test_formal_contracts_valid(name):
    Draft202012Validator.check_schema(logical_schema(name))
    assert arrow_schema(name).names == list(SCHEMAS[name])
    assert logical_schema(name)['additionalProperties'] is False


def test_manifest_contract():
    Draft202012Validator.check_schema(manifest_schema())
    assert manifest_schema()['properties']['publication_kind']['const'] == 'real'


def test_payload_hash_preserves_upstream_operational_looking_columns():
    # Generic upstream metadata must not be stripped by the L2 operational filter.
    a = [{'provenance_json': serialize({'layer2_run_id': 'one', 'layer1': [{'original_values': {'started_at': 'a'}}]})}]
    b = [{'provenance_json': serialize({'layer2_run_id': 'two', 'layer1': [{'original_values': {'started_at': 'b'}}]})}]
    assert payload_hash(a) != payload_hash(b)


def test_publish_rollback_without_filesystem():
    candidate, destination, archive = MagicMock(), MagicMock(), MagicMock()
    journal = archive.parents.__getitem__.return_value.__truediv__.return_value
    journal.exists.return_value = False
    destination.exists.return_value = True
    candidate.rename.side_effect = OSError('technical failure')
    with pytest.raises(OSError):
        publish_directory(candidate, destination, archive, lambda: None)
    destination.rename.assert_called_once()
    archive.__truediv__.return_value.rename.assert_called_once_with(destination)
    journal.unlink.assert_called_once()


def test_schemas_exported_without_drift():
    for name in SCHEMAS:
        assert json.loads((ROOT / 'schemas/layer2' / (name + '.schema.json')).read_text(encoding='utf-8')) == logical_schema(name)


def test_lineage_projection_keeps_field_origin_without_personal_values():
    from layer2_processing.knowledge.provenance import project_lineage
    refs = [{'record_source': 'technical-input', 'source_row': 2,
             'source_record_id': 'private', 'field_mapping': {'field': 'column', 'email': 'email'},
             'original_values': {'column': 'texto', 'email': 'technical@example.invalid'}}]
    projected = project_lineage(refs, ['field'])
    assert projected[0]['original_values'] == {'column': 'texto'}
    assert projected[0]['field_mapping'] == {'field': 'column'}
    assert projected[0]['record_source'] == 'technical-input' and projected[0]['source_row'] == 2
    assert 'source_record_id' not in projected[0]
    assert 'email' in refs[0]['original_values']


def test_pii_pattern_detects_exact_identifiers_and_email_without_substring_matches():
    from layer2_processing.knowledge.security import pii_matcher
    config = load_config(ROOT, 'config/layer2.yaml')[0]
    matches = pii_matcher({'technical': [{'document_number': '12345678'}]}, config)
    assert matches('Valor 12345678.')
    assert matches('technical@example.invalid')
    assert not matches('Valor 9123456780.')
    assert not matches('Texto académico sin identificadores.')


def test_email_only_masking_preserves_null_and_scientific_text():
    from layer2_processing.knowledge.security import apply_email_privacy
    assert apply_email_privacy(None, 'mask') == (None, 0)
    text = 'Resultado β. Contacto: technical@example.invalid. Método intacto.'
    masked, count = apply_email_privacy(text, 'mask')
    assert masked == 'Resultado β. Contacto: [EMAIL_EXCLUDED]. Método intacto.'
    assert count == 1
    assert apply_email_privacy(text, 'reject') == (text, 0)


def test_projected_lineage_masks_email_and_keeps_input_hash():
    from layer2_processing.knowledge.provenance import project_lineage
    ref = [{'record_source': 'technical-input', 'source_row': 2,
            'field_mapping': {'field': 'column'}, 'original_values': {'column': 'Texto technical@example.invalid'}}]
    projected = project_lineage(ref, ['field'], 'mask')
    assert projected[0]['original_values']['column'] == 'Texto [EMAIL_EXCLUDED]'
    assert projected[0]['privacy_redactions'][0]['count'] == 1
    assert projected[0]['privacy_redactions'][0]['input_value_sha256'] == text_hash(serialize(ref[0]['original_values']['column']))
    assert project_lineage(projected, ['field'], 'mask') == projected


def test_publish_finalize_failure_restores_previous():
    candidate, destination, archive = MagicMock(), MagicMock(), MagicMock()
    journal = archive.parents.__getitem__.return_value.__truediv__.return_value
    journal.exists.return_value = False
    destination.exists.return_value = True
    def failure():
        raise RuntimeError('Finalize failed')
    with pytest.raises(RuntimeError, match='Finalize failed'):
        publish_directory(candidate, destination, archive, failure)
    assert destination.rename.call_count == 2
    archive.__truediv__.return_value.rename.assert_called_once_with(destination)


def test_chunking_many_technical_lengths(config):
    for maximum in (3, 8, 17):
        for target in (maximum, max(2, maximum//2)):
            for overlap in (0, target-1):
                options = config['chunking'] | {'max_words': maximum, 'target_words': target, 'overlap_words': overlap}
                for length in (1, maximum, maximum+1, maximum*5+1):
                    text = ' '.join('palabra.' if i % 3 == 0 else 'palabra' for i in range(length))
                    result = spans(text, options)
                    assert result[-1][1] == len(text)
                    assert all(len(words(text[a:b])) <= maximum for a, b, _ in result)
                    assert all(result[i][1] > result[i-1][1] for i in range(1, len(result)))
