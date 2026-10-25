"""Read-only fingerprint of the publications protected by territorial work."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = (
    'data/canonical', 'data/knowledge', 'data/graphrag',
    'src/layer3_graphrag', 'schemas/layer3', 'tests/layer3',
    'config/layer3.yaml', 'scripts/run_layer3.py', 'docs/architecture/layer3.md',
    'docs/architecture/layer3_source_level_acceptance.md',
)


def fingerprint(root=ROOT):
    result = {}
    for name in PROTECTED:
        target = root / name
        if not target.exists():
            raise ValueError(f'Missing protected input: {name}')
        files = sorted(target.rglob('*')) if target.is_dir() else [target]
        for path in files:
            if path.is_file() and '__pycache__' not in path.parts:
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result


if __name__ == '__main__':
    print(json.dumps(fingerprint(), sort_keys=True, indent=2))
