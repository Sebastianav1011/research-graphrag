"""Resource scheduling and explicit policy amendments; all inference is fake."""
from pathlib import Path
from types import SimpleNamespace
import shutil

import pytest

from autonomous_execution import lifecycle as l,store as s,resource_wait as r,policy as p
from tests.test_autonomous_execution import environment,ClientFactory,authorize
from tests.test_context_budget import corpus
from tests.test_ollama_provider import sample


def limited(e,seconds=0):
    manifest=s.read(e.directory/'manifest.json')
    manifest['resource_wait']['max_wait_seconds']=seconds
    s.write(e.directory/'manifest.json',manifest)
    e.prepared['manifest_sha256']=s.sha(e.directory/'manifest.json')


def clock(monkeypatch):
    tick=[1000];sleeps=[]
    monkeypatch.setattr(r,'time',SimpleNamespace(time=lambda:tick[0]))
    def sleep(seconds):
        sleeps.append(seconds);tick[0]+=seconds
    return tick,sleeps,sleep


def execute(e,ram,sleep,factory=None):
    return l.execute(e.root,e.run,ram=ram,sleep=sleep,client_factory=factory or ClientFactory(e.sample))


def test_sufficient_ram_does_not_wait_or_change_retry_budget(environment):
    e=environment;authorize(e);factory=ClientFactory(e.sample);sleeps=[]
    result=execute(e,lambda:1536,sleeps.append,factory)
    assert result['status']=='COMPLETE' and result['calls']==2 and not sleeps
    assert result['waiting_resources']==0


def test_temporary_pressure_waits_then_recovers_without_inference_retries(environment,monkeypatch):
    e=environment;authorize(e);_,sleeps,sleep=clock(monkeypatch)
    values=iter([500,700,2000,2000,100000]);factory=ClientFactory(e.sample)
    result=execute(e,lambda:next(values),sleep,factory)
    assert result['status']=='COMPLETE' and len(factory.calls)==2
    assert sleeps==[60,120,60]
    db=s.connect(e.directory)
    try:
        assert list(db.execute('SELECT available_mib FROM resource_samples'))[0][0]==500
        assert all(row[0]==0 for row in db.execute('SELECT rounds FROM jobs'))
        assert all(row[0]==1 for row in db.execute('SELECT attempts FROM jobs'))
    finally:db.close()
    observation=s.read(next((e.directory/'resource_wait').rglob('*.json')))
    assert observation['first_free_ram_mib']==500 and observation['required_ram_mib']==1536
    assert observation['unit']=='MiB' and observation['state']=='RECOVERED'


def test_long_pressure_keeps_recoverable_waiting_checkpoint(environment,monkeypatch):
    e=environment;limited(e,600);authorize(e);_,sleeps,sleep=clock(monkeypatch);factory=ClientFactory(e.sample)
    result=execute(e,lambda:1,sleep,factory)
    assert result['status']=='WAITING_RESOURCES' and result['worker']['state']=='FINISHED'
    assert result['blocked']==0 and result['waiting_resources']==1 and result['pending']==2
    assert not factory.calls and max(sleeps)<=300 and sum(sleeps)>=600
    db=s.connect(e.directory)
    try:
        assert db.execute('SELECT SUM(attempts) FROM jobs').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM steps').fetchone()[0]==0
    finally:db.close()


def test_explicit_resume_after_finite_wait_limit_can_recover(environment,monkeypatch):
    e=environment;limited(e,60);authorize(e);_,_,sleep=clock(monkeypatch);factory=ClientFactory(e.sample)
    assert execute(e,lambda:0,sleep,factory)['status']=='WAITING_RESOURCES'
    assert not factory.calls
    assert execute(e,lambda:100000,sleep,factory)['status']=='COMPLETE'
    assert len(factory.calls)==2


def test_restart_during_wait_preserves_pass_and_resumes_only_pending(environment,monkeypatch):
    e=environment;authorize(e);tick,_,sleep=clock(monkeypatch);factory=ClientFactory(e.sample)
    values=iter([100000,0])
    def interrupted(seconds):
        tick[0]+=seconds;raise KeyboardInterrupt()
    assert execute(e,lambda:next(values),interrupted,factory)['status']=='INTERRUPTED'
    assert len(factory.calls)==1 and s.status(e.directory)['status']=='WAITING_RESOURCES'
    path=next((e.directory/'results').rglob('*.json'));before=path.read_bytes()
    result=execute(e,lambda:100000,sleep,factory)
    assert result['status']=='COMPLETE' and len(factory.calls)==2
    assert path.read_bytes()==before


def test_resource_blocks_requeue_automatically_without_spending_recovery_rounds(environment):
    e=environment;manifest=s.read(e.directory/'manifest.json');manifest['policy']['recovery_rounds']=0
    s.write(e.directory/'manifest.json',manifest);e.prepared['manifest_sha256']=s.sha(e.directory/'manifest.json');authorize(e)
    db=s.connect(e.directory)
    try:
        db.execute("UPDATE jobs SET status='BLOCKED',error='RESOURCE_RAM_FLOOR' WHERE iid='I00'")
        db.execute("UPDATE jobs SET status='BLOCKED',error='INVALID_ASSESSMENT' WHERE iid='I01'")
    finally:db.close()
    factory=ClientFactory(e.sample);result=execute(e,lambda:100000,lambda _:None,factory)
    assert result['evaluated']==1 and result['blocked']==1 and len(factory.calls)==1
    db=s.connect(e.directory)
    try:assert db.execute("SELECT rounds FROM jobs WHERE iid='I00'").fetchone()[0]==0
    finally:db.close()


def test_measurement_error_waits_without_starting_client(environment,monkeypatch):
    e=environment;limited(e,60);authorize(e);_,_,sleep=clock(monkeypatch);factory=ClientFactory(e.sample)
    def error():raise RuntimeError('measurement unavailable')
    result=execute(e,error,sleep,factory)
    assert result['status']=='WAITING_RESOURCES' and result['resources']['free_ram_mib'] is None
    assert result['resources']['cause']=='RESOURCE_MEASUREMENT_ERROR' and not factory.calls


def test_optional_sqlite_cleanup_failure_does_not_block_indicator(environment,monkeypatch):
    import sqlite3
    from autonomous_execution.engine import Worker
    e=environment;manifest=s.read(e.directory/'manifest.json');manifest['resource_wait']['max_wait_seconds']=60
    _,_,sleep=clock(monkeypatch)
    worker=Worker(e.directory,manifest,ram=lambda:0,sleep=sleep)
    class BusyCache:
        def __init__(self,db):self.db=db
        def __getattr__(self,name):return getattr(self.db,name)
        def execute(self,sql,*args):
            if sql=='PRAGMA shrink_memory':raise sqlite3.OperationalError('cache busy')
            return self.db.execute(sql,*args)
    worker.db=BusyCache(worker.db);worker.resource_job=(next(iter(manifest['projects'])),next(iter(manifest['profiles'])))
    try:
        with pytest.raises(r.WaitPaused):worker.ram_gate()
    finally:worker.close()
    status=s.status(e.directory)
    assert status['blocked']==0 and status['status']=='WAITING_RESOURCES'
    assert 'sqlite_cache_release_unavailable' in status['resources']['cleanup']


@pytest.mark.parametrize('key,value',[('poll_seconds',0),('max_poll_seconds',10),('stable_samples',0),('max_wait_seconds',-1)])
def test_wait_policy_rejects_hot_loops_and_invalid_bounds(key,value):
    policy=r.defaults();policy[key]=value
    with pytest.raises(ValueError):r.validate(policy)


def test_windows_ram_measurement_uses_mib_without_decimal_unit_error(monkeypatch):
    if p.os.name!='nt':pytest.skip('Windows API layout')
    def measure(pointer):
        assert pointer._obj.length==64
        pointer._obj.available=1536*1048576-1
        return 1
    monkeypatch.setattr(p.ctypes.windll.kernel32,'GlobalMemoryStatusEx',measure)
    assert p.free_ram_mb()==1535


@pytest.fixture
def amendment(environment):
    e=environment
    software=Path(r.__file__).resolve().parents[2]
    target=e.root/r.SNAPSHOT;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(software/r.SNAPSHOT,target)
    (e.root/'scripts').mkdir();(e.root/'scripts/__init__.py').write_text('# reviewed runtime',encoding='utf-8')
    authorize(e)
    e.original_manifest=(e.directory/'manifest.json').read_bytes()
    e.original_auth=(e.directory/'authorization.json').read_bytes()
    return e


def test_amendment_requires_new_hash_authorization_and_preserves_original(amendment):
    e=amendment;factory=ClientFactory(e.sample)
    assert execute(e,lambda:100000,lambda _:None,factory)['status']=='COMPLETE'
    results={p:p.read_bytes() for p in (e.directory/'results').rglob('*.json')}
    excel=e.run/'resultado_indicadores.autonomous.partial.xlsx';excel.write_bytes(b'synthetic preserved workbook')
    review=r.prepare_amendment(e.root,e.run,r.defaults())
    assert review['status']=='REVIEW_REQUIRED' and review['preserved_pass']==2
    with pytest.raises(ValueError,match='autorizar'):l.verify(e.root,e.run)
    r.authorize_amendment(e.root,e.run,review['manifest_sha256'])
    assert execute(e,lambda:100000,lambda _:None,factory)['status']=='COMPLETE'
    assert len(factory.calls)==2
    assert (e.directory/'manifest.json').read_bytes()==e.original_manifest
    assert (e.directory/'authorization.json').read_bytes()==e.original_auth
    assert all(path.read_bytes()==data for path,data in results.items())
    assert excel.read_bytes()==b'synthetic preserved workbook'
    assert next((r.paths(e.run)[0].parent/'preserved_exports').glob('*.xlsx')).read_bytes()==excel.read_bytes()


def test_amendment_wrong_hash_or_changed_code_cannot_be_authorized(amendment):
    e=amendment;review=r.prepare_amendment(e.root,e.run,r.defaults())
    with pytest.raises(ValueError,match='SHA-256'):r.authorize_amendment(e.root,e.run,'0'*64)
    (e.root/'scripts/__init__.py').write_text('# changed after review',encoding='utf-8')
    with pytest.raises(ValueError,match='INTEGRITY_MISMATCH'):r.authorize_amendment(e.root,e.run,review['manifest_sha256'])
    assert not r.paths(e.run)[1].exists()


def test_amendment_preserves_original_integrity_checks(amendment):
    e=amendment
    (e.root/'run.py').write_text('# incompatible original runtime',encoding='utf-8')
    with pytest.raises(ValueError,match='INTEGRITY_MISMATCH'):r.prepare_amendment(e.root,e.run,r.defaults())
    assert (e.directory/'manifest.json').read_bytes()==e.original_manifest


def test_exact_prepare_authorize_resume_commands_use_amendment_without_real_worker(amendment,monkeypatch):
    import run as console
    e=amendment;software=Path(r.__file__).resolve().parents[2]
    s.write(e.root/r.CONFIG,s.read(software/r.CONFIG))
    monkeypatch.setattr(console,'ROOT',e.root)
    monkeypatch.setattr(e.coordinator,'configuration',lambda root,path:({},root/'data/layer1_sources',root/'outputs/runs'))
    assert console.main(['prepare','--autonomous','--run-id',e.run.name,'--policy',r.CONFIG,'--non-interactive'])==3
    path,_=r.paths(e.run)
    assert console.main(['authorize','--run-id',e.run.name,'--manifest-sha256',s.sha(path)])==0
    launched=[]
    def background(root,run,**kwargs):
        assert l.verify(root,run)['resource_wait']['version']==r.VERSION
        launched.append(run);return dict(status='STARTED',pid=0)
    monkeypatch.setattr(l,'background',background)
    assert console.main(['resume','--autonomous','--run-id',e.run.name,'--non-interactive','--through','export','--background'])==0
    assert launched==[e.run]
