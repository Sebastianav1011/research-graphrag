"""Validate inputs, extract territories and publish a complete private package."""
from run_paths import file_path as run_file
from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import uuid

import pyarrow as pa
import pyarrow.parquet as pq

from layer2_processing.preprocessing.dane_reference import load_reference
from .contracts import SCHEMAS, EVIDENCE, table
from .inputs import load_projects, check_unchanged, sha256
from .matching import ACTIVE_RULES, EXTRACTOR_VERSION, extract_territories
from .workbook import export_review

OUTPUT_NAMES = {'relationships': 'project_territories', 'evidence': 'project_territory_evidence',
                'ambiguous': 'project_territory_ambiguous'}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def logical_hash(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def _code_hashes(root):
    paths = sorted((root / 'src/layer4_evaluation/territories').glob('*.py'))
    paths += [root / 'src/layer4_evaluation/__init__.py']
    paths += [root / 'scripts/run_territories.py', root / 'scripts/render_territory_workbook.mjs']
    paths += [root / 'src/layer2_processing/preprocessing/dane_reference.py', root / 'src/layer2_processing/preprocessing/__init__.py']
    return {path.relative_to(root).as_posix(): sha256(path) for path in paths}


def validate_result(documents, sections, territories, result):
    """Check bridge uniqueness, real catalogue membership, provenance and isolation."""
    projects = {d['source_id'] for d in documents}
    section_by_id = {s['section_id']: s for s in sections}
    catalog = {(t['territory_type'], t['dane_code']): t for t in territories}
    keys = [(r['project_id'], r['territory_type'], r['dane_code']) for r in result['relationships']]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate project-territory bridge rows')
    bridge = set(keys)
    evidence_keys = set()
    for row in result['evidence']:
        key = (row['project_id'], row['territory_type'], row['dane_code'])
        if row['resolution_status'] != 'RESOLVED' or key not in bridge:
            raise ValueError('Unpublished or unresolved evidence in resolved table')
        if key[1:] not in catalog or row['territory_name'] != catalog[key[1:]]['territory_name']:
            raise ValueError('Territory not present in authoritative reference')
        evidence_keys.add(key)
    if bridge != evidence_keys or any(key[0] not in projects for key in bridge):
        raise ValueError('Bridge missing source or explicit mention evidence')
    specific = {key[0] for key in bridge if key[1] != 'COUNTRY'}
    if any(key[1] == 'COUNTRY' and (key[2] != '000' or key[0] in specific) for key in bridge):
        raise ValueError('COUNTRY000 must have an explicit country mention and no specific territory')
    for row in result['ambiguous']:
        if row['dane_code'] is not None or row['resolution_status'] != 'AMBIGUOUS':
            raise ValueError('Ambiguous mention exposes a resolved code')
        fields = ('candidate_dane_codes', 'candidate_names', 'candidate_departments', 'candidate_territory_types')
        if row['candidate_count'] < 1 or any(len(row[field]) != row['candidate_count'] for field in fields):
            raise ValueError('Incomplete ambiguity candidates')
        for kind, code, name, department in zip(row['candidate_territory_types'], row['candidate_dane_codes'],
                                               row['candidate_names'], row['candidate_departments']):
            territory = catalog.get((kind, code))
            if territory is None or (name, department) != (territory['territory_name'], territory['department_name']):
                raise ValueError('Invented ambiguous candidate')
    for row in result['evidence'] + result['ambiguous'] + result.get('national_mentions', []):
        section = section_by_id[row['section_id']]
        text = section['text_original'] if section['text_original'] is not None else section['text_normalized']
        if (section['source_id'] != row['project_id'] or section['document_id'] != row['document_id']
                or section['field_name'] != row['field_name']
                or text[row['start_char']:row['end_char']] != row['matched_text']):
            raise ValueError('Mention provenance or original offsets mismatch')
    summary = result['summary']
    if summary['total_projects'] != len(projects) or summary['resolved_relationships'] != len(bridge):
        raise ValueError('Summary does not reconcile to all PROJECT inputs')
    return {'status': 'PASS', 'all_projects_considered': len(projects),
            'bridge_unique': True, 'evidence_offsets_verified': True, 'catalog_membership_verified': True,
            'ambiguous_codes_null': True, 'country_only_without_specific_territory': True}


def _check_reference(root, reference_manifest):
    _, current = load_reference(root / 'outputs/layer2/reference')
    if current != reference_manifest:
        raise ValueError('Territorial reference changed during extraction')
    from layer2_processing.checkpoints import resolve
    if sha256(resolve(root, current['source_file'])) != current['source_sha256']:
        raise ValueError('DANE workbook changed; publish its independent reference before extraction')


def _verify_workbook(path, result, territory_count):
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=False)
    try:
        if wb.sheetnames != ['RESUELTOS', 'AMBIGUOS', 'CATALOGO_DANE', 'METADATA']:
            raise ValueError('Review workbook sheets mismatch')
        counts = [len(result['relationships']), len(result['ambiguous']), territory_count]
        for name, count in zip(wb.sheetnames[:3], counts):
            # Some XLSX exporters omit optional dimension metadata.
            if sum(1 for _ in wb[name].iter_rows()) - 1 != count:
                raise ValueError(f'Review workbook row mismatch: {name}')
        for row, expected in zip(wb['RESUELTOS'].iter_rows(min_row=2), result['relationships']):
            if not isinstance(row[2].value, str) or row[2].data_type != 's':
                raise ValueError('Workbook code lost string representation')
            if [cell.value for cell in row[:3]] != [expected['project_id'], expected['territory_type'], expected['dane_code']]:
                raise ValueError('Workbook altered bridge identifiers or leading zeros')
        for sheet in wb:
            for row in sheet:
                if any(cell.data_type == 'f' for cell in row):
                    raise ValueError('Unexpected formula in static review data')
    finally:
        wb.close()


def build(root):
    root = Path(root).resolve()
    parent = root / 'outputs/layer4'
    parent.mkdir(parents=True, exist_ok=True)
    lock = parent / '.territories.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps({'started_at': datetime.now(timezone.utc).isoformat()}))
    destination = parent / 'territorios/publicacion'
    candidate = parent / ('.territories-candidate-' + uuid.uuid4().hex)
    candidate.mkdir()
    previous = None
    published = False
    try:
        documents, sections, upstream = load_projects(root)
        territories, reference = load_reference(root / 'outputs/layer2/reference')
        if reference.get('country_count') != 1:
            raise ValueError('Build the authorized reference including COUNTRY Colombia 000 first')
        _check_reference(root, reference)
        code_hashes = _code_hashes(root)
        result = extract_territories(documents, sections, territories)
        quality = validate_result(documents, sections, territories, result)
        generated_at = datetime.now(timezone.utc).isoformat()
        payload_hashes = {key: logical_hash(value) for key, value in result.items()}
        build_id = logical_hash({'payloads': payload_hashes, 'upstream': upstream,
                                 'reference_id': reference['reference_id'], 'code_hashes': code_hashes})
        for key, name in OUTPUT_NAMES.items():
            output_table = table(name, result[key])
            target = candidate / (name + '.parquet')
            pq.write_table(output_table, target, compression='zstd')
            if not pq.read_table(target).equals(output_table):
                raise ValueError(f'Parquet roundtrip failed: {name}')
        national_schema = pa.schema(list(EVIDENCE) + [pa.field('publication_status', pa.string())])
        national = pa.Table.from_pylist(result.get('national_mentions', []), schema=national_schema)
        pq.write_table(national, candidate / 'project_national_mentions.parquet', compression='zstd')
        with (candidate / 'project_territories_powerbi.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=SCHEMAS['project_territories'].names)
            writer.writeheader()
            writer.writerows(result['relationships'])
        with (candidate / 'project_territories_powerbi.csv').open(encoding='utf-8-sig', newline='') as stream:
            if list(csv.DictReader(stream)) != result['relationships']:
                raise ValueError('Power BI export differs from resolved bridge')
        (candidate / 'territory_summary.json').write_bytes(json_bytes(result['summary']))
        metadata = {'generated_at_utc': generated_at, 'extractor_version': EXTRACTOR_VERSION,
                    'build_id': build_id, 'layer2_manifest': upstream['manifest_path'],
                    'layer2_manifest_sha256': upstream['manifest_sha256'],
                    'layer2_run_id': upstream['layer2_run_id'], 'layer2_input_hashes': upstream['input_hashes'],
                    'dane_source_file': reference['source_file'], 'dane_source_sha256': reference['source_sha256'],
                    'dane_reference_id': reference['reference_id'], 'code_hashes': code_hashes,
                    'rules': ACTIVE_RULES + ['COUNTRY000 only when no resolved municipality/department'],
                    'policy': 'No LLM / no fuzzy matching / deterministic territorial resolution',
                    'country_extension': '000 = Colombia (USER_DEFINED_COUNTRY, not a DANE department/municipality)',
                    'scope': 'All Layer 2 PROJECT; fields kept separate; no Layer 3 input',
                    'evidence': 'Original matched text and offsets in project_territory_evidence.parquet'}
        workbook_qa = export_review(root, candidate, documents, territories, result, metadata)
        _verify_workbook(candidate / 'revision_territorios.xlsx', result, len(territories))
        (candidate / 'quality.json').write_bytes(json_bytes({**quality, 'workbook': workbook_qa}))
        check_unchanged(root, upstream)
        _check_reference(root, reference)
        if _code_hashes(root) != code_hashes:
            raise ValueError('Territorial source code changed during the build; retry with frozen code')
        prior = None
        if (destination / 'territory_manifest.json').exists():
            prior = json.loads((destination / 'territory_manifest.json').read_text(encoding='utf-8'))
        identical_inputs = bool(prior and prior['layer2'] == upstream and
                                prior['reference_id'] == reference['reference_id'] and
                                prior['code_hashes'] == code_hashes)
        if identical_inputs and prior['payload_hashes'] != payload_hashes:
            raise ValueError('Non-deterministic territorial output for identical inputs/code')
        idempotence = {'status': 'PASS' if identical_inputs else 'FIRST_BUILD_OR_INPUT_CHANGE',
                       'same_inputs_and_code': identical_inputs,
                       'previous_build_id': prior['build_id'] if prior else None,
                       'current_build_id': build_id, 'payload_hashes': payload_hashes}
        (candidate / 'idempotence.json').write_bytes(json_bytes(idempotence))
        manifest = {'status': 'SUCCESS', 'architecture': 'PROJECT_TERRITORY_V1',
                    'extractor_version': EXTRACTOR_VERSION, 'build_id': build_id,
                    'generated_at_utc': generated_at, 'layer2': upstream,
                    'reference_id': reference['reference_id'], 'reference_manifest': reference,
                    'code_hashes': code_hashes, 'payload_hashes': payload_hashes,
                    'summary': result['summary'], 'rules': metadata['rules'],
                    'outputs': {p.relative_to(candidate).as_posix(): {'sha256': sha256(p), 'bytes': p.stat().st_size}
                                for p in sorted(candidate.rglob('*')) if p.is_file()},
                    'no_llm': True, 'no_external_api': True, 'no_embeddings': True,
                    'layer3_consumed_or_modified': False}
        (candidate / 'territory_manifest.json').write_bytes(json_bytes(manifest))
        if destination.exists():
            previous = parent / 'territorios/versiones' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex)
            previous.parent.mkdir(parents=True, exist_ok=True)
            destination.rename(previous)
        try:
            candidate.rename(destination)
            published = True
            check_unchanged(root, upstream)
            _check_reference(root, reference)
        except BaseException:
            if published:
                destination.rename(candidate)
                published = False
            if previous:
                previous.rename(destination)
            raise
        return {'status': 'SUCCESS', 'output_directory': str(destination),
                'build_id': build_id, 'idempotence': idempotence['status'], **result['summary']}
    except BaseException as exc:
        # Preserve failed candidates for diagnosis; never replace a valid publication.
        if candidate.exists():
            (run_file(candidate, 'failure.json')).write_bytes(json_bytes({'status': 'FAILED', 'error': str(exc)}))
        raise
    finally:
        lock.unlink()
