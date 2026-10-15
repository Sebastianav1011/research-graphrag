"""Forensic replay in memory. Writes only identity_alias_forensics reports."""
import csv
import hashlib
import hmac
import json
import os
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from layer1_data.runtime import read_config
from layer1_data.runtime import resolve_input
from layer1_data.canonicalize import canonical_entities, canonical_researchers
from layer1_data.identity import STRONG, evidence_values, resolve
from layer1_data.ingestion import ingest
from layer1_data.normalize import header, identifier, name, normalize_record, text
from layer1_data.pipeline import source_specs
from layer1_data.provenance import file_hash
from layer1_data.quality import write_csv
from layer1_data.ingestion import map_rows, mapped_values, validate_rows

OUT = ROOT / 'outputs/layer1/reports/identity_alias_forensics'
CATEGORIES = ('SOURCE_ALREADY_CONFLICTING', 'TRANSFORMATION_CONFLICT', 'COLUMN_MAPPING_ERROR',
              'ROW_ALIGNMENT_ERROR', 'DUPLICATE_RECORD_CONFLICT', 'FORMAT_ONLY', 'UNKNOWN')


def clean(value):
    value = text(value)
    if value and len(value) >= 2 and value[0] == value[-1] == '"':
        value = text(value[1:-1])
    return identifier(value)


def occurrence(row):
    return (row['_file'], row.get('_sheet'), row['_row'], row['_candidate_domain'])


def independent_csv_records(decoded, delimiter):
    """Independent lexical scanner preserves physical lines and literal field slices."""
    i = start = field_start = 0
    line = record_line = 1
    quoted = False
    fields, literals = [], []

    def cell(literal):
        if literal.startswith('"') and literal.endswith('"'):
            return literal[1:-1].replace('""', '"')
        return literal

    while i < len(decoded):
        char = decoded[i]
        if char == '"':
            if quoted:
                if i + 1 < len(decoded) and decoded[i + 1] == '"':
                    i += 2
                    continue
                quoted = False
            elif i == field_start:
                quoted = True
        if not quoted and (char == delimiter or char in '\r\n'):
            literal = decoded[field_start:i]
            fields.append(cell(literal))
            literals.append(literal)
            if char != delimiter:
                end = i + (2 if char == '\r' and decoded[i:i + 2] == '\r\n' else 1)
                yield record_line, line, fields, literals, decoded[start:end]
                fields, literals = [], []
                start = field_start = end
                i = end
                line += 1
                record_line = line
                continue
            field_start = i + 1
        if char == '\n' or (char == '\r' and decoded[i:i + 2] != '\r\n'):
            line += 1
        i += 1
    assert not quoted, 'Unclosed quoted field in independent scanner'
    if field_start < len(decoded) or fields:
        literal = decoded[field_start:]
        yield record_line, line, fields + [cell(literal)], literals + [literal], decoded[start:]


def reconstruct_graph(rows):
    """Replay the actual token/union order and record all effective unions."""
    parent = list(range(len(rows)))
    sizes = [1] * len(rows)
    tokens, unions = {}, []

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, row in enumerate(rows):
        keys = [(field, value) for field in STRONG for value in evidence_values(row, field)]
        if row.get('normalized_name') and row.get('email'):
            keys.append(('name_email', (row['normalized_name'], row['email'])))
        prior_alias_roots = {find(tokens[key]) for key in keys if key[0] == 'institutional_id' and key in tokens}
        for key in keys:
            if key not in tokens:
                tokens[key] = i
                continue
            j = tokens[key]
            a, b = find(i), find(j)
            if a == b:
                continue
            prior_bridge = sizes[a] > 1 and sizes[b] > 0
            unions.append({'sequence': len(unions) + 1, 'i': i, 'j': j,
                           'field': key[0], 'token': key[1], 'left_size': sizes[a], 'right_size': sizes[b],
                           'merges_preexisting_components': prior_bridge,
                           'alias_bridge': prior_bridge and key[0] == 'institutional_id' and len(prior_alias_roots) >= 2})
            lo, hi = min(a, b), max(a, b)
            parent[hi] = lo
            sizes[lo] = sizes[a] + sizes[b]
    groups = defaultdict(list)
    for i in range(len(rows)):
        groups[find(i)].append(i)
    largest = max(groups.values(), key=len)
    included = set(largest)
    return largest, [event for event in unions if event['i'] in included and event['j'] in included]


def main():
    canonical = ROOT / 'data/canonical'
    manifest_path = canonical / '_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    run_id = manifest['run_id']
    assert manifest['status'] == 'SUCCESS'
    frozen_paths = list(canonical.iterdir())
    frozen_paths += [Path(meta['path']) for meta in manifest['input_files']]
    frozen_paths += [ROOT / rel for rel in manifest['code_hashes']]
    frozen_paths += [ROOT / 'config/sources.yaml', ROOT / 'config/layer1.yaml', ROOT / 'templates/resultado_final_indicadores.xlsx']
    frozen_paths += list((ROOT / 'data/staging').glob('*/' + run_id + '/*.parquet'))
    frozen_paths += list((ROOT / 'outputs/layer1/quality').iterdir())
    frozen_paths += [ROOT / 'outputs/layer1/audit/anomalies.csv', ROOT / 'outputs/layer1/latest_run.json']
    protected = {str(path): file_hash(path) for path in frozen_paths if path.is_file()}
    assert all(protected[meta['path']] == meta['sha256'] for meta in manifest['input_files'])
    assert all(file_hash(ROOT / rel) == sha for rel, sha in manifest['code_hashes'].items())
    for field in ('sources', 'settings'):
        assert file_hash(Path(manifest['configuration'][field])) == manifest['configuration'][field + '_sha256']
    OUT.mkdir(parents=True, exist_ok=True)
    private = OUT / '_private'
    private.mkdir(exist_ok=True)
    key_path = private / 'pseudonym_key.bin'
    if not key_path.exists():
        key_path.write_bytes(os.urandom(32))
    secret = key_path.read_bytes()

    def anon(value, namespace='identifier'):
        if value is None:
            return None
        payload = json.dumps([namespace, value], ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')
        return 'P_' + hmac.new(secret, payload, hashlib.sha256).hexdigest()[:24]

    sources = read_config(ROOT / 'config/sources.yaml')
    settings = read_config(ROOT / 'config/layer1.yaml')
    normalized = defaultdict(list)
    batches, mappings, sources_summary = [], [], []
    stages = {}
    for stage_path in (ROOT / 'data/staging').glob('*/' + run_id + '/*.parquet'):
        for row in pq.read_table(stage_path).to_pylist():
            key = (row['record_source'], row['source_row'])
            assert key not in stages
            stages[key] = row | {'original': json.loads(row['original_values_json']),
                                 'interpreted': json.loads(row['interpreted_values_json']),
                                 'mapping': json.loads(row['field_mapping_json'])}
    for domain, spec in source_specs(sources):
        path = resolve_input(ROOT, spec['path'])
        rows, events, meta = ingest(path, domain, spec, settings, run_id)
        assert not any(e['severity'] == 'CRITICAL' for e in events)
        mapped = map_rows(rows, spec)
        for row in mapped:
            stage = stages[(row['_file'], row['_row'])]
            assert stage['original'] == row['_raw']
            assert stage['mapping'] == spec['mapping']
            assert stage['interpreted'] == {k: text(v, settings['normalization']) for k, v in row.items() if not k.startswith('_')}
        normalized[domain].extend(normalize_record(row, settings['normalization']) for row in mapped)
        headers = meta['original_headers']
        names = {header(h): h for h in headers}
        diagnostic = {'source_file': str(path), 'domain': domain, 'records': len(rows),
                      'header_count': len(headers), 'id_empleado_exists': 'id_empleado' in names,
                      'id_investigador_exists': 'id_investigador' in names,
                      'both_exist': all(f in names for f in ('id_empleado', 'id_investigador')),
                      'original_headers': headers, 'structural_anomalies': dict(Counter(e['anomaly_code'] for e in events)),
                      'literal_conflicts': 0, 'normalized_conflicts': 0, 'format_only_pairs_outside_target': 0}
        sources_summary.append(diagnostic)
        for source_col in ('id_empleado', 'id_investigador', 'cedula_empleado', 'cedula_investigador', 'documento', 'cedula', 'nombre_completo', 'nombre_investigador'):
            consumers = []
            for section in ('mapping', 'researcher_mapping'):
                for dest, cols in spec.get(section, {}).items():
                    if source_col in (cols if isinstance(cols, list) else [cols]):
                        consumers.append({'config_section': section, 'canonical_field': dest})
            mappings.append({'source_file': str(path), 'domain': domain, 'column_name': source_col,
                             'exists': source_col in names, 'literal_header': names.get(source_col),
                             'position_1based': headers.index(names[source_col]) + 1 if source_col in names else None,
                             'both_id_columns_exist': diagnostic['both_exist'], 'mapping_json': json.dumps(consumers),
                             'canonical_fields': '|'.join(c['canonical_field'] for c in consumers),
                             'original_headers_json': json.dumps(headers, ensure_ascii=False)})
        independent = {}
        if diagnostic['both_exist']:
            decoded = path.read_bytes().decode(meta['encoding'])
            lex = independent_csv_records(decoded, meta['delimiter'])
            _, _, lexical_headers, _, _ = next(lex)
            assert lexical_headers == headers
            actual_rows = {row['_row']: row for row in rows}
            for row_no, end_line, fields, literals, record_literal in lex:
                if row_no not in actual_rows:
                    continue
                assert len(fields) == len(headers)
                assert dict(zip(headers, fields)) == actual_rows[row_no]['_raw']
                encoding = 'utf-8' if meta['encoding'].replace('_', '-').lower() == 'utf-8-sig' else meta['encoding']
                independent[row_no] = {'values': dict(zip(headers, fields)), 'literals': dict(zip(headers, literals)),
                                       'end_line': end_line, 'record_sha256': hashlib.sha256(record_literal.encode(encoding)).hexdigest()}
                a, b = fields[headers.index(names['id_empleado'])], fields[headers.index(names['id_investigador'])]
                if clean(a) and clean(b) and a != b:
                    diagnostic['literal_conflicts'] += 1
                if clean(a) and clean(b) and clean(a) != clean(b):
                    diagnostic['normalized_conflicts'] += 1
                elif clean(a) and clean(b) and a != b:
                    diagnostic['format_only_pairs_outside_target'] += 1
            assert len(independent) == len(rows)
        batches.append({'domain': domain, 'spec': spec, 'path': str(path), 'rows': rows,
                        'independent': independent, 'headers': names})
    print('Source, independent CSV scan and published staging comparisons: PASS', flush=True)
    valid = {}
    for domain, rows in normalized.items():
        valid[domain], _, _ = validate_rows(rows, domain, settings, run_id)
    for domain in ('proyectos', 'articulos', 'indicadores'):
        _, valid[domain], _, _ = canonical_entities(valid[domain], domain, run_id)
    candidates = []
    for row in valid['investigadores']:
        row['_candidate_domain'] = 'investigadores'
        candidates.append(row)
    for domain in ('proyectos', 'articulos'):
        for row in valid[domain]:
            mapping = row['_spec'].get('researcher_mapping')
            if not mapping:
                continue
            candidate = mapped_values(row['_parsed'], mapping)
            if not any(text(v) for v in candidate.values()):
                continue
            candidate.update({k: v for k, v in row.items() if k.startswith('_')})
            candidate['_mapping'] = mapping
            candidate['_candidate_domain'] = domain
            candidate = normalize_record(candidate, settings['normalization'])
            if domain == 'proyectos':
                candidate['source_project_id'] = row['source_project_id']
            good, _, _ = validate_rows([candidate], 'investigadores', settings, run_id)
            candidates.extend(good)
    assert len(candidates) == manifest['identity_candidates']
    entities, assignments, _ = resolve(deepcopy(candidates), run_id)
    published_researchers = pq.read_table(canonical / 'investigadores.parquet').to_pylist()
    assert canonical_researchers(entities, run_id) == published_researchers
    researcher_by_id = {row['researcher_id']: row for row in published_researchers}
    largest, union_events = reconstruct_graph(candidates)
    assert len(largest) == 21348
    giant_indices = set(largest)
    batch_lookup = {batch['path']: batch for batch in batches}
    source_conflicts, comparisons = [], []
    exact_duplicates = Counter(json.dumps(row['_raw'], sort_keys=True, ensure_ascii=False) for row in candidates if row['_candidate_domain'] == 'investigadores')
    names_comparison = Counter()
    responsibility_comparison = Counter()
    project_aliases, alternate_id_names, alternate_id_member_ids = defaultdict(set), defaultdict(set), defaultdict(set)
    for candidate in candidates:
        if candidate['_candidate_domain'] != 'investigadores':
            continue
        original = candidate['_raw']
        pid, employee, researcher = clean(original.get('id_actividad')), clean(original.get('id_empleado')), clean(original.get('id_investigador'))
        if pid and researcher:
            project_aliases[pid].add(researcher)
        if researcher:
            if name(original.get('nombre_investigador')):
                alternate_id_names[researcher].add(name(clean(original['nombre_investigador'])))
            if employee:
                alternate_id_member_ids[researcher].add(employee)
    conflict_indices = set()
    for i, row in enumerate(candidates):
        batch = batch_lookup[row['_file']]
        original = row['_raw']
        a, b = clean(original.get('id_empleado')), clean(original.get('id_investigador'))
        if not (a and b and a != b):
            continue
        conflict_indices.add(i)
        lex = batch['independent'][row['_row']]
        assert lex['values'] == original
        stage = stages[(row['_file'], row['_row'])]
        rid = assignments[occurrence(row)]
        published = researcher_by_id[rid]
        ref = next(ref for ref in json.loads(published['provenance_json'])
                   if ref['record_source'] == row['_file'] and ref['source_row'] == row['_row'])
        assert ref['original_values'] == original
        assert evidence_values(row, 'institutional_id') == sorted({a, b})
        assert row['institutional_id'] is None and published['institutional_id'] is None
        assert published['identity_status'] == 'ambiguous'
        own_name, alternate_name = name(clean(original.get('nombre_completo'))), name(clean(original.get('nombre_investigador')))
        names_label = 'equal' if own_name and own_name == alternate_name else 'different' if own_name and alternate_name else 'missing_one_or_both'
        names_comparison[names_label] += 1
        responsibility_comparison[str(clean(original.get('responsable')))] += 1
        source_conflicts.append({'source_file': row['_file'], 'source_row': row['_row'],
                                'source_record_id': anon(row.get('_source_id')), 'etl_run_id': run_id,
                                'category': 'SOURCE_ALREADY_CONFLICTING', 'first_divergence_stage': 'SOURCE_ORIGINAL',
                                'employee_value': anon(a), 'researcher_value': anon(b),
                                'researcher_id': rid, 'largest_component': i in giant_indices,
                                'csv_width_valid': True, 'independent_reader_matches_ingest': True,
                                'ingest_matches_staging_and_provenance': True,
                                'source_record_sha256': lex['record_sha256'], 'source_row_end': lex['end_line'],
                                'duplicate_exact_record_count': exact_duplicates[json.dumps(original, sort_keys=True, ensure_ascii=False)],
                                'diagnostic_names_comparison': names_label,
                                'classification_basis': 'Both unequal normalized values occupy their literal source columns before ingestion.'})
        for column in ('id_empleado', 'id_investigador'):
            literal_name = batch['headers'][column]
            comparisons.append({'source_file': row['_file'], 'source_row': row['_row'],
                                'source_row_end': lex['end_line'], 'source_record_id': anon(row.get('_source_id')),
                                'etl_run_id': run_id, 'original_column': literal_name,
                                'column_position_1based': list(lex['values']).index(literal_name) + 1,
                                'source_original_value': anon(lex['values'][literal_name]),
                                'source_csv_literal_token': anon(lex['literals'][literal_name]),
                                'ingest_value': anon(row['_parsed'][column]),
                                'staging_original_value': anon(stage['original'][literal_name]),
                                'staging_mapped_institutional_id': anon(stage['interpreted'].get('institutional_id')),
                                'normalized_alias_value': anon(clean(original[literal_name])),
                                'normalized_institutional_id': None,
                                'identity_evidence_values': json.dumps([anon(v) for v in evidence_values(row, 'institutional_id')]),
                                'identity_alias_value': anon(clean(original[literal_name])),
                                'canonical_institutional_id': None, 'canonical_source_record_id': anon(published['source_record_id']),
                                'canonical_researcher_id': rid, 'canonical_identity_status': published['identity_status'],
                                'canonical_provenance_value': anon(ref['original_values'][literal_name]),
                                'original_equals_ingest_equals_staging_equals_provenance': True,
                                'first_divergence_stage': 'SOURCE_ORIGINAL', 'source_record_sha256': lex['record_sha256']})
    assert len(source_conflicts) == 5447
    counts = Counter(row['category'] for row in source_conflicts)
    group_counts = Counter((row['source_file'], row['category']) for row in source_conflicts)
    by_source = []
    for source in sources_summary:
        by_source.append({'source_file': source['source_file'], 'domain': source['domain'], 'source_records': source['records'],
                          'both_id_columns_exist': source['both_exist'],
                          'literal_conflicts': source['literal_conflicts'], 'normalized_conflicts': source['normalized_conflicts'],
                          'format_only_pairs_outside_target': source['format_only_pairs_outside_target'],
                          **{cat: group_counts[(source['source_file'], cat)] for cat in CATEGORIES}})
    component_rows = [candidates[i] for i in largest]
    employee_ids = {clean(row['_raw'].get('id_empleado')) for row in component_rows} - {None}
    researcher_ids = {clean(row['_raw'].get('id_investigador')) for row in component_rows} - {None}
    docs = {v for row in component_rows for v in evidence_values(row, 'document_number')}
    researcher_names = {row.get('normalized_name') for row in component_rows} - {None}
    alternate_names = {name(clean(row['_raw'].get('nombre_investigador'))) for row in component_rows} - {None}
    projects = {row.get('source_project_id') for row in component_rows} - {None}
    covered_project_ids = {row['source_project_id'] for row in pq.read_table(canonical / 'proyectos.parquet').to_pylist()}
    articles = {row.get('_canonical_id') for row in component_rows if row['_candidate_domain'] == 'articulos'} - {None}
    conflict_in_giant = len(conflict_indices & giant_indices)
    directed = defaultdict(list)
    for i in conflict_indices & giant_indices:
        row = candidates[i]
        directed[(clean(row['_raw'].get('id_empleado')), clean(row['_raw'].get('id_investigador')))].append(i)
    outgoing = defaultdict(list)
    for a, b in directed:
        outgoing[a].append(b)
    chain = None
    for a, b in sorted(directed):
        for c in sorted(outgoing.get(b, [])):
            if len({a, b, c}) == 3:
                ia, ib = directed[(a, b)][0], directed[(b, c)][0]
                chain = {'ids': [anon(a), anon(b), anon(c)], 'source_rows': [candidates[ia]['_row'], candidates[ib]['_row']],
                         'source_files': [candidates[ia]['_file'], candidates[ib]['_file']]}
                break
        if chain:
            break
    first_union = union_events[0]
    first_bridge = next((event for event in union_events if event['alias_bridge']), None)

    def event_info(event):
        if event is None:
            return None
        left, right = candidates[event['i']], candidates[event['j']]
        namespace = 'identifier' if event['field'] == 'institutional_id' else 'document' if event['field'] == 'document_number' else event['field']
        return {'sequence': event['sequence'], 'field': event['field'], 'matching_value': anon(event['token'], namespace),
                'source_file': left['_file'], 'source_row': left['_row'],
                'previous_source_file': right['_file'], 'previous_source_row': right['_row'],
                'left_size_before': event['left_size'], 'right_size_before': event['right_size'],
                'left_alias_values': [anon(v) for v in evidence_values(left, 'institutional_id')],
                'right_alias_values': [anon(v) for v in evidence_values(right, 'institutional_id')]}

    component = {'occurrences': len(largest), 'conflicting_source_rows': conflict_in_giant,
                 'conflicting_source_rows_outside_component': len(conflict_indices) - conflict_in_giant,
                 'unique_id_empleado': len(employee_ids), 'unique_id_investigador': len(researcher_ids),
                 'unique_institutional_values_union': len(employee_ids | researcher_ids),
                 'unique_document_number': len(docs), 'unique_researcher_names_normalized': len(researcher_names),
                 'unique_alternate_researcher_names_normalized': len(alternate_names),
                 'unique_names_either_column': len(researcher_names | alternate_names),
                 'unique_projects_in_source_memberships': len(projects),
                 'unique_projects_in_canonical_coverage': len(projects & covered_project_ids),
                 'unique_articles': len(articles),
                 'member_occurrences': sum(row['_candidate_domain'] == 'investigadores' for row in component_rows),
                 'article_occurrences': sum(row['_candidate_domain'] == 'articulos' for row in component_rows),
                 'unique_conflicting_alias_pairs': len(directed),
                 'effective_union_events': len(union_events), 'first_connection': event_info(first_union),
                 'first_alias_bridge_merging_preexisting_components': event_info(first_bridge),
                 'real_chain_example': chain,
                 'order_note': 'Reconstructed in current pipeline candidate/token order, verified against the published researcher payloads. Historical union events were not logged.'}
    analysis = []
    for metric, value in component.items():
        analysis.append({'record_type': 'METRIC', 'metric': metric, 'value': json.dumps(value, ensure_ascii=False)})
    for i in largest:
        row = candidates[i]
        analysis.append({'record_type': 'OCCURRENCE', 'source_file': row['_file'], 'source_row': row['_row'],
                         'etl_run_id': run_id, 'source_record_id': anon(row.get('_source_id')),
                         'candidate_order_0based': i, 'domain': row['_candidate_domain'],
                         'employee_value': anon(clean(row['_raw'].get('id_empleado'))),
                         'researcher_value': anon(clean(row['_raw'].get('id_investigador'))),
                         'document_number': anon(row.get('document_number'), 'document'),
                         'normalized_name': anon(row.get('normalized_name'), 'name'),
                         'project_id': anon(row.get('source_project_id'), 'project'),
                         'article_id': row.get('_canonical_id') if row['_candidate_domain'] == 'articulos' else None,
                         'canonical_researcher_id': assignments[occurrence(row)], 'source_alias_conflict': i in conflict_indices})
    for event in union_events:
        detail = event_info(event)
        analysis.append({'record_type': 'UNION', 'metric': event['field'], 'value': detail['matching_value'],
                         'source_file': detail['source_file'], 'source_row': detail['source_row'],
                         'previous_source_file': detail['previous_source_file'], 'previous_source_row': detail['previous_source_row'],
                         'union_sequence': event['sequence'], 'left_size_before': event['left_size'],
                         'right_size_before': event['right_size'], 'alias_bridge': event['alias_bridge']})
    source_context = {'projects_with_nonnull_id_investigador': len(project_aliases),
                      'projects_with_one_id_investigador': sum(len(values) == 1 for values in project_aliases.values()),
                      'projects_with_multiple_id_investigador': sum(len(values) > 1 for values in project_aliases.values()),
                      'distinct_id_investigador': len(alternate_id_names),
                      'id_investigador_with_single_alternate_name': sum(len(values) == 1 for values in alternate_id_names.values()),
                      'id_investigador_associated_with_multiple_id_empleado': sum(len(values) > 1 for values in alternate_id_member_ids.values()),
                      'conflicting_rows_responsable_values': dict(responsibility_comparison),
                      'interpretation': 'Descriptive source context only. Does not establish authoritative identity or the roles behind source joins.'}
    for metric, value in source_context.items():
        analysis.append({'record_type': 'SOURCE_CONTEXT_METRIC', 'metric': metric, 'value': json.dumps(value, ensure_ascii=False)})

    def save_csv(filename, rows):
        columns = list(dict.fromkeys(key for row in rows for key in row))
        write_csv(OUT / filename, rows, columns)

    save_csv('conflicts_by_source.csv', by_source)
    save_csv('conflict_classification.csv', source_conflicts)
    save_csv('pipeline_stage_comparison.csv', comparisons)
    save_csv('largest_component_analysis.csv', analysis)
    save_csv('mapping_analysis.csv', mappings)
    assert all(file_hash(Path(path)) == sha for path, sha in protected.items()), 'Protected input/output changed during audit'
    summary = {'status': 'PASS', 'project_root': str(ROOT), 'etl_run_id': run_id, 'target_conflicts': len(source_conflicts),
               'classification': {cat: {'count': counts[cat], 'percent': round(100 * counts[cat] / len(source_conflicts), 6)} for cat in CATEGORIES},
               'classification_rule': 'Primary category is the earliest demonstrated stage of divergence; secondary duplicate/name associations do not replace source origin.',
               'first_divergence_stage': 'SOURCE_ORIGINAL', 'source_schema_analysis': sources_summary,
               'mapping_error_detected': False, 'pipeline_row_alignment_error_detected': False,
               'upstream_export_alignment': 'Not verifiable without upstream export/join lineage; CSV width and all pipeline row values were verified.',
               'names_comparison_diagnostic_only': dict(names_comparison), 'source_context_diagnostic_only': source_context,
               'largest_component': component,
               'published_identity_payload_reproduced_exactly': True, 'protected_files_unchanged': True,
               'protected_hashes_before_after': [{'path': path, 'before': sha, 'after': file_hash(Path(path))} for path, sha in protected.items()],
               'source_record_id_note': 'NULL for conflicted members because institutional_id is NULL after alias contradiction; source_file + physical source_row + row SHA-256 retain exact locator.',
               'pseudonymization': 'HMAC-SHA256; key in local ignored _private/pseudonym_key.bin. No original identifiers, documents or names copied into reports.',
               'recommendation': 'SOURCE_DATA_REQUIRES_RESOLUTION'}
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    findings = f'''# Auditoría forense de identidad

Ejecución publicada: {run_id}. Diagnóstico sin publicar ni modificar Capa 1.

## 1. ¿Las 5447 discrepancias ya existen en las fuentes originales?

Sí: las 5447 (100%) están en el archivo externo miembros-doc-limpio.csv,
antes de INGEST. Los dos encabezados literales existen simultáneamente:
id_empleado ocupa la columna 10 e id_investigador la 18.
Un scanner CSV independiente comprobó los valores de sus posiciones literales,
las filas físicas y el SHA-256 de cada registro; coincidieron con ingest y staging.
La fuente auditada es la entrada institucional actual configurada. No se dispone
del sistema transaccional ni de la transformación que produjo este CSV para rastrear
la discrepancia antes de ese archivo.

## 2. ¿En qué etapa aparecen?

En SOURCE_ORIGINAL, ya presentes. INGEST no los crea. STAGING preserva ambos
en original_values_json. Su vista interpreted_values_json guarda el primer alias
configurado (id_empleado) como institutional_id antes de normalizar.
NORMALIZATION conserva ambos valores normalizados en _identity_values.institutional_id
y deja el valor escalar institutional_id NULL si son distintos. IDENTITY usa ambos
como evidencia del MISMO atributo y bloquea los componentes contradictorios.
CANONICAL publica la ocurrencia ambiguous con institutional_id NULL y conserva ambas
copias originales en provenance_json. Esto es el comportamiento reproducido, no una corrección.

## 3. ¿Qué archivo concentra la mayoría?

miembros-doc-limpio.csv: 5447/5447 (100%). Las otras entradas configuradas no
contienen ambos encabezados. No se encontró una fuente con solo id_empleado en la
que el pipeline haya inventado id_investigador con otro valor.
mapping_analysis.csv registra encabezados completos, nombres literales, posiciones,
presencia, sección de config consumidora y campo canonical de destino.

## 4. ¿Existe algún mapping incorrecto?

No se detectó una selección incorrecta de columnas dentro de este pipeline:
config/sources.yaml declara institutional_id: [id_empleado, id_investigador]
y consume exactamente las columnas 10 y 18 con ese nombre, conforme a la regla
de dominio confirmada. researcher_id es generado por el resolver, no es ninguno
de esos encabezados ni sustituye su significado. Las copias discrepantes del CSV
no cumplen la equivalencia de dominio; cambiar el mapping para ignorar una sería
una nueva decisión de autoridad, que esta auditoría no aplica.
Esto valida la selección física de columnas, no el linaje semántico de una unión
institucional anterior. Las 5447 filas también tienen nombre_completo y nombre_investigador
distintos al compararlos sin usar similitud. Es evidencia para revisar el contexto
de cada columna en el export, sin afirmar qué persona o rol representa cada valor.

## 5. ¿Hay desplazamiento o problemas estructurales?

No se detectaron anomalías de ancho, quoting o encabezados duplicados en ingest
de las fuentes actuales; los valores de cada fila se verificaron completos contra
staging y, en los conflictos, contra la lectura léxica independiente y provenance.
Esto descarta desplazamiento introducido por el lector o el pipeline para estas filas.
No descarta una unión/exportación institucional incorrecta anterior al CSV.
Diagnóstico de las dos columnas de nombre en las filas conflictivas: {dict(names_comparison)}.
Los nombres se usaron solo para conteos; no produjeron conexiones ni decisiones.
Perfil de contexto de la fuente: {json.dumps(source_context, ensure_ascii=False)}.
En los {source_context['projects_with_nonnull_id_investigador']} proyectos con ese campo,
id_investigador tiene exactamente un valor por proyecto; {source_context['id_investigador_associated_with_multiple_id_empleado']}
de sus valores aparecen junto a múltiples id_empleado. Este patrón es compatible
con un export que mezcla contextos de investigador del proyecto y miembro, pero
esa interpretación requiere confirmar el join y el rol de cada columna con el custodio.
No se establece como hecho ni se usa para elegir un ID.

## 6. ¿Por qué hay un componente de 21348 ocurrencias?

Contiene {conflict_in_giant} filas fuente con ambos aliases diferentes, de las 5447.
IDs únicos: id_empleado={len(employee_ids)}, id_investigador={len(researcher_ids)},
unión del atributo institucional={len(employee_ids | researcher_ids)}.
Documentos distintos: {len(docs)}. Nombres normalizados del candidato: {len(researcher_names)}.
Proyectos distintos de membresías fuente: {len(projects)};
en cobertura canonical: {len(projects & covered_project_ids)}; artículos: {len(articles)}.
Incluye {component['member_occurrences']} ocurrencias de miembros y
{component['article_occurrences']} ocurrencias de producción aceptada.

Cada fila discrepante introduce dos tokens institucionales del mismo atributo.
Si otra fila comparte cualquiera de ellos, une sus ocurrencias; los documentos
exactos conectan también la producción. Repetir estos puentes produce un componente
con muchos valores incompatibles. La política vigente marca todas sus ocurrencias
ambiguous. No equivale a confirmar que representan una sola persona.

Primera unión reconstruida del componente: {json.dumps(event_info(first_union), ensure_ascii=False)}.
Primer puente de aliases que une componentes ya existentes: {json.dumps(event_info(first_bridge), ensure_ascii=False)}.
Ejemplo real de cadena A→B→C, con valores seudonimizados: {json.dumps(chain, ensure_ascii=False)}.
largest_component_analysis.csv contiene todas las ocurrencias y todas las uniones
efectivas, con sus filas origen y tamaños antes de unir. El orden es el de candidatos
y tokens del pipeline actual. No había log histórico de cada unión: es una reconstrucción
exacta de entradas/código vigentes, corroborada contra todos los payloads investigadores.
Las filas discrepantes se cuentan como puentes observados; la auditoría no afirma que
cada una sea necesaria o suficiente por sí sola para producir el componente completo.

## 7. Proporciones

SOURCE_ALREADY_CONFLICTING: 5447 (100%). TRANSFORMATION_CONFLICT: 0 (0%).
COLUMN_MAPPING_ERROR: 0 (0%). ROW_ALIGNMENT_ERROR: 0 (0%).
DUPLICATE_RECORD_CONFLICT: 0 (0%). FORMAT_ONLY: 0 (0%). UNKNOWN: 0 (0%).
La clasificación primaria registra la primera divergencia demostrada. Repeticiones
del mismo registro pueden coexistir y se contabilizan como diagnóstico secundario
en conflict_classification.csv, pero no crearon la diferencia ya visible dentro de la fila.
Las diferencias de formato fuera de las 5447 se reportan por separado en summary.json.

## 8. ¿Puede corregirse sin modificar RAW?

Sí, técnicamente podría aplicarse una resolución institucional externa y trazable
en una transformación posterior manteniendo RAW inmutable. Todavía falta evidencia
para seleccionar qué valor representa realmente el identificador personal.

## 9. ¿Qué regla/configuración debería modificarse?

No hay una modificación de mapping justificada solo por la evidencia actual.
Si el custodio certifica qué columna es la copia autoritativa en este export específico,
se podría configurar institutional_id desde esa columna y conservar/auditar la otra
como evidencia de exportación incompatible; no usarla como un token adicional de unión.
Si la autoridad varía por registro, haría falta una tabla de resolución por hash de fuente,
fila/llave verificable, valor aprobado y evidencia/fecha/autoridad, aplicada antes de identity.
Esto requiere un cambio explícito futuro; no existe una configuración vigente que aplique
esas resoluciones automáticamente. No se modifica identity.py ni se implementa esa regla aquí.

## 10. Evidencia institucional necesaria

Diccionario y linaje del export de miembros que expliquen las columnas id_empleado,
id_investigador, nombre_completo y nombre_investigador; consulta/join que los generó;
llaves y cardinalidades originales; y un directorio autoritativo de personas o una
resolución aprobada de las 5447 filas vinculada al hash de la fuente.
La regla semántica confirmada no identifica cuál copia discrepante es materialmente correcta.

## Integridad y privacidad

Todos los archivos protegidos conservaron SHA-256 antes/después: RAW, código de Capa 1,
config, staging publicado, canonical completo (incluidas relaciones), quality y audit.
No hubo ejecución ETL, corrección de IDs, nombres, datasets ni commits/push.
Los valores personales se representan por tokens HMAC; el localizador exacto es
source_file + source_row física + source_record_sha256. El source_record_id de estas
ocurrencias es NULL por la regla vigente de contradicción; no se fabricó uno nuevo.

Recomendación: SOURCE_DATA_REQUIRES_RESOLUTION.
'''
    (OUT / 'findings.md').write_text(findings, encoding='utf-8')
    print(json.dumps({'status': 'PASS', 'classification': summary['classification'],
                      'largest_component': component, 'names_diagnostic': dict(names_comparison),
                      'source_context_diagnostic': source_context,
                      'sources': [{k: v for k, v in source.items() if k != 'original_headers'} for source in sources_summary],
                      'protected_files_unchanged': True, 'recommendation': summary['recommendation']}, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
