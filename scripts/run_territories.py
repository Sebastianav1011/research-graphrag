"""Offline Layer 4B territorial characterization from approved Layer 2 PROJECT."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from layer4.territories.pipeline import build


def main():
    try:
        print(json.dumps(build(ROOT), ensure_ascii=True))
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
