"""Read historical receipts without inference or modifying the source run."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime
import csv
import json
from pathlib import Path
import sqlite3
import statistics


def analyze(run):
    run=Path(run);directory=run/'autonomous/main'
    db=sqlite3.connect((directory/'queue.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:
        jobs=[dict(r) for r in db.execute('SELECT * FROM jobs')]
        usage=[dict(r) for r in db.execute('SELECT * FROM usage')]
        events=db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        event_counts=[dict(r) for r in db.execute('SELECT stage,code,COUNT(*) AS count FROM events GROUP BY stage,code')]
        resource_events=[dict(r) for r in db.execute("SELECT at,code FROM events WHERE stage='resources' ORDER BY seq")]
        projects_selected=db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
    finally:db.close()
    waits=[];waiting=None
    for event in resource_events:
        if event['code']=='RESOURCE_RAM_FLOOR' and waiting is None:waiting=event['at']
        if event['code']=='RAM_RECOVERED' and waiting is not None:
            waits.append((datetime.fromisoformat(event['at'])-datetime.fromisoformat(waiting)).total_seconds());waiting=None
    calls=[];rules=Counter();settings=Counter();durations=defaultdict(list)
    for path in directory.glob('attempts/**/call.json'):
        call=json.loads(path.read_text(encoding='utf-8'))
        for issue in call.get('validation_issues',[]):rules[issue.get('rule','UNKNOWN')]+=1
        settings[str(call.get('runtime',{}).get('configuration',{}).get('num_ctx'))]+=1
        for key,value in call.get('ollama_durations_ns',{}).items():
            if isinstance(value,int):durations[key].append(value/1e9)
        calls.append(dict(path=path.relative_to(run).as_posix(),pid=call['project_id'],
            started=call['timestamp'],finished=call.get('finished_at'),error=call['exit_status'],
            wall=call.get('performance',{}).get('wall_seconds',{}).get('value'),
            **call.get('usage_observations',[{}])[0]))
    calls.sort(key=lambda c:c['started']);gaps=[]
    for a,b in zip(calls,calls[1:]):
        if a['finished']:gaps.append(max(0,(datetime.fromisoformat(b['started'])-datetime.fromisoformat(a['finished'])).total_seconds()))
    def stats(values):
        values=[v for v in values if v is not None]
        return dict(count=len(values),sum=sum(values),mean=statistics.mean(values) if values else None,
            median=statistics.median(values) if values else None,max=max(values) if values else None)
    per_project={}
    for pid in sorted({j['pid'] for j in jobs}):
        selected=[j for j in jobs if j['pid']==pid];observed=[u for u in usage if u['pid']==pid]
        per_project[pid]=dict(jobs=len(selected),states=dict(Counter(j['status'] for j in selected)),
            calls=len(observed),inference_seconds=sum(u['wall'] or 0 for u in observed),
            input_tokens=sum(u['input_tokens'] or 0 for u in observed),output_tokens=sum(u['output_tokens'] or 0 for u in observed))
    performance={}
    path=run/'resultados/performance/resumen.csv'
    if path.exists():
        with path.open(encoding='utf-8-sig',newline='') as f:performance=next(csv.DictReader(f,delimiter=';'),{})
    return dict(run_id=run.name,source_modified=False,inference_calls_executed=0,
        projects=projects_selected,projects_with_jobs=len(per_project),jobs=len(jobs),job_states=dict(Counter(j['status'] for j in jobs)),
        history_events=events,event_counts=event_counts,resource_wait_seconds=stats(waits),registered_calls=len(usage),transport_receipts=len(calls),
        steps=dict(Counter(u['step'] for u in usage)),errors=dict(Counter(str(u['error']) for u in usage)),
        inference_seconds=stats([u['wall'] for u in usage]),input_tokens=stats([u['input_tokens'] for u in usage]),
        output_tokens=stats([u['output_tokens'] for u in usage]),missing_token_calls=sum(u['input_tokens'] is None or u['output_tokens'] is None for u in usage),
        contexts=dict(settings),validation_rules=dict(rules.most_common()),inter_call_gaps_seconds=stats(gaps),
        ollama_seconds={k:stats(v) for k,v in durations.items()},performance=performance,
        per_project=per_project,per_indicator=[dict(pid=j['pid'],iid=j['iid'],status=j['status'],
            calls=sum(u['pid']==j['pid'] and u['iid']==j['iid'] for u in usage)) for j in jobs],requests=calls)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run');parser.add_argument('--output',required=True)
    args=parser.parse_args();run=Path(args.run).resolve();target=Path(args.output).resolve()
    if target.is_relative_to(run):raise ValueError('No escribir dentro del run historico')
    result=analyze(run);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('requests','per_project','per_indicator','performance')},indent=2))
