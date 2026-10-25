"""Validate original publication inputs; never accept migrated code by substitution.

An archived file proves only the historical bytes named in a stored manifest.
Current runtime baselines must continue to use strict on-disk hashes.
"""
import hashlib
from pathlib import Path, PurePosixPath
import zipfile

ARCHIVE = Path('archives/layer4/pre_namespace_migration.zip')
DANE_ARCHIVE = Path('archives/layer4/pre_layer1_unification.zip')


def verify_historical_files(root, expected):
    """Verify every original checksum, using the source archive only when needed.

    There is no old-to-new path mapping and no replacement of expected hashes.
    Missing/unarchived inputs and byte mismatches always fail closed.
    """
    root = Path(root).resolve()
    archived = []
    for name, checksum in expected.items():
        key = PurePosixPath(name)
        if key.is_absolute() or '..' in key.parts or '\\' in name or ':' in name:
            raise ValueError('Unsafe historical input path: ' + name)
        path = root / name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == checksum:
            continue
        found = False
        candidate_present = False
        for archive in (ARCHIVE, DANE_ARCHIVE):
            if not (root / archive).is_file():
                continue
            try:
                with zipfile.ZipFile(root / archive) as source:
                    matches = [item for item in source.infolist() if item.filename == name]
                    if len(matches) > 1:
                        raise ValueError('Historical input duplicated: ' + name)
                    if not matches:
                        continue
                    candidate_present = True
                    payload = source.read(matches[0])
            except (OSError, zipfile.BadZipFile) as exc:
                raise ValueError('Historical archive unavailable for: ' + name) from exc
            if hashlib.sha256(payload).hexdigest() == checksum:
                found = True
                break
        if not found:
            reason = 'checksum mismatch' if candidate_present else 'input missing'
            raise ValueError('Historical ' + reason + ': ' + name)
        archived.append(name)
    return {'status': 'PASS', 'protected_files': len(expected), 'changed_files': [],
            'verification_scope': 'HISTORICAL_INPUTS', 'archived_files': sorted(archived),
            'current_code_acceptance': 'NOT_GRANTED_BY_HISTORICAL_VERIFICATION'}
