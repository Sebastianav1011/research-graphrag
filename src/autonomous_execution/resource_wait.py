"""Persistent pre-dispatch RAM waits; explicit amendments for authorized runs."""
from run_paths import file_path as run_file
from copy import deepcopy
from functools import wraps
import gc
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

from . import store as s,policy as p

VERSION='RESOURCE_WAIT_V1'
CONFIG='config/autonomous_resources.json'
SNAPSHOT='src/autonomous_execution/compatibility/resource_wait_scripts_init.txt'


def validate(value):
    limits=dict(poll_seconds=(30,3600),max_poll_seconds=(30,3600),
        resume_headroom_mib=(0,4096),stable_samples=(1,5),max_wait_seconds=(0,604800))
    if not isinstance(value,dict) or set(value)!=set(limits)|{'version'} or value['version']!=VERSION:
        raise ValueError('Politica de espera desconocida')
    for key,(low,high) in limits.items():
        if type(value[key]) is not int or not low<=value[key]<=high:
            raise ValueError('Limite de espera invalido: '+key)
    if value['max_poll_seconds']<value['poll_seconds']:
        raise ValueError('Intervalos de espera incoherentes')
    return deepcopy(value)


def defaults():
    return validate(s.read(Path(__file__).resolve().parents[2]/CONFIG)['resource_wait'])


def read_db(directory):
    db=sqlite3.connect((Path(directory)/'queue.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    return db


def baseline(root,run):
    """Original data/auth/queue checks; only the reviewed initializer has moved.

    Its original bytes remain provable in SNAPSHOT. Any effective new executable
    receipt is checked separately by the explicitly authorized amendment.
    """
    from . import lifecycle as l,scope
    from scripts import pipeline_coordinator as c
    from .preparation_integrity import receipt
    root=Path(root).resolve();directory=l.folder(run);path=directory/'manifest.json';m=s.read(path)
    if m['repository_root']!=str(root) or m['run_id']!=Path(run).name or m['version']!=l.VERSION:
        raise ValueError('Manifiesto original incompatible')
    auth=s.read(directory/'authorization.json')
    if auth.get('authorized') is not True or auth.get('manifest_sha256')!=s.sha(path):
        raise ValueError('Falta autorizacion original verificable')
    p.validate(m['policy']);scope.check(root,m['source_inventory']);c.check(root,run)
    for name,digest in m['files'].items():receipt(root,name,digest,origin=str(path))
    for name,digest in m['code'].items():
        if name=='scripts/__init__.py' and s.sha(root/name)!=digest:
            receipt(root,SNAPSHOT,digest,origin=str(path))
        else:receipt(root,name,digest,origin=str(path))
    db=read_db(directory)
    try:
        jobs=[dict(r) for r in db.execute('SELECT * FROM jobs')]
        if len(jobs)!=len(m['projects'])*len(m['profiles']):raise ValueError('Cobertura original modificada')
        for job in jobs:
            if job['pid'] not in m['projects'] or job['iid'] not in m['profiles']:
                raise ValueError('Checkpoint fuera del alcance')
            if job['status']=='PASS':
                target=(directory/job['result_path']).resolve()
                if not target.is_relative_to(directory.resolve()) or s.sha(target)!=job['result_hash']:
                    raise ValueError('Resultado PASS modificado')
    finally:db.close()
    return m


def paths(run):
    base=Path(run)/'autonomous/resource_recovery'
    return base/'manifest.json',base/'authorization.json'


def active_worker(directory):
    path=run_file(Path(directory), 'worker.json')
    if not path.exists():return False
    worker=s.read(path);current=s.process_info(worker['pid'])
    return bool(current['alive'] and worker.get('state')!='FINISHED' and
        (worker.get('creation') is None or current['creation']==worker['creation']))


def verify_passes_offline(root,run,m):
    """Validate copied receipts; never open the real queue for writing."""
    from . import lifecycle as l,engine
    directory=l.folder(run)
    output=Path(root)/'outputs';output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='resource-pass-check-',dir=output) as temp:
        target=Path(temp)
        assert target.resolve().is_relative_to(output.resolve())
        for name in ('inputs','results','attempts'):
            if (directory/name).exists():shutil.copytree(directory/name,target/name)
        for name in ('manifest.json','candidate_index.sqlite','graph.binding.json'):
            if (directory/name).exists():shutil.copyfile(directory/name,target/name)
        source=read_db(directory);copy=sqlite3.connect(target/'queue.sqlite')
        try:source.backup(copy)
        finally:source.close();copy.close()
        worker=engine.Worker(target,m)
        try:
            count=0
            for job in worker.db.execute("SELECT * FROM jobs WHERE status='PASS'"):
                job=dict(job)
                if not worker.adopt(job,worker.load_project(job['pid']),commit=False):
                    raise ValueError('PASS no recuperable')
                count+=1
        finally:worker.close()
    return count


def prepare_amendment(root,run,value):
    from . import lifecycle as l
    from .preparation_integrity import runtime_files,receipt
    from scripts.pipeline_coordinator import lock
    wait=validate(value)
    with lock(Path(run).parent),lock(Path(run)):
        if active_worker(l.folder(run)):raise ValueError('El worker debe haber terminado antes de preparar la recuperacion')
        m=baseline(root,run)
        if m['policy']['workers']!=1:raise ValueError('Espera de recursos requiere una inferencia a la vez')
        path,auth=paths(run)
        if path.exists():
            if auth.exists():
                effective(root,run)
                return dict(status='AUTHORIZED',manifest_sha256=s.sha(path),manifest=str(path))
            previous=s.read(path)
            if previous['resource_wait']==wait and all((Path(root)/n).is_file() and s.sha(Path(root)/n)==v for n,v in previous['code'].items()):
                return dict(status='REVIEW_REQUIRED',manifest_sha256=s.sha(path),manifest=str(path))
            archive=path.parent/('review_'+s.sha(path)+'.json')
            if not archive.exists():shutil.copyfile(path,archive)
        count=verify_passes_offline(root,run,m)
        db=read_db(l.folder(run))
        try:passes={r['result_path']:r['result_hash'] for r in db.execute("SELECT result_path,result_hash FROM jobs WHERE status='PASS'")}
        finally:db.close()
        exports={}
        for source in Path(run).glob('*.partial.xlsx'):
            target=path.parent/'preserved_exports'/source.name
            if target.exists() and s.sha(target)!=s.sha(source):
                raise ValueError('Exportacion original archivada distinta; conservar ambas versiones')
            if not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            exports[target.relative_to(root).as_posix()]=s.sha(target)
        code=runtime_files(root)
        for n,v in code.items():receipt(root,n,v,origin='resource_recovery preparation')
        amendment=dict(version=VERSION,created_at=s.now(),run_id=Path(run).name,
            original_manifest_sha256=s.sha(l.folder(run)/'manifest.json'),
            original_authorization_sha256=s.sha(l.folder(run)/'authorization.json'),
            resource_wait=wait,code=code,original_code_snapshot=dict(path=SNAPSHOT,sha256=s.sha(Path(root)/SNAPSHOT)),
            preserved_pass=passes,preserved_exports=exports,
            verified_pass=count,policy_changes=['WAIT_BEFORE_RAM_DISPATCH','REQUEUE_PRE_DISPATCH_RAM_BLOCKS'],
            unchanged=['models','prompts','schemas','evidence_validation','confidence','min_free_ram_mb','workers','keep_alive'])
        s.write(path,amendment)
    return dict(status='REVIEW_REQUIRED',manifest=str(path),manifest_sha256=s.sha(path),preserved_pass=count,
        original_manifest_unchanged=True,resource_wait=wait,inference_calls=0)


def effective(root,run,require_authorization=True):
    from . import lifecycle as l
    from .preparation_integrity import receipt
    path,auth=paths(run);a=s.read(path)
    if a['version']!=VERSION or a['run_id']!=Path(run).name:raise ValueError('Ampliacion de recursos incompatible')
    validate(a['resource_wait'])
    receipt(root,l.folder(run)/'manifest.json',a['original_manifest_sha256'],origin=str(path))
    receipt(root,l.folder(run)/'authorization.json',a['original_authorization_sha256'],origin=str(path))
    receipt(root,a['original_code_snapshot']['path'],a['original_code_snapshot']['sha256'],origin=str(path))
    for name,digest in a['code'].items():receipt(root,name,digest,origin=str(path))
    for name,digest in a.get('preserved_exports',{}).items():receipt(root,name,digest,origin=str(path))
    for name,digest in a.get('preserved_pass',{}).items():receipt(root,l.folder(run)/name,digest,origin=str(path))
    if require_authorization:
        if not auth.exists() or s.read(auth).get('manifest_sha256')!=s.sha(path) or s.read(auth).get('authorized') is not True:
            raise ValueError('Revisar y autorizar la ampliacion RESOURCE_WAIT_V1 antes de reanudar')
    m=baseline(root,run)
    return m|dict(resource_wait=a['resource_wait'],resource_amendment_sha256=s.sha(path))


def authorize_amendment(root,run,digest):
    from scripts.pipeline_coordinator import lock
    with lock(Path(run).parent),lock(Path(run)):
        from . import lifecycle as l
        if active_worker(l.folder(run)):raise ValueError('Esperar a que termine el worker antes de autorizar la ampliacion')
        path,auth=paths(run)
        if s.sha(path)!=digest:raise ValueError('SHA-256 revisado no coincide con ampliacion')
        effective(root,run,require_authorization=False)
        if not auth.exists():s.write(auth,dict(authorized=True,manifest_sha256=digest,authorized_at=s.now()))
        elif s.read(auth).get('manifest_sha256')!=digest:raise ValueError('Autorizacion de ampliacion incompatible')
    return dict(status='AUTHORIZED',manifest_sha256=digest,inference_calls=0)


class WaitPaused(BaseException):
    """Scheduling pause, outside semantic/transport error handlers."""


def worker_class(base):
    class ResourceWorker(base):
        def __init__(self,directory,manifest,stop=None,client_factory=None,ram=None,sleep=None):
            self.wait_policy=validate(manifest['resource_wait']) if 'resource_wait' in manifest else None
            if self.wait_policy and manifest['policy']['workers']!=1:
                raise ValueError('Espera de recursos requiere un worker')
            self.raw_ram=ram or p.free_ram_mb
            self.wait_sleep=sleep
            self.clock=time.time
            self.resource_job=None
            super().__init__(directory,manifest,stop,client_factory,self.ram_gate if self.wait_policy else ram,sleep)
            if self.wait_policy:
                self.db.execute('CREATE TABLE IF NOT EXISTS resource_samples '
                    '(seq INTEGER PRIMARY KEY,at TEXT,pid TEXT,iid TEXT,available_mib INTEGER,required_mib INTEGER,state TEXT,next_seconds INTEGER)')

        def _step(self,project,profile,*args,**kwargs):
            self.resource_job=(project['project_id'],profile['indicator_id'])
            return super()._step(project,profile,*args,**kwargs)

        def ram_gate(self):
            pid,iid=self.resource_job;floor=self.policy['min_free_ram_mb'];policy=self.wait_policy
            file=self.directory/'resource_wait'/pid/(iid+'.json')
            previous=s.read(file) if file.exists() else {}
            waiting=previous.get('state')=='WAITING_RESOURCES'
            started=previous.get('started_epoch',self.clock());stable=0;failures=0
            window_started=self.clock()
            first_at=previous.get('first_detected_at') if waiting else None
            first_available=previous.get('first_free_ram_mib') if waiting else None
            cleanup=None
            while True:
                if (run_file(self.directory.parents[1], 'stop.request.json')).exists():
                    self.stop.set();raise WaitPaused()
                measured=s.now()
                try:
                    available=self.raw_ram()
                    if type(available) is not int or available<0:raise ValueError('RAM invalid')
                    cause='RESOURCE_RAM_FLOOR'
                except (OSError,RuntimeError,ValueError):
                    available=None;cause='RESOURCE_MEASUREMENT_ERROR'
                if not waiting and available is not None and available>=floor:return available
                if not waiting:
                    waiting=True;started=self.clock()
                    first_at=measured;first_available=available
                if cleanup is None:
                    gc.collect();cleanup=['python_gc']
                    try:
                        if not self.db.in_transaction:
                            self.db.execute('PRAGMA shrink_memory');cleanup.append('sqlite_shrink_memory')
                    except sqlite3.Error:
                        cleanup.append('sqlite_cache_release_unavailable')
                stable=stable+1 if available is not None and available>=floor+policy['resume_headroom_mib'] else 0
                recovered=stable>=policy['stable_samples']
                interval=policy['poll_seconds'] if stable else min(policy['max_poll_seconds'],policy['poll_seconds']*2**min(failures,12))
                observation=dict(state='RECOVERED' if recovered else 'WAITING_RESOURCES',cause=cause,
                    at=measured,started_epoch=started,free_ram_mib=available,required_ram_mib=floor,
                    first_detected_at=first_at,first_free_ram_mib=first_available,unit='MiB',
                    cleanup=cleanup,ollama_release='existing_keep_alive',
                    resume_ram_mib=floor+policy['resume_headroom_mib'],next_check_seconds=0 if recovered else interval,
                    stable_samples=stable,elapsed_seconds=max(0,self.clock()-started),pid=pid,iid=iid,
                    wait_window_elapsed_seconds=max(0,self.clock()-window_started),
                    manifest_sha256=s.sha(self.directory/'manifest.json'),
                    amendment_sha256=self.manifest.get('resource_amendment_sha256'))
                s.write(file,observation)
                with s.transaction(self.db):
                    self.db.execute('UPDATE jobs SET status=?,error=?,updated=? WHERE pid=? AND iid=?',
                        ('RUNNING' if recovered else 'WAITING_RESOURCES',None if recovered else cause,measured,pid,iid))
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES('resource_wait',?)",(__import__('json').dumps(observation),))
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES('stage',?)",('evaluation' if recovered else 'waiting_resources',))
                    self.db.execute('INSERT INTO resource_samples(at,pid,iid,available_mib,required_mib,state,next_seconds) VALUES(?,?,?,?,?,?,?)',
                        (measured,pid,iid,available,floor,observation['state'],observation['next_check_seconds']))
                    s.event(self.db,'resources','RAM_RECOVERED' if recovered else cause,pid,iid)
                if recovered:return available
                if self.stop.is_set() or policy['max_wait_seconds'] and observation['wait_window_elapsed_seconds']>=policy['max_wait_seconds']:
                    self.stop.set();raise WaitPaused()
                if self.wait_sleep:self.wait_sleep(interval)
                elif self.stop.wait(interval):raise WaitPaused()
                failures+=not bool(stable)

        def loop(self):
            if self.wait_policy:
                with s.transaction(self.db):
                    count=self.db.execute("UPDATE jobs SET status='PENDING',error=NULL,updated=? WHERE status='WAITING_RESOURCES' OR (status='BLOCKED' AND error='RESOURCE_RAM_FLOOR')",(s.now(),)).rowcount
                    if count:s.event(self.db,'resources','RESOURCE_JOBS_REQUEUED')
            try:return super().loop()
            except WaitPaused:return
    return ResourceWorker


def install():
    from . import lifecycle as l,engine,cli,prepare_menu
    if getattr(l.verify,'_resource_wait',False):return
    original_verify=l.verify;original_prepare=l.prepare;original_status=s.status;original_dispatch=cli.dispatch;original_review=prepare_menu.review;original_progress=l.progress
    cls=worker_class(engine.Worker);engine.Worker=cls;l.Worker=cls
    @wraps(original_verify)
    def verify(root,run,**kwargs):
        path,auth=paths(run)
        if path.exists():return effective(root,run)  # Pending amendments never bypass approval.
        manifest=original_verify(root,run,**kwargs)
        if 'resource_wait' in manifest:
            validate(manifest['resource_wait'])
            if manifest['policy']['workers']!=1:raise ValueError('Espera de recursos requiere un worker')
        return manifest
    @wraps(original_prepare)
    def prepare(root,run,policy,**kwargs):
        wait=defaults()
        if isinstance(policy,dict) and 'extends' in policy:
            if set(policy)!={'extends','resource_wait'} or policy['extends']!='config/autonomous.json':
                raise ValueError('Extension de politica no admitida')
            wait=validate(policy['resource_wait']);policy=s.read(Path(root)/policy['extends'])
        existed=(l.folder(run)/'manifest.json').exists()
        result=original_prepare(root,run,policy,**kwargs)
        if not existed:
            path=l.folder(run)/'manifest.json';manifest=s.read(path)
            if manifest['policy']['workers']==1:
                manifest['resource_wait']=wait;s.write(path,manifest)
                # Imported historical PASS receipts bind to the final reviewed hash.
                db=s.connect(l.folder(run))
                try:
                    for row in db.execute("SELECT pid,iid,result_path FROM jobs WHERE status='PASS'").fetchall():
                        f=l.folder(run)/row['result_path'];bundle=s.read(f);bundle['manifest_sha256']=s.sha(path);s.write(f,bundle)
                        db.execute('UPDATE jobs SET result_hash=? WHERE pid=? AND iid=?',(s.sha(f),row['pid'],row['iid']))
                finally:db.close()
                result=result|dict(manifest_sha256=s.sha(path))
        return result
    @wraps(original_status)
    def status(directory):
        result=original_status(directory);db=read_db(directory)
        try:row=db.execute("SELECT value FROM meta WHERE key='resource_wait'").fetchone()
        finally:db.close()
        waiting=result['counts'].get('WAITING_RESOURCES',0)
        result['waiting_resources']=waiting
        if row:result['resources']=__import__('json').loads(row[0])
        if waiting:result.update(status='WAITING_RESOURCES',stage='waiting_resources',pending=result['pending']+waiting)
        return result
    @wraps(original_dispatch)
    def dispatch(root,args,coordinator):
        if args.command=='prepare' and args.autonomous and args.run_id and args.policy==CONFIG:
            if any((args.authorize_llm,args.approve_build,args.background,args.partial,args.acknowledge_uncertain,args.manifest_sha256,args.source,args.input_file,args.delivery,args.projects,args.project_id)):
                raise ValueError('La ampliacion conserva el alcance; no aceptar nuevos selectores o permisos')
            _,_,runs=coordinator.configuration(root,args.config);run=coordinator.find_run(root,runs,args.run_id)
            if (l.folder(run)/'manifest.json').exists():
                return prepare_amendment(root,run,s.read(Path(root)/CONFIG)['resource_wait'])
        if args.command=='authorize' and args.run_id:
            _,_,runs=coordinator.configuration(root,args.config);run=coordinator.find_run(root,runs,args.run_id)
            path,_=paths(run)
            if path.exists() and args.manifest_sha256==s.sha(path):
                if any((args.authorize_llm,args.approve_build,args.background,args.partial,args.acknowledge_uncertain,args.source,args.input_file,args.delivery,args.projects,args.project_id)):
                    raise ValueError('Autorizar solo el hash revisado, sin cambiar alcance')
                return authorize_amendment(root,run,args.manifest_sha256)
        return original_dispatch(root,args,coordinator)
    @wraps(original_review)
    def review(manifest,*args):
        result=original_review(manifest,*args)
        if 'resource_wait' in manifest:
            wait=manifest['resource_wait'];result+=f"RAM insuficiente: espera automatica persistente; comprobaciones cada {wait['poll_seconds']}-{wait['max_poll_seconds']} s; sin inferencias hasta recuperar recursos.\n"
        return result
    @wraps(original_progress)
    def progress(root,run):
        path,auth=paths(run)
        if not path.exists():return original_progress(root,run)
        m=effective(root,run,require_authorization=auth.exists())
        result=s.status(l.folder(run))|dict(run_id=Path(run).name,
            manifest_sha256=s.sha(l.folder(run)/'manifest.json'),resource_manifest_sha256=s.sha(path),
            authorized=auth.exists(),imported_pass=m['imported_pass'],integrity='ORIGINAL_AND_RESOURCE_AMENDMENT_VERIFIED')
        if not auth.exists():result['status']='REVIEW_REQUIRED_RESOURCE_POLICY'
        return result
    verify._resource_wait=True
    l.verify=verify;l.prepare=prepare;l.progress=progress;s.status=status;cli.dispatch=dispatch;prepare_menu.review=review
