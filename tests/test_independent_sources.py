"""Independent incoming corpora use the same native ETL/knowledge interfaces."""
import json
from types import SimpleNamespace

import pyarrow.parquet as pq
import pytest
import yaml

from .test_manual_pipeline import sandbox
from .test_scoped_identity import setup_sources, paper, rows
from .test_unified_runner import system
from layer2_processing.preprocessing import adapters
from layer3_graphrag import embeddings
from scripts import pipeline_coordinator as runner


@pytest.mark.parametrize('mode', ['file', 'file_projects', 'delivery'])
def test_incoming_never_reads_base_and_keeps_local_evidence(sandbox, monkeypatch, mode):
    root, _, _ = sandbox
    setup_sources(root, [paper(), paper(title='Base quarantine conflict')])
    primary = root/'data/layer1_sources/incoming/local/objectives.json'
    adapters.write(primary, [dict(id_proyecto=p, titulo='Local '+p,
        descripcion_objetivo='Authorized synthetic objective '+p) for p in ('LOCAL1', 'LOCAL2')])
    second = primary.parent/'results.json'
    if mode == 'delivery':
        adapters.write(second, [dict(id_proyecto='LOCAL1', titulo='Local LOCAL1',
            resultados_obtenidos='Authorized synthetic reported result')])
    cfg = adapters.read(root/'config/pipeline_manual.json')
    cfg['text_columns']['include'] = ['descripcion_objetivo', 'resultados_obtenidos']
    adapters.write(root/'config/pipeline_manual.json', cfg)
    original = adapters.read_source
    def read_only_selected(path, *a, **kw):
        assert 'base' not in path.parts, 'Independent run accessed an institutional base'
        return original(path, *a, **kw)
    monkeypatch.setattr(adapters, 'read_source', read_only_selected)
    args = {'delivery':'local'} if mode == 'delivery' else {'input_file':str(primary)}
    if mode == 'file_projects': args['project_ids'] = ['LOCAL2']
    settings, raw, _ = runner.selected_configuration(root, 'config/pipeline_manual.json', **{k:v for k,v in args.items() if k!='project_ids'})
    found = adapters.discover_sources(root, settings, raw)
    assert found['status'] == 'READY_FOR_VALIDATION'
    assert all('exact_base_matches' not in r for f in found['files'] for r in f['relations'])
    before = adapters.sha(primary)
    result = runner.execute_pipeline(root, run_id=mode, through='knowledge', **args)
    assert result['status'] == 'COMPLETE'
    run = root/'outputs/runs'/mode
    expected = {'LOCAL2'} if mode == 'file_projects' else {'LOCAL1','LOCAL2'}
    assert {r['source_project_id'] for r in rows(run,'proyectos')} == expected
    sources = adapters.read(run/'raw_manifest.json')['files']
    assert set(sources) == {p.relative_to(raw).as_posix() for p in ([primary,second] if mode=='delivery' else [primary])}
    knowledge = run/'workspace/outputs/layer2/knowledge'
    docs = pq.read_table(knowledge/'source_documents.parquet').to_pylist()
    assert len(docs) == len(expected)
    for d in docs:
        assert d['source_id'].removeprefix('PROJ_') in expected
        assert 'base/' not in d['provenance_json'].replace('\\','/')
    sections = pq.read_table(knowledge/'source_sections.parquet').to_pylist()
    assert any('objective' in json.dumps(s).lower() for s in sections)
    if mode == 'delivery':
        assert any('reported result' in json.dumps(s) for s in sections)
    assert pq.read_table(knowledge/'reference_documents.parquet').num_rows == 48
    assert runner.graph(root,run)['status'] == 'VALIDATED_APPROVED_LAYER_2_INPUT'
    graph_cfg = yaml.safe_load((run/'workspace/config/layer3.yaml').read_text(encoding='utf-8'))
    assert graph_cfg['input']['knowledge_manifest'].startswith('outputs/')
    assert not (run/'workspace/outputs/layer3/publication').exists()
    original_canonical = adapters.sha(run/'workspace/outputs/layer2/canonical/proyectos.parquet')
    runner.execute_pipeline(root,run_id=mode,resume=True,through='knowledge')
    assert adapters.sha(run/'workspace/outputs/layer2/canonical/proyectos.parquet') == original_canonical
    assert adapters.sha(primary) == before
    adapters.write(primary, [dict(id_proyecto='CHANGED', descripcion_objetivo='changed')])
    with pytest.raises(ValueError, match='RAW cambio'):
        runner.check(root,run)


def test_missing_local_id_never_falls_back_to_base(sandbox):
    root, _, _ = sandbox
    setup_sources(root, [paper()])
    p = root/'data/layer1_sources/incoming/local.json'
    adapters.write(p,[dict(id_proyecto='LOCAL',resumen='Local synthetic evidence')])
    with pytest.raises(ValueError,match='no presentes.*P1'):
        runner.execute_pipeline(root,input_file=str(p),project_ids=['P1'],through='knowledge')
    assert not list((root/'outputs/runs').rglob('proyectos.parquet'))


def test_local_identity_contradiction_still_blocks(sandbox):
    root, _, _ = sandbox
    p = root/'data/layer1_sources/incoming/conflict.json'
    adapters.write(p,[dict(id_proyecto='LOCAL',titulo=t,resumen='Local evidence') for t in ('First','Contradiction')])
    with pytest.raises(ValueError,match='ETL rechazo'):
        runner.execute_pipeline(root,input_file=str(p),through='knowledge')
    assert not list((root/'outputs/runs').rglob('source_documents.parquet'))


def test_unapproved_new_field_remains_outside_documents(sandbox):
    root, _, _ = sandbox
    p = root/'data/layer1_sources/incoming/local.json'
    adapters.write(p,[dict(id_proyecto='LOCAL',resumen='Authorized known narrative',
        impacto_regional='UNAPPROVED_MARKER',campo_desconocido='UNKNOWN_MARKER')])
    cfg, raw, _ = runner.selected_configuration(root,'config/pipeline_manual.json',input_file=str(p))
    item = adapters.discover_sources(root,cfg,raw)['files'][0]
    assert 'impacto_regional' in item['pending_authorization']
    runner.execute_pipeline(root,run_id='privacy',input_file=str(p),through='knowledge')
    folder = root/'outputs/runs/privacy/workspace/outputs/layer2/knowledge'
    texts = [(s['text_original'] or '') + (s['text_normalized'] or '')
             for s in pq.read_table(folder/'source_sections.parquet').to_pylist()]
    assert all('UNAPPROVED_MARKER' not in t and 'UNKNOWN_MARKER' not in t for t in texts)


def test_embedding_bundle_from_another_corpus_is_not_reused(monkeypatch):
    bundle = SimpleNamespace(metadata={'embedding_config_hash':'same-model','layer2_manifest_hash':'other-corpus'},records=[])
    monkeypatch.setattr(embeddings,'load_bundle',lambda p:bundle)
    monkeypatch.setattr(embeddings,'embedding_config_hash',lambda *a:'same-model')
    snapshot = SimpleNamespace(manifest_hash='selected-corpus',tables={'source_chunks':[]})
    assert embeddings.reuse_bundle('unused',snapshot,'SOURCE',object(),{},'run') is None


def test_delivery_joins_only_its_verified_members_and_articles(sandbox):
    root, _, _ = sandbox
    setup_sources(root,[paper('BASE','BASE_DOC')])
    folder = root/'data/layer1_sources/incoming/local'
    adapters.write(folder/'projects.json',[dict(id_proyecto='LOCAL',titulo='Local project',resumen='Local evidence')])
    adapters.write(folder/'members.json',[dict(id_actividad='LOCAL',id_empleado='LOCAL_EMP',documento='LOCAL_DOC',nombre_completo='Synthetic local person')])
    adapters.write(folder/'articles.json',[paper('LOCAL_ART','LOCAL_DOC')])
    runner.execute_pipeline(root,run_id='links',delivery='local',through='knowledge')
    run = root/'outputs/runs/links'
    assert {r['source_project_id'] for r in rows(run,'proyectos')} == {'LOCAL'}
    assert {r['source_article_id'] for r in rows(run,'articulos')} == {'LOCAL_ART'}
    memberships = rows(run,'proyecto_investigador')
    authors = rows(run,'articulo_investigador')
    assert len(memberships) == len(authors) == 1
    assert memberships[0]['researcher_id'] == authors[0]['researcher_id']
    assert all('base/' not in json.dumps(r).replace('\\','/') for r in memberships+authors)


def test_old_mixed_checkpoint_cannot_resume_as_independent(system):
    primary = system.intake/'incoming/local.json'
    adapters.write(primary,[dict(id='001',summary='Local narrative')])
    system.projects[0]['provenance_json'] = json.dumps([dict(record_source=str(primary))])
    runner.execute_pipeline(system.root,run_id='legacy',input_file=str(primary),through='knowledge')
    path = system.run()/'run.json'
    state = adapters.read(path)
    state['configuration']['source_paths'].append('base/descriptores-limpio.json')
    adapters.write(path,state)
    with pytest.raises(ValueError,match='fuentes externas'):
        runner.execute_pipeline(system.root,run_id='legacy',resume=True,through='knowledge')
