"""Real end-to-end run of the main V5 flow with projects and articles (Qwen local).

Equivalent to answering S to the single run authorization of the interactive menu;
every other confirmation (for example a Knowledge rebuild) is answered NO. Not a
pytest module. Resumable: the same --run-id continues without repeating calls.

  uv run python tests/real_runs/run_v5_sources.py --run-id <id> --projects 21844 \
      --articles ART_2-s2.0-105001255605 --indicators CUL-02,SAL-02
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT), str(ROOT / 'scripts')]

MIN_FREE_MIB = 2048


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--projects', required=True)
    parser.add_argument('--articles')
    parser.add_argument('--indicators')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    import evaluate_source
    free = evaluate_source.free_mib()
    if free < MIN_FREE_MIB + 2048:
        raise SystemExit(f'Memoria libre {free:.0f} MiB: insuficiente para cargar Qwen con la reserva de {MIN_FREE_MIB} MiB')
    from scripts import pipeline_coordinator as engine

    def confirm(kind, summary):
        print(json.dumps(dict(confirm=kind, **{k: summary.get(k) for k in ('project_ids', 'article_ids', 'model', 'run_id')}),
                         ensure_ascii=False), flush=True)
        return kind == 'run'

    result = engine.execute_pipeline(ROOT, source=None if args.resume else 'base', run_id=args.run_id, through='export',
        resume=args.resume, project_ids=None if args.resume else args.projects.split(','),
        article_ids=None if args.resume or not args.articles else args.articles.split(','),
        indicator_ids=None if args.resume or not args.indicators else args.indicators.split(','),
        evaluation_mode=None if args.resume else 'prospective-v2', context_mode=None if args.resume else 'retrieved-graph',
        knowledge_action=None if args.resume else 'reuse', single_authorization=True, confirm=confirm,
        notify=lambda event: print(json.dumps({k: event.get(k) for k in ('status', 'stage', 'message')}, ensure_ascii=False), flush=True))
    print(json.dumps(result, ensure_ascii=False, indent=1, default=str)[:6000])
    print('free_mib_after', round(evaluate_source.free_mib()))


if __name__ == '__main__':
    main()
