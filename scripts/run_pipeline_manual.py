"""Local, explicit, run-isolated entry point. See docs/pipeline_manual.md."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from scripts.pipeline_coordinator import main

if __name__ == '__main__':
    raise SystemExit(main())
