"""Structural checks only. No production embeddings, models or LLM calls."""
import hashlib
import importlib
import json
from pathlib import Path

import pytest

from scripts import pipeline_coordinator as runner
from layer2_processing.preprocessing.adapters import inventory
from layer2_processing.checkpoints import resolve
from .test_manual_pipeline import sandbox, project

ROOT = Path(__file__).resolve().parents[1]


def test_only_canonical_packages_and_physical_raw():
    assert (ROOT / 'data/layer1_sources').is_dir()
    assert not (ROOT / 'data/layer1_sources').is_junction()
    assert not (ROOT / 'capa_1_raw').exists()
    assert not (ROOT / 'src/layer1_raw').exists()
    for retired in ('layer1_raw', 'layer1_data', 'layer2_knowledge', 'layer2_preprocessing',
                    'layer3_knowledge', 'layer4_graphrag', 'layer5_results', 'manual_pipeline', 'layer4', 'pipeline_compat'):
        assert importlib.util.find_spec(retired) is None
    for folder in (ROOT / 'src', ROOT / 'tests'):
        assert not any(p.is_junction() for p in folder.iterdir())
    assert {p.name for p in (ROOT / 'src').iterdir() if p.is_dir() and p.name != '__pycache__'} == {
        'layer2_processing', 'layer3_graphrag', 'layer4_evaluation'}
    assert (ROOT / 'src/layer2_processing/preprocessing').is_dir()
    assert (ROOT / 'src/layer2_processing/knowledge').is_dir()
    assert runner.processing.prepare.__module__ == 'layer2_processing.pipeline'
    assert runner.processing.knowledge.__module__ == 'layer2_processing.pipeline'
    assert runner.graph.__module__ == 'scripts.pipeline_coordinator'


def test_official_raw_configuration_has_no_alternate_location(sandbox):
    root, raw, config = sandbox
    assert config['raw_base'] == 'data/layer1_sources'
    assert runner.configuration(root, 'config/pipeline_manual.json')[1] == (root / 'data/layer1_sources').resolve()
    previous = root / 'config/previous_location.json'
    previous.write_text(json.dumps(config | {'raw_base': 'capa_1_raw'}), encoding='utf-8')
    with pytest.raises(ValueError):
        runner.configuration(root, 'config/previous_location.json')


def test_all_sources_compile_and_only_import_canonical_layers():
    import ast
    retired = {'layer1_data', 'layer2_knowledge', 'layer2_preprocessing', 'layer3_knowledge',
               'layer4_graphrag', 'layer5_results', 'manual_pipeline', 'layer4', 'pipeline_compat'}
    for directory in ('src', 'scripts'):
        for path in (ROOT / directory).rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
            compile(tree, str(path), 'exec')
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert node.module.split('.')[0] not in retired, path
                elif isinstance(node, ast.Import):
                    assert all(n.name.split('.')[0] not in retired for n in node.names), path


def test_official_input_copies_still_match_original_hashes():
    records = json.loads((ROOT / 'docs/architecture/auditoria_consolidacion/raw_importados.json').read_text(encoding='utf-8'))
    assert len(records) == 3
    for record in records:
        assert hashlib.sha256(resolve(ROOT, record['official_path']).read_bytes()).hexdigest() == record['sha256']
        assert hashlib.sha256(Path(record['source']).read_bytes()).hexdigest() == record['sha256']


def test_confidence_arithmetic_unchanged():
    import ast
    old = ROOT / 'archives/architecture_20261029/src/layer5_results/indicators/assessment_v3.py'
    current = ROOT / 'src/layer4_evaluation/indicators/assessment_v3.py'
    def arithmetic(path):
        return ast.dump(next(n for n in ast.parse(path.read_text(encoding='utf-8')).body
                             if isinstance(n, ast.FunctionDef) and n.name == 'confidence'))
    assert arithmetic(old) == arithmetic(current)


def test_preprocessing_and_knowledge_are_independent_and_idempotent(sandbox):
    root, raw, config = sandbox
    source = raw / 'nuevo.json'
    source.write_text(json.dumps(project()), encoding='utf-8')
    before = source.read_bytes()
    assert inventory(root, 'prueba_en_vivo')['files'][0]['name'] == 'nuevo.json'
    run = root / 'outputs/runs/separate'
    result = runner.prepare(root, run, raw, 'prueba_en_vivo', config, through='preprocessing')
    assert result['status'] == 'PREPROCESSED'
    assert (run / 'workspace/outputs/layer2/canonical/proyectos.parquet').exists()
    assert not (run / 'workspace/outputs/layer2/knowledge').exists()
    with pytest.raises(ValueError, match='knowledge'):
        runner.graph(root, run)
    canonical = (run / 'workspace/outputs/layer2/canonical/proyectos.parquet').read_bytes()
    assert runner.prepare(root, run, raw, 'prueba_en_vivo', config, through='preprocessing')['status'] == 'ALREADY_PREPARED'
    assert runner.knowledge(root, run)['status'] == 'PREPARED'
    manifest = (run / 'workspace/outputs/layer2/knowledge/_manifest.json').read_bytes()
    assert runner.knowledge(root, run)['status'] == 'ALREADY_PREPARED'
    assert (run / 'workspace/outputs/layer2/knowledge/_manifest.json').read_bytes() == manifest
    assert (run / 'workspace/outputs/layer2/canonical/proyectos.parquet').read_bytes() == canonical
    assert source.read_bytes() == before
    runner.graph(root, run)


def test_full_coordinator_stops_at_selected_checkpoint(sandbox, monkeypatch):
    root, raw, _ = sandbox
    (raw / 'nuevo.json').write_text(json.dumps(project()), encoding='utf-8')
    monkeypatch.setattr(runner, 'ROOT', root)
    assert runner.main(['run', '--dataset', 'prueba_en_vivo', '--run-id', 'steps', '--through', 'preprocessing']) == 0
    run = root / 'outputs/runs/steps'
    assert not (run / 'workspace/outputs/layer2/knowledge').exists()
    assert runner.main(['run', '--dataset', 'prueba_en_vivo', '--run-id', 'steps', '--through', 'knowledge']) == 0
    assert (run / 'workspace/outputs/layer2/knowledge/source_documents.parquet').exists()
    assert runner.main(['run', '--dataset', 'prueba_en_vivo', '--run-id', 'steps', '--through', 'results', '--authorize']) == 2
    assert not (run / 'workspace/outputs/layer3/publication').exists()
    assert not list(run.rglob('dispatch.claim.json'))


def test_canonical_entrypoints_in_windows_powershell(sandbox):
    import shutil
    import subprocess
    root, raw, _ = sandbox
    (raw / 'nuevo.json').write_text(json.dumps(project()), encoding='utf-8')
    python = str(ROOT / '.venv/Scripts/python.exe').replace("'", "''")
    commands = []
    for operation in ('raw', 'preprocess', 'knowledge', 'verify'):
        commands.append(f"& '{python}' -B scripts/run_pipeline_manual.py {operation} --dataset prueba_en_vivo --run-id canonical_windows\nif ($LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', '\n'.join(commands)], cwd=root,
        text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    run = root / 'outputs/runs/canonical_windows'
    assert (run / 'workspace/outputs/layer2/knowledge/source_chunks.parquet').exists()
    assert not (run / 'workspace/outputs/layer3/publication').exists()


def test_run_reuses_saved_authorization_without_requesting_again(sandbox, monkeypatch):
    root, raw, config = sandbox
    (raw / 'nuevo.json').write_text(json.dumps(project()), encoding='utf-8')
    run = root / 'outputs/runs/resume'
    runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    batch = run / 'layer5_results' / runner.batch_name(['000701'])
    batch.mkdir(parents=True)
    (batch / 'review.txt').write_text('previously reviewed', encoding='utf-8')
    (batch / 'authorization.json').write_text('{}', encoding='utf-8')
    graph = run / 'workspace/outputs/layer3/publication'
    graph.mkdir(parents=True)
    (graph / '_manifest.json').write_text('{}', encoding='utf-8')
    calls = []

    def simulated_evaluation(root, run, selected, authorize=False, execute=False):
        calls.append((authorize, execute))
        return {'status': 'COMPLETE'}

    # Only test coordination: actual executor still validates authorization hash/content.
    monkeypatch.setattr(runner, 'ROOT', root)
    monkeypatch.setattr(runner, 'graph', lambda *a, **k: {'status': 'SUCCESS'})
    monkeypatch.setattr(runner, 'evaluate', simulated_evaluation)
    monkeypatch.setattr(runner, 'export', lambda *a: {'status': 'COMPLETE'})
    assert runner.main(['run', '--dataset', 'prueba_en_vivo', '--run-id', 'resume', '--through', 'results']) == 0
    assert calls == [(False, False), (False, True)]
