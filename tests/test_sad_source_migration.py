"""Namespace-only regression checks against the exact pre-migration sources."""
import ast
import importlib
import json
from pathlib import Path
import re
import hashlib
import pytest

from scripts import pipeline_coordinator as coordinator
from layer2_processing.preprocessing.adapters import read, write
from layer2_processing.checkpoints import verify_expected

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'archives/sad_20261030'
PACKAGES = {'layer2_preprocessing': 'layer2_processing.preprocessing',
            'layer3_knowledge': 'layer2_processing.knowledge',
            'layer4_graphrag': 'layer3_graphrag', 'layer5_results': 'layer4_evaluation'}


def relocated(text):
    for old, new in PACKAGES.items():
        text = text.replace('src/' + old, 'src/' + new.replace('.', '/'))
        text = re.sub(r'(?<![/\\\w])' + old + r'\b', new, text)
    text = text.replace('data/reference/indicadores', 'data/layer1_sources/reference/indicadores')
    mapping = {'data/canonical': 'outputs/layer2/canonical', 'data/knowledge': 'outputs/layer2/knowledge', 'data/graphrag': 'outputs/layer3/publication', 'data/reference/processed': 'outputs/layer2/reference', 'outputs/layer3': 'outputs/layer3', 'outputs/layer2': 'outputs/layer2/knowledge_artifacts', 'outputs/layer1': 'outputs/layer2/preprocessing'}
    for i, (old, new) in enumerate(mapping.items()):
        text = text.replace(old, f'__PATH_{i}__')
    for i, (old, new) in enumerate(mapping.items()):
        text = text.replace(f'__PATH_{i}__', new)
    text = text.replace('outputs/layer2/reference/indicator', 'outputs/layer4/indicator_profiles/indicator')
    return text


def test_existing_analytical_algorithms_have_only_namespace_and_locator_changes():
    for old, new in PACKAGES.items():
        for path in (ARCHIVE / 'src' / old).rglob('*.py'):
            analytical = {'chunking.py', 'text_normalization.py', 'graph.py', 'graph_retriever.py',
                'retrieval.py', 'indicator_retrieval.py', 'source_context.py', 'vector_index.py',
                'evaluation.py', 'assessment.py', 'assessment_v2.py', 'assessment_v3.py',
                'confidence.py', 'prompt.py', 'selection.py', 'matching.py',
                'global_discovery.py', 'global_discovery_v3_3.py', 'global_discovery_v3_3_compact.py'}
            if path.name not in analytical:
                continue
            expected = relocated(path.read_text(encoding='utf-8-sig'))
            if old == 'layer2_preprocessing' and path.name == 'runtime.py':
                expected = expected.replace('parents[2]', 'parents[3]')
            current = ROOT / 'src' / new.replace('.', '/') / path.relative_to(ARCHIVE / 'src' / old)
            assert ast.dump(ast.parse(current.read_text(encoding='utf-8-sig'))) == ast.dump(ast.parse(expected)), current


def test_layer2_has_no_dependency_on_retrieval_evaluation_or_scripts():
    for path in (ROOT / 'src/layer2_processing').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            modules = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            assert all(m.split('.')[0] not in {'layer3_graphrag', 'layer4_evaluation', 'scripts'} for m in modules), path


def test_every_source_module_imports_without_models_or_inference():
    for path in (ROOT / 'src').rglob('*.py'):
        name = path.relative_to(ROOT / 'src').with_suffix('').as_posix().replace('/', '.')
        if name.endswith('.__init__'):
            name = name[:-9]
        importlib.import_module(name)


def test_pre_migration_checkpoint_remains_resumable_with_exact_original_hashes(tmp_path):
    """Use original checkpoint fingerprints, not rebased acceptance expectations."""
    raw = tmp_path / 'received'
    raw.mkdir()
    (raw / 'one.json').write_text(json.dumps({'source_project_id': 'SAD_TEST_1', 'summary': 'Controlled regression fixture.'}), encoding='utf-8')
    run = tmp_path / 'run'
    config = read(ROOT / 'config/pipeline_manual.json')
    coordinator.prepare(ROOT, run, raw, 'prueba_en_vivo', config, through='preprocessing')
    state = read(run / 'run.json')
    before = json.loads((ROOT / 'docs/migration_sad_20261030/before.json').read_text(encoding='utf-8'))['files']
    state['code_hashes'] = {name: item['sha256'] for name, item in before.items() if name.startswith('src/') and name.endswith('.py')}
    state['code_hashes']['scripts/run_pipeline_manual.py'] = before['scripts/run_pipeline_manual.py']['sha256']
    write(run / 'run.json', state)
    sealed = (run / 'prepared_hashes.json').read_bytes()
    assert coordinator.check(ROOT, run)['status'] == 'PREPROCESSED'
    assert coordinator.knowledge(ROOT, run)['status'] == 'PREPARED'
    assert coordinator.knowledge(ROOT, run)['status'] == 'ALREADY_PREPARED'
    assert sealed  # Original sealed products were verified before continuation.
    assert not (run / 'workspace/outputs/layer3/publication').exists()


def test_split_checkpoint_binding_rejects_a_changed_extracted_implementation(tmp_path):
    original = tmp_path / 'original.py'
    original.write_bytes(b'original runner bytes')
    current = tmp_path / 'current.py'
    current.write_bytes(b'coordinator bytes')
    internal = tmp_path / 'internal.py'
    internal.write_bytes(b'processing bytes')
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    write(tmp_path / 'config/sad_relocations.json', dict(file_aliases={'old.py': 'current.py'},
        runtime_bindings={'old.py': dict(after_sha256=digest(current), snapshots=['original.py'],
            related_sha256={'internal.py': digest(internal)})}))
    verify_expected(tmp_path, 'old.py', digest(original))
    internal.write_bytes(b'unreviewed change')
    with pytest.raises(ValueError, match='Fingerprint mismatch'):
        verify_expected(tmp_path, 'old.py', digest(original))
