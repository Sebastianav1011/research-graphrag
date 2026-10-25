"""Verified read-only publications for Layer 4A. Never rebuild upstream data."""
from collections import Counter
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

from layer4.territories.inputs import load_projects, sha256 as _sha256
from layer4.paths import resolve, verify_expected
from .profiles import load_profiles
from .selection import eligible_projects
from .powerbi import territory_rows

ROOT = Path(__file__).resolve().parents[3]


def read(path):
    return json.loads(resolve(ROOT,path).read_text(encoding='utf-8-sig'))


def sha256(path):
    return _sha256(resolve(ROOT,path))


def safe_path(root, name):
    path = (Path(root) / name).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('Publication path escapes repository')
    return resolve(root,path)


def verify_hashes(root, hashes):
    for name, digest in hashes.items():
        verify_expected(root,name,digest)
    return {'status': 'PASS', 'files': len(hashes)}


def protected_snapshot(root):
    root = Path(root)
    # Include all published inputs (including vectors), accepted 4B and the
    # historical experiment. No model caches, raw researcher tables or auth.
    folders = ('data/knowledge', 'data/graphrag', 'data/reference/processed',
               'src/layer1_data', 'src/layer2_knowledge', 'src/layer3_graphrag',
               'src/layer4/territories', 'outputs/layer4/territorios/publicacion',
               'outputs/layer4/territorios/aceptacion', 'outputs/layer4/auditoria/historicos/preliminar_20',
               'outputs/layer4/auditoria/historicos/powerbi_preliminar_20')
    paths = {p for folder in folders for p in (root / folder).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts}
    paths.update(p for p in (root / 'data/canonical').glob('*manifest*.json'))
    return {p.relative_to(root).as_posix(): sha256(p) for p in sorted(paths)}


def load_inputs(root, config):
    root = Path(root).resolve()
    l3_path = safe_path(root, config['layer3_manifest'])
    l3_digest = sha256(l3_path)
    l3 = read(l3_path)
    if l3.get('status') != 'SUCCESS' or l3.get('candidate_architecture') != 'SOURCE_INDICATOR_V1':
        raise ValueError('Layer 3 is not a successful SOURCE_INDICATOR_V1 publication')
    for sentinel in ('outputs/layer3/.publish.lock', 'outputs/layer3/publication_pending.json'):
        if (root / sentinel).exists():
            raise ValueError('Layer 3 publication writer/pending publication')
    hashes = {}
    for name, digest in l3['output_hashes'].items():
        hashes[(Path('data/graphrag') / name).as_posix()] = digest
    verify_hashes(root, hashes)
    documents, sections, l2 = load_projects(root)
    if l3['layer2_run_id'] != l2['layer2_run_id'] or l3['layer2_manifest_hash'] != l2['manifest_sha256']:
        raise ValueError('Layer 3 does not reference active Layer 2')
    l2_manifest = read(root / 'data/knowledge/_manifest.json')
    verify_hashes(root, {l2_manifest['output_files'][name]: digest for name, digest in l2_manifest['output_hashes'].items()})
    profiles_list, profile_manifest = load_profiles(root)
    profiles = {p['indicator_id']: p for p in profiles_list}
    if len(profiles) != 48:
        raise ValueError('Expected all 48 v2 profiles')
    candidates = pq.read_table(root / 'data/graphrag/retrieval/source_indicator_candidates.parquet').to_pylist()
    contexts = pq.read_table(root / 'data/graphrag/retrieval/source_context_packages.parquet').to_pylist()
    eligible = eligible_projects(candidates, contexts, documents, sections, run_id=l3['layer3_run_id'])
    docs = {d['document_id']: d for d in documents}
    secs = {s['section_id']: s for s in sections}
    if len(secs) != len(sections):
        raise ValueError('Duplicate source sections')
    for section in sections:
        for text_key, hash_key in (('text_original', 'text_hash_original'), ('text_normalized', 'text_hash_normalized')):
            text = section[text_key]
            # Layer 2 fingerprints missing originals as the empty string.
            expected = hashlib.sha256((text or '').encode('utf-8')).hexdigest()
            if section[hash_key] != expected:
                raise ValueError('Source section content/hash mismatch: ' + section['section_id'])
    section_by_field = {(s['document_id'], s['field_name']): s for s in sections}
    siap_seen = set()
    for project in eligible:
        doc = docs[project['document_id']]
        metadata = json.loads(doc['metadata_json'])
        siap = metadata.get('source_project_id')
        if not isinstance(siap, str) or not siap or siap in siap_seen:
            raise ValueError('Missing/duplicate institutional SIAP identity')
        siap_seen.add(siap)
        project.update(siap_id=siap, knowledge_area=metadata.get('knowledge_area'),
                       knowledge_subarea=metadata.get('knowledge_subarea'),
                       provenance_json=doc['provenance_json'], canonical_run_id=doc['canonical_run_id'],
                       layer2_run_id=doc['layer2_run_id'], layer3_run_id=l3['layer3_run_id'],
                       field_provenance={f: {k: section_by_field[project['document_id'], f][k] for k in
                                            ('section_id', 'text_hash_original', 'text_hash_normalized', 'provenance_json')}
                                         for f in project['fields']})
        if any(c['indicator_id'] not in profiles for c in project['candidates']):
            raise ValueError('Candidate missing v2 profile')
    tpath = safe_path(root, config['territory_manifest'])
    territory_manifest = read(tpath)
    if territory_manifest.get('status') != 'SUCCESS' or territory_manifest.get('architecture') != 'PROJECT_TERRITORY_V1':
        raise ValueError('Territory publication not SUCCESS')
    if territory_manifest['layer2']['manifest_sha256'] != l2['manifest_sha256']:
        raise ValueError('Territory publication references different Layer 2')
    verify_hashes(root, {(tpath.parent / name).relative_to(root).as_posix(): value['sha256']
                         for name, value in territory_manifest['outputs'].items()})
    relationships = pq.read_table(tpath.parent / 'project_territories.parquet').to_pylist()
    evidence = pq.read_table(tpath.parent / 'project_territory_evidence.parquet').to_pylist()
    resolved = {(r['project_id'], r['territory_type'], r['dane_code']) for r in evidence if r['resolution_status'] == 'RESOLVED'}
    if any((r['project_id'], r['territory_type'], r['dane_code']) not in resolved for r in relationships):
        raise ValueError('Published territory bridge lacks RESOLVED evidence')
    dimension = pq.read_table(root / 'data/reference/processed/dane_territories.parquet').to_pylist()
    if sha256(l3_path) != l3_digest:
        raise ValueError('Layer 3 publication changed while reading')
    return dict(eligible=eligible, profiles=profiles, profile_manifest=profile_manifest,
                rules=read(root / 'data/reference/processed/indicator_assessment_rules.json')['rules'],
                relationships=relationships, dimension=dimension, layer2=l2, layer3=l3,
                territory_manifest=territory_manifest,
                candidate_distribution=dict(Counter(c['source_type'] + ':' + c['context_status'] for c in candidates)))


def selected_territories(data, selected):
    return territory_rows(data['relationships'], data['dimension'], {p['project_id']: p['siap_id'] for p in selected})
