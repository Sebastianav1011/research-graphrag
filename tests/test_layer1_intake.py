"""Small intake and relocation integrations; no models, LLM or official writes."""
import json
from pathlib import Path
import zipfile

import openpyxl
import pyarrow.parquet as pq
import pytest

from layer2_processing.preprocessing.adapters import discover_sources, read, sha
from layer2_processing.preprocessing.adapters import PROJECT_HEADERS, validate_project_input
from layer2_processing.checkpoints import destination, resolve, verify_expected
from scripts import pipeline_coordinator as runner
from .test_manual_pipeline import sandbox, project, SOURCE


def delivery(root):
    folder = root / 'data/layer1_sources/incoming/entrega_test'
    folder.mkdir(parents=True)
    return folder


@pytest.fixture
def historical_intake(sandbox):
    """Keep former flexible-format regressions in the historical fixture flow."""
    root, raw, config = sandbox
    config['raw_base'] = raw.relative_to(root).as_posix()
    (raw / 'incoming/entrega_test').mkdir(parents=True)
    (raw / 'base').mkdir()
    return root, raw, config


def official_project_file(root, headers=PROJECT_HEADERS, records=None, sheet='Proyectos', relative='incoming/entrega_test/proyectos.xlsx'):
    path = root / 'data/layer1_sources' / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    book = openpyxl.load_workbook(SOURCE / 'data/templates/plantilla_entrada_proyectos.xlsx')
    ws = book['Proyectos']
    ws.title = sheet
    ws.delete_rows(1, ws.max_row)
    ws.append(list(headers))
    for record in records if records is not None else [dict(id_actividad='000701', resumen='Texto documental del proyecto.')]:
        ws.append([record.get(c) for c in headers])
    book.save(path)
    book.close()
    return path


@pytest.mark.parametrize('field', ['resumen', 'justificacion', 'metodologia', 'objetivos',
                                  'resultados_esperados', 'actividades_formacion'])
def test_official_project_contract_reaches_existing_knowledge_and_graph_validation(sandbox, field):
    root, _, config = sandbox
    identity = ' 001.0 / Á '
    text = 'Se estudian los aportes del proyecto a la comunidad.'
    source = official_project_file(root, tuple(reversed(PROJECT_HEADERS)), [dict(id_actividad=identity,
        convocatoria_codigo='C-01', convocatoria_nombre='Convocatoria institucional',
        objetivo_socioeconomico='Desarrollo social', gran_area='Ciencias sociales', area='Educación', **{field: text})])
    report = discover_sources(root, config)
    assert report['status'] == 'READY_FOR_VALIDATION', report
    config['processing_scope'] = dict(mode='file', project_ids=[identity], primary_files=['incoming/entrega_test/proyectos.xlsx'])
    run = root / 'outputs/runs/official'
    result = runner.prepare(root, run, root / 'data/layer1_sources', 'raw', config)
    assert result['counts']['proyectos'] == 1
    folder = run / 'workspace/outputs/layer2'
    project = pq.read_table(folder / 'canonical/proyectos.parquet').to_pylist()[0]
    assert project['source_project_id'] == identity and project['title'] is None
    assert project['summary'] == (text if field == 'resumen' else None)
    assert project['socioeconomic_objective'] == 'Desarrollo social'
    assert project['knowledge_area'] == 'Ciencias sociales' and project['knowledge_subarea'] == 'Educación'
    refs = json.loads(project['provenance_json'])
    assert refs[0]['original_values'][field] == text
    assert refs[0]['original_values']['convocatoria_codigo'] == 'C-01'
    sections = pq.read_table(folder / 'knowledge/source_sections.parquet').to_pylist()
    section = next(s for s in sections if s['text_original'] == text)
    assert json.loads(section['provenance_json'])['layer1'][0]['field_mapping'][section['field_name']] == field
    assert runner.graph(root, run)['status'] == 'VALIDATED_APPROVED_LAYER_2_INPUT'
    assert not (run / 'workspace/outputs/layer3/publication').exists()
    assert sha(source) == report['files'][0]['sha256']


@pytest.mark.parametrize('case,expected', [
    ('institutional', 'inesperados'), ('missing', 'faltantes'), ('duplicate_header', 'duplicados'),
    ('empty_id', 'id_actividad'), ('duplicate_id', 'fila 2'), ('no_text', 'contenido textual'),
    ('numeric_text', 'resumen'), ('wrong_sheet', 'Proyectos'), ('damaged', '.xlsx'),
    ('formula', 'Formula'), ('wrong_extension', '.xlsx'), ('renamed_content', '.xlsx')])
def test_official_invalid_file_stops_before_etl_or_graph(sandbox, monkeypatch, case, expected):
    root, _, config = sandbox
    headers = PROJECT_HEADERS
    records = [dict(id_actividad='P1', resumen='Texto documental del proyecto.')]
    if case == 'institutional':
        headers = ('id_actividad', 'resumen', 'resultados_investigacion', 'area_conocimiento')
    elif case == 'missing':
        headers = PROJECT_HEADERS[:-1]
    elif case == 'duplicate_header':
        headers = (*PROJECT_HEADERS, 'resumen')
    elif case == 'empty_id':
        records[0]['id_actividad'] = None
    elif case == 'duplicate_id':
        records.append(dict(records[0]))
    elif case == 'no_text':
        records.append(dict(id_actividad='P2', titulo_proyecto='Solo título', palabras_clave='palabras', resumen='   '))
        config['processing_scope'] = dict(mode='file', project_ids=['P1'])
    elif case == 'numeric_text':
        records[0]['resumen'] = 123
    elif case == 'formula':
        records[0]['resumen'] = '=1+1'
    path = official_project_file(root, headers, records, 'Otra' if case == 'wrong_sheet' else 'Proyectos')
    if case == 'damaged':
        path.write_bytes(b'not an Excel workbook')
    elif case == 'renamed_content':
        with zipfile.ZipFile(path) as archive:
            content = {name: archive.read(name) for name in archive.namelist()}
        content['[Content_Types].xml'] = content['[Content_Types].xml'].replace(
            b'spreadsheetml.sheet.main+xml', b'spreadsheetml.template.main+xml')
        with zipfile.ZipFile(path, 'w') as archive:
            for name, value in content.items():
                archive.writestr(name, value)
    elif case == 'wrong_extension':
        path.unlink()
        path = path.with_suffix('.csv')
        path.write_text('id_actividad,resumen\nP1,Texto documental\n', encoding='utf-8')
    checksum = sha(path)
    def expensive(*args, **kwargs):
        pytest.fail('Una entrada inválida no debe alcanzar ETL ni GraphRAG')
    monkeypatch.setattr('layer2_processing.preprocessing.pipeline.run', expensive)
    monkeypatch.setattr('layer3_graphrag.pipeline.run', expensive)
    report = discover_sources(root, config)
    assert report['status'] == 'PENDING_OR_INVALID'
    assert report['files'][0]['status'] == 'INVALID', report
    assert expected in str(report['files'][0]['diagnostics'])
    assert 'plantilla oficial' in str(report['files'][0]['diagnostics'])
    run = root / 'outputs/runs/rejected'
    with pytest.raises(ValueError, match='plantilla oficial'):
        runner.prepare(root, run, root / 'data/layer1_sources', 'raw', config)
    assert not (run / 'workspace').exists()
    assert not (run / 'preprocess/adapted').exists()
    assert sha(path) == checksum


def test_official_template_has_only_headers_and_passes_contract():
    path = SOURCE / 'data/templates/plantilla_entrada_proyectos.xlsx'
    book = openpyxl.load_workbook(path, read_only=True)
    assert book.sheetnames == ['Proyectos']
    values = list(book['Proyectos'].values)
    assert values[0] == PROJECT_HEADERS
    assert all(all(v is None for v in row) for row in values[1:])
    validate_project_input(path, list(values[0]), [], 'Proyectos')
    book.close()


def test_original_csv_hashes_and_data_contains_only_sources():
    expected = read(SOURCE / 'docs/architecture/auditoria_consolidacion/raw_importados.json')
    assert {p.name for p in (SOURCE / 'data').iterdir()} == {'layer1_sources', 'templates'}
    for record in expected:
        path = SOURCE / 'data/layer1_sources/base' / Path(record['official_path']).name
        assert sha(path) == record['sha256']
    assert not any(p.suffix in {'.parquet', '.npy', '.npz'} for p in (SOURCE / 'data').rglob('*'))


def test_xlsx_unknown_column_preserved_then_explicitly_authorized_as_a_section(historical_intake):
    root, raw, config = historical_intake
    folder = raw / 'incoming/entrega_test'
    source = folder / 'aporte.xlsx'
    book = openpyxl.Workbook()
    book.active.title = 'Proyectos'
    book.active.append(['id_actividad', 'resumen', 'beneficiarios_comunidad', 'correo_contacto'])
    book.active.append(['INTAKE_TEST_1', 'Controlled test narrative.', 'Controlled additional community description.', 'private@example.invalid'])
    book.save(source)
    book.close()
    original_hash = sha(source)
    preview = discover_sources(root, config)
    item = preview['files'][0]
    assert item['domain'] == 'proyectos' and item['status'] == 'READY_FOR_VALIDATION'
    assert item['text_columns'] == {}
    cell = item['records'][0]
    assert cell['original_values']['beneficiarios_comunidad'] == 'Controlled additional community description.'
    assert cell['field_provenance']['beneficiarios_comunidad'] == dict(file=str(source), sheet='Proyectos', row=2, column='beneficiarios_comunidad')
    config['files'] = {'incoming/entrega_test/aporte.xlsx': dict(domain='proyectos', sheet='Proyectos', text_columns={'include': ['beneficiarios_comunidad', 'correo_contacto']})}
    run = root / 'outputs/runs/authorized'
    runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    canonical = pq.read_table(run / 'workspace/outputs/layer2/canonical/proyectos.parquet').to_pylist()[0]
    original = json.loads(canonical['provenance_json'])[0]['original_values']
    assert original['correo_contacto'] == 'private@example.invalid'
    sections = pq.read_table(run / 'workspace/outputs/layer2/knowledge/source_sections.parquet').to_pylist()
    assert any(s['field_name'] == 'text__beneficiarios_comunidad' for s in sections)
    assert not any(s['field_name'] == 'text__correo_contacto' for s in sections)
    assert all('private@example.invalid' not in json.dumps(s) for s in sections)
    assert not (run / 'workspace/data').exists()
    assert sha(source) == original_hash
    assert runner.prepare(root, run, raw, 'prueba_en_vivo', config)['status'] == 'ALREADY_PREPARED'


def test_incoming_semantic_header_is_not_automatically_authorized(historical_intake):
    root, raw, config = historical_intake
    source = raw / 'incoming/entrega_test/nuevo.json'
    source.write_text(json.dumps(project() | {'resultado': 'Additional unknown narrative preserved for explicit review.'}), encoding='utf-8')
    run = root / 'outputs/runs/unreviewed'
    runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    rows = pq.read_table(run / 'workspace/outputs/layer2/knowledge/source_sections.parquet').to_pylist()
    assert all(s['field_name'] != 'text__resultado' for s in rows)
    canonical = pq.read_table(run / 'workspace/outputs/layer2/canonical/proyectos.parquet').to_pylist()[0]
    assert json.loads(canonical['provenance_json'])[0]['original_values']['resultado'].startswith('Additional unknown')


@pytest.mark.parametrize('name,value', [('unknown.csv', 'resumen\nUnknown domain narrative\n'),
    ('invalid.csv', 'id_actividad,resumen\nX,text,unexpected\n'), ('unknown.xls', 'Unsupported format'),
    ('invalid.json', '{"source_project_id":"A","source_project_id":"B","summary":"Controlled test."}')])
def test_invalid_or_ambiguous_files_remain_intact_and_are_never_published(sandbox, name, value):
    root, _, config = sandbox
    source = delivery(root) / name
    source.write_text(value, encoding='utf-8')
    expected = sha(source)
    report = discover_sources(root, config)
    assert report['status'] == 'PENDING_OR_INVALID'
    assert report['files'][0]['status'] in {'INVALID', 'PENDING_CONFIGURATION'}
    run = root / 'outputs/runs/blocked'
    with pytest.raises(ValueError):
        runner.prepare(root, run, root / 'data/layer1_sources', 'raw', config)
    assert not (run / 'workspace/outputs/layer2/canonical').exists()
    assert sha(source) == expected


def test_base_and_deliveries_are_additive_and_conflicts_remain_visible(historical_intake):
    root, raw, config = historical_intake
    base = raw / 'base/project.json'
    base.write_text(json.dumps(project()), encoding='utf-8')
    additional = raw / 'incoming/entrega_test/more.json'
    additional.write_text(json.dumps([project(), project('INTAKE_NEW')]), encoding='utf-8')
    report = discover_sources(root, config)
    assert any(isinstance(d, dict) and d.get('code') == 'REPEATED_ID_REQUIRES_CANONICAL_VALIDATION' for item in report['files'] for d in item['diagnostics'])
    run = root / 'outputs/runs/additive'
    runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    records = pq.read_table(run / 'workspace/outputs/layer2/canonical/proyectos.parquet').to_pylist()
    assert {r['source_project_id'] for r in records} == {'000701', 'INTAKE_NEW'}
    assert len(json.loads(next(r for r in records if r['source_project_id'] == '000701')['provenance_json'])) == 2
    conflict = additional.parent
    (conflict / 'contradictory.json').write_text(json.dumps(project() | {'id_actividad': 'CONTRADICTION'}), encoding='utf-8')
    pending = discover_sources(root, config)
    assert any(i['status'] == 'INVALID' and any('contradictorios' in str(d) for d in i['diagnostics']) for i in pending['files'])


def test_registered_aliases_work_without_python_changes(historical_intake):
    root, raw, config = historical_intake
    source = raw / 'incoming/entrega_test/renombrado.csv'
    source.write_text('codigo_vri,narrativa\nINTAKE_ALIAS,Controlled test narrative\n', encoding='utf-8')
    config['files'] = {'incoming/entrega_test/*.csv': {'domain': 'proyectos', 'mapping': {'source_project_id': 'codigo_vri', 'summary': 'narrativa'}}}
    report = discover_sources(root, config)
    assert report['status'] == 'READY_FOR_VALIDATION'
    run = root / 'outputs/runs/aliases'
    runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    row = pq.read_table(run / 'workspace/outputs/layer2/canonical/proyectos.parquet').to_pylist()[0]
    assert row['project_id'] == 'PROJ_INTAKE_ALIAS'


def test_production_can_use_eid_or_doi_without_requiring_both(sandbox):
    root, _, config = sandbox
    source = delivery(root) / 'produccion.csv'
    source.write_text('nombre_producto,doi,eid,resumen\nControlled first,10.9999/intake-test,,Controlled text\nControlled second,,EID_TEST_ONLY,Controlled text\n', encoding='utf-8')
    assert discover_sources(root, config)['status'] == 'READY_FOR_VALIDATION'
    run = root / 'outputs/runs/articles'
    result = runner.prepare(root, run, root / 'data/layer1_sources', 'raw', config)
    assert result['counts']['proyectos'] == 0 and result['counts']['articulos'] == 2


def test_researchers_follow_the_existing_optional_name_rule(sandbox):
    root, _, config = sandbox
    source = delivery(root) / 'miembros.csv'
    source.write_text('id_empleado,nombre_completo\nINTAKE_RESEARCHER,\n', encoding='utf-8')
    assert discover_sources(root, config)['status'] == 'READY_FOR_VALIDATION'
    run = root / 'outputs/runs/researcher'
    result = runner.prepare(root, run, root / 'data/layer1_sources', 'raw', config, through='preprocessing')
    assert result['counts']['investigadores'] == 1


def test_new_destination_never_falls_back_to_historical_data(tmp_path):
    old = tmp_path / 'data/canonical'
    old.mkdir(parents=True)
    registry = tmp_path / 'config/sad_relocations.json'
    registry.parent.mkdir()
    registry.write_text(json.dumps({'prefixes': {'data/canonical': 'outputs/layer2/canonical'}}), encoding='utf-8')
    assert resolve(tmp_path, 'outputs/layer2/canonical') == old
    assert destination(tmp_path, 'data/canonical') == tmp_path / 'outputs/layer2/canonical'


def test_frozen_windows_paths_use_the_original_binding(tmp_path):
    original = tmp_path / 'original.py'
    current = tmp_path / 'current.py'
    original.write_text('original source bytes', encoding='utf-8')
    current.write_text('relocated current source', encoding='utf-8')
    config = tmp_path / 'config/sad_relocations.json'
    config.parent.mkdir()
    config.write_text(json.dumps(dict(file_aliases={'old/code.py': 'current.py'}, runtime_bindings={
        'old/code.py': dict(after_sha256=sha(current), snapshots=['original.py'])})), encoding='utf-8')
    verify_expected(tmp_path, 'old\\code.py', sha(original))
