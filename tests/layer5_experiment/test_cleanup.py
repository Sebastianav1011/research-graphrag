import json
from pathlib import Path
import zipfile

import pytest
from layer4_evaluation.indicators import cleanup


def sample(root):
    target = root / 'outputs/layer4/preliminary_tests'
    target.mkdir(parents=True)
    (target / 'synthetic.json').write_text('{"synthetic": true}', encoding='utf-8')
    return target


def test_inventory_and_recovery_before_deletion(tmp_path):
    target = sample(tmp_path)
    inv = cleanup.inventory(tmp_path)
    planned = cleanup.plan(tmp_path, inv, ['outputs/layer4/preliminary_tests'])
    assert target.exists() and not inv['deletion_performed']
    backup = tmp_path / 'archives/layer4/recovery.zip'
    result = cleanup.apply(tmp_path, planned, backup, tmp_path / 'outputs/layer4/auditoria/cierre_v2/cleanup/journal.json')
    assert not target.exists() and result['status'] == 'COMPLETE'
    with zipfile.ZipFile(backup) as archive:
        assert archive.read('outputs/layer4/preliminary_tests/synthetic.json') == b'{"synthetic": true}'
    assert result['backup_sha256'] == cleanup.digest(backup)
    assert cleanup.restore(tmp_path, result)['status'] == 'RESTORED'
    assert (target / 'synthetic.json').read_text(encoding='utf-8') == '{"synthetic": true}'
    (target / 'synthetic.json').write_text('New current data', encoding='utf-8')
    with pytest.raises(ValueError, match='overwrite'):
        cleanup.restore(tmp_path, result)


def test_runtime_or_hash_consumers_block_deletion(tmp_path):
    sample(tmp_path)
    config = tmp_path / 'config'
    config.mkdir()
    (config / 'active.yaml').write_text('input: outputs/layer4/preliminary_tests/synthetic.json', encoding='utf-8')
    inv = cleanup.inventory(tmp_path)
    assert inv['directories'][0]['action'] == 'KEEP'
    with pytest.raises(ValueError, match='consumers'):
        cleanup.plan(tmp_path, inv, ['outputs/layer4/preliminary_tests'])


def test_stale_plan_never_rebased(tmp_path):
    target = sample(tmp_path)
    planned = cleanup.plan(tmp_path, cleanup.inventory(tmp_path), ['outputs/layer4/preliminary_tests'])
    (target / 'synthetic.json').write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='Stale'):
        cleanup.apply(tmp_path, planned, tmp_path / 'archives/layer4/recovery.zip',
                      tmp_path / 'outputs/layer4/auditoria/cierre_v2/cleanup/journal.json')
    assert target.exists() and not (tmp_path / 'archives/layer4/recovery.zip').exists()


@pytest.mark.parametrize('relative', ['outputs/layer4/territories', 'outputs/layer4/preliminary_20',
    '../outside', 'outputs/layer4/preliminary_tests/nested', 'outputs/layer4'])
def test_recursive_target_boundary_and_allowlist(tmp_path, relative):
    with pytest.raises(ValueError, match='allowlisted'):
        cleanup.safe_target(tmp_path, relative)


def test_backup_must_be_private_and_new(tmp_path):
    target = sample(tmp_path)
    planned = cleanup.plan(tmp_path, cleanup.inventory(tmp_path), ['outputs/layer4/preliminary_tests'])
    with pytest.raises(ValueError, match='private'):
        cleanup.apply(tmp_path, planned, tmp_path / 'outputs/layer4/recovery.zip',
                      tmp_path / 'outputs/layer4/auditoria/cierre_v2/cleanup/journal.json')
    assert target.exists()


def test_internal_pytest_alias_is_backed_up_without_following_and_restored(tmp_path):
    target = sample(tmp_path)
    fixture = target / 'fixture0'
    fixture.mkdir()
    (fixture / 'data.txt').write_text('fixture bytes', encoding='utf-8')
    alias = target / 'fixturecurrent'
    alias.symlink_to(fixture, target_is_directory=True)
    empty = target / 'empty0'
    empty.mkdir()
    (target / 'emptycurrent').symlink_to(empty, target_is_directory=True)
    planned = cleanup.plan(tmp_path, cleanup.inventory(tmp_path), ['outputs/layer4/preliminary_tests'])
    assert len(planned['targets'][0]['links']) == 2
    assert len(planned['targets'][0]['files']) == 2
    result = cleanup.apply(tmp_path, planned, tmp_path / 'archives/layer4/recovery.zip',
                           tmp_path / 'outputs/layer4/auditoria/cierre_v2/cleanup/journal.json')
    cleanup.restore(tmp_path, result)
    assert alias.is_symlink() and alias.resolve() == fixture
    assert (alias / 'data.txt').read_text(encoding='utf-8') == 'fixture bytes'
    assert (target / 'emptycurrent').is_dir()


def test_external_current_alias_blocks_cleanup(tmp_path):
    target = sample(tmp_path)
    external = tmp_path / 'external'
    external.mkdir()
    (target / 'externalcurrent').symlink_to(external, target_is_directory=True)
    row = cleanup.inventory(tmp_path)['directories'][0]
    assert row['action'] == 'KEEP' and row['unsafe_links']
    with pytest.raises(ValueError):
        cleanup.plan(tmp_path, cleanup.inventory(tmp_path), ['outputs/layer4/preliminary_tests'])


def test_unreadable_directory_is_not_reported_as_empty(tmp_path, monkeypatch):
    target = sample(tmp_path)
    original = cleanup._entries
    def restricted(folder):
        if Path(folder) == target:
            raise PermissionError(13, 'Synthetic access denied', str(target))
        yield from original(folder)
    monkeypatch.setattr(cleanup, '_entries', restricted)
    inv = cleanup.inventory(tmp_path)
    assert inv['scan_errors']
    assert inv['directories'][0]['file_count'] is None
    assert inv['directories'][0]['bytes'] is None
    assert inv['directories'][0]['action'] == 'KEEP'
    with pytest.raises(ValueError, match='Unreadable'):
        cleanup.plan(tmp_path, inv, ['outputs/layer4/preliminary_tests'])
