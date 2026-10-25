"""Unification preserves reference logic and exact historical checksums."""
import ast
import hashlib
from pathlib import Path
import zipfile

import pytest

from layer1_data import dane_reference
from layer4.history import DANE_ARCHIVE, verify_historical_files

ROOT = Path(__file__).resolve().parents[2]


def test_dane_reference_function_bodies_are_unchanged():
    with zipfile.ZipFile(ROOT / DANE_ARCHIVE) as source:
        before = ast.parse(source.read('src/layer1_territories/reference.py').decode('utf-8-sig'))
    after = ast.parse(Path(dane_reference.__file__).read_text(encoding='utf-8-sig'))
    assert ast.dump(before) == ast.dump(after)
    assert not (ROOT / 'src/layer1_territories').exists()


def test_second_archive_verifies_original_path_and_bytes(tmp_path):
    path = tmp_path / DANE_ARCHIVE
    path.parent.mkdir(parents=True)
    name = 'src/layer1_territories/reference.py'
    with zipfile.ZipFile(path, 'w') as source:
        source.writestr(name, b'original')
    expected = hashlib.sha256(b'original').hexdigest()
    report = verify_historical_files(tmp_path, {name: expected})
    assert report['archived_files'] == [name]
    assert report['current_code_acceptance'] == 'NOT_GRANTED_BY_HISTORICAL_VERIFICATION'
    with pytest.raises(ValueError, match='checksum mismatch'):
        verify_historical_files(tmp_path, {name: '0' * 64})


def test_auxiliary_scripts_resolve_the_repository_root():
    for name in ('audit_identity_aliases.py', 'audit_identity_alias_forensics.py',
                 'create_source_level_review_workbook.py', 'verify_layer4_preparation.py'):
        path = ROOT / 'scripts/auxiliary' / name
        tree = ast.parse(path.read_text(encoding='utf-8'))
        root = next(n for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'ROOT' for t in n.targets))
        assert ast.unparse(root.value) == 'Path(__file__).resolve().parents[2]'
        assert not (ROOT / 'scripts' / name).exists()
