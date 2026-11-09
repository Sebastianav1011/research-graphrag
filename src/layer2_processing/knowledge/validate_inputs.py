from layer2_processing.checkpoints import resolve
"""Canonical-only reader. Never dereferences provenance file paths."""
import json
import hashlib
from pathlib import Path
import yaml
import pyarrow as pa
import pyarrow.parquet as pq
from .provenance import file_hash
from .security import excluded

EXPECTED = {'proyectos': 'PROJECT', 'articulos': 'ARTICLE', 'investigadores': 'RESEARCHER',
            'organizaciones': 'ORGANIZATION', 'indicadores': 'INDICATOR'}
RELATIONS = {'proyecto_investigador': 'PROJECT_HAS_RESEARCHER', 'articulo_investigador': 'ARTICLE_HAS_RESEARCHER'}
PROVENANCE_FIELDS = ['record_source', 'source_row', 'etl_run_id', 'provenance_json']


class WaitingForLayer1(RuntimeError):
    pass


class ConfigurationPending(RuntimeError):
    pass


def load_config(root, config_path, include_bytes=False):
    path = Path(config_path)
    if not path.is_absolute():
        path = root / path
    content = path.read_bytes()
    config = yaml.safe_load(content.decode('utf-8'))
    validate_config(root, config)
    result = (config, hashlib.sha256(content).hexdigest())
    return result + (content,) if include_bytes else result


def validate_config(root, config):
    if set(config['datasets']) != set(EXPECTED) or set(config['relations']) != set(RELATIONS):
        raise ValueError('Exactly five canonical entity datasets and two explicit relations required')
    if resolve(root, config['input']['canonical']).resolve() != (resolve(root, 'outputs/layer2/canonical')).resolve():
        raise ValueError('Only official outputs/layer2/canonical input permitted')
    if not (root / config['input']['canonical']).resolve().is_relative_to(root.resolve()):
        raise ValueError('Canonical symlink/junction cannot escape official root')
    for key, relative in config['outputs'].items():
        resolved = (root / relative).resolve()
        allowed = root / ('outputs/layer2/knowledge' if key == 'knowledge' else 'outputs/layer2/knowledge_artifacts')
        if not resolved.is_relative_to(root.resolve()) or not resolved.is_relative_to(allowed.resolve()):
            raise ValueError('Output must remain within its Layer 2 boundary')
    paths = [(root / value).resolve() for value in config['outputs'].values()]
    for i, left in enumerate(paths):
        if any(left.is_relative_to(right) or right.is_relative_to(left) for right in paths[i+1:]):
            raise ValueError('Output paths must be disjoint')
    for dataset, spec in config['datasets'].items():
        if spec['entity_type'] != EXPECTED[dataset]:
            raise ValueError('Entity type incompatible with canonical dataset')
        fields = spec.get('text_fields', [])
        if len(fields) != len(set(fields)) or any(excluded(f, config) for f in fields):
            raise ValueError('Duplicate, sensitive or technical corpus field requested')
        if dataset in {'investigadores', 'organizaciones'} and fields:
            raise ValueError('Researcher/organization documents are not corpus inputs')
        if excluded(spec['label_field'], config, corpus=False):
            raise ValueError('Sensitive field cannot be a document title or entity label')
    for dataset, spec in config['relations'].items():
        expected_source = 'proyectos' if dataset == 'proyecto_investigador' else 'articulos'
        if (spec['relation_type'] != RELATIONS[dataset] or spec['source_dataset'] != expected_source
                or spec['target_dataset'] != 'investigadores'
                or spec['source_field'] != config['datasets'][expected_source]['id_field']
                or spec['target_field'] != config['datasets']['investigadores']['id_field']):
            raise ValueError('Only configured explicit canonical membership relations permitted')
        if any(excluded(f, config, corpus=False) for f in spec.get('attribute_fields', [])):
            raise ValueError('Sensitive relation attribute requested')
    attributes = config['datasets']['indicadores']['reference_attributes']
    if set(attributes) != {'name', 'category', 'dimension', 'description'}:
        raise ValueError('Reference attributes must map name/category/dimension/description explicitly')
    chunk = config['chunking']
    if chunk['strategy'] != 'hierarchical_words_v1':
        raise ValueError('Unsupported chunking strategy')
    if any(type(chunk[k]) is not int for k in ('target_words', 'max_words', 'overlap_words')):
        raise ValueError('Chunk sizes must be integers')
    if not (0 <= chunk['overlap_words'] < chunk['target_words'] <= chunk['max_words']):
        raise ValueError('Require 0 <= overlap < target <= maximum')
    if config['normalization']['unicode'] != 'NFC':
        raise ValueError('Conservative normalization requires NFC')
    privacy = config.get('privacy', {})
    if privacy.get('email_policy', 'reject') not in {'reject', 'mask'}:
        raise ValueError('Unsupported email privacy policy')
    if privacy.get('email_policy') == 'mask' and (not privacy.get('authorization') or privacy.get('email_marker') != '[EMAIL_EXCLUDED]'):
        raise ValueError('Email masking requires explicit recorded authorization and fixed marker')
    if not 0 <= config['quality']['max_empty_document_ratio'] <= 1:
        raise ValueError('Empty document ratio must be in [0,1]')


def require_approval(root, config, publishing=False):
    if (root / '.layer1.lock').exists():
        raise WaitingForLayer1('LAYER_2_WAITING_FOR_LAYER_1: active writer')
    manifest_path = root / 'outputs/layer2/canonical/_manifest.json'
    if not manifest_path.is_file():
        manifest_path = resolve(root, 'outputs/layer2/canonical/_manifest.json')
    if not manifest_path.is_file():
        raise WaitingForLayer1('LAYER_2_WAITING_FOR_LAYER_1: no published manifest')
    readiness = config['readiness']
    if readiness['publication_kind'] != 'real' or not readiness['approved_layer1_manifest_sha256']:
        raise ConfigurationPending('LAYER_2_CONFIGURATION_PENDING: attest real publication and approve manifest hash')
    if publishing and not (readiness['mappings_verified'] and readiness['chunking_calibrated']):
        raise ConfigurationPending('LAYER_2_CONFIGURATION_PENDING: mappings/calibration unapproved')
    if manifest_path.resolve().parent != (resolve(root, 'outputs/layer2/canonical')).resolve():
        raise ValueError('UPSTREAM_DATA_ISSUE: manifest link escapes canonical')
    if file_hash(manifest_path) != readiness['approved_layer1_manifest_sha256']:
        raise ConfigurationPending('LAYER_2_CONFIGURATION_PENDING: approved snapshot changed')
    return manifest_path


def assert_unchanged(root, hashes, manifest_hash):
    if (root / '.layer1.lock').exists():
        raise WaitingForLayer1('LAYER_2_WAITING_FOR_LAYER_1: writer started')
    folder = resolve(root, 'outputs/layer2/canonical')
    if file_hash(folder / '_manifest.json') != manifest_hash:
        raise ValueError('UPSTREAM_DATA_ISSUE: manifest changed during read')
    for dataset, digest in hashes.items():
        if file_hash(folder / (dataset + '.parquet')) != digest:
            raise ValueError('UPSTREAM_DATA_ISSUE: canonical changed during read: ' + dataset)


def validate_inputs(root, config):
    manifest_path = require_approval(root, config)
    manifest_hash = file_hash(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('status') != config['input']['manifest_success_status']:
        raise WaitingForLayer1('LAYER_2_WAITING_FOR_LAYER_1: manifest not SUCCESS')
    if manifest.get('synthetic') is True or manifest.get('publication_kind') == 'synthetic':
        raise ValueError('UPSTREAM_DATA_ISSUE: synthetic publication forbidden')
    run_id = manifest.get(config['input']['manifest_run_id_field'])
    if not isinstance(run_id, str) or not run_id:
        raise ValueError('UPSTREAM_DATA_ISSUE: missing layer1 run ID')
    files = manifest.get(config['input']['manifest_files_field'], {})
    datasets, hashes, inspection = {}, {}, {}
    for name in list(config['datasets']) + list(config['relations']):
        path = manifest_path.parent / (name + '.parquet')
        if path.resolve().parent != manifest_path.parent.resolve():
            raise ValueError('UPSTREAM_DATA_ISSUE: canonical file link escapes dataset directory')
        if not path.is_file():
            raise ValueError('UPSTREAM_DATA_ISSUE: required dataset missing: ' + name)
        meta = files.get(name, {})
        digest = file_hash(path)
        if meta.get('sha256') != digest:
            raise ValueError('UPSTREAM_DATA_ISSUE: absent/mismatched manifest hash: ' + name)
        table = pq.read_table(path)
        spec = config['datasets'].get(name, config['relations'].get(name))
        if name in config['datasets']:
            required = list(dict.fromkeys([spec['id_field']] + spec['required_fields'] + PROVENANCE_FIELDS))
            keys = [spec['id_field']]
        else:
            required = [spec['source_field'], spec['target_field']] + PROVENANCE_FIELDS
            keys = [spec['source_field'], spec['target_field']] + spec['attribute_fields']
        missing = set(required) - set(table.column_names)
        if missing:
            raise ValueError('UPSTREAM_DATA_ISSUE: REQUIRED fields absent: ' + name + ': ' + ','.join(sorted(missing)))
        for field in set(required + spec.get('text_fields', []) + spec.get('metadata_fields', []) + spec.get('attribute_fields', []) + [spec.get('label_field', '')]):
            if field not in table.column_names:
                continue
            kind = config.get('field_types', {}).get(field, 'string')
            typ = table.schema.field(field).type
            valid = {'string': pa.types.is_string(typ) or pa.types.is_large_string(typ),
                     'integer': pa.types.is_integer(typ), 'boolean': pa.types.is_boolean(typ),
                     'list_string': pa.types.is_list(typ) and pa.types.is_string(typ.value_type)}
            if not valid.get(kind, False):
                raise ValueError('UPSTREAM_DATA_ISSUE: unexpected Arrow type: ' + name + '.' + field)
        rows = table.to_pylist()
        if meta.get('rows') != len(rows) or meta.get('columns') != len(table.column_names):
            raise ValueError('UPSTREAM_DATA_ISSUE: manifest counts incompatible: ' + name)
        seen = set()
        for row in rows:
            if any(row.get(k) is None for k in required) or row['etl_run_id'] != run_id:
                raise ValueError('UPSTREAM_DATA_ISSUE: required null/mixed run: ' + name)
            if any(isinstance(row[k], str) and not row[k].strip() for k in required):
                raise ValueError('UPSTREAM_DATA_ISSUE: empty required value: ' + name)
            if name == 'investigadores' and row['identity_status'] not in spec['allowed_identity_statuses']:
                raise ValueError('UPSTREAM_DATA_ISSUE: identity status incompatible with contract')
            key = tuple(row.get(k) for k in keys)
            if key in seen:
                raise ValueError('UPSTREAM_DATA_ISSUE: duplicate canonical key: ' + name)
            seen.add(key)
            refs = json.loads(row['provenance_json'])
            if not isinstance(refs, list) or not refs or any(not isinstance(r, dict) or not r.get('record_source')
                    or not isinstance(r.get('source_row'), int) or r['source_row'] < 1
                    or not isinstance(r.get('field_mapping'), dict) or not isinstance(r.get('original_values'), dict) for r in refs):
                raise ValueError('UPSTREAM_DATA_ISSUE: invalid Layer 1 provenance: ' + name)
        datasets[name] = sorted(rows, key=lambda r: tuple(str(r.get(k)) for k in keys))
        hashes[name] = digest
        optional = spec.get('text_fields', []) + spec.get('metadata_fields', []) + spec.get('attribute_fields', [])
        inspection[name] = {'rows': len(rows), 'columns': {f.name: str(f.type) for f in table.schema},
            'keys': keys, 'missing_optional': sorted(set(optional) - set(table.column_names)),
            'sensitive_fields': [f for f in table.column_names if excluded(f, config, corpus=False)]}
    for name, spec in config['relations'].items():
        source = {r[config['datasets'][spec['source_dataset']]['id_field']] for r in datasets[spec['source_dataset']]}
        target = {r[config['datasets'][spec['target_dataset']]['id_field']] for r in datasets[spec['target_dataset']]}
        if any(r[spec['source_field']] not in source or r[spec['target_field']] not in target for r in datasets[name]):
            raise ValueError('UPSTREAM_DATA_ISSUE: orphan canonical relation: ' + name)
    assert_unchanged(root, hashes, manifest_hash)
    return {'datasets': datasets, 'hashes': hashes, 'inspection': inspection,
            'manifest': manifest, 'manifest_hash': manifest_hash, 'layer1_run_id': run_id}
