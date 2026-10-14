"""Inventory concrete file purposes and consumers; verify upstream without rebuilding."""
import argparse
import ast
from collections import Counter, defaultdict
import csv
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/repository_audit'
CLASSES = ('RUNTIME_ACTIVE','ENTRYPOINT_ACTIVE','TEST_ACTIVE','CONFIG_ACTIVE','SCHEMA_ACTIVE',
'DOCUMENTATION_ACTIVE','TEMPLATE_ACTIVE','OPERATIONAL_TOOL_ACTIVE','REPRODUCIBILITY_REQUIRED',
'PRIVATE_RUNTIME_DATA','GENERATED_REQUIRED','GENERATED_DISPOSABLE','HISTORICAL_RECORD_REQUIRED',
'ONE_OFF_OBSOLETE','LEGACY_OBSOLETE','DUPLICATE','UNREFERENCED','EMPTY_PLACEHOLDER_REQUIRED',
'EMPTY_UNNECESSARY','UNKNOWN')


def owned_files():
    errors = []
    for folder, dirs, files in os.walk(ROOT, followlinks=False, onerror=lambda e: errors.append(str(e))):
        dirs[:] = [d for d in dirs if d != '.git' and not (Path(folder)/d).is_junction()
                   and not (Path(folder)/d).is_symlink()]
        for name in files:
            path = Path(folder)/name
            if not path.is_symlink():
                yield path
    if errors:
        raise RuntimeError('Incomplete inventory: ' + '; '.join(errors))


def hash_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def protected_inventory():
    names = ('data/canonical','data/knowledge','src/layer1_data','src/layer2_knowledge',
             'tests/layer1','tests/layer2','config/layer1.yaml','config/layer2.yaml',
             'scripts/run_layer1.py','scripts/run_layer2.py')
    return {p.relative_to(ROOT).as_posix(): hash_file(p) for name in names
            for p in ([ROOT/name] if (ROOT/name).is_file() else sorted((ROOT/name).rglob('*')))
            if p.is_file() and '__pycache__' not in p.parts}


def purpose(name):
    """Unfamiliar paths fail review instead of receiving a generic generated classification."""
    if '__pycache__/' in name or name.endswith(('.pyc','.pyo')) or name.startswith(('.pytest_cache/','.mypy_cache/','.ruff_cache/')):
        return 'GENERATED_DISPOSABLE', 'Recreatable tooling cache'
    if name.startswith('.venv/'):
        return 'REPRODUCIBILITY_REQUIRED', 'Installed pinned environment: Python, dependency implementations, distribution metadata and resources'
    if name == '.env' or (name.startswith('.env.') and name != '.env.example'):
        return 'PRIVATE_RUNTIME_DATA', 'Private local environment configuration; contents not read by inventory'
    if name in ('.env.example','.gitignore','pytest.ini','requirements.txt','requirements-dev.txt'):
        return 'CONFIG_ACTIVE', 'Environment example, privacy boundary, test runner or distinct dependency entrypoint'
    if name.startswith('requirements/'):
        return 'REPRODUCIBILITY_REQUIRED', 'Portable embedding requirements or exact verified Windows/CUDA dependency lock'
    if name.startswith('config/'):
        return 'CONFIG_ACTIVE', 'Pipeline input/settings configuration; sources.synthetic.yaml is read by Layer1 test fixtures'
    if name.startswith('data/samples/synthetic/'):
        return 'TEST_ACTIVE', 'Static synthetic fixtures copied by tests/layer1/conftest.py; not institutional data'
    if name == 'data/raw/README.md':
        return 'DOCUMENTATION_ACTIVE', 'Instructions for supplying authorized local inputs'
    if name.startswith(('data/canonical/','data/knowledge/','data/graphrag/','data/reference/','data/raw/')):
        return 'PRIVATE_RUNTIME_DATA', 'Authorized input or immutable active publication consumed by pipelines and validators'
    if name.startswith('data/staging/'):
        return 'REPRODUCIBILITY_REQUIRED', 'Real staging snapshot read by audit_identity_alias_forensics.py to replay ingestion against identity decisions'
    if name == 'src/layer2_knowledge/README.md':
        return 'HISTORICAL_RECORD_REQUIRED', 'Frozen upstream package note protected by the 57-file baseline; current status belongs to docs/architecture'
    if name.startswith('src/') and name.endswith('.py'):
        return 'RUNTIME_ACTIVE', 'Imported pipeline implementation or required Python package initializer'
    if name == 'tests/layer2/.gitkeep':
        return 'REPRODUCIBILITY_REQUIRED', 'Frozen marker explicitly hashed in the upstream baseline; preserved to prove upstream unchanged'
    if name.startswith('tests/') and name.endswith('.py'):
        return 'TEST_ACTIVE', 'Pytest test or fixture for current contracts/runtime; integration explicitly opt-in'
    if name.startswith('schemas/') and name.endswith('.schema.json'):
        return 'SCHEMA_ACTIVE', 'Maintained contract export checked by its builder; indicator_profile is the approved pending reserve'
    if name == 'templates/resultado_final_indicadores.xlsx':
        return 'TEMPLATE_ACTIVE', 'Final empty workbook contract validated by verify_layer1/verify_layer2'
    if name.startswith('scripts/') and name.endswith(('.py','.ps1')):
        if Path(name).name in ('run_layer1.py','run_layer2.py','run_layer3.py'):
            return 'ENTRYPOINT_ACTIVE', 'Stable pipeline CLI documented in RUNBOOK'
        return 'OPERATIONAL_TOOL_ACTIVE', 'Reusable contract/publication/identity/repository/workbook tool documented in CODE_MAP'
    if name in ('docs/status/layer3_source_refactor_review.md','docs/identity_alias_audit.md'):
        return 'HISTORICAL_RECORD_REQUIRED', 'Methodological migration or conservative identity/bridge decision record; not current gate status'
    if name == 'README.md' or name.startswith('docs/'):
        return 'DOCUMENTATION_ACTIVE', 'Current architecture, contract, data dictionary, approved pending design or operating instructions'
    if name.startswith(('outputs/layer3/cache/','outputs/layer3/query_cache/')):
        return 'REPRODUCIBILITY_REQUIRED', 'Checksummed fingerprint-keyed embedding cache read by EmbeddingCache; prevents repeated inference'
    if name.startswith('outputs/layer3/models/'):
        if '/download_parts' in name or name.endswith(('.part','.candidate','.headers')):
            return 'GENERATED_DISPOSABLE', 'Transfer residue superseded by the complete verified weights'
        return 'REPRODUCIBILITY_REQUIRED', 'Pinned local model weights, pooling configuration or tokenizer read by the embedding provider'
    if name.startswith(('outputs/layer1/runs/','outputs/layer2/runs/','outputs/layer3/runs/')):
        return 'HISTORICAL_RECORD_REQUIRED', 'Real publication history: rollback snapshot, config and quality needed for reproducibility'
    if name.startswith('outputs/layer4/diagnostic_pre_source_refactor/'):
        return 'HISTORICAL_RECORD_REQUIRED', 'Benchmark inputs, labels and generating code audit the superseded design; no final assessment claim'
    if name == 'outputs/layer4/state.json':
        return 'GENERATED_REQUIRED', 'Pending state explicitly located in docs/architecture/layer4.md; no assessment execution'
    if name == 'outputs/layer3/reports/final_acceptance.json':
        return 'HISTORICAL_RECORD_REQUIRED', 'Acceptance of the previous real chunk-oriented publication; migration baseline, never source-level acceptance'
    prefixes = ('outputs/layer1/audit/','outputs/layer1/manifests/','outputs/layer1/quality/','outputs/layer1/reports/',
                'outputs/layer2/manifests/','outputs/layer2/quality/','outputs/layer2/reports/',
                'outputs/layer3/manifests/','outputs/layer3/quality/','outputs/layer3/reports/')
    if name.startswith(prefixes) or name == 'outputs/layer1/latest_run.json':
        return 'GENERATED_REQUIRED', 'Current publication diagnostics, technical gate evidence or reusable validator result; private and ignored'
    if name in ('outputs/repository_audit/file_inventory.csv','outputs/repository_audit/file_inventory_summary.json',
                'outputs/repository_audit/cleanup_changes.json','outputs/repository_audit/upstream_immutability.json',
                'outputs/repository_audit/upstream_before_source_refactor.json'):
        return 'GENERATED_REQUIRED', 'Current inventory, cleanup proof or protected upstream checksum baseline/result'
    return 'UNKNOWN', 'No approved purpose: must be reviewed or removed'


def dependencies(paths):
    texts = {}
    for p in paths:
        n = p.relative_to(ROOT).as_posix()
        if not n.startswith(('data/','outputs/','.venv/')) and n != 'config/sources.yaml' and p.suffix in ('.py','.md','.yaml','.json','.ps1','.txt','.ini'):
            texts[n] = p.read_text(encoding='utf-8-sig')
    modules = {n[4:-3].replace('/','.').removesuffix('.__init__'):n for n in texts if n.startswith('src/') and n.endswith('.py')}
    users, calls = defaultdict(set), {}
    for name,text in texts.items():
        if not name.endswith('.py'):
            continue
        tree = ast.parse(text)
        package = name[4:-3].replace('/','.').split('.')[:-1] if name.startswith('src/') else []
        if name.endswith('/__init__.py'):
            package = name[4:-12].replace('/','.').split('.')
        calls[name] = sorted({ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)})
        for node in ast.walk(tree):
            targets = []
            if isinstance(node,ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node,ast.ImportFrom):
                prefix = '.'.join(package[:len(package)-node.level+1]) if node.level else ''
                module = '.'.join(x for x in (prefix,node.module) if x)
                targets = [module] + [module+'.'+a.name for a in node.names]
            for target in targets:
                if target in modules:
                    users[modules[target]].add(name)
    return texts,users,calls


def inventory(output_name='file_inventory.csv'):
    if Path(output_name).name != output_name:
        raise ValueError('Output must be a filename inside outputs/repository_audit')
    OUT.mkdir(parents=True,exist_ok=True)
    target, summary_path = OUT/output_name, OUT/(Path(output_name).stem+'_summary.json')
    for p in (target,summary_path):
        p.touch(exist_ok=True)
    paths = sorted(owned_files())
    texts,users,calls = dependencies(paths)
    counts, unresolved = Counter(), []
    with target.open('w',encoding='utf-8-sig',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=['path','classification','purpose','imported_by','calls','referenced_in_docs','referenced_in_tests','generated_or_source'])
        writer.writeheader()
        for p in paths:
            name = p.relative_to(ROOT).as_posix()
            classification,reason = purpose(name)
            counts[classification] += 1
            if classification in ('UNKNOWN','GENERATED_DISPOSABLE','ONE_OFF_OBSOLETE','LEGACY_OBSOLETE','DUPLICATE','UNREFERENCED'):
                unresolved.append(name)
            references = [k for k,v in texts.items() if k != name and (name in v or p.name in v)]
            consumer = sorted(users.get(name,set()))
            if name.startswith('schemas/'):
                consumer += ['scripts/build_layer3_contracts.py' if '/layer3/' in name else 'scripts/build_layer2_contracts.py' if '/layer2/' in name else 'scripts/build_contracts.py']
            writer.writerow(dict(path=name,classification=classification,purpose=reason,imported_by=';'.join(consumer),
                calls=';'.join(calls.get(name,[])),referenced_in_docs=';'.join(k for k in references if k.endswith('.md')),
                referenced_in_tests=';'.join(k for k in references if k.startswith('tests/')),
                generated_or_source='managed_environment' if name.startswith('.venv/') else 'private' if name.startswith(('data/','outputs/')) and not name.startswith('data/samples/') else 'source'))
    directories,empty = [],[]
    for folder,children,files in os.walk(ROOT,followlinks=False):
        children[:] = [d for d in children if d != '.git' and not (Path(folder)/d).is_junction() and not (Path(folder)/d).is_symlink()]
        name = Path(folder).relative_to(ROOT).as_posix()
        directories.append(name)
        if not children and not files:
            empty.append(name)
    summary = dict(files=len(paths),directories=len(directories),empty_directories=empty,
        classifications={k:counts[k] for k in CLASSES},
        managed_environment_files=sum(p.relative_to(ROOT).as_posix().startswith('.venv/') for p in paths),
        scope='Entire workspace including environment; Git internals excluded; junctions/symlinks not followed',
        unresolved=unresolved,symlinks_junctions_followed=False)
    summary_path.write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary))
    if unresolved or empty:
        raise SystemExit(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['inventory','freeze-upstream','verify-upstream'],default='inventory')
    parser.add_argument('--output',default='file_inventory.csv')
    args = parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    baseline = OUT/'upstream_before_source_refactor.json'
    if args.mode == 'freeze-upstream':
        if baseline.exists():
            raise RuntimeError('Frozen baseline already exists')
        value = protected_inventory()
        baseline.write_text(json.dumps(value,indent=2),encoding='utf-8')
        print('UPSTREAM_FILES_FROZEN',len(value))
    elif args.mode == 'verify-upstream':
        before, after = json.loads(baseline.read_text()), protected_inventory()
        changes = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        result = dict(status='FAIL' if changes else 'PASS',protected_files=len(before),changes=changes)
        (OUT/'upstream_immutability.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
        raise SystemExit(bool(changes))
    else:
        inventory(args.output)

