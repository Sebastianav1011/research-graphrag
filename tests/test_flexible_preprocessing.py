"""Controlled RAW -> original ETL -> knowledge -> GraphRAG tests, without LLM."""
import csv
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import openpyxl
import pyarrow.parquet as pq
import pytest
from jsonschema import Draft202012Validator

from .test_manual_pipeline import sandbox, project, SOURCE
from layer2_processing.preprocessing.adapters import select_text_columns, sha, tabular, write
from scripts import pipeline_coordinator as runner
from layer4_evaluation.indicators import assessment_v3 as v3


def test_base_isolates_missing_identity_retains_sparse_entities_and_lineage(sandbox):
    from layer2_processing.preprocessing.adapters import discover_sources
    root,_,config=sandbox;base=root/'data/layer1_sources/base'
    write(base/'descriptores.json',[
        dict(id_actividad='',resumen='Excluded anonymous row'),
        dict(id_actividad='0001',resumen='',metodologia='',objetivos=''),
        dict(id_actividad='0002',objetivos='Desarrollar una intervencion comunitaria concreta.',
            justificacion='Necesidad documentada de la comunidad atendida.',actividades_formacion='Talleres previstos para investigadores locales.')])
    write(base/'produccion.json',[
        dict(nombre_producto='',doi='10.1234/valid',resumen='Evidence from identified publication.',cedula='D1',investigador_docente='Synthetic Person'),
        dict(nombre_producto='Title without verifiable identifier',resumen='Excluded unidentifiable publication'),
        dict(nombre_producto='',eid='2-s2.0-12345',resumen='Another identified publication')])
    write(base/'miembros.json',[dict(id_actividad='0001',id_empleado='E1',documento='D1',nombre_completo='Synthetic Person')])
    config=config|dict(knowledge_scope='BASE_GLOBAL_V1')
    fingerprints={p.name:sha(p) for p in base.iterdir()}
    preview=discover_sources(root,config,base)
    assert preview['status']=='READY_FOR_VALIDATION'
    counts={i['domain']:i['record_validation'] for i in preview['files']}
    assert counts['proyectos']['valid']==2 and counts['proyectos']['rejected_rows'][0]['row']==1
    assert counts['articulos']['valid']==2 and counts['articulos']['rejected_rows'][0]['row']==2
    production=next(i for i in preview['files'] if i['domain']=='articulos')
    assert 'nombre_producto' not in production['pending_authorization']
    run=root/'outputs/runs/sparse_base'
    runner.prepare(root,run,base,'raw',config)
    folder=run/'workspace/outputs/layer2/canonical'
    projects=pq.read_table(folder/'proyectos.parquet').to_pylist()
    assert {p['source_project_id'] for p in projects}=={'0001','0002'}
    assert len(pq.read_table(folder/'articulos.parquet'))==2
    assert pq.read_table(folder/'proyecto_investigador.parquet').num_rows==1
    assert pq.read_table(folder/'articulo_investigador.parquet').num_rows==1
    sections=pq.read_table(run/'workspace/outputs/layer2/knowledge/source_sections.parquet').to_pylist()
    assert {s['field_name'] for s in sections if s['source_id']=='PROJ_0002'}>={'objectives','text__justificacion','text__actividades_formacion'}
    section=next(s for s in sections if s['source_id']=='PROJ_0002' and s['field_name']=='objectives')
    assert json.loads(section['provenance_json'])['layer1'][0]['source_row']==3
    assert not any('Excluded' in (s['text_original'] or '') for s in sections)
    assert fingerprints=={p.name:sha(p) for p in base.iterdir()}
    diagnostics=json.loads((run/'preprocess/diagnostics.json').read_text(encoding='utf-8'))
    assert sum(d['code']=='BASE_ROW_EXCLUDED' for d in diagnostics)==2


@pytest.mark.parametrize('rows',[[{'resumen':'Missing ID column'}],[{'id_actividad':'','resumen':'No usable identity'}]])
def test_base_structurally_invalid_or_entirely_unusable_source_stays_blocked(sandbox,rows):
    from layer2_processing.preprocessing.adapters import discover_sources
    root,_,config=sandbox;base=root/'data/layer1_sources/base'
    write(base/'descriptores.json',rows)
    preview=discover_sources(root,config,base)
    assert preview['status']=='PENDING_OR_INVALID' and preview['files'][0]['status']=='INVALID'


def test_incoming_article_title_contract_is_not_relaxed(sandbox):
    from layer2_processing.preprocessing.ingestion import validate_rows
    import yaml
    root,_,_=sandbox
    settings=yaml.safe_load((root/'config/layer1.yaml').read_text(encoding='utf-8'))
    row=dict(_file='incoming/synthetic.csv',_row=2,title=None,doi='10.1234/valid')
    accepted,rejected,_=validate_rows([row],'articulos',settings,'synthetic')
    assert not accepted and len(rejected)==1


def test_new_fields_survive_with_exact_lineage_and_separate_meanings(sandbox):
    root, raw, config = sandbox
    values = project() | {
        'resultado': 'Se entregó un mecanismo de colaboración documentado.',
        'resultados_esperados': 'Se espera aumentar la colaboración en el futuro.',
        'posibles_resultados': 'Podría formarse una nueva red de trabajo local.',
        'nota_nueva': 'Una observación útil que aún requiere revisión.',
        'correo_contacto': 'privado@example.org',
        'json_desconocido': {'detalle': ['dato exacto', 7]},
    }
    path = raw / 'nuevo.json'
    path.write_text(json.dumps(values, ensure_ascii=False), encoding='utf-8')
    fingerprint = sha(path)
    run = root / 'outputs/runs/flexible'
    runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    assert sha(path) == fingerprint
    canonical = pq.read_table(run / 'workspace/outputs/layer2/canonical/proyectos.parquet').to_pylist()[0]
    ref = json.loads(canonical['provenance_json'])[0]
    assert ref['original_values'] == values
    sections = pq.read_table(run / 'workspace/outputs/layer2/knowledge/source_sections.parquet').to_pylist()
    fields = {s['field_name']: s for s in sections}
    assert fields['text__resultado']['text_original'] == values['resultado']
    assert fields['expected_results']['text_original'] == values['resultados_esperados']
    assert fields['text__posibles_resultados']['text_original'] == values['posibles_resultados']
    assert 'text__nota_nueva' not in fields and 'text__correo_contacto' not in fields
    lineage = json.loads(fields['text__resultado']['provenance_json'])['layer1'][0]
    assert lineage['field_mapping'] == {'text__resultado': 'resultado'}
    assert lineage['original_values'] == {'resultado': values['resultado']}
    assert lineage['record_source'] == str(path) and lineage['source_row'] == 1
    assert runner.evidence_sources({'field_provenance': {'text__resultado': {'raw_sources': [lineage]}}},
                                   {'field': 'text__resultado'}).endswith('campo_preprocesado=text__resultado')
    assert runner.graph(root, run)['status'] == 'VALIDATED_APPROVED_LAYER_2_INPUT'
    assert not list(raw.rglob('*.parquet'))


def test_configured_unknown_column_and_sensitive_override(sandbox):
    root, raw, config = sandbox
    path = raw / 'descriptores-nuevos.csv'
    path.write_text('id_actividad,nota_nueva,correo_contacto\n00012,Texto documental adicional para analizar,privado@example.org\n', encoding='utf-8')
    config['text_columns'] = {'include': ['nota_nueva', 'correo_contacto']}
    run = root / 'outputs/runs/configured'
    runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    sections = pq.read_table(run / 'workspace/outputs/layer2/knowledge/source_sections.parquet').to_pylist()
    assert any(s['field_name'] == 'text__nota_nueva' for s in sections)
    assert not any('privado@example.org' in (s['text_original'] or '') for s in sections)
    decisions = json.loads((run / 'preprocess/diagnostics.json').read_text(encoding='utf-8'))
    assert any(e['code'] == 'TEXT_COLUMN_POLICY' for e in decisions)


@pytest.mark.parametrize('name', ['resultado', 'resultado_clinico', 'detalle_tecnico'])
def test_text_selection_never_authorizes_personal_content(name):
    selected, decisions = select_text_columns([name], [(2, {name: 'Contacto privado@example.org con información personal.'})], {}, {'include': [name]})
    assert not selected and decisions[0]['selected'] is False


def test_unknown_format_rejected_with_diagnostics_and_intact_raw(sandbox):
    root, raw, config = sandbox
    path = raw / 'recibido.xls'
    path.write_bytes(b'unsupported-format')
    run = root / 'outputs/runs/unsupported'
    with pytest.raises(ValueError, match='Entrada rechazada'):
        runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    assert path.read_bytes() == b'unsupported-format'
    assert 'no soportado' in (run / 'preprocess/diagnostics.json').read_text(encoding='utf-8')
    assert not (run / 'workspace/outputs/layer2/knowledge').exists()


def test_xlsx_identifier_unknown_column_and_read_only(tmp_path):
    path = tmp_path / 'nuevo.xlsx'
    book = openpyxl.Workbook()
    book.active.append(['id', 'resultado', 'extra'])
    book.active.append([7, 'Texto documental de un resultado nuevo', 'Valor desconocido'])
    book.active['A2'].number_format = '00000'
    book.save(path)
    book.close()
    before = sha(path)
    headers, rows, sheet = tabular(path)
    assert rows[0][1] == {'id': '00007', 'resultado': 'Texto documental de un resultado nuevo', 'extra': 'Valor desconocido'}
    assert sha(path) == before


def test_additional_evidence_uses_same_v3_arithmetic_and_temporal_rules():
    spec = importlib.util.spec_from_file_location('v3_flexible_fixture', SOURCE / 'tests/layer5_experiment/test_assessment_v3.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    case = fixture.case.__wrapped__()
    p, r, f, a = [deepcopy(case[k]) for k in ('profile', 'rubric', 'fields', 'assessment')]
    old = v3.confidence(f, p, a, r)
    f['text__resultado'] = f['methodology']
    a['evidence'][0]['field'] = 'text__resultado'
    assert v3.confidence(f, p, a, r) == old
    v3.make_input({'project_id': 'SYNTH', 'fields': f}, [p], [], {p['indicator_id']: r})
    wrapper = {'project_id': 'SYNTH', 'assessments': [a | {'indicator_id': p['indicator_id']}]}
    v3.validate_wrapper(wrapper, 'SYNTH', [p['indicator_id']], f)
    a['evidence'][0]['stage'] = 'RESULT_EXPECTED'
    assert v3.validate(f, p, a, r)  # Expected outcomes do not demonstrate this existing mechanism.


def test_single_root_command_without_dataset(sandbox, monkeypatch):
    root, raw, config = sandbox
    (root / 'data/layer1_sources/base/directo.json').write_text(json.dumps(project()), encoding='utf-8')
    monkeypatch.setattr(runner, 'ROOT', root)
    assert runner.main(['run', '--run-id', 'direct', '--through', 'knowledge']) == 0
    assert (root / 'outputs/runs/direct/workspace/outputs/layer2/knowledge/source_sections.parquet').is_file()


def test_text_document_and_extension_registry(sandbox):
    from layer2_processing.preprocessing.adapters import READERS
    root, raw, config = sandbox
    (raw / 'nuevo.txt').write_text('ID SIAP: 000001\nTítulo: Documento textual\nResultado: Se documentó una colaboración con fuentes verificables.', encoding='utf-8')
    run = root / 'outputs/runs/text'
    runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    sections = pq.read_table(run / 'workspace/outputs/layer2/knowledge/source_sections.parquet').to_pylist()
    assert any(s['field_name'] == 'text__resultado' for s in sections)
    READERS['.testformat'] = lambda path, sheet: (['id'], [(1, {'id': '000001'})], None)
    try:
        assert tabular(Path('unused.testformat'))[1][0][1]['id'] == '000001'
    finally:
        del READERS['.testformat']


def test_full_command_batches_projects_without_new_inference(sandbox, monkeypatch):
    from types import SimpleNamespace
    root, raw, config = sandbox
    (raw / 'proyectos.json').write_text(json.dumps([project(str(i)) for i in range(5)]), encoding='utf-8')
    monkeypatch.setattr(runner, 'ROOT', root)
    def graph(root,run,**kwargs):
        write(run/'workspace/outputs/layer3/publication/_manifest.json',{'mock':'validated separately'})
        for batch in (['0','1'],['2','3'],['4']):
            write(root/'unused'/runner.batch_name(batch)/'review.txt','Previously reviewed mock batch')
        return {'status':'SUCCESS'}
    monkeypatch.setattr(runner,'graph',graph)
    monkeypatch.setattr(runner,'validated_graph',lambda *a:{})
    completed=set()
    monkeypatch.setattr(runner, 'engine', lambda *a: SimpleNamespace(BASE=root/'unused',
        verify_run=lambda directory:dict(errors=[],status='COMPLETE' if directory.name in completed else 'PARTIAL')))
    calls = []
    def evaluate(root, run, selected, authorize=False, execute=False):
        if execute:
            assert authorize
            calls.append(selected)
            completed.add(runner.batch_name(selected))
        return {'status': 'COMPLETE'}
    monkeypatch.setattr(runner, 'evaluate', evaluate)
    monkeypatch.setattr(runner, 'export', lambda *a: {'status': 'COMPLETE'})
    assert runner.main(['run', '--dataset', 'prueba_en_vivo', '--through', 'results', '--approve-build', '--authorize']) == 0
    assert list(map(len, calls)) == [2, 2, 1]
    assert {i for batch in calls for i in batch} == {'0', '1', '2', '3', '4'}


def test_optional_config_applies_only_where_column_exists(sandbox):
    root, raw, config = sandbox
    (raw / 'nuevo.json').write_text(json.dumps(project() | {'nota_nueva': 'Texto seleccionado adicional.'}), encoding='utf-8')
    (raw / 'produccion.csv').write_text('nombre_producto,resumen\nArtículo nuevo,Texto de la publicación.\n', encoding='utf-8')
    config['text_columns'] = {'include': ['nota_nueva']}
    run = root / 'outputs/runs/optional'
    assert runner.prepare(root, run, raw, 'prueba_en_vivo', config)['counts']['articulos'] == 1
    diagnostics = json.loads((run / 'preprocess/diagnostics.json').read_text(encoding='utf-8'))
    assert any(d['reason'] == 'CONFIGURED_OPTIONAL_COLUMN_ABSENT' for e in diagnostics if e['code'] == 'TEXT_COLUMN_POLICY' for d in e['decisions'])


def test_occurrence_identifiers_do_not_depend_on_adapter_run_path(sandbox):
    root, raw, config = sandbox
    (raw / 'proyecto.json').write_text(json.dumps(project()), encoding='utf-8')
    (raw / 'produccion.csv').write_text('nombre_producto,resumen\nArtículo sin DOI ni EID,Texto documental.\n', encoding='utf-8')
    (raw / 'miembros.csv').write_text('nombre_completo\nPersona sin identificación externa\n', encoding='utf-8')
    ids = []
    for name in ('identity_first', 'identity_second'):
        run = root / 'outputs/runs' / name
        runner.prepare(root, run, raw, 'prueba_en_vivo', config, through='preprocessing')
        folder = run / 'workspace/outputs/layer2/canonical'
        ids.append((pq.read_table(folder/'articulos.parquet')['article_id'].to_pylist(),
                    pq.read_table(folder/'investigadores.parquet')['researcher_id'].to_pylist()))
    assert ids[0] == ids[1]


def test_controlled_sample_of_original_csv_files(sandbox):
    root, raw, config = sandbox
    before = {}
    for name in ('descriptores-limpio.csv', 'produccion-limpio.csv', 'miembros-doc-limpio.csv'):
        original = SOURCE / 'data/layer1_sources/base' / name
        if not original.is_file():
            pytest.skip('Private institutional inputs are not distributed with Git')
        before[original] = sha(original)
        for encoding in ('utf-8-sig', 'cp1252'):
            try:
                with original.open(encoding=encoding, newline='') as stream:
                    reader = csv.DictReader(stream)
                    columns, row = reader.fieldnames, next(reader)
                break
            except UnicodeDecodeError:
                continue
        with (raw / name).open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerow(row)
    run = root / 'outputs/runs/real_csv_sample'
    result = runner.prepare(root, run, raw, 'prueba_en_vivo', config)
    assert result['counts']['proyectos'] == result['counts']['articulos'] == 1
    assert runner.graph(root, run)['status'] == 'VALIDATED_APPROVED_LAYER_2_INPUT'
    assert all(sha(path) == digest for path, digest in before.items())


def test_personal_alias_conflicts_reach_existing_identity_resolver(sandbox):
    root, raw, config = sandbox
    (raw / 'nuevo.json').write_text(json.dumps(project()), encoding='utf-8')
    (raw / 'miembros.csv').write_text('id_empleado,id_investigador,nombre_completo\nEMP01,OTHER01,Persona de prueba\n', encoding='utf-8')
    run = root / 'outputs/runs/aliases'
    runner.prepare(root, run, raw, 'prueba_en_vivo', config, through='preprocessing')
    row = pq.read_table(run / 'workspace/outputs/layer2/canonical/investigadores.parquet').to_pylist()[0]
    assert row['identity_status'] == 'ambiguous' and row['identity_rule'] == 'conflicting_identifiers'
    original = json.loads(row['provenance_json'])[0]['original_values']
    assert original['id_empleado'] == 'EMP01' and original['id_investigador'] == 'OTHER01'


def test_excel_dates_use_existing_date_normalizer(tmp_path):
    from datetime import datetime
    from layer2_processing.preprocessing.normalize import date_value
    path = tmp_path / 'fechas.xlsx'
    book = openpyxl.Workbook()
    book.active.append(['fecha_inicio'])
    book.active.append([datetime(2026, 10, 29)])
    book.save(path)
    book.close()
    value = tabular(path)[1][0][1]['fecha_inicio']
    assert date_value(value) == '2026-10-29'
