"""Active official exporter, reusing the existing acceptance and atomic publication.

The old closure_export remains an exact historical input. This module changes
only final territorial columns and obtains verified originals from closure_runtime.
"""
from run_paths import file_path as run_file
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import shutil
import uuid

from . import experiment
from .closure_export import acceptance_gate, consumer_rows, render_workbook
from .experiment_export import sheet
from .experiment_inputs import read, sha256, verify_hashes, safe_path
from .final_projection import TERRITORY_COLUMNS, territories
from .powerbi import COLUMNS
from .selection import canonical_hash


def _runtime(root, config_path):
    from .closure_runtime import verify_current
    return verify_current(root, config_path)


def build_spec(selected, records, data):
    return {'sheets': [sheet('RESULTADO_INDICADORES', COLUMNS, consumer_rows(selected, records)),
                       sheet('TERRITORIOS', TERRITORY_COLUMNS, territories(data, selected))]}


def records_from_rows(selected, rows):
    """Prepare a consumer-only view of already verified semantic results.

    The evidence wrapper is used exclusively for literal quote locations. It is
    not a new assessment and never replaces the immutable original model response.
    """
    records = {p['project_id']: {'rows': [], 'wrapper': {'assessments': []}} for p in selected}
    seen = set()
    for row in rows:
        key = row['project_id'], row['indicator_id']
        if key in seen or key[0] not in records:
            raise ValueError('Unknown/duplicate effective PROJECT+INDICATOR')
        seen.add(key)
        fields, texts = row['evidence_source_fields'], row['evidence_texts']
        if len(fields) != len(texts):
            raise ValueError('Effective evidence field/text alignment mismatch')
        records[key[0]]['rows'].append(row)
        records[key[0]]['wrapper']['assessments'].append({'indicator_id': key[1],
            'evidence': [{'field': field, 'text': text} for field, text in zip(fields, texts)]})
    return records


def _accepted_records(root, out, manifest, selected, review_data, approval, technical_hash):
    # The accepted pilot remains immutable when final options disable fallback.
    # The approval must explicitly bind the definitive plan used for consumption.
    supplemental = safe_path(root, approval.get('supplemental_output_directory',
        'outputs/layer4/auditoria/historicos/cierre_v2_20'))
    if not supplemental.is_relative_to((root / 'outputs/layer4/pruebas').resolve()):
        raise ValueError('Accepted execution must stay within Layer4 pruebas')
    if 'supplemental_output_directory' in approval and not (supplemental / 'plan.json').is_file():
        raise ValueError('Explicit accepted execution has no prepared plan')
    if (supplemental / 'plan.json').exists():
        from . import semantic_fallback
        accepted = semantic_fallback.publication_check(root, supplemental, approval, review_data)
        if accepted.get('status') != 'PASS':
            raise ValueError('BLOCKED: supplemental/fallback human acceptance is incomplete')
        rows = accepted['rows']
        return (records_from_rows(selected, rows), accepted['human_review_summary'],
                {**{k: accepted[k] for k in ('effective_results_sha256', 'supplemental_plan_sha256')},
                 'supplemental_output_directory': supplemental.relative_to(root).as_posix()})
    records = {p.stem: read(p) for p in (out / 'records').glob('*.json')}
    metrics = acceptance_gate(manifest, selected, records, review_data, approval, technical_hash)
    return records, metrics, {}


def publish(root, config_path, approval_path=None, review_path=None):
    root = Path(root)
    state = _runtime(root, config_path)
    config, out, manifest, data, selected, requests, runtime = state['verified']
    if not experiment.is_v2(config):
        raise ValueError('Official exporter accepts only V2 closure results')
    publication_root = root / 'outputs/layer4/auditoria/cierre_v2'
    publication_root.mkdir(parents=True, exist_ok=True)
    with experiment.run_lock(out), experiment.run_lock(publication_root):
        if (publication_root / 'publication_pending.json').exists():
            raise ValueError('BLOCKED: recover the existing publication journal before another publication')
        state = _runtime(root, config_path)
        if not approval_path or not review_path:
            raise ValueError('BLOCKED: actual completion and human acceptance required; no official workbook published')
        review_data, approval = read(review_path), read(approval_path)
        technical_hash = sha256(out / 'technical_results.jsonl')
        records, metrics, supplemental = _accepted_records(root, out, manifest, selected, review_data, approval, technical_hash)
        spec = build_spec(selected, records, data)
        publication_id = canonical_hash({'spec': spec, 'execution_id': manifest['execution_id'],
            'technical_results_sha256': technical_hash, 'approval_sha256': sha256(approval_path),
            'review_sha256': sha256(review_path)})[:20]
        directory = publication_root / 'publications' / publication_id
        directory.mkdir(parents=True, exist_ok=True)
        candidate = directory / 'resultado_capa4.xlsx'
        qa = render_workbook(root, spec, candidate, directory / 'qa')
        verify_hashes(root, read(out / 'protected_inputs.json'))
        for source, name in ((review_path, 'human_review.accepted.json'),
                             (approval_path, 'final_approval.accepted.json')):
            target = directory / name
            if Path(source).resolve() != target.resolve():
                shutil.copyfile(source, target)
        destination = root / 'outputs/layer4/final/resultado_capa4.xlsx'
        destination.parent.mkdir(parents=True, exist_ok=True)
        if any(p.name != destination.name for p in destination.parent.iterdir()):
            raise ValueError('Official folder must contain only resultado_capa4.xlsx')
        publication = {'status': 'CAPA_4_COMPLETE', 'version': 'LAYER4_FINAL_V2_MINIMAL_TERRITORIES',
            'execution_id': manifest['execution_id'], 'config_path': str(config_path),
            'selection_sha256': manifest['selection_sha256'], 'technical_results_sha256': technical_hash,
            'confidence_version': 'EVIDENCE_CONFIDENCE_V2', 'approval_sha256': sha256(approval_path),
            'human_review_sha256': sha256(review_path),
            'approval_snapshot': (directory / 'final_approval.accepted.json').relative_to(root).as_posix(),
            'review_snapshot': (directory / 'human_review.accepted.json').relative_to(root).as_posix(),
            'human_metrics': metrics, 'assessment_count': len(spec['sheets'][0]['rows']), 'projects': 20,
            'territory_rows': len(spec['sheets'][1]['rows']), 'territory_columns': TERRITORY_COLUMNS,
            'territory_join_key': ['territory_type', 'territory_code', 'code_system'],
            'decisions': dict(Counter(r['estado_cumplimiento'] for r in consumer_rows(selected, records))),
            'workbook_sha256': sha256(candidate), 'qa': qa,
            'published_at': datetime.now(timezone.utc).isoformat(),
            'protected_inputs': read(out / 'protected_inputs.json'),
            'runtime_verification': state['verification'],
            'active_export_code_hashes': {name: sha256(root / name) for name in (
                'src/layer4_evaluation/indicators/final_export.py', 'src/layer4_evaluation/indicators/final_projection.py',
                'src/layer4_evaluation/indicators/closure_runtime.py')}, **supplemental}
        experiment.write_json(directory / 'publication_manifest.json', publication)
        journal = publication_root / 'publication_pending.json'
        experiment.write_json(journal, {'candidate': candidate.relative_to(root).as_posix(),
            'destination': destination.relative_to(root).as_posix(),
            'previous_sha256': sha256(destination) if destination.exists() else None,
            'expected_sha256': publication['workbook_sha256'],
            'publication_manifest': (directory / 'publication_manifest.json').relative_to(root).as_posix()})
        if destination.exists() and sha256(destination) != publication['workbook_sha256']:
            history = publication_root / 'publications' / ('previous_' + uuid.uuid4().hex)
            history.mkdir()
            shutil.copy2(destination, history / destination.name)
        temporary = destination.with_suffix('.xlsx.pending')
        shutil.copyfile(candidate, temporary)
        temporary.replace(destination)
        experiment.write_json(publication_root / 'final_manifest.json', publication)
        journal.unlink()
        return publication


def verify_final(root, config_path):
    from .preliminary_output import verify_workbook
    root = Path(root)
    publication_root = root / 'outputs/layer4/auditoria/cierre_v2'
    if (run_file(publication_root, '.execution.lock')).exists():
        raise ValueError('BLOCKED: official publication writer active')
    if (publication_root / 'publication_pending.json').exists():
        raise ValueError('BLOCKED: interrupted official publication; inspect recovery journal')
    manifest_path = publication_root / 'final_manifest.json'
    if not manifest_path.exists():
        return {'status': 'BLOCKED', 'cause': 'No completed and human-accepted V2 publication'}
    publication = read(manifest_path)
    verify_hashes(root, publication['protected_inputs'])
    verify_hashes(root, publication['active_export_code_hashes'])
    state = _runtime(root, config_path)
    config, out, manifest, data, selected, requests, runtime = state['verified']
    if (publication['version'] != 'LAYER4_FINAL_V2_MINIMAL_TERRITORIES'
            or publication['execution_id'] != manifest['execution_id']
            or publication['technical_results_sha256'] != sha256(out / 'technical_results.jsonl')):
        raise ValueError('Official publication does not match verified final execution')
    workbook = root / 'outputs/layer4/final/resultado_capa4.xlsx'
    if set(p.name for p in workbook.parent.iterdir()) != {workbook.name} or sha256(workbook) != publication['workbook_sha256']:
        raise ValueError('Official output/hash mismatch')
    verify_hashes(root, {publication['approval_snapshot']: publication['approval_sha256'],
                         publication['review_snapshot']: publication['human_review_sha256']})
    approval, review_data = read(root / publication['approval_snapshot']), read(root / publication['review_snapshot'])
    records, metrics, supplemental = _accepted_records(root, out, manifest, selected, review_data, approval,
                                                       publication['technical_results_sha256'])
    if any(publication.get(key) != value for key, value in supplemental.items()):
        raise ValueError('Official publication does not match accepted supplemental provenance')
    return {'status': 'PASS', 'publication_status': publication['status'],
            'qa': verify_workbook(workbook, build_spec(selected, records, data)),
            'protected_files': len(publication['protected_inputs'])}
