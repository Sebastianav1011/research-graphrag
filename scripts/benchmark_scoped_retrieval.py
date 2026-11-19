"""Before/after benchmark of V5 scoped retrieval and request preparation. No model calls.

Each source runs in its own subprocess so that timings and the peak working set are
independent. Output: outputs/audits/optimizacion_v5_recuperacion/<label>/<source>.json
with candidates (IDs, order, scores, reference IDs), relational paths, request and
prompt hashes, fragment/token counts and per-phase timings.

  uv run python scripts/benchmark_scoped_retrieval.py --label antes
  uv run python scripts/benchmark_scoped_retrieval.py --label despues
  uv run python scripts/benchmark_scoped_retrieval.py --compare antes despues
"""
import argparse
import ctypes
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/audits/optimizacion_v5_recuperacion'
SOURCES = [('project', '21844'), ('project', '21736'), ('project', '21869'), ('article', 'ART_2-s2.0-105001255605')]


def peak_mib():
    """Peak working set of this process (Windows); None elsewhere."""
    if not hasattr(ctypes, 'windll'):
        return None
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong), ('peak', ctypes.c_size_t),
                    ('working', ctypes.c_size_t), ('qpp', ctypes.c_size_t), ('qp', ctypes.c_size_t),
                    ('qnpp', ctypes.c_size_t), ('qnp', ctypes.c_size_t), ('pagefile', ctypes.c_size_t),
                    ('peak_pagefile', ctypes.c_size_t)]
    counters = Counters(); counters.cb = ctypes.sizeof(Counters)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.windll.psapi
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return round(counters.peak / 2 ** 20, 1), round(counters.peak_pagefile / 2 ** 20, 1)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def one(kind, source_id, label):
    sys.path.insert(0, str(ROOT / 'src')); sys.path.insert(0, str(ROOT / 'scripts'))
    import evaluate_source as e
    from layer4_evaluation.indicators import scoped_retrieval as sr, context_budget as cb
    from layer3_graphrag import vector_index as vi
    timings = {}

    def timed(module, name, key):
        original = getattr(module, name)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                timings[key] = timings.get(key, 0.0) + time.perf_counter() - start
        setattr(module, name, wrapper)
    timed(sr, 'validate_publication', 'validate_publication_s')
    for name in ('load', 'open_mapped'):
        if hasattr(vi.NumpyVectorIndex, name):
            original = getattr(vi.NumpyVectorIndex, name).__func__
            def bound(cls, *args, _original=original, _name=name, **kwargs):
                start = time.perf_counter()
                try:
                    return _original(cls, *args, **kwargs)
                finally:
                    timings['index_load_s'] = timings.get('index_load_s', 0.0) + time.perf_counter() - start
            setattr(vi.NumpyVectorIndex, name, classmethod(bound))
    timed(sr, 'rank_project_passages', 'rank_s')
    if hasattr(sr, '_rank_selected'):
        timed(sr, '_rank_selected', 'rank_s')
    timed(sr, 'project_relations', 'graph_relations_s')
    timed(cb, 'prepare_contexts', 'prepare_contexts_s')
    start = time.perf_counter()
    args = argparse.Namespace(source_type=kind, source_id=source_id, indicators='all')
    captured = {}
    original_cache = sr.from_published_cache
    def capture(*a, **k):
        candidates, report = original_cache(*a, **k)
        captured['candidates'] = candidates
        return candidates, report
    sr.from_published_cache = capture
    prepared = e.prepare(args)
    timings['total_prepare_s'] = time.perf_counter() - start
    candidates = {c['indicator_id']: c for c in captured['candidates']}
    requests = prepared['requests']
    result = dict(label=label, source_type=kind, source_id=source_id, timings={k: round(v, 3) for k, v in timings.items()},
        peak_working_set_mib=peak_mib(), retrieval=prepared.get('retrieval'),
        candidates={iid: dict(hits=[(h['chunk_id'], h['vector_rank'], h['vector_score'], h['reference_chunk_ids'])
                                    for h in c['discovery_chunks']],
                              relational=(c.get('relational_context') or {}).get('support_paths'))
                    for iid, c in sorted(candidates.items())},
        scored_chunks_per_indicator=prepared.get('retrieval', {}).get('scored_positions'),
        requests={iid: dict(request_sha256=digest(r), prompt_sha256=hashlib.sha256(r['prompt'].encode()).hexdigest(),
                            status=r['context_selection']['status'], fragments=len(r['payload']['project']['fragments']),
                            tokens=r['context_budget']['estimated_input_tokens'])
                  for iid, r in sorted(requests.items())})
    path = OUT / label / f'{kind}_{source_id}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(dict(source=source_id, timings=result['timings'], peak=result['peak_working_set_mib'])))


def index_only(method):
    """Isolated index opening + scoring of all 48 indicators for one source: time and peak memory."""
    sys.path.insert(0, str(ROOT / 'src'))
    import numpy as np
    from layer3_graphrag.vector_index import NumpyVectorIndex
    from layer4_evaluation.indicators.mapped_index import open_mapped
    active = json.loads((ROOT / 'outputs/shared/base/active.json').read_text(encoding='utf-8'))
    path = ROOT / 'outputs/shared/base/versions' / active['version_id'] / 'artifacts/workspace/outputs/layer3/publication/indexes/source'
    start = time.perf_counter()
    index = getattr(NumpyVectorIndex, method)(path)
    opened = time.perf_counter() - start
    rows = list(range(0, 200))
    start = time.perf_counter()
    subset = np.asarray(index.vectors[rows], dtype=np.float64)
    read = time.perf_counter() - start
    print(json.dumps(dict(method=method, open_s=round(opened, 3), read_selected_rows_s=round(read, 6),
        vectors_type=type(index.vectors).__name__, dtype=str(index.vectors.dtype), shape=list(index.vectors.shape),
        peak_working_set_and_private_mib=peak_mib())))


def chunks_only(method):
    """Isolated chunk loading of the main flow: all rows with text (before) vs load_chunks (after)."""
    sys.path.insert(0, str(ROOT / 'src'))
    import pyarrow.parquet as pq
    active = json.loads((ROOT / 'outputs/shared/base/active.json').read_text(encoding='utf-8'))
    workspace = ROOT / 'outputs/shared/base/versions' / active['version_id'] / 'artifacts/workspace'
    start = time.perf_counter()
    if method == 'full':
        chunks = pq.read_table(workspace / 'outputs/layer2/knowledge/source_chunks.parquet').to_pylist()
    else:
        from layer4_evaluation.indicators.scoped_retrieval import load_chunks
        chunks = load_chunks(workspace, ['PROJ_21844'])
    print(json.dumps(dict(method=method, rows=len(chunks), seconds=round(time.perf_counter() - start, 3),
        with_text=sum('text' in c for c in chunks), peak_working_set_and_private_mib=peak_mib())))


def float32_check(label):
    """Precision study: same rows and queries scored in float32 vs float64 (no change in production)."""
    sys.path.insert(0, str(ROOT / 'src'))
    import numpy as np
    from layer3_graphrag.vector_index import NumpyVectorIndex
    from layer4_evaluation.indicators.mapped_index import open_mapped
    from layer4_evaluation.indicators import scoped_retrieval as sr
    active = json.loads((ROOT / 'outputs/shared/base/active.json').read_text(encoding='utf-8'))
    workspace = ROOT / 'outputs/shared/base/versions' / active['version_id'] / 'artifacts/workspace'
    index = open_mapped(workspace / 'outputs/layer3/publication/indexes/source')
    embeddings = np.load(workspace / 'outputs/layer3/publication/embeddings/source/vectors.npy', mmap_mode='r')
    position = {r['chunk_id']: n for n, r in enumerate(index.records)}
    captured = {}
    original = sr._rank_selected
    def capture(projects, profiles, chunks, records, vectors, queries, relational=None):
        captured['queries'] = queries
        return original(projects, profiles, chunks, records, vectors, queries, relational)
    sr._rank_selected = capture
    sys.path.insert(0, str(ROOT / 'scripts'))
    import evaluate_source as e
    e.prepare(argparse.Namespace(source_type='article', source_id=SOURCES[-1][1], indicators='all'))
    queries = captured['queries']
    report = dict(embedding_file_dtype=str(embeddings.dtype), index_file_dtype=str(index.vectors.dtype), sources={})
    for kind, sid in SOURCES:
        data = json.loads((OUT / label / f'{kind}_{sid}.json').read_text(encoding='utf-8'))
        stats = dict(indicators=0, max_abs_diff=0.0, order_changes=0, top1_changes=0, reference_changes=0)
        for iid, c in data['candidates'].items():
            rows = [position[h[0]] for h in c['hits']]
            v64 = np.asarray(index.vectors[rows], dtype=np.float64)
            ids, q = queries[iid]
            q64 = np.asarray(q, dtype=np.float64); q64 = q64 / np.linalg.norm(q64, axis=1)[:, None]
            s64 = np.clip(q64 @ v64.T, -1, 1); s32 = np.clip(q64.astype(np.float32) @ v64.astype(np.float32).T, -1, 1)
            b64, b32 = s64.max(axis=0), s32.max(axis=0)
            chunk_ids = [h[0] for h in c['hits']]
            o64 = sorted(range(len(rows)), key=lambda i: (-float(b64[i]), chunk_ids[i]))
            o32 = sorted(range(len(rows)), key=lambda i: (-float(b32[i]), chunk_ids[i]))
            stats['indicators'] += 1
            stats['max_abs_diff'] = max(stats['max_abs_diff'], float(np.abs(s64 - s32).max()))
            stats['order_changes'] += o64 != o32
            stats['top1_changes'] += o64[:1] != o32[:1]
            stats['reference_changes'] += any([ids[n] for n in range(len(ids)) if s64[n, i] == b64[i]] !=
                                              [ids[n] for n in range(len(ids)) if s32[n, i] == b32[i]] for i in range(len(rows)))
        report['sources'][sid] = stats
    path = OUT / 'precision_float32.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))


def compare(before, after):
    rows = []
    for kind, sid in SOURCES:
        a = json.loads((OUT / before / f'{kind}_{sid}.json').read_text(encoding='utf-8'))
        b = json.loads((OUT / after / f'{kind}_{sid}.json').read_text(encoding='utf-8'))
        ids = order = refs = relational = requests = prompts = True; diff = 0.0
        for iid in a['candidates']:
            x, y = a['candidates'][iid], b['candidates'][iid]
            ids &= sorted(h[0] for h in x['hits']) == sorted(h[0] for h in y['hits'])
            order &= [h[0] for h in x['hits']] == [h[0] for h in y['hits']]
            refs &= [h[3] for h in x['hits']] == [h[3] for h in y['hits']]
            relational &= x['relational'] == y['relational']
            diff = max([diff] + [abs(p[2] - q[2]) for p, q in zip(x['hits'], y['hits'])])
        for iid in a['requests']:
            requests &= a['requests'][iid]['request_sha256'] == b['requests'][iid]['request_sha256']
            prompts &= a['requests'][iid]['prompt_sha256'] == b['requests'][iid]['prompt_sha256']
        rows.append(dict(source=sid, same_chunk_ids=ids, same_order=order, same_reference_ids=refs,
            same_relational_paths=relational, same_requests=requests, same_prompts=prompts, max_score_abs_diff=diff,
            fragments_sent=sum(r['fragments'] for r in b['requests'].values()),
            tokens=sum(r['tokens'] for r in b['requests'].values()),
            before=dict(timings=a['timings'], peak=a['peak_working_set_mib']),
            after=dict(timings=b['timings'], peak=b['peak_working_set_mib'], scored=b.get('scored_chunks_per_indicator'))))
    (OUT / f'comparacion_{before}_{after}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(rows, ensure_ascii=False, indent=1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label')
    parser.add_argument('--one', nargs=2)
    parser.add_argument('--compare', nargs=2)
    parser.add_argument('--index-only', choices=('load', 'open_mapped'))
    parser.add_argument('--float32-check')
    parser.add_argument('--chunks-only', choices=('full', 'light'))
    args = parser.parse_args()
    if args.chunks_only:
        return chunks_only(args.chunks_only)
    if args.float32_check:
        return float32_check(args.float32_check)
    if args.index_only:
        return index_only(args.index_only)
    if args.compare:
        return compare(*args.compare)
    if args.one:
        return one(*args.one, args.label)
    for kind, sid in SOURCES:
        subprocess.run([sys.executable, '-B', __file__, '--label', args.label, '--one', kind, sid], check=True, cwd=ROOT)


if __name__ == '__main__':
    main()
