"""Small SQLite transactions and durable per-indicator receipts, Windows safe."""
from run_paths import file_path as run_file
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def process_info(pid):
    """PID plus creation identity distinguish a restarted/reused Windows process."""
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.windll.kernel32
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return dict(alive=False,creation=None)
        try:
            created=wintypes.FILETIME();exited=wintypes.FILETIME();cpu_kernel=wintypes.FILETIME();cpu_user=wintypes.FILETIME()
            kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
            code=wintypes.DWORD()
            kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
            if not kernel.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(cpu_kernel),ctypes.byref(cpu_user)):
                return dict(alive=None,creation=None)
            kernel.GetExitCodeProcess(handle,ctypes.byref(code))
            return dict(alive=code.value==259,creation=(created.dwHighDateTime<<32)|created.dwLowDateTime)
        finally:
            kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle(handle)
    try:
        os.kill(pid,0)
        path=Path(f'/proc/{pid}/stat')
        marker=path.read_text().rsplit(')',1)[1].split()[19] if path.exists() else None
        return dict(alive=True,creation=marker)
    except (OSError,IndexError,OverflowError):
        return dict(alive=False,creation=None)


def sha(path):
    from layer2_processing.checkpoints import locate
    path=locate(path)
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    from layer4_evaluation.indicators.ollama_provider import strict_json
    from layer2_processing.checkpoints import locate
    path=locate(path)
    return strict_json(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    from run_paths import resolve_file
    path = resolve_file(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.pending')
    try:
        with temp.open('x',encoding='utf-8',newline='\n') as stream:
            json.dump(value,stream,ensure_ascii=False,allow_nan=False,sort_keys=True)
            stream.flush(); os.fsync(stream.fileno())
        # Concurrent replacements and short antivirus reads can transiently deny
        # Windows rename access. Keep the durable candidate and retry only that
        # filesystem operation; never repeat evaluation or overwrite in-place.
        for attempt in range(6):
            try:
                temp.replace(path)
                break
            except PermissionError as exc:
                if os.name!='nt' or getattr(exc,'winerror',None) not in (5,32,33) or attempt==5:
                    raise
                time.sleep(.01*2**attempt)
    finally:
        temp.unlink(missing_ok=True)


def connect(directory):
    db = sqlite3.connect(Path(directory)/'queue.sqlite', timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS projects(pid TEXT PRIMARY KEY, siap TEXT, path TEXT, digest TEXT);
      CREATE TABLE IF NOT EXISTS jobs(pid TEXT, iid TEXT, status TEXT, attempts INTEGER DEFAULT 0, rounds INTEGER DEFAULT 0,
        result_path TEXT, result_hash TEXT, error TEXT, updated TEXT, PRIMARY KEY(pid,iid));
      CREATE TABLE IF NOT EXISTS steps(pid TEXT, iid TEXT, name TEXT, attempt INTEGER,
        status TEXT, path TEXT, error TEXT, PRIMARY KEY(pid,iid,name,attempt));
      CREATE TABLE IF NOT EXISTS usage(pid TEXT,iid TEXT,step TEXT,attempt INTEGER,
        input_tokens INTEGER,output_tokens INTEGER,wall REAL,error TEXT,
        PRIMARY KEY(pid,iid,step,attempt));
      CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,at TEXT,stage TEXT,pid TEXT,iid TEXT,code TEXT);
      CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
    ''')
    return db


@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback(); raise


def event(db, stage, code, pid=None, iid=None):
    db.execute('INSERT INTO events(at,stage,pid,iid,code) VALUES(?,?,?,?,?)',(now(),stage,pid,iid,code))


def claim(db):
    with transaction(db):
        row = db.execute("""SELECT * FROM jobs WHERE status='PENDING'
            ORDER BY COALESCE((SELECT CAST(key AS INTEGER) FROM json_each(
                COALESCE((SELECT value FROM meta WHERE key='project_order'),'[]')) WHERE value=jobs.pid),2147483647),pid,iid LIMIT 1""").fetchone()
        if row:
            db.execute("UPDATE jobs SET status='RUNNING',updated=? WHERE pid=? AND iid=?",(now(),row['pid'],row['iid']))
            event(db,'evaluation','STARTED',row['pid'],row['iid'])
        return dict(row) if row else None


def status(directory):
    db = connect(directory)
    try:
        counts = dict(db.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status'))
        total = sum(counts.values())
        projects = db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
        complete = db.execute("SELECT COUNT(*) FROM projects p WHERE NOT EXISTS (SELECT 1 FROM jobs j WHERE j.pid=p.pid AND j.status!='PASS')").fetchone()[0]
        processed=db.execute("SELECT COUNT(*) FROM projects p WHERE EXISTS (SELECT 1 FROM jobs j WHERE j.pid=p.pid) AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.pid=p.pid AND j.status NOT IN ('PASS','BLOCKED','UNCERTAIN'))").fetchone()[0]
        tokens = db.execute('SELECT COUNT(*),COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),'
            'SUM(input_tokens IS NULL OR output_tokens IS NULL),COALESCE(SUM(wall),0) FROM usage').fetchone()
        last = db.execute('SELECT at,stage,code FROM events ORDER BY seq DESC LIMIT 1').fetchone()
        recovered = db.execute("SELECT COUNT(*) FROM jobs WHERE status='PASS' AND (attempts>1 OR EXISTS(SELECT 1 FROM usage u WHERE u.pid=jobs.pid AND u.iid=jobs.iid AND u.error IS NOT NULL))").fetchone()[0]
        errors = [dict(r) for r in db.execute("SELECT error,COUNT(*) AS evaluations FROM jobs WHERE error IS NOT NULL GROUP BY error")]
        recent_errors=[dict(r) for r in db.execute("SELECT pid,iid,error,updated FROM jobs WHERE error IS NOT NULL ORDER BY updated DESC LIMIT 20")]
        diagnostics=[dict(r) for r in db.execute("SELECT pid,iid,name,attempt,error,path FROM steps WHERE error IS NOT NULL ORDER BY rowid DESC LIMIT 20")]
        export = db.execute("SELECT value FROM meta WHERE key='export'").fetchone()
        stage = db.execute("SELECT value FROM meta WHERE key='stage'").fetchone()
        state='COMPLETE' if projects and counts.get('PASS',0)==total else 'RUNNING' if counts.get('RUNNING') else 'PAUSED' if stage and stage[0]=='paused' else 'PARTIAL'
        worker=read(run_file(Path(directory), 'worker.json')) if (run_file(Path(directory), 'worker.json')).exists() else None
        if worker:
            current=process_info(worker['pid'])
            active=current['alive'] and (worker.get('creation') is None or worker['creation']==current['creation']) and worker.get('state')!='FINISHED'
            worker=dict(pid=worker['pid'],alive=bool(active),state=worker.get('state','STARTED'))
            if state not in ('COMPLETE','PAUSED'):
                state='RUNNING' if active else 'INTERRUPTED' if counts.get('RUNNING') else 'PARTIAL'
        return dict(status=state,
            projects_total=projects,projects_completed=complete,projects_processed=processed,indicators_total=total,
            processing_complete=bool(total) and processed==projects,results_available=bool(counts.get('PASS')),
            evaluated=counts.get('PASS',0),pending=counts.get('PENDING',0),running=counts.get('RUNNING',0),
            blocked=counts.get('BLOCKED',0),uncertain=counts.get('UNCERTAIN',0),recovered=recovered,
            counts=counts,calls=tokens[0],input_tokens=tokens[1],output_tokens=tokens[2],
            total_tokens=tokens[1]+tokens[2],missing_usage_metrics=tokens[3] or 0,wall_seconds=tokens[4],
            stage=stage[0] if stage else 'prepared',last_activity=dict(last) if last else None,
            errors=errors,recent_errors=recent_errors,diagnostic_steps=diagnostics,
            worker=worker,
            export=json.loads(export[0]) if export else dict(status='PENDING'))
    finally:
        db.close()
