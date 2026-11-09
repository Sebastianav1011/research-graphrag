from layer2_processing.checkpoints import resolve
"""Conservative, lossless projection of the authorized enriched indicator XLSX."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from statistics import median
import unicodedata

from openpyxl import load_workbook
import pyarrow as pa
import pyarrow.parquet as pq

VERSION = 'INDICATOR_ASSESSMENT_PROFILES_V2'
SOURCE = 'data/layer1_sources/reference/indicadores/catalogo_indicadores_v2.xlsx'
SHEET = 'Indicadores_enriquecidos'
COLUMNS = ['id_indicador', 'categoria', 'ambito', 'indicador', 'tipo', 'forma_evaluacion', 'unidad',
           'descripcion_ampliada', 'elementos_clave', 'evidencia_favorable', 'evidencia_insuficiente',
           'terminos_relacionados', 'contexto_relacional', 'fuentes_relevantes']
RULE_COLUMNS = ['id_regla', 'nombre_regla', 'descripcion', 'aplicacion', 'ejemplo_ilustrativo']
FIELDS = ('title', 'keywords', 'summary', 'methodology', 'objectives', 'expected_results')
ALIASES = dict(zip(FIELDS, FIELDS)) | {
    'titulo': 'title', 'palabras clave': 'keywords', 'resumen': 'summary',
    'metodologia': 'methodology', 'objetivos': 'objectives', 'resultados esperados': 'expected_results'}
STRING_FIELDS = ['indicator_id', 'indicator_name', 'indicator_category', 'indicator_dimension',
    'descripcion_ampliada', 'key_elements_original', 'key_elements_status', 'key_elements_parse_method',
    'favorable_evidence', 'insufficient_evidence', 'related_terms', 'relational_context',
    'fuentes_relevantes_original', 'preferred_fields_mapping_status', 'source_catalog', 'source_sheet',
    'source_hash', 'source_record_json', 'profile_version']
PROFILE_SCHEMA = pa.schema([(field, pa.string()) for field in STRING_FIELDS] +
    [('key_elements', pa.list_(pa.string())), ('preferred_evidence_fields', pa.list_(pa.string())),
     ('source_row', pa.int64())])
MAPPING_SCHEMA = pa.schema([('indicator_id', pa.string()), ('original_value', pa.string()),
    ('mapped_fields', pa.list_(pa.string())), ('mapping_status', pa.string()),
    ('preferred_evidence_fields', pa.list_(pa.string()))])


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode('utf-8')


def key_elements(value):
    """Split only syntactically explicit lists, preserving the entire original separately.

    Period lists require a final period, every item capitalized, no abbreviations,
    numeric decimal points or internal periods. Otherwise retain one whole item.
    No proposition is summarized or discarded; commas/conjunctions are not split.
    """
    if value is None or isinstance(value, str) and not value.strip():
        return [], 'EMPTY'
    if not isinstance(value, str):
        raise ValueError('elementos_clave must be text or NULL')
    text = value.strip()
    if text.startswith('['):
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            result = None
        if isinstance(result, list) and all(isinstance(x, str) and x.strip() for x in result):
            return result, 'JSON_ARRAY'
    if '\n' in text and all(re.match(r'^\s*(?:[-•*]|\d+[.)])\s+\S', s)
                             for s in text.splitlines() if s.strip()):
        return [re.sub(r'^\s*(?:[-•*]|\d+[.)])\s+', '', s) for s in text.splitlines() if s.strip()], 'MARKED_LIST'
    if ';' in text:
        parts = [s.strip() for s in text.split(';')]
        if all(parts):
            return parts, 'SEMICOLON_LIST'
    parts = re.findall(r'[^.]+\.(?:\s+|$)', text)
    if (len(parts) > 1 and ''.join(parts) == text and not re.search(r'\d\.\d|\b[A-ZÁÉÍÓÚÑ]\.', text)
            and all(part.lstrip()[0].isupper() and len(part.strip()) > 3 for part in parts)):
        return [part.strip() for part in parts], 'PERIOD_LIST'
    return [text], 'WHOLE_VALUE'


def _label(value):
    plain = ''.join(c for c in unicodedata.normalize('NFD', value.casefold()) if not unicodedata.combining(c))
    return ' '.join(plain.split())


def preferred_fields(value):
    """Whole-label aliases only. Narrative suggestions are not source-field mappings."""
    if value is None or isinstance(value, str) and not value.strip():
        return [], 'EMPTY', []
    if not isinstance(value, str):
        raise ValueError('fuentes_relevantes must be text or NULL')
    text = value.strip()
    # Colon/period prose is intentionally not mined for embedded field words.
    if re.search(r'[:.!?]', text):
        return [], 'UNMAPPED', []
    labels = re.split(r'\s*(?:;|,|\n|\by\b)\s*', text, flags=re.I)
    matched = list(dict.fromkeys(ALIASES[_label(s)] for s in labels if _label(s) in ALIASES))
    all_mapped = bool(labels) and all(_label(s) in ALIASES for s in labels)
    status = 'MAPPED' if all_mapped else 'PARTIALLY_MAPPED' if matched else 'UNMAPPED'
    return matched if all_mapped else [], status, matched


def inspect_catalog(root):
    root = Path(root).resolve()
    path = root / SOURCE
    source_hash = sha256(path)
    wb = load_workbook(path, read_only=True, data_only=False)
    try:
        sheets = [{'name': s.title, 'rows': s.max_row, 'columns': s.max_column} for s in wb]
        if SHEET not in wb.sheetnames:
            raise ValueError('The inspected enriched indicator sheet is missing')
        values = list(wb[SHEET].values)
        if not values or list(values[0]) != COLUMNS:
            raise ValueError('Enriched indicator columns changed; review the mapping explicitly')
        profiles, mappings, seen = [], [], set()
        nulls = Counter()
        types = {name: Counter() for name in COLUMNS}
        empty_rows = []
        for source_row, row in enumerate(values[1:], 2):
            if not any(v is not None for v in row):
                empty_rows.append(source_row)
                continue
            raw = dict(zip(COLUMNS, row))
            for name, value in raw.items():
                if value is not None and not isinstance(value, str):
                    raise ValueError(f'Expected text at {SHEET}/{source_row}/{name}')
                if isinstance(value, str) and value.startswith('='):
                    raise ValueError('Formula cells are not evaluated as reference facts')
                nulls[name] += value is None or isinstance(value, str) and not value.strip()
                types[name][type(value).__name__] += 1
            indicator_id = raw['id_indicador']
            if not indicator_id or not indicator_id.strip() or indicator_id in seen:
                raise ValueError('Missing or duplicate indicator ID')
            if not raw['indicador'] or not raw['categoria']:
                raise ValueError('Missing official indicator name/category')
            seen.add(indicator_id)
            elements, parse_method = key_elements(raw['elementos_clave'])
            preferred, mapping_status, mapped = preferred_fields(raw['fuentes_relevantes'])
            profile = {'indicator_id': indicator_id, 'indicator_name': raw['indicador'],
                'indicator_category': raw['categoria'], 'indicator_dimension': raw['ambito'],
                'descripcion_ampliada': raw['descripcion_ampliada'], 'key_elements': elements,
                'key_elements_original': raw['elementos_clave'],
                'key_elements_status': 'AVAILABLE' if elements else 'MISSING',
                'key_elements_parse_method': parse_method, 'favorable_evidence': raw['evidencia_favorable'],
                'insufficient_evidence': raw['evidencia_insuficiente'], 'related_terms': raw['terminos_relacionados'],
                'relational_context': raw['contexto_relacional'], 'preferred_evidence_fields': preferred,
                'fuentes_relevantes_original': raw['fuentes_relevantes'], 'preferred_fields_mapping_status': mapping_status,
                'source_catalog': SOURCE, 'source_sheet': SHEET, 'source_row': source_row,
                'source_hash': source_hash, 'source_record_json': json.dumps(raw, ensure_ascii=False, sort_keys=True),
                'profile_version': VERSION}
            profiles.append(profile)
            mappings.append({'indicator_id': indicator_id, 'original_value': raw['fuentes_relevantes'],
                'mapped_fields': mapped, 'mapping_status': mapping_status, 'preferred_evidence_fields': preferred})
        if not profiles:
            raise ValueError('No valid indicator profiles')
        rules = []
        if 'Reglas_generales' in wb.sheetnames:
            rows = list(wb['Reglas_generales'].values)
            if list(rows[0]) != RULE_COLUMNS:
                raise ValueError('General rule columns changed; inspect before mapping')
            rule_ids = set()
            for number, row in enumerate(rows[1:], 2):
                if not any(v is not None for v in row):
                    continue
                raw = dict(zip(RULE_COLUMNS, row))
                if (not all(isinstance(v, str) and v.strip() for v in row)
                        or any(v.startswith('=') for v in row) or raw['id_regla'] in rule_ids):
                    raise ValueError('Invalid or duplicate general rule')
                rule_ids.add(raw['id_regla'])
                rules.append({**raw, 'rule_status': 'RULE_TEXT', 'implemented_rule': False,
                              'source_sheet': 'Reglas_generales', 'source_row': number, 'source_hash': source_hash})
        counts = [len(p['key_elements']) for p in profiles]
        audit = {'source_catalog': SOURCE, 'source_hash': source_hash, 'sheets': sheets,
            'source_sheet': SHEET, 'header_row': 1, 'columns': COLUMNS, 'valid_indicator_rows': len(profiles),
            'empty_source_rows': empty_rows, 'null_counts': dict(nulls),
            'observed_types': {k: dict(v) for k, v in types.items()},
            'indicators_with_key_elements': sum(bool(n) for n in counts),
            'indicators_without_key_elements': sum(not n for n in counts),
            'key_elements_count': {'min': min(counts), 'median': median(counts), 'max': max(counts)},
            'key_element_parse_methods': dict(Counter(p['key_elements_parse_method'] for p in profiles)),
            'preferred_field_mapping_counts': {s: sum(m['mapping_status'] == s for m in mappings)
                for s in ('MAPPED', 'PARTIALLY_MAPPED', 'UNMAPPED', 'EMPTY')}, 'general_rules': len(rules)}
        if sha256(path) != source_hash:
            raise ValueError('Indicator source changed during inspection')
        return profiles, {'version': VERSION, 'source_hash': source_hash, 'rules': rules}, mappings, audit
    finally:
        wb.close()


def build_profiles(root):
    root = Path(root).resolve()
    destination = root / 'outputs/layer4/indicator_profiles'
    profiles, rules, mappings, audit = inspect_catalog(root)
    software_root = Path(__file__).resolve().parents[3]
    code = {name: sha256(software_root/name) for name in (
        'src/layer4_evaluation/__init__.py', 'src/layer4_evaluation/indicators/__init__.py',
        'src/layer4_evaluation/indicators/profiles.py')}
    code['scripts/build_indicator_assessment_profiles.py'] = sha256(software_root/'scripts/build_indicator_assessment_profiles.py')
    from jsonschema import Draft202012Validator
    validator=Draft202012Validator(json.loads((software_root/'schemas/layer4_assessment/indicator_profile.schema.json').read_text(encoding='utf-8')))
    for profile in profiles:validator.validate(profile)
    logical_hash = hashlib.sha256(encoded(profiles)).hexdigest()
    reference_id = hashlib.sha256(encoded({'version': VERSION, 'source': audit['source_hash'],
                                            'payload': logical_hash, 'code': code})).hexdigest()
    version = destination / 'indicator_assessment_versions' / reference_id
    payloads = {'indicator_assessment_rules.json': encoded(rules), 'indicator_assessment_profiles_audit.json': encoded(audit)}
    for name, rows, schema in [('indicator_assessment_profiles', profiles, PROFILE_SCHEMA),
                               ('indicator_preferred_field_mappings', mappings, MAPPING_SCHEMA)]:
        table = pa.Table.from_pylist(rows, schema=schema)
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink, compression='zstd')
        payloads[name+'.parquet'] = sink.getvalue().to_pybytes()
        if not pq.read_table(pa.BufferReader(payloads[name+'.parquet'])).equals(table):
            raise ValueError('Profile output roundtrip failed')
    source_bytes = (root/SOURCE).read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != audit['source_hash']:
        raise ValueError('Source changed before snapshot')
    manifest = {'status': 'SUCCESS', 'version': VERSION, 'reference_id': reference_id,
        'source_catalog': SOURCE, 'source_sheet': SHEET, 'source_hash': audit['source_hash'],
        'logical_sha256': logical_hash, 'code_hashes': code, 'indicator_count': len(profiles),
        'metrics': audit, 'general_rules_kind': 'RULE_TEXT', 'general_rules_implemented': 0,
        'version_directory': version.relative_to(root).as_posix(),
        'source_snapshot': (version/'source_catalog.xlsx').relative_to(root).as_posix(),
        'outputs': {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
        'layer3_modified': False, 'assessment_executed': False}
    payloads['indicator_assessment_profiles_manifest.json'] = encoded(manifest)
    version.mkdir(parents=True, exist_ok=True)
    for name, data in {**payloads, 'source_catalog.xlsx': source_bytes}.items():
        target = version/name
        if target.exists() and target.read_bytes() != data:
            raise ValueError('Immutable indicator assessment version mismatch')
        if not target.exists():
            target.write_bytes(data)
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        target = destination/name
        temporary = destination/('.'+name+'.pending')
        temporary.write_bytes(data)
        temporary.replace(target)
    return profiles, manifest


def load_profiles(root):
    root = Path(root).resolve()
    directory = root/'outputs/layer4/indicator_profiles'
    path = directory/'indicator_assessment_profiles_manifest.json'
    before = path.read_bytes()
    manifest = json.loads(before)
    if manifest.get('status') != 'SUCCESS' or manifest.get('version') != VERSION:
        raise ValueError('Unsupported indicator assessment reference')
    for name, digest in manifest['outputs'].items():
        if Path(name).name != name or sha256(directory/name) != digest:
            raise ValueError('Indicator profile checksum mismatch: '+name)
    table = pq.read_table(directory/'indicator_assessment_profiles.parquet')
    if not table.schema.equals(PROFILE_SCHEMA):
        raise ValueError('Indicator profile Arrow schema mismatch')
    profiles = table.to_pylist()
    if hashlib.sha256(encoded(profiles)).hexdigest() != manifest['logical_sha256']:
        raise ValueError('Indicator profile logical hash mismatch')
    if (len(profiles) != manifest['indicator_count'] or sha256(resolve(root,manifest['source_catalog'])) != manifest['source_hash']
            or sha256(resolve(root,manifest['source_snapshot'])) != manifest['source_hash'] or path.read_bytes() != before):
        raise ValueError('Indicator source/snapshot changed')
    return profiles, manifest
