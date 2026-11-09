"""Conservative Layer 4 cleanup: inventory, dependency dry-run, verified ZIP, delete.

No hash baseline is rewritten. A plan can target only specifically named obsolete
visual drafts or temporary test outputs, never an active/accepted publication.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import zipfile


OBSOLETE = {
    'experiment_50_before_visual_fix': 'Visual draft superseded by the original pilot and corrected workbook.',
    'experiment_50_before_visual_fix_2': 'Second visual-only draft superseded by corrected workbook.',
    'preliminary_tests': 'Recreatable synthetic regression temporary output; no accepted publication.',
    'territories-reference-test-temp': 'Recreatable synthetic reference test temporary output.',
    'pilot_delivery_tests_20261019': 'Recreatable synthetic delivery test temporary output.',
}
OBSOLETE.update({
    'closure/' + name: 'Recreatable synthetic regression temporary files; preserve XML reports and original-code snapshots separately.'
    for name in ('accepted-code-test-temp', 'final-4a-temp', 'l1-temp', 'l2-temp', 'l3-temp',
                 'native-schema-test-temp', 'preparation-temp', 'projection-test-temp', 'territory-temp',
                 'test-temp', 'v2-export-temp', 'v2-flow-temp', 'v2-unit-temp')})
OBSOLETE.update({'experiment_tests_20261019/run' + str(n):
    'Recreatable synthetic test working directory; accepted regression XML remains in the parent.' for n in range(1, 6)})
ALWAYS_KEEP = {
    'experiment_closure20_v2_final': 'Current 20-project V2 preparation, 5-project pilot and mutable human review.',
    'experiment_20': 'Historical real experiment and fixed sample source for current preparation.',
    'experiment_50_pilot': 'Original accepted real pilot, provenance and historical reuse source.',
    'territories': 'Accepted 4B publication; immutable.',
    'territory_acceptance': 'Acceptance and invariance evidence for accepted 4B.',
    'territory_runs': 'Historical 4B accepted versions and recovery evidence.',
    'preliminary_20': 'Historical real run included in protected input fingerprints.',
    'powerbi_preliminary_20': 'Historical published projection in protected input fingerprints.',
    'performance': 'Current private academic performance deliverables.',
    'closure': 'Integrity baselines, original code snapshots, QA, authorization and cleanup journals.',
}
TEXT_SUFFIXES = {'.py', '.mjs', '.js', '.json', '.yaml', '.yml', '.toml', '.md', '.txt', '.ps1'}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def safe_target(root, relative):
    root = Path(root).resolve()
    candidate = (root / relative).resolve()
    layer = (root / 'outputs/layer4').resolve()
    if (not candidate.is_relative_to(layer) or candidate.relative_to(layer).as_posix() not in OBSOLETE
            or candidate.is_symlink()):
        raise ValueError('Cleanup target must be an exact allowlisted Layer 4 directory')
    return candidate


def _entries(folder):
    """Walk without traversing symbolic links or Windows junctions."""
    def unreadable(error):
        raise error
    if not Path(folder).exists():
        return
    for current, directories, filenames in os.walk(folder, followlinks=False, onerror=unreadable):
        current = Path(current)
        for name in list(directories):
            path = current / name
            yield path
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                directories.remove(name)
        for name in filenames:
            yield current / name


def _link_metadata(folder, root):
    folder, root = Path(folder).resolve(), Path(root).resolve()
    result = []
    for path in _entries(folder):
        junction = hasattr(path, 'is_junction') and path.is_junction()
        if not path.is_symlink() and not junction:
            continue
        target = path.resolve()
        if (junction or not path.name.endswith('current') or not path.is_dir()
                or not target.is_relative_to(folder) or not target.is_relative_to(root)):
            raise ValueError('Only internal pytest *current directory symbolic links may be cleaned')
        result.append({'path': path.relative_to(root).as_posix(),
                       'target': target.relative_to(root).as_posix(),
                       'original_target': str(path.readlink()), 'kind': 'SYMBOLIC_LINK_DIRECTORY'})
    return sorted(result, key=lambda r: r['path'])


def _files(folder, strict=True):
    paths = list(_entries(folder))
    links = [p for p in paths if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())]
    if strict and links:
        _link_metadata(folder, folder)
    return sorted(p for p in paths if p.is_file() and p not in links)


def _dependencies(root, names):
    references = {name: [] for name in names}
    pattern = re.compile(r'(?<![A-Za-z0-9_])(?:' + '|'.join(
        re.escape(name) for name in sorted(names, key=len, reverse=True)) + r')(?![A-Za-z0-9_])')
    errors = []
    paths = set()
    for directory in ('config', 'src', 'scripts', 'tests', 'docs', 'outputs/layer4'):
        try:
            paths.update(p for p in _entries(root / directory) if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES
                         and '__pycache__' not in p.parts and 'cleanup' not in p.parts)
        except OSError as exc:
            errors.append({'path': str(exc.filename), 'error': type(exc).__name__, 'stage': 'DIRECTORY_TRAVERSAL'})
    if (root / 'README.md').is_file():
        paths.add(root / 'README.md')
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        # Cleanup reports contain the inventory itself, not consumers.
        if relative.startswith('outputs/layer4/auditoria/cierre_v2/cleanup/') or relative in (
                'src/layer4_evaluation/indicators/cleanup.py', 'scripts/cleanup_layer4.py',
                'tests/layer5_experiment/test_cleanup.py', 'docs/methodology/layer4_cleanup.md'):
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            errors.append({'path': relative, 'error': type(exc).__name__})
            continue
        matched = {match.group(0) for match in pattern.finditer(text.replace('\\', '/'))}
        # A reference to an explicitly inventoried child is also a consumer of
        # its parent directory. One scan per file avoids repeated large JSON scans.
        matched.update(name for name in names if any(value.startswith(name + '/') for value in tuple(matched)))
        for name in matched:
            own = 'outputs/layer4/' + name + '/'
            if relative.startswith(own):
                continue
            # Full normalized path references and explicit direct directory names.
            references[name].append({'path': relative,
                'kind': 'DOCUMENTARY' if path.suffix.lower() == '.md' else 'RUNTIME_OR_INTEGRITY'})
    return references, errors


def inventory(root):
    root = Path(root).resolve()
    layer = root / 'outputs/layer4'
    folders = sorted({p for p in layer.iterdir() if p.is_dir() and not p.is_symlink()} |
                     {layer / name for name in OBSOLETE if (layer / name).is_dir()})
    refs, errors = _dependencies(root, [p.relative_to(layer).as_posix() for p in folders])
    entries = []
    for folder in folders:
        unreadable = False
        try:
            files = _files(folder, strict=False)
            links = [p.relative_to(root).as_posix() for p in _entries(folder)
                     if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())]
        except OSError as exc:
            files, links, unreadable = [], [], True
            errors.append({'path': str(exc.filename), 'error': type(exc).__name__, 'stage': 'DIRECTORY_INVENTORY'})
        try:
            safe_links = _link_metadata(folder, root)
            unsafe_links = []
        except (ValueError, OSError, RuntimeError):
            safe_links, unsafe_links = [], links
        stamps = [p.stat().st_mtime for p in files]
        meta = []
        for path in files:
            if path.name not in ('experiment_manifest.json', 'territory_manifest.json', 'export_manifest.json',
                                 'preliminary_manifest.json', 'progress.json', 'status.json'):
                continue
            try:
                value = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            meta.append({'path': path.relative_to(root).as_posix(),
                         **{key: value[key] for key in ('version', 'status', 'execution_id', 'generated_at_utc',
                            'created_at', 'prepared_at', 'assessment_version', 'confidence_version') if key in value}})
        folder_key = folder.relative_to(layer).as_posix()
        dependencies = refs[folder_key]
        blockers = [r for r in dependencies if r['kind'] != 'DOCUMENTARY']
        purpose = ALWAYS_KEEP.get(folder_key, OBSOLETE.get(folder_key,
            'Historical/audit output; retain until a specific deletion justification is established.'))
        eligible = folder_key in OBSOLETE and not blockers and not errors and not unsafe_links
        entries.append({'directory': folder.relative_to(root).as_posix(), 'purpose': purpose,
            'file_count': None if unreadable else len(files),
            'bytes': None if unreadable else sum(p.stat().st_size for p in files),
            'content_inventory_status': 'NOT_AVAILABLE_ACCESS_DENIED' if unreadable else 'MEASURED',
            'oldest_file_utc': datetime.fromtimestamp(min(stamps), timezone.utc).isoformat() if stamps else None,
            'newest_file_utc': datetime.fromtimestamp(max(stamps), timezone.utc).isoformat() if stamps else None,
            'metadata': meta, 'references': dependencies, 'runtime_or_integrity_blockers': blockers,
            'unsafe_links': unsafe_links, 'internal_pytest_aliases': safe_links,
            'action': 'ELIGIBLE_AFTER_REVIEW_AND_VERIFIED_BACKUP' if eligible else 'KEEP',
            'active_or_mandatory': folder_key in ALWAYS_KEEP,
            'reproducibility': 'Preserve raw results and fingerprints unless explicitly allowlisted as recreatable.'})
    return {'version': 'LAYER4_CLEANUP_V1', 'generated_at': datetime.now(timezone.utc).isoformat(),
            'mode': 'DRY_RUN', 'directories': entries, 'scan_errors': errors,
            'deletion_performed': False}


def plan(root, inventory_data, directories):
    root = Path(root).resolve()
    listed = {row['directory']: row for row in inventory_data['directories']}
    targets = []
    if inventory_data.get('scan_errors'):
        raise ValueError('Unreadable dependency inputs; cleanup fails closed')
    for relative in directories:
        path = safe_target(root, relative)
        row = listed[relative]
        if row['action'] != 'ELIGIBLE_AFTER_REVIEW_AND_VERIFIED_BACKUP':
            raise ValueError('Cleanup target has integrity/runtime consumers or no deletion justification: ' + relative)
        targets.append({'directory': relative, 'reason': row['purpose'], 'links': _link_metadata(path, root),
                        'files': {p.relative_to(root).as_posix(): digest(p) for p in _files(path)}})
    return {'version': 'LAYER4_CLEANUP_V1', 'mode': 'DRY_RUN',
            'generated_at': datetime.now(timezone.utc).isoformat(), 'targets': targets,
            'deletion_performed': False}


def apply(root, plan_data, backup, journal):
    root, backup, journal = Path(root).resolve(), Path(backup).resolve(), Path(journal).resolve()
    private = (root / 'archives/layer4').resolve()
    if not backup.is_relative_to(private) or backup.suffix.lower() != '.zip' or backup.exists():
        raise ValueError('Use a new private archives/layer4 ZIP recovery file')
    if not journal.is_relative_to(root / 'outputs/layer4/auditoria/cierre_v2/cleanup') or journal.exists():
        raise ValueError('Use a new cleanup journal in the private audit directory')
    targets = plan_data['targets']
    fresh = inventory(root)
    checked = plan(root, fresh, [t['directory'] for t in targets])
    if checked['targets'] != targets or not targets:
        raise ValueError('Stale/empty plan; regenerate dry-run instead of rebasing hashes')
    # Resolve every recursive target before any filesystem mutation (Windows safety).
    paths = [safe_target(root, t['directory']) for t in targets]
    backup.parent.mkdir(parents=True, exist_ok=True)
    expected = {name: value for target in targets for name, value in target['files'].items()}
    with zipfile.ZipFile(backup, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(expected):
            archive.write(root / name, name)
    with zipfile.ZipFile(backup) as archive:
        if set(archive.namelist()) != set(expected) or archive.testzip() is not None:
            raise ValueError('Recovery ZIP failed integrity check; nothing deleted')
        if any(hashlib.sha256(archive.read(name)).hexdigest() != value for name, value in expected.items()):
            raise ValueError('Recovery bytes differ from plan; nothing deleted')
    result = {'version': 'LAYER4_CLEANUP_V1', 'status': 'BACKED_UP_PENDING_DELETION',
              'backup': backup.relative_to(root).as_posix(), 'backup_sha256': digest(backup),
              'targets': targets, 'deleted': [], 'started_at': datetime.now(timezone.utc).isoformat()}
    journal.parent.mkdir(parents=True, exist_ok=True)
    def save():
        temporary = journal.with_suffix('.json.pending')
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(journal)
    save()
    for path, target in zip(paths, targets):
        safe_target(root, target['directory'])
        if (_link_metadata(path, root) != target['links'] or
                {p.relative_to(root).as_posix(): digest(p) for p in _files(path)} != target['files']):
            raise ValueError('Target changed after backup; inspect pending journal')
        shutil.rmtree(path)
        result['deleted'].append(target['directory'])
        save()
    result.update(status='COMPLETE', finished_at=datetime.now(timezone.utc).isoformat())
    save()
    return result


def restore(root, journal_data):
    """Restore the verified original bytes without overwriting later changes."""
    root = Path(root).resolve()
    archive_path = (root / journal_data['backup']).resolve()
    if not archive_path.is_relative_to(root / 'archives/layer4') or digest(archive_path) != journal_data['backup_sha256']:
        raise ValueError('Recovery archive path/hash mismatch')
    targets = journal_data['targets']
    expected = {name: value for target in targets for name, value in target['files'].items()}
    directories = [safe_target(root, target['directory']) for target in targets]
    with zipfile.ZipFile(archive_path) as archive:
        if set(archive.namelist()) != set(expected) or archive.testzip() is not None:
            raise ValueError('Recovery archive members differ from journal')
        for name, value in expected.items():
            path = (root / name).resolve()
            if not any(path.is_relative_to(folder) for folder in directories):
                raise ValueError('Recovery member escapes the checked target directories')
            if hashlib.sha256(archive.read(name)).hexdigest() != value:
                raise ValueError('Recovery member hash mismatch')
            if path.exists() and (not path.is_file() or digest(path) != value):
                raise ValueError('Recovery would overwrite changed current bytes')
        aliases = [link for target in targets for link in target.get('links', [])]
        for link in aliases:
            path, target = root / link['path'], (root / link['target']).resolve()
            if (link.get('kind') != 'SYMBOLIC_LINK_DIRECTORY' or not path.name.endswith('current')
                    or not any(path.parent.resolve().is_relative_to(folder) and target.is_relative_to(folder)
                               for folder in directories)):
                raise ValueError('Recovery alias escapes its exact checked target directory')
            if path.exists() or path.is_symlink():
                if not path.is_symlink() or path.resolve() != target:
                    raise ValueError('Recovery would overwrite a changed alias')
        for folder in directories:
            folder.mkdir(parents=True, exist_ok=True)
        for name in sorted(expected):
            path = root / name
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('xb') as stream:
                    stream.write(archive.read(name))
        for link in aliases:
            path = root / link['path']
            if not path.is_symlink():
                # Pytest aliases may point to an entirely empty fixture folder.
                # Its existence is carried by alias metadata, even without files.
                (root / link['target']).mkdir(parents=True, exist_ok=True)
                path.symlink_to(root / link['target'], target_is_directory=True)
    return {'status': 'RESTORED', 'files': len(expected), 'directories': [t['directory'] for t in targets]}
