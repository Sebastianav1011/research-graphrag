"""Safe CLI: defaults to configuration-only preparation plan."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from layer3_graphrag.pipeline import run
from layer3_graphrag.operations import verify,compare,regressions,approve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['plan','validate','build','query','evaluate','verify','compare','test','setup-model','approve'], default='plan')
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--real-integration',action='store_true')
    parser.add_argument('--config', default='config/layer3.yaml')
    parser.add_argument('--query')
    parser.add_argument('--query-id')
    parser.add_argument('--retrieval-mode', choices=['vector', 'graph', 'hybrid'], default='hybrid')
    parser.add_argument('--seed-entity', action='append')
    parser.add_argument('--queries')
    args = parser.parse_args()
    try:
        if args.mode=='approve': result=approve(ROOT,args.manifest_sha256,args.config)
        elif args.mode=='verify': result=verify(ROOT,args.config)
        elif args.mode=='compare': result=compare(ROOT,args.config)
        elif args.mode=='test': result=regressions(ROOT,args.real_integration)
        elif args.mode=='setup-model':
            from layer3_graphrag.model_setup import setup
            result=setup(ROOT)
        else: result = run(ROOT, args.config, args.mode, query_text=args.query, query_id=args.query_id,
                     retrieval_mode=args.retrieval_mode, seed_entity_ids=args.seed_entity, queries_path=args.queries)
        if args.mode == 'query':
            # Context packages are private files; stdout contains only aggregate locators/counts.
            result = {'query_id': result['query_id'], 'source_chunks': len(result['retrieved_chunks']),
                      'candidate_sources':len(result['source_candidates']), 'source_contexts':len(result['source_contexts']),
                      'reference_chunks': len(result['reference_context']), 'saved_to': 'outputs/layer3/reports/'}
        elif args.mode=='build':
            result={k:result[k] for k in ('status','layer3_run_id','pipeline_version','candidate_architecture','candidate_count','context_package_count')}
        print(json.dumps(result, ensure_ascii=True))
    except (ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({'status': 'BLOCKED_OR_FAILED', 'error': str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
