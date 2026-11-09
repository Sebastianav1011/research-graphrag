"""Conservative run migration, immutable result snapshots and 72-hour retention.

Never imports a model or evaluator. Deletion requires a native closed receipt,
no live/uncertain/pending operation, and a verified, durable result snapshot.
"""
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

from run_paths import BUCKETS,FILES,bucket,file_path,list_runs,provider_of,read_json,repo_of,structured

HOURS=72


def now():return datetime.now(timezone.utc)


def stamp():return now().isoformat()


def save(path,value):
    from autonomous_execution.store import write
    write(path,value)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def parse_time(value):
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo is not None else None
    except (AttributeError,TypeError,ValueError):return None


def files_in(run):
    """No junctions or links may be followed, archived or recursively removed."""
    run=Path(run)
    if run.is_symlink() or run.is_junction():raise ValueError('LINK_OR_JUNCTION')
    files=[]
    for base,dirs,names in os.walk(run,followlinks=False):
        for name in [*dirs,*names]:
            path=Path(base)/name
            if path.is_symlink() or path.is_junction():raise ValueError('LINK_OR_JUNCTION')
        files.extend(Path(base)/name for name in names)
    return files


def readonly_db(path,query,consistent=False):
    if not consistent and any(p.exists() and p.stat().st_size for p in (Path(str(path)+'-wal'),Path(str(path)+'-journal'))):
        raise ValueError('SQLITE_PENDING_JOURNAL')
    db=sqlite3.connect(Path(path).resolve().as_uri()+('?mode=ro' if consistent else '?mode=ro&immutable=1'),uri=True)
    try:return db.execute(query).fetchall()
    finally:db.close()


def activity(run):
    from autonomous_execution.store import process_info
    reasons=[]
    for path in [file_path(run,'worker.json'),Path(run)/'autonomous/main/worker.json',Path(run)/'estado/process.json']:
        if not path.exists():continue
        data=read_json(path)
        if type(data.get('pid')) is not int:
            reasons.append('WORKER_IDENTITY_UNKNOWN');continue
        current=process_info(data['pid'])
        if current['alive'] is None:reasons.append('PROCESS_UNVERIFIABLE')
        elif current['alive'] and (data.get('creation') is None or current['creation']==data['creation']):
            reasons.append('ACTIVE_PROCESS')
    # A graph worker can hold this without the coordinator's global lock.
    path=file_path(run,'.execution.lock')
    if path.exists():
        try:
            with path.open('r+b') as stream:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                    stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        except OSError:reasons.append('ACTIVE_LOCK')
    return reasons


def sqlite_idle(run):
    """Probe Windows handles without opening/mutating SQLite or discarding WAL."""
    databases=[p for p in files_in(run) if p.name in ('queue.sqlite','api-ledger.sqlite')]
    if os.name!='nt':
        return not any(Path(str(p)+'-wal').exists() and Path(str(p)+'-wal').stat().st_size for p in databases)
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    for path in databases:
        handle=kernel.CreateFileW(str(path),0x80000000,0,None,3,0x80,None)
        if handle==wintypes.HANDLE(-1).value:return False
        kernel.CloseHandle(handle)
    return True


def pending(run):
    reasons=[];run=Path(run)
    for queue in run.rglob('queue.sqlite'):
        rows=readonly_db(queue,"SELECT status,COUNT(*) FROM jobs GROUP BY status")
        if any(state!='PASS' and count for state,count in rows):reasons.append('RECOVERABLE_OR_UNCERTAIN_JOBS')
        steps=readonly_db(queue,"SELECT COUNT(*) FROM steps WHERE status IN ('RUNNING','UNCERTAIN')")
        if steps[0][0]:reasons.append('PENDING_STEPS')
    for ledger in run.rglob('api-ledger.sqlite'):
        rows=readonly_db(ledger,"SELECT COUNT(*) FROM requests WHERE state IN ('IN_FLIGHT','UNCERTAIN')")
        if rows[0][0]:reasons.append('UNCERTAIN_API_REQUEST')
    for claim in run.rglob('dispatch.claim.json'):
        # A claimed attempt must have its persisted native transport receipt.
        if not list(claim.parent.glob('transport/**/call.json')):reasons.append('UNRESOLVED_DISPATCH');break
    for dispatch in run.rglob('api.dispatch.json'):
        receipt=read_json(dispatch.parent/'call.json')
        if not receipt or 'UNCERTAIN' in str(receipt.get('exit_status','')):
            reasons.append('UNCERTAIN_API_DISPATCH');break
    if list(run.rglob('*.pending')) or list(run.rglob('*.part')):reasons.append('PENDING_FILES')
    return reasons


def export_files(run):
    run=Path(run);result={}
    for path in files_in(run):
        rel=path.relative_to(run).as_posix()
        if rel.startswith('resultados/') and path.suffix.lower() in ('.csv','.json','.md','.xlsx'):
            result[rel.removeprefix('resultados/')]=path
        elif path.parent==run and path.suffix.lower()=='.xlsx':result[path.name]=path
        elif rel in ('metrics.csv','metrics.json','corrected/metrics.csv','corrected/metrics.json'):
            result['performance/legacy_'+rel.replace('/','_')]=path
        elif rel.startswith('autonomous/main/results/') and path.suffix=='.json':
            result['evidencias/'+rel.removeprefix('autonomous/main/results/')]=path
        elif rel.startswith('corrected/results/') and path.suffix=='.json':result['evidencias/legacy/'+rel.removeprefix('corrected/results/')]=path
    if not any(name in result for name in ('indicadores.csv','indicadores_territorios.csv')) and not any(p.suffix=='.xlsx' for p in result.values()) and not any(name.startswith('performance/') for name in result):
        return {}
    for name in ('execution.json','run.json','raw_manifest.json','prepared_hashes.json','model.binding.json',
            'runtime.manifest.json','project_states.json','export.json','evidence_lineage.json','discovery.json',
            'estado/run.authorization.json'):
        path=file_path(run,name)
        if path.is_file():result['trazabilidad/'+name]=path
    for name in ('autonomous/main/manifest.json','autonomous/main/authorization.json','manifest.json','authorization.json','corrected/manifest.json'):
        path=run/name
        if path.is_file():result['trazabilidad/autonomous/'+name]=path
    return result


def metadata(run,status=None):
    execution=read_json(file_path(run,'execution.json'));runtime=read_json(file_path(run,'runtime.manifest.json'))
    manifest=read_json(Path(run)/'autonomous/main/manifest.json') or read_json(Path(run)/'manifest.json')
    progress=read_json(file_path(run,'progress.json'));worker=read_json(Path(run)/'autonomous/main/worker.json')
    llm=execution.get('llm') or manifest.get('llm') or read_json(file_path(run,'model.binding.json')).get('llm',{})
    groups=runtime.get('project_states') or read_json(file_path(run,'project_states.json'))
    evaluations=None
    queue=Path(run)/'autonomous/main/queue.sqlite'
    if queue.exists():
        grouped=readonly_db(queue,'SELECT p.siap,j.status,COUNT(*) FROM projects p LEFT JOIN jobs j ON p.pid=j.pid GROUP BY p.siap,j.status',consistent=True)
        by_project={};evaluations=0
        for pid,state,count in grouped:
            by_project.setdefault(pid,{})[state]=count
            if state=='PASS':evaluations+=count
        groups={key:[] for key in ('complete','partial','blocked','pending')}
        for pid,states in by_project.items():
            category='complete' if set(states)=={'PASS'} else 'partial' if states.get('PASS') else 'blocked' if states.get('BLOCKED') or states.get('UNCERTAIN') else 'pending'
            groups[category].append(pid)
    projects=manifest.get('projects',{})
    selected=execution.get('project_ids') or ([p.get('siap_id',pid) for pid,p in projects.items()] if isinstance(projects,dict) else
        [p.get('siap_id') or p.get('project_id') for p in projects if isinstance(p,dict)])
    if not groups:groups=dict(complete=[],partial=[],blocked=[],pending=selected)
    model=llm.get('model')
    consumption=read_json(Path(run)/'resultados/performance/provider.json')
    native_export=read_json(file_path(run,'export.json'))
    effective=status or native_export.get('status') or progress.get('status') or 'UNKNOWN'
    if effective=='COMPLETE' and any(groups.get(k) for k in ('partial','blocked','pending')):effective='PARTIAL'
    return dict(run_id=Path(run).name,provider=provider_of(run),model=model,status=effective,
        started_at=worker.get('started_at') or read_json(file_path(run,'run.json')).get('started_at'),
        finished_at=worker.get('finished_at') or progress.get('updated_at'),
        contract=execution.get('evaluation_contract') or manifest.get('evaluation_contract'),
        selected_project_ids=selected,project_states=groups,project_counts={k:len(v) for k,v in groups.items()},
        evaluated_indicators=evaluations,consumption=consumption)


def verify_archive(directory):
    directory=Path(directory);meta=read_json(directory/'metadata.json')
    if not meta.get('files'):raise ValueError('ARCHIVE_WITHOUT_FILES')
    for name,checksum in meta['files'].items():
        path=(directory/name).resolve()
        if not path.is_relative_to(directory.resolve()) or path.is_symlink() or not path.is_file() or sha(path)!=checksum:
            raise ValueError('ARCHIVE_INTEGRITY_FAILED')
    payload={key:value for key,value in meta.items() if key not in ('snapshot_id','archived_at','files','source_run','retention')}
    fingerprint=hashlib.sha256(json.dumps(dict(files=meta['files'],metadata=payload),sort_keys=True).encode()).hexdigest()
    if fingerprint!=meta.get('snapshot_id'):raise ValueError('ARCHIVE_METADATA_CHANGED')
    return meta


def archive(root,run,status=None):
    """Snapshots never overwrite: later exports are immutable revisiones/<hash>."""
    root=Path(root).resolve();run=Path(run).resolve()
    if not run.is_relative_to(root/'outputs/runs'):raise ValueError('Archive source outside runs')
    sources=export_files(run)
    if not sources:return dict(status='NO_EXPORTED_RESULTS')
    checksums={name:sha(path) for name,path in sources.items()};meta=metadata(run,status)
    identity=hashlib.sha256(json.dumps(dict(files=checksums,metadata=meta),sort_keys=True).encode()).hexdigest()
    base=root/'outputs/historico'/bucket(meta['provider'])/run.name
    target=base if not base.exists() else base if read_json(base/'metadata.json').get('snapshot_id')==identity else base/'revisiones'/identity
    if target.exists():
        old=verify_archive(target)
        if old.get('snapshot_id')!=identity:raise ValueError('Archive collision')
        return dict(status='VERIFIED',path=str(target),snapshot_id=identity)
    stage=base.parent/('.archive-'+uuid.uuid4().hex);stage.mkdir(parents=True)
    try:
        for name,path in sources.items():
            output=stage/name;output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,output)
            if sha(output)!=checksums[name] or sha(path)!=checksums[name]:raise ValueError('Export changed during archive')
            with output.open('r+b') as stream:os.fsync(stream.fileno())
        meta.update(snapshot_id=identity,archived_at=stamp(),files=checksums,
            source_run=run.relative_to(root).as_posix(),retention='PERMANENT')
        save(stage/'metadata.json',meta);verify_archive(stage)
        target.parent.mkdir(parents=True,exist_ok=True)
        stage.rename(target)
    except BaseException:
        # Keep a failed staging snapshot for diagnosis, never remove source results.
        raise
    save(base/'latest.json',dict(path=target.relative_to(base).as_posix(),snapshot_id=identity))
    return dict(status='ARCHIVED',path=str(target),snapshot_id=identity)


def archive_export(root,run,result):
    try:receipt=archive(root,run,result.get('status'))
    except (ValueError,OSError,sqlite3.Error) as exc:
        result['historico']=dict(status='RETAINED_UNARCHIVED',reason=type(exc).__name__,note='Conservar el run y reintentar export; no es elegible para limpieza')
        return result
    if receipt['status']!='NO_EXPORTED_RESULTS':
        result['historico']=receipt
        meta=verify_archive(receipt['path'])
        try:clear=not pending(run)
        except (ValueError,OSError,sqlite3.Error):clear=False
        if meta['status']=='COMPLETE' and clear:
            save(Path(run)/'estado/closed.json',dict(version=1,closed_at=stamp(),status='COMPLETE',
                archive=receipt,snapshot_files=meta['files']))
    return result


def reopen(run):
    """Execution locks must be held before invalidating an old cleanup receipt."""
    path=Path(run)/'estado/closed.json'
    if path.exists():
        previous=read_json(path);previous.update(status='OPEN',reopened_at=stamp());save(path,previous)


def decision(root,run,at=None):
    run=Path(run).resolve();root=Path(root).resolve();at=at or now()
    if not run.is_relative_to(root/'outputs/runs') or run.parent.name not in BUCKETS and run.parent!=root/'outputs/runs':
        raise ValueError('Cleanup target outside runs')
    row=dict(run_id=run.name,path=str(run),size_bytes=0,decision='RETAIN',reasons=[])
    try:
        files=files_in(run);row['size_bytes']=sum(p.stat().st_size for p in files)
        provider=provider_of(run);row['provider']=provider
        if provider not in ('ollama','openai'):row['reasons'].append('PROVIDER_UNKNOWN')
        row['reasons']+=activity(run)+pending(run)
        closed=read_json(run/'estado/closed.json')
        if closed.get('status')!='COMPLETE':row['reasons'].append('NOT_DEFINITIVELY_CLOSED')
        ended=parse_time(closed.get('closed_at'))
        if ended is None or ended>at:row['reasons'].append('AGE_UNVERIFIABLE')
        elif at-ended<=timedelta(hours=HOURS):row['reasons'].append('WITHIN_72_HOURS')
        if closed.get('archive'):
            archived=Path(closed['archive']['path']).resolve()
            if not archived.is_relative_to(root/'outputs/historico'):raise ValueError('Invalid archive locator')
            meta=verify_archive(archived)
            current={name:sha(path) for name,path in export_files(run).items()}
            if current!=meta['files'] or current!=closed.get('snapshot_files') or meta['status']!='COMPLETE':
                row['reasons'].append('ARCHIVE_NOT_CURRENT_OR_COMPLETE')
        else:row['reasons'].append('NO_VERIFIED_ARCHIVE')
        if not row['reasons']:row['decision']='DELETE_SAFE'
    except (ValueError,OSError,sqlite3.Error,KeyError,TypeError) as exc:
        row['reasons'].append('UNVERIFIABLE_'+type(exc).__name__)
        row['detail']=str(exc)
    return row


def cleanup(root,apply=False,confirm=None,automatic=False):
    from scripts.pipeline_coordinator import lock
    root=Path(root).resolve();runs=root/'outputs/runs'
    with lock(runs):
        rows=[decision(root,p) for p in list_runs(root) if p.is_relative_to(runs)]
        candidates=[r for r in rows if r['decision']=='DELETE_SAFE']
        if apply and candidates and not automatic:
            if confirm is None or not confirm(candidates):return dict(status='CANCELLED',runs=rows,deleted=0,recovered_bytes=0)
        deleted=[]
        if apply:
            for previous in candidates:
                path=Path(previous['path']).resolve()
                current=decision(root,path)
                if current['decision']!='DELETE_SAFE':continue
                event=runs/'.storage-events'/('delete-'+uuid.uuid4().hex+'.json')
                # Absolute boundary checked again immediately before recursive delete.
                if path==runs or not path.is_relative_to(runs) or path.parent.name not in BUCKETS:continue
                save(event,dict(operation='DELETE',state='VERIFIED_BEFORE_DELETE',at=stamp(),**current))
                shutil.rmtree(path)
                save(event,dict(operation='DELETE',state='DELETED',at=stamp(),**current));deleted.append(current)
        result=dict(status='COMPLETE' if apply else 'DRY_RUN',runs=rows,deleted=len(deleted),
            recovered_bytes=sum(r['size_bytes'] for r in deleted),retention_hours=HOURS)
        if apply:save(runs/'.storage-events'/('cleanup-'+uuid.uuid4().hex+'.json'),result)
        return result


def migrate(root):
    """Journal every move; aliases preserve old bytes and locators after interruption."""
    from scripts.pipeline_coordinator import lock
    root=Path(root).resolve();runs=root/'outputs/runs';events=[]
    with lock(runs):
        aliases=read_json(runs/'.relocations.json',dict(prefixes={}))
        # Resume interrupted moves first, then discover remaining flat directories.
        journals=list((runs/'.storage-events').glob('migrate-*.json'))
        work=[read_json(p) for p in journals if read_json(p).get('state')=='PLANNED']
        seen={item['source'] for item in work}
        for source in list_runs(root):
            if source.parent!=runs or str(source) in seen:continue
            if activity(source):events.append(dict(run_id=source.name,state='RETAINED',reason='ACTIVE_OR_UNVERIFIABLE_PROCESS'));continue
            try:
                files=files_in(source);provider=provider_of(source)
                if not sqlite_idle(source):raise ValueError('SQLITE_IN_USE_OR_UNVERIFIABLE')
                if provider not in (None,'ollama','openai'):raise ValueError('UNSUPPORTED_KNOWN_PROVIDER')
                target=runs/bucket(provider)/source.name
                if target.exists():raise ValueError('DESTINATION_COLLISION')
                entry=dict(operation='MIGRATE',state='PLANNED',source=str(source),target=str(target),provider=provider,
                    inventory={p.relative_to(source).as_posix():p.stat().st_size for p in files},
                    metadata_hashes={p.name:sha(p) for p in files if p.parent==source and p.suffix=='.json'},
                    journal=str(runs/'.storage-events'/('migrate-'+uuid.uuid4().hex+'.json')))
                save(entry['journal'],entry);work.append(entry)
            except (ValueError,OSError) as exc:events.append(dict(run_id=source.name,state='RETAINED',reason=str(exc)))
        for entry in work:
            source=Path(entry['source']).resolve();target=Path(entry['target']).resolve()
            if source.parent!=runs or target.parent.parent!=runs or target.parent.name not in BUCKETS:
                raise ValueError('Migration journal outside runs')
            if source.exists() and target.exists():raise ValueError('Migration collision; nothing overwritten')
            aliases['prefixes'][source.relative_to(root).as_posix()]=target.relative_to(root).as_posix()
            save(runs/'.relocations.json',aliases)
            if source.exists():
                target.parent.mkdir(parents=True,exist_ok=True);source.rename(target)
            if not target.is_dir():raise ValueError('Migration lost its source; manual recovery required')
            for old,new in FILES.items():
                before=target/old;after=target/new
                if before.exists():
                    if after.exists():raise ValueError('Internal migration collision')
                    after.parent.mkdir(parents=True,exist_ok=True);before.rename(after)
            expected={FILES.get(name,name):size for name,size in entry['inventory'].items()}
            actual={p.relative_to(target).as_posix():p.stat().st_size for p in files_in(target)}
            if actual!=expected:raise ValueError('Migration inventory mismatch; checkpoints retained')
            for name,checksum in entry['metadata_hashes'].items():
                if sha(file_path(target,name))!=checksum:raise ValueError('Migration changed metadata bytes')
            entry['state']='MIGRATED';entry['finished_at']=stamp();save(entry['journal'],entry)
            events.append(dict(run_id=target.name,provider=entry['provider'],state='MIGRATED',source=str(source),target=str(target)))
            try:
                result=archive(root,target)
                if result['status']!='NO_EXPORTED_RESULTS':events[-1]['archive']=result
            except (ValueError,OSError,sqlite3.Error) as exc:events[-1]['archive_retained_reason']=type(exc).__name__
        result=dict(status='COMPLETE',events=events,migrated=sum(r['state']=='MIGRATED' for r in events),deleted=0,recovered_bytes=0)
        save(runs/'.storage-events'/('migration-summary-'+uuid.uuid4().hex+'.json'),result)
        return result


def restore(root,run_id,provider=None):
    """Reverse an untouched migration for use with its exact original runtime."""
    from scripts.pipeline_coordinator import lock
    root=Path(root).resolve();runs=root/'outputs/runs'
    with lock(runs):
        entries=[read_json(p) for p in (runs/'.storage-events').glob('migrate-*.json')]
        entries=[e for e in entries if Path(e['target']).name==run_id and e['state'] in ('MIGRATED','RESTORING')
            and (provider is None or e['provider']==provider)]
        if len(entries)!=1:raise ValueError('Migracion ausente o ambigua; indicar proveedor')
        entry=entries[0];source=Path(entry['source']).resolve();target=Path(entry['target']).resolve()
        if source.parent!=runs or target.parent.parent!=runs or target.parent.name not in BUCKETS:raise ValueError('Restore fuera de runs')
        if source.exists():raise ValueError('Destino original ocupado; no sobrescribir')
        if activity(target) or not sqlite_idle(target):raise ValueError('Run activo o SQLite no verificable')
        allowed={FILES.get(name,name) for name in entry['inventory']}|set(entry['inventory'])
        if any(p.relative_to(target).as_posix() not in allowed for p in files_in(target)):
            raise ValueError('Run modificado desde migracion; restauracion automatica denegada, datos conservados')
        for name,checksum in entry['metadata_hashes'].items():
            if sha(file_path(target,name))!=checksum:raise ValueError('Metadatos modificados; no restaurar automaticamente')
        entry['state']='RESTORING';save(entry['journal'],entry)
        for old in entry['inventory']:
            new=FILES.get(old,old)
            if new==old:continue
            before=target/new;after=target/old
            if before.exists():
                if after.exists():raise ValueError('Colision de restauracion')
                after.parent.mkdir(parents=True,exist_ok=True);before.rename(after)
        # Remove only empty organizational directories introduced by the migration.
        for name in ('estado','manifiestos','grafo','logs','resultados'):
            path=target/name
            if path.is_dir() and not any(path.iterdir()):path.rmdir()
        actual={p.relative_to(target).as_posix():p.stat().st_size for p in files_in(target)}
        if actual!=entry['inventory']:raise ValueError('Inventario distinto; no restaurar ni borrar')
        target.rename(source)
        aliases=read_json(runs/'.relocations.json',dict(prefixes={}))
        aliases['prefixes'].pop(source.relative_to(root).as_posix(),None);save(runs/'.relocations.json',aliases)
        entry['state']='RESTORED';entry['restored_at']=stamp();save(entry['journal'],entry)
        return dict(status='COMPLETE',run_id=run_id,path=str(source),note='Usar su version exacta de codigo; historico conservado')


def status(root,run,reason=None):
    """Diagnostic fallback only; never relaxes inference integrity checks."""
    run=Path(run)
    if not run.is_dir():raise ValueError('Run no encontrado')
    result=dict(status='INTEGRITY_REVIEW_REQUIRED',run_id=run.name,location=str(run),
        integrity='NOT_VERIFIED_FOR_INFERENCE',note=reason or 'Formato historico; checkpoints conservados')
    try:result.update(metadata(run));result['status']='INTEGRITY_REVIEW_REQUIRED'
    except (ValueError,OSError,sqlite3.Error,KeyError,TypeError):result['metadata']='UNVERIFIABLE'
    result['active_reasons']=activity(run)
    return result


def automatic_cleanup(root):
    """Explicit per-computer opt-in; the identical verified deletion policy applies."""
    settings=read_json(Path(root)/'config/storage.local.json')
    if settings.get('automatic_cleanup') is not True:return None
    try:return cleanup(root,apply=True,automatic=True)
    except OSError:return dict(status='SKIPPED_ACTIVE_LOCK',deleted=0,recovered_bytes=0)
