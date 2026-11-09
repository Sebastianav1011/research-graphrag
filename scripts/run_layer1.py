"""Thin CLI; all ETL orchestration lives in layer2_processing.preprocessing.pipeline."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from layer2_processing.preprocessing.pipeline import run


def main():
    parser = argparse.ArgumentParser(description="Run the deterministic data layer")
    parser.add_argument("--config", default="config/sources.yaml")
    parser.add_argument("--settings", default="config/layer1.yaml")
    args = parser.parse_args()
    result = run(ROOT, args.config, args.settings)
    print(f"run_id={result['run_id']} status={result['status']}")
    return 0 if result["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

