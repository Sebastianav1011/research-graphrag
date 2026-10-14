"""Descriptive quality and complete ancestry validation, without semantic inference."""
import csv
import json
from collections import Counter, defaultdict
from .provenance import serialize, text_hash, project_lineage
from .security import excluded, scan_corpus, scan_package_structure
from .text_normalization import words

REPORT_COLUMNS = {
    'empty_sections': ['section_id', 'source_type', 'field_name'],
    'duplicate_chunks': ['chunk_id', 'chunk_hash', 'source_type', 'source_id', 'field_name', 'scope', 'group_size'],
    'oversized_chunks': ['chunk_id', 'word_count'],
    'provenance_issues': ['object_id', 'reason'],
    'orphan_entities': ['entity_id'], 'orphan_relations': ['relation_id'],
    'excluded_sensitive_fields': ['dataset', 'field_name', 'scope'],
    'pii_findings': ['chunk_id', 'reason'],
    'privacy_structure_issues': ['object_id', 'reason'],
}


def statistics(values):
    values = sorted(values)
    def percentile(p):
        if not values:
            return None
        position = (len(values)-1) * p
        low = int(position)
        high = min(low + 1, len(values)-1)
        return values[low] + (values[high] - values[low]) * (position - low)
    return {'count': len(values), 'min': min(values) if values else None,
        'mean': sum(values)/len(values) if values else None, 'median': percentile(.5),
        'p50': percentile(.5), 'p75': percentile(.75), 'p90': percentile(.9),
        'p95': percentile(.95), 'p99': percentile(.99), 'max': max(values) if values else None}


def profile_sections(sections):
    groups = defaultdict(list)
    for row in sections:
        groups[row['source_type'] + ':' + row['field_name']].append(row)
    return {field: {metric: statistics([s[metric] for s in rows])
            for metric in ('word_count', 'char_count')} | {
                'non_null_count': sum(s['text_original'] is not None for s in rows),
                'null_count': sum(s['text_original'] is None for s in rows),
                'empty_count': sum(not s['text_normalized'] for s in rows),
                'empty_non_null_count': sum(s['text_original'] is not None and not s['text_normalized'] for s in rows)}
            for field, rows in sorted(groups.items())}


def write_text_profile(folder, source_sections, reference_sections):
    rows = []
    for group, metrics in profile_sections(source_sections + reference_sections).items():
        kind, field = group.split(':', 1)
        row = {'source_type': kind, 'field_name': field, 'count': metrics['word_count']['count'],
               **{k: metrics[k] for k in ('non_null_count', 'null_count', 'empty_count', 'empty_non_null_count')}}
        for metric, suffix in [('word_count', 'words'), ('char_count', 'chars')]:
            row.update({key + '_' + suffix: metrics[metric][key]
                       for key in ('min', 'mean', 'median', 'p75', 'p90', 'p95', 'p99', 'max')})
        rows.append(row)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'text_field_profile.csv').open('w', encoding='utf-8', newline='') as stream:
        columns = ['source_type', 'field_name', 'count', 'non_null_count', 'null_count', 'empty_count', 'empty_non_null_count']
        columns += [key + '_' + suffix for suffix in ('words', 'chars') for key in ('min', 'mean', 'median', 'p75', 'p90', 'p95', 'p99', 'max')]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def field_traceable(provenance, field):
    for ref in provenance['layer1']:
        original = ref.get('field_mapping', {}).get(field)
        names = original if isinstance(original, list) else [original]
        if any(name in ref.get('original_values', {}) for name in names if isinstance(name, str)):
            return True
    return False


def provenance_issues(package, datasets, config, context):
    issues = []
    canonical_index = {name: {row[spec['id_field']]: row for row in datasets[name]}
                       for name, spec in config['datasets'].items()}
    relation_index = {name: {serialize([row[spec['source_field']], row[spec['target_field']],
        {f: row.get(f) for f in spec['attribute_fields']}]): row for row in datasets[name]}
        for name, spec in config['relations'].items()}
    def issue(identifier, reason):
        issues.append({'object_id': identifier, 'reason': reason})
    for prefix in ('source', 'reference'):
        docs = {d['document_id']: d for d in package[prefix + '_documents']}
        sections = {s['section_id']: s for s in package[prefix + '_sections']}
        for d in docs.values():
            p = json.loads(d['provenance_json'])
            spec = config['datasets'][d['canonical_dataset']]
            upstream = canonical_index[d['canonical_dataset']].get(d['source_id'])
            fields = [spec['id_field'], spec['label_field']] + spec.get('text_fields', []) + [f for f in spec.get('metadata_fields', []) if not excluded(f, config, corpus=False)]
            if (upstream is None or p.get('lineage_fields') != fields
                    or p['layer1'] != project_lineage(json.loads(upstream['provenance_json']), fields, context.get('email_policy', 'reject'))
                    or p.get('layer1_provenance_hash') != text_hash(upstream['provenance_json'])):
                issue(d['document_id'], 'CANONICAL_ANCESTRY_BROKEN')
            if p.get('document_id') != d['document_id'] or p.get('canonical_id') != d['source_id'] or p.get('canonical_dataset') != d['canonical_dataset']:
                issue(d['document_id'], 'DOCUMENT_PROVENANCE_LINK_BROKEN')
        for s in sections.values():
            d = docs.get(s['document_id'])
            p = json.loads(s['provenance_json'])
            if not d or any(s[k] != d[k] for k in ('source_id', 'source_type')):
                issue(s['section_id'], 'SECTION_DOCUMENT_BROKEN')
            elif (p['layer1'] != project_lineage(json.loads(d['provenance_json'])['layer1'], [s['field_name']], context.get('email_policy', 'reject'))
                    or p.get('layer1_provenance_hash') != json.loads(d['provenance_json']).get('layer1_provenance_hash')):
                issue(s['section_id'], 'SECTION_ANCESTRY_BROKEN')
            if s['text_normalized'] and not field_traceable(p, s['field_name']):
                issue(s['section_id'], 'UPSTREAM_DATA_ISSUE: FIELD_MAPPING_MISSING')
            if (p.get('section_id') != s['section_id'] or p.get('document_id') != s['document_id']
                    or p.get('source_field') != s['field_name'] or p.get('canonical_id') != s['source_id']):
                issue(s['section_id'], 'SECTION_PROVENANCE_LINK_BROKEN')
            if s['text_hash_normalized'] != text_hash(s['text_normalized']) or s['word_count'] != len(words(s['text_normalized'])):
                issue(s['section_id'], 'SECTION_HASH_COUNT_BROKEN')
        for c in package[prefix + '_chunks']:
            s = sections.get(c['section_id'])
            p = json.loads(c['provenance_json'])
            if not s or any(c[k] != s[k] for k in ('document_id', 'source_id', 'source_type', 'field_name')):
                issue(c['chunk_id'], 'CHUNK_SECTION_BROKEN')
                continue
            if (not 0 <= c['char_start'] < c['char_end'] <= len(s['text_normalized'])
                    or c['text'] != s['text_normalized'][c['char_start']:c['char_end']]
                    or c['chunk_hash'] != text_hash(c['text']) or c['word_count'] != len(words(c['text']))):
                issue(c['chunk_id'], 'CHUNK_OFFSETS_HASH_BROKEN')
            if p['layer1'] != json.loads(s['provenance_json'])['layer1'] or not field_traceable(p, c['field_name']):
                issue(c['chunk_id'], 'CHUNK_FIELD_ANCESTRY_BROKEN')
            if (p.get('chunk_id') != c['chunk_id'] or p.get('section_id') != c['section_id']
                    or p.get('document_id') != c['document_id'] or p.get('source_field') != c['field_name']
                    or p.get('char_start') != c['char_start'] or p.get('char_end') != c['char_end']
                    or p.get('chunk_hash') != c['chunk_hash'] or p.get('offset_basis') != 'text_normalized'):
                issue(c['chunk_id'], 'CHUNK_PROVENANCE_LINK_BROKEN')
    for name, rows in package.items():
        for row in rows:
            p = json.loads(row['provenance_json'])
            identifier = next(row[k] for k in ('chunk_id', 'section_id', 'document_id', 'entity_id', 'relation_id') if k in row)
            if (p.get('layer1_run_id') != context['layer1_run_id'] or p.get('layer2_run_id') != context['layer2_run_id']
                    or p.get('config_hash') != context['config_hash'] or p.get('config_version') != context['config_version']):
                issue(identifier, 'RUN_CONFIG_PROVENANCE_BROKEN')
            if name == 'entities':
                dataset = p['canonical_dataset']
                spec = config['datasets'].get(dataset)
                upstream = canonical_index.get(dataset, {}).get(row['canonical_id'])
                fields = [spec['id_field'], spec['label_field']] + [f for f in spec.get('metadata_fields', []) if not excluded(f, config, corpus=False)]
                if (upstream is None or p.get('lineage_fields') != fields
                        or p['layer1'] != project_lineage(json.loads(upstream['provenance_json']), fields, context.get('email_policy', 'reject'))
                        or p.get('layer1_provenance_hash') != text_hash(upstream['provenance_json'])):
                    issue(identifier, 'ENTITY_CANONICAL_ANCESTRY_BROKEN')
            elif name == 'relations':
                dataset = p['canonical_dataset']
                spec = config['relations'].get(dataset)
                key = p['canonical_id']
                upstream = relation_index.get(dataset, {}).get(serialize(key))
                fields = [spec['source_field'], spec['target_field']] + spec['attribute_fields']
                if (upstream is None or p.get('lineage_fields') != fields
                        or p['layer1'] != project_lineage(json.loads(upstream['provenance_json']), fields, context.get('email_policy', 'reject'))
                        or p.get('layer1_provenance_hash') != text_hash(upstream['provenance_json'])):
                    issue(identifier, 'RELATION_CANONICAL_ANCESTRY_BROKEN')
    return issues


def evaluate(package, datasets, config, context):
    docs, sections, chunks = (package['source_' + name] for name in ('documents', 'sections', 'chunks'))
    all_sections = sections + package['reference_sections']
    all_chunks = chunks + package['reference_chunks']
    reports = {name: [] for name in REPORT_COLUMNS}
    reports['empty_sections'] = [{k: s[k] for k in REPORT_COLUMNS['empty_sections']} for s in all_sections if not s['text_normalized']]
    groups = defaultdict(list)
    for c in all_chunks:
        groups[c['chunk_hash']].append(c)
    for digest, group in groups.items():
        if len(group) > 1:
            for c in group:
                reports['duplicate_chunks'].append({k: c[k] for k in ['chunk_id', 'source_type', 'source_id', 'field_name']} |
                    {'chunk_hash': digest, 'group_size': len(group),
                     'scope': 'REFERENCE' if c['source_type'] == 'INDICATOR_REFERENCE' else 'SOURCE'})
    reports['oversized_chunks'] = [{k: c[k] for k in ('chunk_id', 'word_count')} for c in all_chunks if c['word_count'] > config['chunking']['max_words']]
    reports['provenance_issues'] = provenance_issues(package, datasets, config, context)
    expected = {spec['entity_type'] + ':' + row[spec['id_field']] for name, spec in config['datasets'].items() for row in datasets[name]}
    actual = {e['entity_id'] for e in package['entities']}
    reports['orphan_entities'] = [{'entity_id': e} for e in sorted(actual ^ expected)]
    reports['orphan_relations'] = [{'relation_id': r['relation_id']} for r in package['relations']
        if r['source_entity_id'] not in actual or r['target_entity_id'] not in actual]
    for dataset, rows in datasets.items():
        fields = set().union(*(r.keys() for r in rows)) if rows else set()
        reports['excluded_sensitive_fields'].extend({'dataset': dataset, 'field_name': f,
            'scope': 'CORPUS_AND_METADATA' if excluded(f, config, corpus=False) else 'CORPUS'}
            for f in sorted(fields) if excluded(f, config))
    reports['pii_findings'] = scan_corpus(all_chunks, datasets, config)
    reports['privacy_structure_issues'] = scan_package_structure(package, datasets, config)
    usable = {s['document_id'] for s in sections if s['text_normalized']}
    empty_documents = len(docs) - len(usable)
    bad = {r['object_id'] for r in reports['provenance_issues']}
    traceable = sum(c['chunk_id'] not in bad and c['section_id'] not in bad and c['document_id'] not in bad for c in chunks)
    attributes = config['datasets']['indicadores']['reference_attributes']
    summary = {'documents': {'projects_received': len(datasets['proyectos']), 'articles_received': len(datasets['articulos']),
            'total': len(docs), 'without_text': empty_documents},
        'sections': {'total': len(sections), 'by_field': dict(Counter(s['field_name'] for s in sections)),
            'empty': sum(not s['text_normalized'] for s in sections), 'profile': profile_sections(sections)},
        'chunks': {'total': len(chunks), 'by_source_type': dict(Counter(c['source_type'] for c in chunks)),
            'by_field': dict(Counter(c['field_name'] for c in chunks)), 'words': statistics([c['word_count'] for c in chunks]),
            'by_field_words': {f: statistics([c['word_count'] for c in chunks if c['field_name'] == f]) for f in sorted({c['field_name'] for c in chunks})}},
        'reference': {'indicators_received': len(datasets['indicadores']), 'documents': len(package['reference_documents']),
            'sections': len(package['reference_sections']), 'chunks': len(package['reference_chunks']),
            'missing_attributes': {k: sum(not r.get(f) for r in datasets['indicadores']) for k, f in attributes.items()}},
        'entities': dict(Counter(e['entity_type'] for e in package['entities'])),
        'relations': dict(Counter(r['relation_type'] for r in package['relations'])),
        'provenance': {'source_chunks_traceable': traceable, 'source_chunks_total': len(chunks),
            'coverage_percent': 100*traceable/len(chunks) if chunks else None},
        'reports': {k: len(v) for k, v in reports.items()}, 'inferred_relations': 0,
        'security_scope': 'Source/reference text and structured metadata/lineage; researcher entity labels remain private'}
    summary['privacy'] = {'email_policy': context.get('email_policy', 'reject'),
        'sections_with_email_redactions': sum(json.loads(s['provenance_json']).get('email_redactions',0) > 0 for s in all_sections),
        'email_redactions': sum(json.loads(s['provenance_json']).get('email_redactions',0) for s in all_sections),
        'structure_issues': len(reports['privacy_structure_issues'])}
    failures = []
    policy = config['quality']
    if policy['fail_on_orphan'] and (reports['orphan_entities'] or reports['orphan_relations']):
        failures.append('ORPHAN')
    if policy['fail_on_provenance_issue'] and reports['provenance_issues']:
        failures.append('PROVENANCE')
    if policy['fail_on_pii'] and (reports['pii_findings'] or reports['privacy_structure_issues']):
        failures.append('PII')
    if reports['oversized_chunks']:
        failures.append('OVERSIZED')
    if docs and empty_documents/len(docs) > policy['max_empty_document_ratio']:
        failures.append('EMPTY_DOCUMENT_RATIO')
    summary['failures'] = failures
    summary['status'] = 'FAIL' if failures else 'PASS'
    return summary, reports


def write_reports(folder, summary, reports):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'summary.json').write_text(serialize(summary), encoding='utf-8')
    for name, columns in REPORT_COLUMNS.items():
        with (folder / (name + '.csv')).open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for row in reports[name]:
                writer.writerow({k: "'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v for k, v in row.items()})
