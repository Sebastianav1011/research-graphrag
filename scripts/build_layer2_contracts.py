"""Export only Layer 2 JSON Schemas; never invoke Layer 1 contract generation."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from layer2_knowledge.contracts import SCHEMAS, logical_schema, manifest_schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    folder = ROOT / 'schemas/layer2'
    definitions = {name: logical_schema(name) for name in SCHEMAS} | {'layer2_manifest': manifest_schema()}
    if not args.check:
        folder.mkdir(parents=True, exist_ok=True)
    for name, schema in definitions.items():
        path = folder / (name + '.schema.json')
        if args.check:
            if json.loads(path.read_text(encoding='utf-8')) != schema:
                raise ValueError('Schema drift: ' + name)
        else:
            path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Layer 2 schemas: ' + ('consistent' if args.check else 'exported'))


if __name__ == '__main__':
    main()
