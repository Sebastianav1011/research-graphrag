"""Maintain/check Layer 3 schemas without touching data or upstream contracts."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from layer3_graphrag.contracts import context_schema, embedding_schema, evaluation_query_schema, layer3_manifest_schema
from layer3_graphrag.contracts import arrow_json_schema,source_candidate_arrow_schema,source_context_arrow_schema
from layer3_graphrag.provenance import serialize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    directory = ROOT / 'schemas/layer3'
    schemas = {'embedding': embedding_schema(), 'context_package': context_schema(),
               'evaluation_query': evaluation_query_schema(), 'layer3_manifest': layer3_manifest_schema()}
    schemas.update(source_indicator_candidate=arrow_json_schema(source_candidate_arrow_schema()),
        source_context_package=arrow_json_schema(source_context_arrow_schema()))
    for name, schema in schemas.items():
        path = directory / (name + '.schema.json')
        expected = serialize(schema) + '\n'
        if args.check:
            if not path.is_file() or path.read_text(encoding='utf-8') != expected:
                raise ValueError('Layer 3 schema drift: ' + name)
        else:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding='utf-8')
    print('Layer 3 schemas: ' + ('CHECKED' if args.check else 'PREPARED'))


if __name__ == '__main__':
    main()
