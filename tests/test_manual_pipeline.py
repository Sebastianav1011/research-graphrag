"""Small new-document integration checks; no model downloads, embeddings or LLM."""
import json
from pathlib import Path
import shutil
import zipfile

import openpyxl
import pyarrow.parquet as pq
import pytest

from scripts import pipeline_coordinator as runner
from layer2_processing.preprocessing.adapters import prepare_files, read, sha, tabular

SOURCE = Path(__file__).resolve().parents[1]


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / 'isolated repo with spaces'
    shutil.copytree(SOURCE / 'src', root / 'src', ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
    for name in ('sources.example.yaml', 'layer1.yaml', 'layer2.yaml', 'layer3.yaml', 'pipeline_manual.json'):
        destination = root / 'config' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / 'config' / name, destination)
    for name in ('run_pipeline_manual.py', 'pipeline_coordinator.py'):
        destination = root / 'scripts' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / 'scripts' / name, destination)
    for name in ('catalogo_indicadores.xlsx', 'catalogo_indicadores_v2.xlsx'):
        destination = root / 'data/layer1_sources/reference/indicadores' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / 'data/layer1_sources/reference/indicadores' / name, destination)
    raw = root / 'tests/fixtures/prueba_en_vivo'
    raw.mkdir(parents=True)
    (root / 'data/layer1_sources/base').mkdir(parents=True)
    return root, raw, read(root / 'config/pipeline_manual.json')


def project(identity='000701'):
    return {'siap_id': identity, 'title': 'Proyecto mínimo nuevo', 'summary': 'Texto documental recibido para validar la integración.',
        'methodology': 'Se revisarán registros.', 'objectives': 'Describir los datos.', 'expected_results': None, 'keywords': ['prueba', 'datos']}


def test_prepare_graph_boundary_and_empty_export(sandbox):
    root, raw, config = sandbox
    path = raw / 'recibido.json'
    path.write_text(json.dumps(project(), ensure_ascii=False), encoding='utf-8')
    before = sha(path)
    run = root / 'outputs/runs/test'
    result = runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    assert result['counts']['proyectos'] == 1
    assert sha(path) == before
    row = pq.read_table(run / 'workspace/outputs/layer2/canonical/proyectos.parquet').to_pylist()[0]
    assert row['source_project_id'] == '000701' and row['project_id'] == 'PROJ_000701'
    refs = json.loads(row['provenance_json'])
    assert refs[0]['record_source'] == str(path) and refs[0]['source_row'] == 1
    assert refs[0]['field_mapping']['summary'] == 'summary'
    chunks = pq.read_table(run / 'workspace/outputs/layer2/knowledge/source_chunks.parquet').to_pylist()
    assert chunks and all(json.loads(c['provenance_json'])['layer1'][0]['record_source'] == str(path) for c in chunks)
    validation = runner.graph(root, run)
    assert validation['status'] == 'VALIDATED_APPROVED_LAYER_2_INPUT'
    assert not (run / 'workspace/outputs/layer3/publication').exists()
    export = runner.export(root, run)
    assert export['relationships'] == 0 and export['status'] == 'PARTIAL'
    book = openpyxl.load_workbook(export['excel'])
    assert book.sheetnames == ['RESULTADO_INDICADORES', 'TERRITORIOS']
    assert list(next(book.worksheets[0].values)) == runner.COLUMNS
    assert book.worksheets[0].max_row == 1
    book.close()
    assert not (root / 'outputs/layer2/canonical').exists() and not (root / 'outputs/layer2/knowledge').exists()
    assert runner.prepare(root, run, raw, 'prueba_en_vivo', config)['status'] == 'ALREADY_PREPARED'
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='RAW cambio'):
        runner.check(root, run)


def test_institutional_csv_join_duplicates_and_sources(sandbox):
    root, raw, config = sandbox
    (raw / 'descriptores-limpio.csv').write_text('id_actividad,resumen,metodologia,objetivos\n0009,Texto real,Método,Objetivo\n0009,Texto real,Método,Objetivo\n', encoding='utf-8')
    (raw / 'miembros-doc-limpio.csv').write_text('id_actividad,id_empleado,nombre_completo,titulo,rol_miembro\n0009,EMP01,Nombre Persona,Título aportado,Investigador\n', encoding='utf-8')
    (raw / 'produccion-limpio.csv').write_text('source_article_id,nombre_producto,resumen,doi,investigador_docente,cedula\n00012,Artículo,Texto publicación,10.0000/example,Nombre Persona,\n', encoding='utf-8')
    run = root / 'outputs/runs/join'
    result = runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    assert result['counts']['proyectos'] == 1 and result['counts']['articulos'] == 1
    folder = run / 'workspace/outputs/layer2/canonical'
    projects = pq.read_table(folder / 'proyectos.parquet').to_pylist()
    assert projects[0]['title'] == 'Título aportado' and projects[0]['source_project_id'] == '0009'
    assert pq.read_table(folder / 'articulos.parquet').to_pylist()[0]['source_article_id'] == '00012'
    assert len(json.loads(projects[0]['provenance_json'])) >= 2
    assert pq.read_table(folder / 'proyecto_investigador.parquet').num_rows == 1
    knowledge = run / 'workspace/outputs/layer2/knowledge'
    relations = pq.read_table(knowledge / 'relations.parquet').to_pylist()
    assert all(r['relation_type'] in ('PROJECT_HAS_RESEARCHER', 'ARTICLE_HAS_RESEARCHER') for r in relations)
    assert not any('PROJECT' in r['relation_type'] and 'ARTICLE' in r['relation_type'] for r in relations)
    runner.graph(root, run)


@pytest.mark.parametrize('kind', ['empty', 'no_id', 'bad_json', 'alias_conflict', 'unsupported'])
def test_invalid_never_falls_back(sandbox, kind):
    root, raw, config = sandbox
    if kind == 'no_id':
        value = project()
        value.pop('siap_id')
        (raw / 'bad.json').write_text(json.dumps(value), encoding='utf-8')
    elif kind == 'bad_json':
        (raw / 'bad.json').write_text('{', encoding='utf-8')
    elif kind == 'alias_conflict':
        (raw / 'bad.json').write_text(json.dumps(project() | {'id_actividad': 'DIFFERENT'}), encoding='utf-8')
    elif kind == 'unsupported':
        (raw / 'bad.exe').write_bytes(b'test')
    run = root / 'outputs/runs/bad'
    with pytest.raises(ValueError):
        runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    assert read(run / 'run.json')['status'] == 'FAILED'
    assert not (run / 'workspace/outputs/layer2/knowledge').exists()


def test_xlsx_docx_and_formula_guard(sandbox):
    root, raw, config = sandbox
    book = openpyxl.Workbook()
    ws = book.active
    ws.append(['siap_id', 'title', 'summary'])
    ws.append([7, 'Título de Excel', 'Texto de Excel'])
    ws['A2'].number_format = '00000'
    book.save(raw / 'entrada.xlsx')
    book.close()
    _, rows, _ = tabular(raw / 'entrada.xlsx')
    assert rows[0][1]['siap_id'] == '00007'
    with zipfile.ZipFile(raw / 'entrada.docx', 'w') as archive:
        lines = ['ID SIAP: 00008', 'Título: Documento Word', 'Resumen: Texto de Word', 'Objetivos: Revisar registros']
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        xml += ''.join('<w:p><w:r><w:t>' + s + '</w:t></w:r></w:p>' for s in lines)
        archive.writestr('word/document.xml', xml + '</w:body></w:document>')
    run = root / 'outputs/runs/formats'
    assert runner.prepare(root, run, raw, 'prueba_en_vivo', config)['counts']['proyectos'] == 2
    assert (run / 'preprocess/extracted/1.txt').exists()
    runner.graph(root, run)
    book = openpyxl.load_workbook(raw / 'entrada.xlsx')
    book.active['C2'] = '=1+1'
    book.save(raw / 'entrada.xlsx')
    book.close()
    with pytest.raises(ValueError, match='Formula'):
        tabular(raw / 'entrada.xlsx')


def test_output_paths_cannot_target_history(sandbox):
    root, _, config = sandbox
    path = root / 'config/unsafe.json'
    path.write_text(json.dumps(config | {'runs_base': 'outputs/layer4'}), encoding='utf-8')
    with pytest.raises(ValueError):
        runner.configuration(root, 'config/unsafe.json')


def test_real_stage_wiring_with_injected_test_embeddings(tmp_path, monkeypatch):
    """Actual existing build/retrieval path, synthetic vectors; never a real result."""
    import hashlib
    import numpy as np
    import yaml
    from layer3_graphrag.embeddings import EmbeddingProvider
    from layer3_graphrag.pipeline import run as build

    class TestProvider(EmbeddingProvider):
        model_name = 'LOCAL_TEST_ONLY'
        model_version = 'TEST_VECTORS_NO_SEMANTIC_MEANING'
        dimensions = 4
        batch_size = 4

        def embed_documents(self, texts):
            return np.asarray([[1 + b for b in hashlib.sha256(t.encode()).digest()[:4]] for t in texts], dtype=np.float32).reshape(-1, 4)

        def embed_queries(self, texts):
            return self.embed_documents(texts)

    # basetemp is explicitly inside this workspace; actual frozen reference configuration
    # can be verified without copying/modifying it or consulting old project caches.
    assert tmp_path.resolve().is_relative_to(SOURCE)
    raw = tmp_path / 'raw'
    raw.mkdir()
    additional = 'Se documentó un resultado adicional con referencia a la fuente.'
    (raw / 'fresh.json').write_text(json.dumps(project() | {'resultado': additional}), encoding='utf-8')
    run = tmp_path / 'run'
    config = read(SOURCE / 'config/pipeline_manual.json')
    runner.prepare(SOURCE, run, raw, 'prueba_en_vivo', config)
    workspace = run / 'workspace'
    settings = yaml.safe_load((workspace / 'config/layer3.yaml').read_text(encoding='utf-8'))
    settings['execution']['allow_real_build'] = True
    settings['embeddings'].update(model=TestProvider.model_name, model_version=TestProvider.model_version, dimensions=4)
    (workspace / 'config/layer3.test.yaml').write_text(yaml.safe_dump(settings), encoding='utf-8')
    result = build(workspace, config_path='config/layer3.test.yaml', mode='build', provider=TestProvider())
    assert result['status'] == 'SUCCESS'
    assert (workspace / 'outputs/layer3/publication/retrieval/source_context_packages.parquet').exists()
    contexts = pq.read_table(workspace / 'outputs/layer3/publication/retrieval/source_context_packages.parquet').to_pylist()
    assert any('text__resultado' in c['available_field_names'] for c in contexts)
    with pytest.raises(ValueError, match='incompatible'):
        runner.prepare_evaluation(SOURCE, run, ['000701'])
    # Explicit test seam: no production CLI can select this provider or bypass this gate.
    from layer3_graphrag.manifest import validate_publication
    monkeypatch.setattr(runner, 'validated_graph', lambda root, folder: validate_publication(workspace / 'outputs/layer3/publication', sha(workspace / 'outputs/layer2/knowledge/_manifest.json')))
    batch = runner.prepare_evaluation(SOURCE, run, ['000701'])
    engine = runner.engine(SOURCE, run)
    plan = engine.check(engine.BASE / batch)
    assert len(plan['profiles']) == 48 and plan['projects'][0]['siap_id'] == '000701'
    assert plan['projects'][0]['fields']['summary'] == project()['summary']
    assert plan['projects'][0]['fields']['text__resultado'] == additional
    request = engine.request_for(plan, plan['projects'][0], 'discovery', [])
    assert request['payload']['project']['fields']['text__resultado'] == additional
    assert engine.verify_run(engine.BASE / batch)['new_calls'] == 0
    with pytest.raises(ValueError, match='autorizacion'):
        runner.evaluate(SOURCE, run, ['000701'], execute=True)
    assert not list(engine.BASE.rglob('dispatch.claim.json'))
    assert runner.export(SOURCE, run)['relationships'] == 0
    assert not list(engine.BASE.rglob('authorization.json'))


@pytest.mark.parametrize('blocked', [False, True])
def test_export_keeps_partial_evidence_and_original_numeric_score(sandbox, monkeypatch, blocked):
    """Real V3 validation/arithmetic on an existing synthetic fixture; no model call."""
    import importlib.util
    from types import SimpleNamespace
    from layer4_evaluation.indicators import assessment_v3 as v3
    from layer4_evaluation.indicators.review import evidence_locations
    root, raw, config = sandbox
    (raw / 'project.json').write_text(json.dumps(project()), encoding='utf-8')
    run = root / 'outputs/runs/export'
    runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    spec = importlib.util.spec_from_file_location('existing_v3_test_fixture', SOURCE / 'tests/layer5_experiment/test_assessment_v3.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    case = fixture.case.__wrapped__()
    assessment = case['assessment']
    assessment.update(decision='INSUFFICIENT_EVIDENCE', support_strength=1)
    assessment['criterion_assessments'][0]['support'] = 'PARTIAL'
    assessment['criterion_assessments'][1].update(support='NOT_DEMONSTRATED', evidence_indices=[])
    p = dict(project_id='PROJ_000701', siap_id='000701', fields=case['fields'],
        field_provenance={'methodology': dict(section_id='TEST_SECTION', raw_sources=[dict(record_source=str(raw / 'project.json'), source_row=1,
            field_mapping={'methodology': 'methodology'}, original_values={'methodology': case['fields']['methodology']})])})
    assert not v3.validate(p['fields'], case['profile'], assessment, case['rubric'])
    row = v3.indicator_row(p, case['profile'], assessment, case['rubric'])
    assert row['confidence_raw_score'] < 50
    directory = run / 'layer5_results/batch_fixture'
    directory.mkdir(parents=True)
    plan = dict(projects=[p], profiles={'SYNTH_I': case['profile']}, rubrics={'SYNTH_I': case['rubric']})
    engine = SimpleNamespace(BASE=run / 'layer5_results', check=lambda d: plan,
        verify_run=lambda d: dict(projects=[dict(project_id=p['project_id'], complete=not blocked, rows=[row],
            selected=['SYNTH_I','BLOCKED'] if blocked else ['SYNTH_I'],
            blocked_indicators={'BLOCKED':'BLOCKED_ERROR'} if blocked else {})],
            errors=[p['project_id']+': BLOCKED_ERROR'] if blocked else []),
        v3=v3, assessment_from_row=__import__('layer4_evaluation.live_execution', fromlist=['assessment_from_row']).assessment_from_row,
        evidence_locations=evidence_locations, SUBSTANTIVE={'summary', 'methodology', 'objectives', 'expected_results'})
    monkeypatch.setattr(runner, 'engine', lambda r, d: engine)
    monkeypatch.setattr(runner, 'validated_graph', lambda r, d: {})
    result = runner.export(root, run)
    assert result['relationships'] == 1 and result['status'] == ('PARTIAL' if blocked else 'COMPLETE')
    assert result['valid_assessments']==1
    assert read(Path(result['valid_results']))['assessments']==[dict(row,siap_id='000701')]
    assert bool(result['blocked_indicators'])==blocked
    if blocked:
        assert result['blocked_indicators'][0]['status']=='BLOCKED_ERROR'
        assert not result['blocked_indicators'][0]['project_complete']
    import csv
    with (run/'resultados/indicadores.csv').open(encoding='utf-8-sig',newline='') as stream:
        exported = list(csv.DictReader(stream,delimiter=';'))
    assert len(exported)==1
    assert exported[0]['estado_cumplimiento']==row['decision']
    assert float(exported[0]['confianza'])==row['confidence_raw_score']
    assert 'territorio' not in exported[0]
    assert (run/'resultados/indicadores_territorios.csv').is_file()
    book = openpyxl.load_workbook(result['excel'])
    cells = list(book.worksheets[0].rows)[1]
    assert cells[0].value == '000701' and cells[0].data_type == 's'
    assert cells[5].value == row['confidence_raw_score'] and cells[5].data_type == 'n'
    assert len(cells) == 6 and list(next(book.worksheets[0].values)) == runner.COLUMNS
    book.close()


def test_powershell_entrypoint_with_spaces(sandbox):
    import subprocess
    root, raw, _ = sandbox
    shutil.copytree(SOURCE / 'src', root / 'src', ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
    (raw / 'received.json').write_text(json.dumps(project()), encoding='utf-8')
    python = str(SOURCE / '.venv/Scripts/python.exe').replace("'", "''")
    commands = [f"& '{python}' -B scripts/run_pipeline_manual.py {op} --dataset prueba_en_vivo --run-id windows_check\nif ($LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}" for op in ('prepare', 'validate', 'export', 'verify')]
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', '\n'.join(commands)], cwd=root,
        text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr + result.stdout
    run = root / 'outputs/runs/windows_check'
    assert read(run / 'export.json')['relationships'] == 0
    assert not (run / 'workspace/outputs/layer3/publication').exists()
    before = sha(raw / 'received.json')
    assert before == read(run / 'raw_manifest.json')['files']['received.json']


def test_historical_publications_intact():
    expected = {
        'outputs/layer4/final/resultado_capa4.xlsx': 'fc6f876493ee327f140f5fbdbd234b93242eeaee15d86aa752388980f03332e1',
        'outputs/layer4/final/candidatos/resultado_capa4_demo_30.xlsx': 'cdd83be1ecf06bc732d00e6f85d6b8602314282200a222a019b2199e1cf7690f',
        'outputs/layer4/final/candidatos/resultado_capa4_demo_30_ampliado.xlsx': 'd75379384c042025b607dbc80c3bc6f6cd780ea689948732bc51dd7ba78ca64e',
    }
    assert all(sha(SOURCE / path) == fingerprint for path, fingerprint in expected.items())
