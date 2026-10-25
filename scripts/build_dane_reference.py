"""Build the independent Layer 1 DANE reference from the supplied local workbook."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from layer1_data.dane_reference import build_reference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    _, manifest = build_reference(ROOT, args.source, args.output)
    print("DANE_REFERENCE_V1_READY", manifest["reference_id"])
    print("Departments:", manifest["department_count"], "municipalities:", manifest["municipality_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
