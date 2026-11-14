"""Reviewed historical retention; simulation is the default, no model/network use."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
import run_retention as retention

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy',default='config/retention.example.json')
    parser.add_argument('--apply',action='store_true',help='Archive evidence, then recycle reviewed inactive runs')
    parser.add_argument('--archive',help='New ZIP under outputs/historico/compactados; or existing ZIP to verify/extract')
    parser.add_argument('--journal',help='New JSON under outputs/runs/.storage-events (required for apply)')
    parser.add_argument('--verify',action='store_true')
    parser.add_argument('--extract-run',help='Provider bucket/run ID from archive')
    parser.add_argument('--destination',help='New destination for historical evidence, never a live run')
    parser.add_argument('--prune-document-cache',action='store_true',help='Verify coverage and configured cache limits; simulate by default')
    args=parser.parse_args()
    if args.verify or args.extract_run:
        if args.apply or not args.archive:parser.error('Verification/extraction requires --archive and forbids --apply')
        if args.extract_run:
            if not args.destination:parser.error('--destination required')
            dest=Path(args.destination).resolve()
            if dest.is_relative_to(ROOT/'outputs/runs'):parser.error('Cannot extract into active runs')
            print(retention.extract_evidence(ROOT/args.archive,args.extract_run,dest))
        else:
            data=retention.verify_archive(ROOT/args.archive)
            print(json.dumps(dict(status='VERIFIED',runs=len(data['runs']),objects=len(data['objects']))))
        return
    policy=json.loads((ROOT/args.policy).read_text(encoding='utf-8'))
    if args.prune_document_cache:
        if args.apply and not args.journal:parser.error('--journal required for cache recycling')
        result=retention.prune_document_cache(ROOT,policy,ROOT/args.journal) if args.apply else retention.document_cache_plan(ROOT,policy)
        print(json.dumps({k:v for k,v in result.items() if k not in ('inventory','checksums','bundles')},ensure_ascii=False,indent=2))
        return
    if args.apply:
        if not args.archive or not args.journal:parser.error('--archive and --journal required')
        result=retention.apply(ROOT,policy,ROOT/args.archive,ROOT/args.journal)
    else:
        result=dict(status='DRY_RUN',runs=[{k:v for k,v in r.items() if k!='inventory'} for r in retention.plan(ROOT,policy)])
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
