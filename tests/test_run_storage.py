"""Synthetic storage lifecycle only. No graph, embeddings, models or network."""
from datetime import timedelta
import json
import os
from pathlib import Path
import sqlite3

import pytest

from autonomous_execution import store as s
from run_paths import file_path,find_run,provider_of,resolve_file
import run_storage as storage


def run_at(root,name='demo',provider='ollama',complete=True,legacy=False):
    run=root/'outputs/runs'/name if legacy else find_run(root,root/'outputs/runs',name,provider)
    llm=dict(provider=provider,model='gpt-6.1-terra' if provider=='openai' else 'qwen3.5:4b-q4_K_M')
    s.write(file_path(run,'execution.json'),dict(llm=llm,project_ids=['P'],evaluation_contract={'sha256':'synthetic'}))
    s.write(file_path(run,'run.json'),dict(status='PREPARED',configuration=dict(llm=llm)))
    s.write(file_path(run,'runtime.manifest.json'),dict(project_states=dict(complete=['P'] if complete else [],
        partial=[],blocked=[],pending=[] if complete else ['P'])))
    target=run/'resultados/indicadores.csv';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text('id;codigo\nP;05001\n',encoding='utf-8')
    (target.parent/'indicadores_territorios.csv').write_text('id;codigo_dane\nP;05001\n',encoding='utf-8')
    return run


def aged_closed(root,run):
    storage.archive_export(root,run,dict(status='COMPLETE'))
    closed=s.read(run/'estado/closed.json')
    closed['closed_at']=(storage.now()-timedelta(hours=73)).isoformat()
    s.write(run/'estado/closed.json',closed)


@pytest.mark.parametrize('provider,category',[('ollama','local'),('openai','api')])
def test_run_locations_and_internal_metadata(tmp_path,provider,category):
    run=run_at(tmp_path,provider=provider)
    assert run==tmp_path/'outputs/runs'/category/'demo'
    assert (run/'estado/execution.json').exists() and (run/'manifiestos/run.json').exists()
    assert not (run/'execution.json').exists()
    assert provider_of(run)==provider
    assert s.read(tmp_path/'outputs/runs/demo/run.json')['status']=='PREPARED'


def test_provider_collision_requires_explicit_selection(tmp_path):
    local=run_at(tmp_path);api=run_at(tmp_path,provider='openai')
    with pytest.raises(ValueError,match='ambiguo'):find_run(tmp_path,tmp_path/'outputs/runs','demo')
    assert find_run(tmp_path,tmp_path/'outputs/runs','demo','openai')==api
    assert find_run(tmp_path,tmp_path/'outputs/runs','demo','ollama')==local


def test_migration_preserves_bytes_and_old_locators(tmp_path):
    run=run_at(tmp_path,legacy=True)
    original=(run/'execution.json').read_bytes()
    s.write(run/'prepared_hashes.json',dict(original='synthetic'))
    report=storage.migrate(tmp_path)
    moved=tmp_path/'outputs/runs/local/demo'
    assert report['migrated']==1 and report['deleted']==0
    assert (moved/'estado/execution.json').read_bytes()==original
    assert resolve_file(run/'execution.json')==moved/'estado/execution.json'
    assert s.read(run/'prepared_hashes.json')==dict(original='synthetic')
    assert storage.verify_archive(tmp_path/'outputs/historico/local/demo')['provider']=='ollama'
    assert storage.migrate(tmp_path)['migrated']==0


def test_interrupted_migration_resumes_without_overwrite(tmp_path,monkeypatch):
    run_at(tmp_path,legacy=True)
    rename=Path.rename
    def fail_once(self,target):
        if self.name=='execution.json':raise OSError('synthetic interruption')
        return rename(self,target)
    monkeypatch.setattr(Path,'rename',fail_once)
    with pytest.raises(OSError):storage.migrate(tmp_path)
    monkeypatch.setattr(Path,'rename',rename)
    assert storage.migrate(tmp_path)['migrated']==1
    assert s.read(tmp_path/'outputs/runs/demo/execution.json')['project_ids']==['P']


def test_unknown_provider_is_anteriores_and_protected(tmp_path):
    run=tmp_path/'outputs/runs/old';s.write(run/'run.json',dict(status='PREPARED'))
    assert storage.migrate(tmp_path)['migrated']==1
    old=tmp_path/'outputs/runs/anteriores/old'
    row=storage.decision(tmp_path,old)
    assert row['decision']=='RETAIN' and 'PROVIDER_UNKNOWN' in row['reasons']


def test_history_never_overwrites_partial_snapshot(tmp_path):
    run=run_at(tmp_path,complete=False)
    first=storage.archive(tmp_path,run,status='PARTIAL')
    original=(Path(first['path'])/'indicadores.csv').read_bytes()
    (run/'resultados/indicadores.csv').write_text('different complete export',encoding='utf-8')
    second=storage.archive(tmp_path,run,status='PARTIAL')
    assert second['path']!=first['path'] and 'revisiones' in second['path']
    assert (Path(first['path'])/'indicadores.csv').read_bytes()==original
    assert storage.archive(tmp_path,run,status='PARTIAL')['path']==second['path']
    assert not (run/'estado/closed.json').exists()


def test_cleanup_requires_confirmation_and_verified_closed_snapshot(tmp_path):
    run=run_at(tmp_path);aged_closed(tmp_path,run)
    assert storage.decision(tmp_path,run)['decision']=='DELETE_SAFE'
    assert storage.cleanup(tmp_path)['deleted']==0 and run.exists()
    assert storage.cleanup(tmp_path,apply=True,confirm=lambda _:False)['status']=='CANCELLED'
    result=storage.cleanup(tmp_path,apply=True,confirm=lambda _:True)
    assert result['deleted']==1 and result['recovered_bytes']>0 and not run.exists()
    assert storage.verify_archive(tmp_path/'outputs/historico/local/demo')['status']=='COMPLETE'


@pytest.mark.parametrize('protection',['recent','active','uncertain','unarchived','changed_export','incomplete','missing_age'])
def test_cleanup_retains_every_unsafe_case(tmp_path,protection):
    run=run_at(tmp_path);aged_closed(tmp_path,run)
    if protection=='recent':
        value=s.read(run/'estado/closed.json');value['closed_at']=storage.stamp();s.write(run/'estado/closed.json',value)
    elif protection=='active':
        info=s.process_info(os.getpid());s.write(run/'estado/process.json',dict(pid=os.getpid(),creation=info['creation']))
    elif protection=='uncertain':
        with sqlite3.connect(run/'api-ledger.sqlite') as db:
            db.execute('CREATE TABLE requests(state TEXT)');db.execute("INSERT INTO requests VALUES('UNCERTAIN')")
    elif protection=='unarchived':(tmp_path/'outputs/historico/local/demo/indicadores.csv').write_text('corrupted',encoding='utf-8')
    elif protection=='changed_export':(run/'resultados/indicadores.csv').write_text('newer',encoding='utf-8')
    elif protection=='incomplete':
        db=s.connect(run/'autonomous/main') if (run/'autonomous/main').exists() else None
        (run/'estado/closed.json').unlink()
    else:
        value=s.read(run/'estado/closed.json');value['closed_at']='unverifiable';s.write(run/'estado/closed.json',value)
    row=storage.decision(tmp_path,run)
    assert row['decision']=='RETAIN' and row['reasons']
    assert storage.cleanup(tmp_path,apply=True,confirm=lambda _:True)['deleted']==0 and run.exists()


def test_future_or_filesystem_age_cannot_authorize_delete(tmp_path):
    run=run_at(tmp_path)
    os.utime(run,(1,1))
    assert 'AGE_UNVERIFIABLE' in storage.decision(tmp_path,run)['reasons']
    with pytest.raises(ValueError):storage.decision(tmp_path,tmp_path/'data')
    aged_closed(tmp_path,run);storage.reopen(run)
    assert 'NOT_DEFINITIVELY_CLOSED' in storage.decision(tmp_path,run)['reasons']


def test_automatic_policy_is_disabled_until_local_opt_in(tmp_path):
    run=run_at(tmp_path);aged_closed(tmp_path,run)
    assert storage.automatic_cleanup(tmp_path) is None and run.exists()
    s.write(tmp_path/'config/storage.local.json',dict(automatic_cleanup=True))
    assert storage.automatic_cleanup(tmp_path)['deleted']==1


def test_untouched_migration_can_be_reversed_for_original_code(tmp_path):
    original=run_at(tmp_path,legacy=True)
    before=(original/'execution.json').read_bytes()
    storage.migrate(tmp_path)
    assert storage.restore(tmp_path,'demo','ollama')['status']=='COMPLETE'
    assert (original/'execution.json').read_bytes()==before
    assert not (tmp_path/'outputs/runs/local/demo').exists()
