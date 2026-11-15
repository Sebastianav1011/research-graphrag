"""Small new-document integration checks; no model downloads, embeddings or LLM."""
import json
from pathlib import Path
import shutil
import zipfile
from copy import deepcopy

import openpyxl
import pyarrow.parquet as pq
import pytest

from scripts import pipeline_coordinator as runner
from layer2_processing.preprocessing.adapters import prepare_files, read, sha, tabular
from tests.layer5_experiment.test_assessment_v3 import case,sk_case

SOURCE = Path(__file__).resolve().parents[1]


def export_fixture(run,ids,monkeypatch):
    """Only persisted export inputs: no preprocessing, graphs or evaluation."""
    import pyarrow as pa
    target=run/'workspace/outputs/layer2/canonical/proyectos.parquet'
    target.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist([dict(source_project_id=pid) for pid in ids]),target)
    monkeypatch.setattr(runner,'check',lambda *args:None)


@pytest.mark.parametrize('layout,positives',[
    ([(48,0,0)],5), ([(47,1,0)],3), ([(47,1,0)],0), ([(45,3,0)],5),
    ([(48,0,0),(46,2,0),(47,1,0),(47,1,0),(47,1,0)],5),
    ([(12,2,34)],5), ([(48,0,0)],0), ([(48,0,0)],48),
])
def test_indicator_coverage_exports_all_indicators_independently(sandbox,monkeypatch,sk_case,layout,positives,contract='THESIS_ALL_INDICATORS_V1'):
    """48 frozen synthetic rubrics; real S/K validation, evidence gates and Excel."""
    from types import SimpleNamespace
    from layer4_evaluation import live_execution as live
    from layer4_evaluation.indicators import assessment_v3 as v3
    from layer4_evaluation.indicators.selection import canonical_hash
    from layer4_evaluation.indicators.review import evidence_locations
    from layer4_evaluation.thesis_output import TEMPLATE,COLUMNS,SHEETS
    root,raw,config=sandbox
    ids=[f'{n:06d}' for n in range(len(layout))]
    (raw/'projects.json').write_text(json.dumps([project(pid) for pid in ids]),encoding='utf-8')
    run=root/'outputs/runs/coverage';export_fixture(run,ids,monkeypatch)
    profiles={};rubrics={}
    for n in range(48):
        iid=f'I{n:02d}';profile=deepcopy(sk_case['profile']);profile['indicator_id']=iid
        rubric=deepcopy(sk_case['rubric']);rubric.update(indicator_id=iid,profile_sha256=canonical_hash(profile))
        rubric.pop('rubric_sha256');rubric['rubric_sha256']=canonical_hash(rubric)
        profiles[iid]=profile;rubrics[iid]=rubric
    projects=[];states=[];errors=[]
    for pid,(valid,blocked,pending) in zip(ids,layout):
        assert valid+blocked+pending==48
        p=dict(project_id='PROJ_'+pid,siap_id=pid,fields=sk_case['fields'],field_provenance={
            'methodology':dict(section_id='SECTION_'+pid,raw_sources=[dict(record_source=str(raw/'projects.json'),
                source_row=1,field_mapping={'methodology':'metodologia'},original_values={'methodology':sk_case['fields']['methodology']})])})
        projects.append(p);rows=[]
        for n,iid in enumerate(profiles):
            if n>=valid:break
            a=deepcopy(sk_case['assessment'])
            if n>=positives:
                a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=0,evidence=[])
                for c in a['criterion_assessments']:c.update(support='NOT_DEMONSTRATED',coverage=0,evidence_indices=[])
                a['strength_rubric']={k:([] if k=='evidence_indices' else 'Sin respaldo suficiente.' if k=='explanation' else 0) for k in a['strength_rubric']}
            assert not v3.validate(p['fields'],profiles[iid],a,rubrics[iid])
            rows.append(v3.indicator_row(p,profiles[iid],a,rubrics[iid]))
        failures={iid:'BLOCKED_ERROR' for iid in list(profiles)[valid:valid+blocked]}
        errors.extend(p['project_id']+': '+iid+' BLOCKED_ERROR' for iid in failures)
        states.append(dict(project_id=p['project_id'],selected=list(profiles),rows=rows,
            complete=valid==48,blocked_indicators=failures))
    plan=dict(projects=projects,profiles=profiles,rubrics=rubrics)
    directory=run/'layer5_results/batch_fixture';directory.mkdir(parents=True)
    module=SimpleNamespace(BASE=directory.parent,check=lambda _:plan,
        verify_run=lambda _:dict(projects=states,errors=errors),v3=v3,
        assessment_from_row=live.assessment_from_row,evidence_locations=evidence_locations)
    monkeypatch.setattr(runner,'engine',lambda *a:module)
    monkeypatch.setattr(runner,'validated_graph',lambda *a:{})
    target=root/TEMPLATE;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(SOURCE/TEMPLATE,target)
    original=deepcopy(states);result=runner.export(root,run,output_contract=contract)
    general=contract=='THESIS_VALID_ASSESSMENTS_V2'
    expected=sum(v for v,b,p in layout) if general else 48*len(layout)
    assert states==original  # No score/result rewriting on partial export.
    assert result['expected_assessments']==48*len(layout)
    assert result['valid_assessments']==sum(v for v,b,p in layout)
    assert result['blocked_assessments']==sum(b for v,b,p in layout)
    assert result['pending_assessments']==sum(p for v,b,p in layout)
    assert result['processed_projects']==sum(p==0 for v,b,p in layout)
    assert result['completed_projects']==sum(v==48 for v,b,p in layout)
    assert result['supported']==positives*len(layout)
    assert result['exported_rows']==expected
    assert result['output_contract']==contract
    assert result['insufficient_evidence']==result['valid_assessments']-result['supported']
    assert result['status']==('COMPLETE' if all(v==48 for v,b,p in layout) else 'PARTIAL')
    persisted=read(Path(result['valid_results']))
    assert persisted['assessments']==[dict(row,siap_id=p['siap_id']) for p,state in zip(projects,original) for row in state['rows']]
    assert len(persisted['assessments'])==result['valid_assessments']
    coverage=read(Path(result['indicator_statuses']))['indicators']
    assert len(coverage)==48*len(layout)
    assert all(c['decision'] is None for c in coverage if c['status']!='VALID')
    assert result['export_exclusions']==[]
    assert result['csv']['indicator_rows']==expected
    book=openpyxl.load_workbook(result['excel'],read_only=True)
    try:
        assert book.sheetnames==SHEETS
        values=list(book['Proyectos'].values)
        assert values[0]==tuple(c for c in COLUMNS if not general or c!='territorio_region') and len(values)-1==expected
        assert len({row[:2] for row in values[1:]})==len(values)-1
        assert sum(row[-1] is None for row in values[1:])==(0 if general else sum(b+p for v,b,p in layout))
        assert sum(row[-1]==0 for row in values[1:])==result['insufficient_evidence']
        assert all(row[3] and row[4]=='metodologia' and 'section_id=' in row[5] for row in values[1:] if row[2]=='SUPPORTED')
        assert all(row[3:]==(None,)*5 for row in values[1:] if row[2] in ('BLOCKED_ERROR','PENDING'))
    finally:book.close()
    if not positives:
        saved=read(runner.run_file(run,'export.json'))
        assert 'todos los indicadores' in saved['note']
        assert saved['export_exclusions']==[] and saved['excel_sha256']==sha(Path(saved['excel']))


def test_valid_general_export_keeps_partial_zero_and_audits_blocked_and_pending(sandbox,monkeypatch,sk_case):
    test_indicator_coverage_exports_all_indicators_independently(sandbox,monkeypatch,sk_case,
        [(2,1,45)],1,contract='THESIS_VALID_ASSESSMENTS_V2')


def test_export_audit_keeps_context_state_evidence_limited_and_truncation(sandbox,monkeypatch,sk_case):
    """C2: limits stay visible in the audit; truncated contexts never become VALID rows."""
    from types import SimpleNamespace
    from layer4_evaluation import live_execution as live
    from layer4_evaluation.indicators import assessment_v3 as v3
    from layer4_evaluation.indicators.selection import canonical_hash
    from layer4_evaluation.indicators.review import evidence_locations
    from layer4_evaluation.thesis_output import TEMPLATE
    root,raw,config=sandbox
    (raw/'projects.json').write_text(json.dumps([project('000001')]),encoding='utf-8')
    run=root/'outputs/runs/context_audit';export_fixture(run,['000001'],monkeypatch)
    profiles,rubrics={},{}
    for iid in ('I00','I01','I02'):
        profile=deepcopy(sk_case['profile']);profile['indicator_id']=iid
        rubric=deepcopy(sk_case['rubric']);rubric.update(indicator_id=iid,profile_sha256=canonical_hash(profile))
        rubric.pop('rubric_sha256');rubric['rubric_sha256']=canonical_hash(rubric)
        profiles[iid],rubrics[iid]=profile,rubric
    p=dict(project_id='PROJ_000001',siap_id='000001',fields=sk_case['fields'],field_provenance={
        'methodology':dict(section_id='SECTION_1',raw_sources=[dict(record_source=str(raw/'projects.json'),
            source_row=1,field_mapping={'methodology':'metodologia'},original_values={})])})
    truncation=lambda reason,material:dict(policy='TOP_RANKED_UNIT_INTACT_V1',material=material,reason=reason)
    contexts={'I00':dict(status='READY',evidence_limited=True,truncation=truncation('LOWER_RANKED_UNITS_OMITTED_BY_BUDGET',False)),
              'I01':dict(status='EVIDENCE_TRUNCATED',evidence_limited=True,truncation=truncation('TOP_RANKED_UNIT_NOT_INTACT',True)),
              'I02':dict(status='STATIC_CONTEXT_TOO_LONG',evidence_limited=False,truncation=truncation('TEMPLATE_EXCEEDS_EVIDENCE_THRESHOLD',False))}
    plan=dict(projects=[p],profiles=profiles,rubrics=rubrics,
        context_requests={'PROJ_000001':{iid:dict(context_selection=c) for iid,c in contexts.items()}})
    a=deepcopy(sk_case['assessment']);assert not v3.validate(p['fields'],profiles['I00'],a,rubrics['I00'])
    state=dict(project_id='PROJ_000001',selected=list(profiles),rows=[v3.indicator_row(p,profiles['I00'],a,rubrics['I00'])],
        complete=False,blocked_indicators={},context_limits={'I01':'EVIDENCE_TRUNCATED','I02':'STATIC_CONTEXT_TOO_LONG'})
    directory=run/'layer5_results/batch_fixture';directory.mkdir(parents=True)
    module=SimpleNamespace(BASE=directory.parent,check=lambda _:plan,verify_run=lambda _:dict(projects=[state],errors=[]),
        v3=v3,assessment_from_row=live.assessment_from_row,evidence_locations=evidence_locations)
    monkeypatch.setattr(runner,'engine',lambda *a:module)
    monkeypatch.setattr(runner,'validated_graph',lambda *a:{})
    result=runner.export(root,run,output_contract='THESIS_VALID_ASSESSMENTS_V2')
    coverage={c['indicator_id']:c for c in read(Path(result['indicator_statuses']))['indicators']}
    assert {k:c['status'] for k,c in coverage.items()}=={'I00':'VALID','I01':'EVIDENCE_TRUNCATED','I02':'STATIC_CONTEXT_TOO_LONG'}
    for iid,c in contexts.items():
        assert (coverage[iid]['context_status'],coverage[iid]['evidence_limited'],coverage[iid]['truncation'])==(
            c['status'],c['evidence_limited'],c['truncation'])
    assert coverage['I01']['decision'] is None and result['valid_assessments']==1 and result['exported_rows']==1
    lineage=read(runner.run_file(run,'evidence_lineage.json'))
    assert [(l['indicator_id'],l['evidence_limited'],l['truncation']['reason']) for l in lineage]==[
        ('I00',True,'LOWER_RANKED_UNITS_OMITTED_BY_BUDGET')]


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / 'isolated repo with spaces'
    from layer4_evaluation.thesis_output import TEMPLATE
    (root/TEMPLATE).parent.mkdir(parents=True)
    shutil.copyfile(SOURCE/TEMPLATE,root/TEMPLATE)
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
    from layer4_evaluation.thesis_output import SHEETS,COLUMNS as thesis_columns
    assert book.sheetnames == SHEETS
    assert list(next(book.worksheets[0].values)) == thesis_columns
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
@pytest.mark.parametrize('decision',['SUPPORTED','INSUFFICIENT_EVIDENCE'])
def test_export_keeps_partial_evidence_and_original_numeric_score(sandbox, monkeypatch, blocked, decision):
    """Real V3 validation/arithmetic on an existing synthetic fixture; no model call."""
    import importlib.util
    from types import SimpleNamespace
    from layer4_evaluation.indicators import assessment_v3 as v3
    from layer4_evaluation.indicators.review import evidence_locations
    root, raw, config = sandbox
    (raw / 'project.json').write_text(json.dumps(project()), encoding='utf-8')
    run = root / 'outputs/runs/export'
    export_fixture(run,['000701'],monkeypatch)
    spec = importlib.util.spec_from_file_location('existing_v3_test_fixture', SOURCE / 'tests/layer5_experiment/test_assessment_v3.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    case = fixture.case.__wrapped__()
    assessment = case['assessment']
    if decision=='INSUFFICIENT_EVIDENCE':
        assessment.update(decision=decision, support_strength=1)
        assessment['criterion_assessments'][0]['support'] = 'PARTIAL'
        assessment['criterion_assessments'][1].update(support='NOT_DEMONSTRATED', evidence_indices=[])
    p = dict(project_id='PROJ_000701', siap_id='000701', fields=case['fields'],
        field_provenance={'methodology': dict(section_id='TEST_SECTION', raw_sources=[dict(record_source=str(raw / 'project.json'), source_row=1,
            field_mapping={'methodology': 'methodology'}, original_values={'methodology': case['fields']['methodology']})])})
    assert not v3.validate(p['fields'], case['profile'], assessment, case['rubric'])
    row = v3.indicator_row(p, case['profile'], assessment, case['rubric'])
    if decision=='INSUFFICIENT_EVIDENCE':assert row['confidence_raw_score'] < 50
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
    from layer4_evaluation.thesis_output import TEMPLATE
    template=root/TEMPLATE;template.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(SOURCE/TEMPLATE,template)
    result = runner.export(root, run)
    assert result['relationships'] == 1+int(blocked) and result['status'] == ('PARTIAL' if blocked else 'COMPLETE')
    assert result['valid_assessments']==1
    assert read(Path(result['valid_results']))['assessments']==[dict(row,siap_id='000701')]
    coverage=read(Path(result['indicator_statuses']))['indicators']
    assert next(c for c in coverage if c['indicator_id']=='SYNTH_I')['decision']==decision
    assert bool(result['blocked_indicators'])==blocked
    if blocked:
        assert result['blocked_indicators'][0]['status']=='BLOCKED_ERROR'
        assert result['blocked_indicators'][0]['decision'] is None
        assert not result['blocked_indicators'][0]['project_complete']
    import csv
    with (run/'resultados/indicadores.csv').open(encoding='utf-8-sig',newline='') as stream:
        exported = list(csv.DictReader(stream,delimiter=';'))
    assert len(exported)==1+int(blocked)
    valid=next(r for r in exported if r['indicador_id']=='SYNTH_I')
    assert valid['estado_cumplimiento']==row['decision']
    assert float(valid['confianza'])==row['confidence_raw_score']
    assert valid['fuente_evidencia']=='methodology'
    assert (run/'resultados/indicadores_territorios.csv').is_file()
    book = openpyxl.load_workbook(result['excel'])
    assert book.sheetnames==['Proyectos','Artículos']
    assert list(next(book.worksheets[0].values))==runner.COLUMNS
    assert list(next(book.worksheets[1].values))==runner.COLUMNS
    if decision in ('SUPPORTED','INSUFFICIENT_EVIDENCE'):
        cells = next(r for r in list(book.worksheets[0].rows)[1:] if r[1].value=='SYNTH_I')
        assert cells[0].value == '000701' and cells[0].data_type == 's'
        assert cells[7].value == row['confidence_raw_score'] and cells[7].data_type == 'n'
        assert len(cells)==8
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


def test_new_base_real_preprocessing_writes_shared_staging_and_resumes(sandbox):
    from knowledge_store import knowledge_root, shared_root, run_state
    root, raw, original = sandbox
    source = raw / 'tiny-base.json'
    source.write_text(json.dumps(project()), encoding='utf-8')
    source_before = source.read_bytes()
    config = dict(original, knowledge_scope='BASE_GLOBAL_V1', base_knowledge_action='rebuild')
    run = root / 'outputs/runs/local/new_shared_base'
    result = runner.prepare(root, run, raw, 'prueba_en_vivo', config, through='preprocessing')
    assert result['status'] == 'PREPROCESSED' and result['counts']['proyectos'] == 1
    stage = knowledge_root(run)
    assert stage.parent == shared_root(root) / 'staging'
    assert not (run / 'workspace').exists()
    table = stage / 'workspace/outputs/layer2/canonical/proyectos.parquet'
    assert pq.read_table(table).to_pylist()[0]['source_project_id'] == '000701'
    sealed_before = {p.relative_to(stage).as_posix(): sha(p) for p in stage.rglob('*') if p.is_file()}
    assert runner.check(root, run)['status'] == 'PREPROCESSED'
    again = runner.prepare(root, run, raw, 'prueba_en_vivo', config, through='preprocessing')
    assert again['status'] == 'ALREADY_PREPARED' and knowledge_root(run) == stage
    assert {p.relative_to(stage).as_posix(): sha(p) for p in stage.rglob('*') if p.is_file()} == sealed_before
    assert run_state(run)['knowledge_build'] == stage.relative_to(root).as_posix()
    assert source.read_bytes() == source_before and not (shared_root(root) / 'active.json').exists()
