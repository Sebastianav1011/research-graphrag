"""Explicit stages. --execute is the only stage that invokes the authorized CLI."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from layer4_evaluation.indicators.preliminary import prepare,execute,verify,finalize

parser=argparse.ArgumentParser()
stages=parser.add_mutually_exclusive_group(required=True)
stages.add_argument('--prepare',action='store_true')
stages.add_argument('--execute',action='store_true')
stages.add_argument('--verify',action='store_true')
stages.add_argument('--finalize',action='store_true',help='Validate/export persisted responses; never execute LLM')
args=parser.parse_args()
try:
    result=prepare() if args.prepare else execute() if args.execute else finalize() if args.finalize else verify()
    print(json.dumps(result,ensure_ascii=True,indent=2))
except Exception as exc:
    print(json.dumps({'status':'BLOCKED_CODEX_CLI' if exc.__class__.__name__=='CodexCliBlocked' else 'BLOCKED',
                      'error':type(exc).__name__+': '+str(exc)[:1000]},ensure_ascii=True))
    raise SystemExit(2)
