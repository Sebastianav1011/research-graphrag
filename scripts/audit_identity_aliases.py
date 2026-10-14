"""Audit alias interpretation from current provenance without publishing canonical."""
import json
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from common.config import read_config
from layer1_data.identity import STRONG, evidence_values, resolve
from layer1_data.normalize import header, identifier, normalize_record, text
from layer1_data.provenance import file_hash
from layer1_data.validate import map_rows


def clean(value):
    value = text(value)
    if value and len(value) >= 2 and value[0] == value[-1] == '"':
        value = text(value[1:-1])
    return identifier(value)


def component_stats(rows):
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    tokens = {}
    for i, row in enumerate(rows):
        keys = [(field, value) for field in STRONG for value in evidence_values(row, field)]
        if row.get('normalized_name') and row.get('email'):
            keys.append(('name_email', (row['normalized_name'], row['email'])))
        for key in keys:
            if key in tokens:
                a, b = find(i), find(tokens[key])
                parent[max(a, b)] = min(a, b)
            else:
                tokens[key] = i
    groups = defaultdict(list)
    for i in range(len(rows)):
        groups[find(i)].append(rows[i])
    conflicts = []
    for members in groups.values():
        values = {f: {v for row in members for v in evidence_values(row, f)}
                  for f in (*STRONG, 'document_type')}
        fields = sorted(f for f, v in values.items() if len(v) > 1)
        if fields:
            conflicts.append({'occurrences': len(members), 'conflict_fields': fields,
                              'distinct_values_by_field': {f: len(v) for f, v in values.items()}})
    return sorted(conflicts, key=lambda item: -item['occurrences'])


def main():
    manifest_path = ROOT / 'data/canonical/_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    canonical = ROOT / 'data/canonical'
    protected = {str(p): file_hash(p) for p in canonical.iterdir() if p.is_file()}
    protected.update({meta['path']: file_hash(Path(meta['path'])) for meta in manifest['input_files']})
    settings = read_config(ROOT / 'config/layer1.yaml')
    published = pq.read_table(canonical / 'investigadores.parquet').to_pylist()
    candidates, expected, alias_stats, document_alias_stats = [], {}, Counter(), Counter()
    seen = set()
    for entity in published:
        for ref in json.loads(entity['provenance_json']):
            domain = 'articulos' if 'produccion' in Path(ref['record_source']).name else 'investigadores'
            key = (ref['record_source'], ref.get('source_sheet'), ref['source_row'], domain)
            assert key not in seen
            seen.add(key)
            expected[key] = entity['researcher_id']
            original = ref['original_values']
            raw = {header(k): v for k, v in original.items()}
            raw.update({'_raw': original, '_file': ref['record_source'], '_sheet': ref.get('source_sheet'),
                        '_row': ref['source_row'], '_candidate_domain': domain})
            spec = {'mapping': ref['field_mapping'],
                    'unwrap_quoted_fields': ['institutional_id', 'document_number', 'document_type', 'full_name'] if domain == 'investigadores' else []}
            candidates.append(normalize_record(map_rows([raw], spec)[0], settings['normalization']))
            if domain == 'investigadores':
                employee, researcher = clean(original.get('id_empleado')), clean(original.get('id_investigador'))
                label = 'both_equal' if employee and employee == researcher else 'both_different' if employee and researcher else 'employee_only' if employee else 'researcher_only' if researcher else 'neither'
                alias_stats[label] += 1
            for field in ('cedula_empleado', 'cedula_investigador'):
                document_alias_stats[field + '_present'] += field in original
    assert len(candidates) == manifest['identity_candidates']
    entities, assignments, _ = resolve(deepcopy(candidates), 'identity_alias_audit')
    assert assignments == expected, 'Reconstructed resolver differs from current publication'
    assert Counter(e['identity_status'] for e in entities) == Counter(e['identity_status'] for e in published)
    rules = Counter(e['identity_rule'] for e in entities)
    components = component_stats(candidates)
    primary_only = deepcopy(candidates)
    for row in primary_only:
        if row['_candidate_domain'] == 'investigadores':
            value = clean(row['_raw'].get('id_empleado'))
            row['institutional_id'] = value
            row.setdefault('_identity_values', {})['institutional_id'] = [value] if value else []
    primary_entities, _, _ = resolve(primary_only, 'diagnostic_primary_only')
    # Demonstrate equal/coexisting nomenclature aliases use exactly one value and identity.
    synthetic = []
    for i, original in enumerate(({'id_empleado': '001', 'id_investigador': '001'},
                                  {'id_empleado': '001'}, {'id_investigador': '001'}), 2):
        row = dict(original, _raw=original, _file='synthetic', _row=i)
        spec = {'mapping': {'institutional_id': ['id_empleado', 'id_investigador']}}
        synthetic.append(normalize_record(map_rows([row], spec)[0], {}))
    one, _, events = resolve(synthetic, 'synthetic_check')
    assert len(one) == 1 and one[0]['institutional_id'] == '001' and not events
    for field in ('cedula_empleado', 'cedula_investigador'):
        row = {field: '002', '_raw': {field: '002'}, '_file': 'synthetic', '_row': 2}
        normalized = normalize_record(map_rows([row], {'mapping': {'document_number': field}})[0], {})
        assert normalized['document_number'] == '002' and normalized.get('institutional_id') is None
    assert all(file_hash(Path(path)) == sha for path, sha in protected.items())
    report = {'status': 'PASS', 'run_id': manifest['run_id'], 'separate_alias_namespaces': False,
              'equal_aliases_one_identity': True, 'personal_document_alias_mapping': 'PASS',
              'source_document_alias_columns': dict(document_alias_stats),
              'member_alias_occurrences': dict(alias_stats),
              'identity_status': dict(Counter(e['identity_status'] for e in published)),
              'identity_rules': dict(rules), 'conflict_components': components,
              'primary_only_counterfactual_status': dict(Counter(e['identity_status'] for e in primary_entities)),
              'counterfactual_note': 'Diagnostic only; drops researcher alias evidence and is not a valid correction or publication.',
              'canonical_and_raw_unchanged': True, 'identity_code_modified': False}
    destination = ROOT / 'outputs/layer1/reports/identity_alias_audit.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
