"""External cooperative stop and offline export; no inference or model initialization."""
from run_paths import file_path as run_file
from pathlib import Path
from autonomous_execution import store as s


def request_stop(run):
    run=Path(run)
    if not (run_file(run, 'run.json')).exists():raise ValueError('Ejecucion no encontrada')
    s.write(run_file(run, 'stop.request.json'),dict(requested_at=s.now(),operation='STOP_NEW_CALLS_AND_EXPORT_PARTIAL'))
    return dict(status='STOP_REQUESTED',run_id=run.name,note='El worker finaliza solicitudes en curso y exporta; consulte status. Si ya termino, use export.')


def export_only(root,run,coordinator):
    from scripts.pipeline_coordinator import lock
    with lock(Path(run).parent),lock(run):
        if not run_file(run,'run.json').exists() and not (Path(run)/'autonomous/main/manifest.json').exists():
            from run_storage import archive
            return archive(root,run)
        if (Path(run)/'autonomous/main/manifest.json').exists():
            from autonomous_execution.lifecycle import export
            result=export(root,run,partial=True)
        else:result=coordinator.export(root,run)
        return result


def project_states(run):
    """Parallel status groups retained beside the immutable execution manifest."""
    run=Path(run);directory=run/'autonomous/main'
    db=s.connect(directory)
    try:
        counts={pid:{} for (pid,) in db.execute('SELECT siap FROM projects')}
        rows=db.execute('SELECT p.siap,j.status,COUNT(*) FROM jobs j JOIN projects p ON p.pid=j.pid GROUP BY p.siap,j.status').fetchall()
    finally:db.close()
    for pid,state,count in rows:counts.setdefault(pid,{})[state]=count
    groups=dict(complete=[],partial=[],blocked=[],pending=[])
    for pid,states in counts.items():
        category='complete' if not states or set(states)=={'PASS'} else 'partial' if states.get('PASS') else 'blocked' if states.get('BLOCKED') or states.get('UNCERTAIN') else 'pending'
        groups[category].append(pid)
    s.write(run_file(run, 'project_states.json'),groups)
    manifest=s.read(directory/'manifest.json')
    s.write(run_file(run, 'runtime.manifest.json'),dict(run_id=run.name,provider=manifest['llm']['provider'],
        model=manifest['llm']['model'],evaluation_contract=manifest.get('evaluation_contract'),
        source_manifest_sha256=s.sha(directory/'manifest.json'),project_states=groups))
    return groups
