"""Inventory/dry-run or explicitly apply a verified, narrowly scoped Layer 4 cleanup."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from layer4_evaluation.indicators import cleanup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    audit = sub.add_parser('inventory')
    audit.add_argument('--output', type=Path, required=True)
    dry = sub.add_parser('plan')
    dry.add_argument('--inventory', type=Path, required=True)
    dry.add_argument('--directory', action='append', required=True)
    dry.add_argument('--output', type=Path, required=True)
    delete = sub.add_parser('apply')
    delete.add_argument('--plan', type=Path, required=True)
    delete.add_argument('--backup', type=Path, required=True)
    delete.add_argument('--journal', type=Path, required=True)
    recovery = sub.add_parser('restore')
    recovery.add_argument('--journal', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'inventory':
        result = cleanup.inventory(ROOT)
    elif args.command == 'plan':
        result = cleanup.plan(ROOT, json.loads(args.inventory.read_text(encoding='utf-8')), args.directory)
    elif args.command == 'apply':
        result = cleanup.apply(ROOT, json.loads(args.plan.read_text(encoding='utf-8')), args.backup, args.journal)
    else:
        result = cleanup.restore(ROOT, json.loads(args.journal.read_text(encoding='utf-8')))
    if args.command in ('inventory', 'plan'):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'status': 'DRY_RUN', 'output': str(args.output)}))
    else:
        print(json.dumps(result if args.command == 'restore' else
                         {'status': result['status'], 'deleted': result['deleted'], 'backup': result['backup']}))


if __name__ == '__main__':
    main()
