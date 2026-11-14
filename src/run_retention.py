"""Explicit retirement of historical runs, separate from execution/72h cleanup.

Only reviewed, inactive runs are eligible. Age alone never authorizes retirement.
Unique evidence is stored in a checksummed, content-deduplicated ZIP before the
original directory is sent to the Windows Recycle Bin. No permanent fallback.
This module is administrative; it is not imported by the pipeline runtime.
"""
from datetime import datetime, timezone
import ast
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import subprocess
import struct
import uuid
import zipfile

from run_paths import file_path, read_json
from run_storage import activity as storage_activity, sha


def process_query_denied(pid):
    """Access denied is not evidence that a recorded Windows worker is dead."""
    if os.name!='nt':return False
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE;kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if handle:kernel.CloseHandle(handle);return False
    return ctypes.get_last_error()!=87  # ERROR_INVALID_PARAMETER: no such PID.


def activity(run):
    reasons=storage_activity(run)
    for p in (file_path(run,'worker.json'),Path(run)/'autonomous/main/worker.json',Path(run)/'estado/process.json'):
        worker=read_json(p);pid=worker.get('pid')
        if type(pid) is int and (pid<=0 or process_query_denied(pid)):
            reasons.append('PROCESS_IDENTITY_UNVERIFIABLE')
    return reasons


def list_runs(root):
    base=Path(root)/'outputs/runs';result=[]
    if not base.exists():return result
    for p in (base,base.parent):
        if p.is_symlink() or p.is_junction():raise ValueError('Linked runs root')
    with os.scandir(base) as buckets:
        for bucket in buckets:
            if bucket.name.startswith('.'):continue
            st=bucket.stat(follow_symlinks=False)
            if stat.S_ISLNK(st.st_mode) or getattr(st,'st_file_attributes',0)&0x400:raise ValueError('Linked provider bucket')
            if not stat.S_ISDIR(st.st_mode):continue
            if bucket.name not in ('local','api','anteriores'):raise ValueError('Migrate flat legacy runs before retirement')
            with os.scandir(bucket.path) as runs:
                for entry in runs:
                    if entry.name.startswith('.'):continue
                    st=entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(st.st_mode) or getattr(st,'st_file_attributes',0)&0x400:raise ValueError('Linked run')
                    if stat.S_ISDIR(st.st_mode):result.append(Path(entry.path))
    return sorted(result)


def files_in(run):
    """One scandir metadata query per entry; do not follow reparse points."""
    run=Path(run)
    if run.is_symlink() or run.is_junction(): raise ValueError('LINK_OR_JUNCTION')
    result=[];stack=[run]
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                st=entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(st.st_mode) or getattr(st,'st_file_attributes',0)&0x400:
                    raise ValueError('LINK_OR_JUNCTION')
                p=Path(entry.path)
                if stat.S_ISDIR(st.st_mode): stack.append(p)
                else: result.append(p)
    return result


def sqlite_idle(run):
    databases=[p for p in files_in(run) if p.suffix=='.sqlite' or p.suffix=='.db']
    if os.name!='nt':
        return not any(Path(str(p)+'-wal').exists() and Path(str(p)+'-wal').stat().st_size for p in databases)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE;kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    for p in databases:
        handle=kernel.CreateFileW(str(p),0x80000000,0,None,3,0x80,None)
        if handle==wintypes.HANDLE(-1).value:return False
        kernel.CloseHandle(handle)
    return True


def safe_relative(value):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or '..' in p.parts or '\\' in value or ':' in value:
        raise ValueError('Unsafe relative path')
    return p


def bin_locations(drive='C:'):
    sid=subprocess.check_output(['whoami','/user','/fo','csv','/nh'],text=True).strip().split(',')[-1].strip('"')
    directory=Path(drive+'/$Recycle.Bin')/sid
    if not directory.is_dir():raise OSError('Recycle Bin metadata inaccessible')
    result={}
    for p in sorted(directory.glob('$I*'),key=lambda p:p.stat().st_mtime_ns):
        raw=p.read_bytes();version=struct.unpack_from('<Q',raw)[0]
        original=raw[28 if version==2 else 24:].decode('utf-16-le').split('\x00')[0]
        result[os.path.normcase(original)]=str(p.with_name('$R'+p.name[2:]))
    return result


def key_of(root, run):
    base = Path(root).resolve()/'outputs/runs'
    run = Path(run)
    # Check the lexical path before resolve to reject a junction into another run.
    for p in [run, *run.parents]:
        if p == base.parent: break
        if p.is_symlink() or p.is_junction(): raise ValueError('LINK_OR_JUNCTION')
    key = run.resolve().relative_to(base).as_posix()
    parts = safe_relative(key).parts
    if len(parts) != 2 or parts[0] not in ('local', 'api', 'anteriores'):
        raise ValueError('Run outside provider buckets')
    return key


def snapshot(run):
    rows = []
    for p in sorted(files_in(run)):
        st = p.stat()
        if st.st_nlink != 1: raise ValueError('HARDLINK_RETAINED')
        rows.append([p.relative_to(run).as_posix(), st.st_size, st.st_mtime_ns])
    return rows


def uncertain(run):
    """Do not discard or classify a live/ambiguous paid request as a stale job."""
    for p in files_in(run):
        if p.name == 'api-ledger.sqlite':
            # Reading only the main file with an outstanding WAL is insufficient.
            if any(Path(str(p)+s).exists() and Path(str(p)+s).stat().st_size for s in ('-wal','-journal')):
                return True
            con = sqlite3.connect(p.resolve().as_uri()+'?mode=ro&immutable=1', uri=True)
            try:
                if con.execute("SELECT COUNT(*) FROM requests WHERE state IN ('IN_FLIGHT','UNCERTAIN')").fetchone()[0]:
                    return True
            finally: con.close()
        if p.name == 'api.dispatch.json':
            receipt = read_json(p.parent/'call.json')
            if not receipt or 'UNCERTAIN' in str(receipt.get('exit_status', '')): return True
    return False


def plan(root, policy):
    root = Path(root).resolve()
    if policy.get('version') != 1: raise ValueError('Unsupported retention policy')
    runs = {key_of(root, p): p for p in list_runs(root)}
    pinned = set(policy.get('pinned', []))
    official=set()
    for locator in ('outputs/layer2/canonical/_manifest.json','outputs/layer2/knowledge/_manifest.json','outputs/layer3/publication/_manifest.json'):
        meta=read_json(root/locator)
        official.update(v for field,v in meta.items() if field in ('run_id','layer1_run_id','layer2_run_id','layer3_run_id') and isinstance(v,str))
    pinned.update(k for k in runs if k.split('/')[-1] in official)
    # Checkpoints backing registered shared knowledge versions are dependencies.
    from knowledge_store import registered_locations
    backing=registered_locations(root)
    pinned.update(k for k,p in runs.items() if p.resolve() in backing)
    # Historical comparators can require a run even when it is not a publication.
    # Match literal IDs/locators in executable code, not timestamps or similar names.
    for source in (root/'src',root/'scripts'):
        if not source.exists():continue
        for p in files_in(source):
            if p.suffix!='.py':continue
            tree=ast.parse(p.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if not isinstance(node,ast.Constant) or not isinstance(node.value,str):continue
                value=node.value.replace('\\','/')
                for key in runs:
                    name=key.split('/')[-1]
                    if value==name or value==f'outputs/runs/{name}' or value.startswith(f'outputs/runs/{name}/') or value==f'outputs/runs/{key}' or value.startswith(f'outputs/runs/{key}/'):
                        pinned.add(key)
    count = policy.get('keep_recent', 2)
    if type(count) is not int or count < 1: raise ValueError('keep_recent must be positive')
    # Explicit timestamps from execution metadata, never directory mtimes.
    dated = []
    for key, run in runs.items():
        progress = read_json(file_path(run, 'progress.json'))
        stamp = progress.get('updated_at')
        if isinstance(stamp, str):
            try:
                when=datetime.fromisoformat(stamp.replace('Z','+00:00'))
                if when.tzinfo is not None:dated.append((when.astimezone(timezone.utc),key))
            except ValueError:pass
    pinned.update(k for _, k in sorted(dated, reverse=True)[:count])
    families={}
    for when,key in dated:
        rule=policy.get('reviewed',{}).get(key,{})
        if rule.get('family'):
            families.setdefault((rule.get('profile','academic'),rule['family']),[]).append((when,key))
    for (profile,_),members in families.items():
        limit=policy.get('keep_per_family',{}).get(profile,0)
        if type(limit) is not int or limit<0:raise ValueError('Invalid family retention limit')
        pinned.update(k for _,k in sorted(members,reverse=True)[:limit])
    # Retained reuse sources are dependencies, not ordinary superseded copies.
    for _ in range(len(runs)):
        previous = set(pinned)
        for key in previous:
            if key not in runs: continue
            source = read_json(file_path(runs[key], 'reuse.json')).get('source_run')
            pinned.update(k for k in runs if k.split('/')[-1] == source)
        if previous == pinned: break
    rows = []
    for key, run in sorted(runs.items()):
        rule = policy.get('reviewed', {}).get(key, {})
        row = dict(key=key, action='KEEP', reason='Unreviewed: unique value not assessed')
        try:
            if key in pinned: row['reason'] = 'Pinned, recent, official or retained reuse dependency'
            elif rule.get('closed_for_retention') is not True or not rule.get('reason'):
                row['reason'] = 'Requires explicit retirement review; not an age policy'
            elif activity(run) or not sqlite_idle(run):
                row.update(action='REVIEW', reason='Active process/lock or open SQLite handle')
            elif uncertain(run): row.update(action='REVIEW', reason='Uncertain API request')
            else:
                inventory = snapshot(run)
                row.update(action='COMPACT', reason=rule['reason'], inventory=inventory,
                           files=len(inventory), bytes=sum(r[1] for r in inventory),
                           family=rule.get('family', 'reviewed'), profile=rule.get('profile', 'academic'))
        except (ValueError, OSError, sqlite3.Error) as exc:
            row.update(action='REVIEW', reason=str(exc))
        rows.append(row)
    return rows


def build_archive(root, rows, target, omissions=None):
    """Preserve every non-omitted byte. Omissions require an exact reviewed hash.

    Omissions are administrative evidence supplied by a separate audit, not
    inferred from suffixes or names here. Each must explain its regeneration or
    identify an independently preserved counterpart. Query caches are forbidden.
    """
    root = Path(root).resolve(); target = Path(target)
    if not target.resolve().is_relative_to(root/'outputs/historico/compactados'):
        raise ValueError('Archive must be outside runs, under historico/compactados')
    omissions = omissions or {}
    for rel, evidence in omissions.items():
        safe_relative(rel)
        if '/query_cache/' in '/'+rel+'/' or not evidence.get('reason') or not evidence.get('sha256'):
            raise ValueError('Unverified omission or protected query cache')
    target.parent.mkdir(parents=True, exist_ok=True)
    index = dict(version=1, status='HISTORICAL_NON_RESUMABLE',
                 created_at=datetime.now(timezone.utc).isoformat(), runs={}, objects={})
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        for row in rows:
            if row['action'] != 'COMPACT': continue
            run = root/'outputs/runs'/row['key']
            if snapshot(run) != row['inventory']: raise ValueError('Run changed before archive')
            record = {k:v for k,v in row.items() if k != 'inventory'}
            record.update(files_preserved={}, omitted={})
            for rel, size, mtime in row['inventory']:
                p = run/rel; digest = sha(p); key = row['key']+'/'+rel
                if key in omissions:
                    evidence = omissions[key]
                    if digest != evidence['sha256']: raise ValueError('Omitted file changed')
                    record['omitted'][rel] = dict(bytes=size, **evidence)
                    continue
                if digest not in index['objects']:
                    z.write(p, 'objects/'+digest)
                    index['objects'][digest] = size
                record['files_preserved'][rel] = [digest, size, mtime]
            if snapshot(run) != row['inventory']: raise ValueError('Run changed during archive')
            index['runs'][row['key']] = record
        z.writestr('index.json', json.dumps(index, ensure_ascii=False, separators=(',',':')))
    verify_archive(target)
    return index


def verify_archive(path):
    with zipfile.ZipFile(path) as z:
        if len(z.namelist()) != len(set(z.namelist())): raise ValueError('Duplicate ZIP member')
        index = json.loads(z.read('index.json'))
        if index.get('version') != 1 or index.get('status') != 'HISTORICAL_NON_RESUMABLE':
            raise ValueError('Unsupported evidence archive')
        expected = {'index.json'} | {'objects/'+h for h in index['objects']}
        if set(z.namelist()) != expected: raise ValueError('Unregistered archive members')
        for h, size in index['objects'].items():
            with z.open('objects/'+h) as f:
                digest = hashlib.file_digest(f, 'sha256').hexdigest()
            if digest != h or z.getinfo('objects/'+h).file_size != size:
                raise ValueError('Evidence checksum mismatch')
        for key, run in index['runs'].items():
            safe_relative(key)
            for rel, (h, size, _) in run['files_preserved'].items():
                safe_relative(rel)
                if index['objects'].get(h) != size: raise ValueError('Broken evidence reference')
    return index


def extract_evidence(archive, key, destination):
    """Extract to a NEW directory only; never restore over a live run."""
    index = verify_archive(archive); run = index['runs'][key]
    dest = Path(destination)
    if dest.exists(): raise FileExistsError('Destination must not exist')
    if any(p.is_symlink() or p.is_junction() for p in dest.parents): raise ValueError('Linked destination')
    dest.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        for rel, (h, _, _) in run['files_preserved'].items():
            target = dest/str(safe_relative(rel)); target.parent.mkdir(parents=True, exist_ok=True)
            with z.open('objects/'+h) as source, target.open('xb') as out:
                import shutil
                shutil.copyfileobj(source, out)
    (dest/'HISTORICAL_NON_RESUMABLE.json').write_text(json.dumps(dict(
        source=key, archive_sha256=sha(archive), omitted=run['omitted'],
        note='Evidence extraction, not an authorized or complete resumable run.'), ensure_ascii=False, indent=2), encoding='utf-8')
    return len(run['files_preserved'])


def document_cache_plan(root, policy):
    """Evict only document vectors already covered by intact current bundles.

    Query embeddings are never considered. No corpus/model/API is loaded.
    Uncovered/invalid pairs retain the entire cache; age has no role.
    """
    import ast
    root=Path(root).resolve();cache=root/'outputs/layer3/cache'
    result=dict(action='KEEP',path=str(cache),reason='Cache absent or within configured limits')
    if not cache.exists():return result
    rows=snapshot(cache);size=sum(r[1] for r in rows)
    result.update(files=len(rows),bytes=size)
    if size<=policy.get('document_cache_budget_bytes',268435456) and len(rows)<=policy.get('document_cache_max_files',20000):
        return result
    if (root/'outputs/layer3/.publish.lock').exists() or (root/'outputs/layer3/publication_pending.json').exists():
        return result|dict(action='REVIEW',reason='Publication in progress')
    if any(activity(run) or not sqlite_idle(run) for run in list_runs(root)):
        return result|dict(action='REVIEW',reason='Active/unverifiable run; shared cache protected')
    published=[root/'outputs/layer3/publication']
    published.extend(run/'workspace/outputs/layer3/publication' for run in list_runs(root))
    covered=set();proof={}
    for pub in published:
        for space in ('source','reference'):
            directory=pub/'embeddings'/space
            if not directory.exists():continue
            for ancestor in [directory,*directory.parents]:
                if ancestor==root:break
                if ancestor.is_junction() or ancestor.is_symlink():raise ValueError('Linked bundle')
            meta=read_json(directory/'metadata.json')
            if not meta.get('file_hashes'):continue
            for name,h in meta['file_hashes'].items():
                p=directory/str(safe_relative(name))
                if not p.resolve().is_relative_to(pub.resolve()) or sha(p)!=h:
                    raise ValueError('Invalid preserved embedding bundle')
                proof[p.relative_to(root).as_posix()]=h
            covered.update(r['embedding_hash'] for r in read_json(directory/'records.json'))
    names={r[0] for r in rows};checks={}
    for rel in sorted(names):
        if not rel.endswith('.json'):continue
        vector=rel[:-5]+'.npy';p=cache/rel;meta=read_json(p)
        if vector not in names or meta.get('key')!=p.stem:
            return result|dict(action='REVIEW',reason='Unknown cache member')
        raw=(cache/vector).read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if raw[:6]!=b'\x93NUMPY':return result|dict(action='REVIEW',reason='Invalid vector')
        n=2 if raw[6]==1 else 4;length=struct.unpack('<H' if n==2 else '<I',raw[8:8+n])[0]
        header=ast.literal_eval(raw[8+n:8+n+length].decode('latin1').strip())
        if header.get('descr') not in ('<f4','=f4') or header.get('shape')!=(meta.get('dimensions'),):
            return result|dict(action='REVIEW',reason='Unexpected vector dimensions')
        payload=hashlib.sha256(raw[8+n+length:]).hexdigest()
        if digest!=meta.get('file_hash') or payload!=meta.get('embedding_hash') or payload not in covered:
            return result|dict(action='REVIEW',reason='Uncovered or invalid vector; keep unique content')
        checks[rel]=sha(p);checks[vector]=digest
    if set(checks)!=names:return result|dict(action='REVIEW',reason='Unexpected cache files; no inference from names')
    return result|dict(action='RECYCLE_CACHE',reason='All optional document vectors preserved in verified publication',
                       inventory=rows,checksums=checks,bundles=proof)


def prune_document_cache(root, policy, journal):
    from scripts.pipeline_coordinator import lock
    root=Path(root).resolve();journal=Path(journal)
    if not journal.resolve().is_relative_to(root/'outputs/runs/.storage-events') or journal.exists():
        raise ValueError('New storage-events journal required')
    with lock(root/'outputs/runs'):
        row=document_cache_plan(root,policy)
        if row['action']!='RECYCLE_CACHE':return row
        path=Path(row['path'])
        if snapshot(path)!=row['inventory'] or any(sha(path/p)!=h for p,h in row['checksums'].items()):
            raise ValueError('Cache changed; retain')
        if any(sha(root/p)!=h for p,h in row['bundles'].items()):raise ValueError('Counterpart changed; retain')
        journal.parent.mkdir(parents=True,exist_ok=True)
        row['state']='BEFORE_RECYCLE'
        with journal.open('x',encoding='utf-8') as f:
            json.dump(row,f,ensure_ascii=False,separators=(',',':'));f.flush();os.fsync(f.fileno())
        row['recovery_path']=recycle(path);row['state']='RECYCLED'
        with journal.open('w',encoding='utf-8') as f:
            json.dump(row,f,ensure_ascii=False,separators=(',',':'));f.flush();os.fsync(f.fileno())
        return row


def recycle(path):
    """Windows IFileOperation with recycle/undo, no permanent-delete fallback."""
    if os.name != 'nt': raise OSError('Recoverable Windows recycling required')
    path=Path(path).resolve()
    # A missing/inaccessible user bin is a reason to stop, not to delete forever.
    bin_locations(path.drive)
    class GUID(ctypes.Structure):
        _fields_=[('a',wintypes.DWORD),('b',wintypes.WORD),('c',wintypes.WORD),('d',ctypes.c_ubyte*8)]
        def __init__(self, value):
            super().__init__(); ctypes.memmove(ctypes.byref(self),uuid.UUID(value).bytes_le,16)
    def call(obj, slot, *types):
        v=ctypes.cast(obj,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(wintypes.LONG,ctypes.c_void_p,*types)(v[slot])
    def check(hr):
        if hr < 0: raise OSError(f'Recycling failed: HRESULT {hr & 0xffffffff:08x}')
    ole=ctypes.OleDLL('ole32'); shell=ctypes.OleDLL('shell32')
    initialized=ole.CoInitializeEx(None,2)
    check(initialized)
    op=ctypes.c_void_p(); item=ctypes.c_void_p()
    try:
        check(ole.CoCreateInstance(ctypes.byref(GUID('3ad05575-8857-4850-9277-11b85bdb8e09')),None,1,
              ctypes.byref(GUID('947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8')),ctypes.byref(op)))
        check(call(op,5,wintypes.DWORD)(op,0x80000|0x20000000|0x100000|0x40|0x4000|0x400|0x10|0x4))
        shell.SHCreateItemFromParsingName.argtypes=[wintypes.LPCWSTR,ctypes.c_void_p,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)]
        check(shell.SHCreateItemFromParsingName(str(Path(path).resolve()),None,
              ctypes.byref(GUID('43826d1e-e718-42ee-bc55-a1e261c37bfe')),ctypes.byref(item)))
        check(call(op,18,ctypes.c_void_p,ctypes.c_void_p)(op,item,None));check(call(op,21)(op))
        aborted=wintypes.BOOL();check(call(op,22,ctypes.POINTER(wintypes.BOOL))(op,ctypes.byref(aborted)))
        if aborted.value or Path(path).exists(): raise OSError('Recycling incomplete; stop')
    finally:
        if item: call(item,2)(item)
        if op: call(op,2)(op)
        if initialized in (0,1): ole.CoUninitialize()
    recovery=bin_locations(path.drive).get(os.path.normcase(str(path)))
    if not recovery or not Path(recovery).exists():raise OSError('Cannot verify recoverable destination; stop')
    return recovery


def apply(root, policy, archive, journal):
    """Explicit apply only. Keep originals until verified archive + durable journal."""
    from scripts.pipeline_coordinator import lock
    root = Path(root).resolve(); journal=Path(journal)
    if not journal.resolve().is_relative_to(root/'outputs/runs/.storage-events'):
        raise ValueError('Journal outside storage-events')
    if journal.exists(): raise FileExistsError('Use a new journal; inspect interrupted operations first')
    with lock(root/'outputs/runs'):
        rows=plan(root,policy); selected=[r for r in rows if r['action']=='COMPACT']
        if not selected:return dict(status='NO_CANDIDATES',runs=rows)
        index=build_archive(root,selected,archive)
        state=dict(status='ARCHIVED_BEFORE_RECYCLE',archive=str(archive),archive_sha256=sha(archive),operations=[])
        journal.parent.mkdir(parents=True,exist_ok=True)
        def save():
            with journal.open('w',encoding='utf-8') as f:
                json.dump(state,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        save()
        for row in selected:
            run=root/'outputs/runs'/row['key']
            if activity(run) or not sqlite_idle(run) or snapshot(run)!=row['inventory']:
                raise ValueError('Run changed or became active; originals retained')
            # Re-hash after archive verification, not just size/mtime.
            if any(sha(run/rel)!=v[0] for rel,v in index['runs'][row['key']]['files_preserved'].items()):
                raise ValueError('Run contents changed after archive')
            event=dict(key=row['key'],files=row['files'],bytes=row['bytes'],state='BEFORE_RECYCLE')
            state['operations'].append(event);save();event['recovery_path']=recycle(run)
            event['state']='RECYCLED';save()
        state['status']='COMPLETE';save();return state
