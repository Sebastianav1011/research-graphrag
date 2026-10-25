"""Migration checks with synthetic history; no institutional pipeline execution."""
import ast
import hashlib
from pathlib import Path
import zipfile

import pytest

from layer4.history import ARCHIVE, verify_historical_files
from layer4.indicators.preliminary import assert_integrity

ROOT = Path(__file__).resolve().parents[2]


def archived(root, entries):
    path = root / ARCHIVE
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, 'w') as source:
        for name, payload in entries.items():
            source.writestr(name, payload)


def test_historical_original_bytes_are_not_a_current_code_acceptance(tmp_path):
    name = 'src/layer4_confidence/confidence.py'
    original = b'original source'
    archived(tmp_path, {name: original})
    expected = {name: hashlib.sha256(original).hexdigest()}
    report = verify_historical_files(tmp_path, expected)
    assert report['archived_files'] == [name]
    assert report['current_code_acceptance'] == 'NOT_GRANTED_BY_HISTORICAL_VERIFICATION'
    with pytest.raises(ValueError, match='Protected inputs changed'):
        assert_integrity(tmp_path, expected)


def test_archive_tamper_fails_instead_of_rebasing_hash(tmp_path):
    name = 'src/layer4_profiles/profiles.py'
    archived(tmp_path, {name: b'changed'})
    with pytest.raises(ValueError, match='checksum mismatch'):
        verify_historical_files(tmp_path, {name: hashlib.sha256(b'original').hexdigest()})


def test_unarchived_upstream_change_fails(tmp_path):
    archived(tmp_path, {'src/layer4_profiles/profiles.py': b'original'})
    with pytest.raises(ValueError, match='missing'):
        verify_historical_files(tmp_path, {'data/knowledge/source_documents.parquet': 'a' * 64})


def test_matching_current_file_needs_no_archive(tmp_path):
    path = tmp_path / 'unchanged.txt'
    path.write_bytes(b'unchanged')
    result = verify_historical_files(tmp_path, {'unchanged.txt': hashlib.sha256(path.read_bytes()).hexdigest()})
    assert result['archived_files'] == []


@pytest.mark.parametrize('name', ['../outside.py', '/outside.py', 'C:/outside.py', 'src\\outside.py'])
def test_historical_paths_cannot_escape_root(tmp_path, name):
    with pytest.raises(ValueError, match='Unsafe'):
        verify_historical_files(tmp_path, {name: 'a' * 64})


@pytest.mark.parametrize('old,new', [
    ('layer4_confidence/configuration.py', 'indicators/confidence.py'),
    ('layer4_confidence/confidence.py', 'indicators/confidence.py'),
    ('layer4_assessment/validation.py', 'indicators/assessment.py'),
    ('layer4_assessment/territories.py', 'territories/contracts.py'),
    ('layer4_territories/matching.py', 'territories/matching.py'),
    ('layer4_preliminary/selection.py', 'indicators/selection.py'),
    ('layer4_preliminary/prompt.py', 'indicators/prompt.py'),
])
def test_core_function_bodies_preserved_in_migration(old, new):
    with zipfile.ZipFile(ROOT / ARCHIVE) as source:
        before = ast.parse(source.read('src/' + old).decode('utf-8-sig'))
    after = ast.parse((ROOT / 'src/layer4' / new).read_text(encoding='utf-8'))
    functions = {n.name: n for n in after.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    for node in before.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            assert ast.dump(node) == ast.dump(functions[node.name]), node.name


def test_old_packages_are_not_active_compatibility_wrappers():
    for package in ('layer4_assessment', 'layer4_confidence', 'layer4_preliminary', 'layer4_profiles', 'layer4_territories'):
        assert not (ROOT / 'src' / package).exists()
