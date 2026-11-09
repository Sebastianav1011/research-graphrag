"""Small scoped ETL/quarantine integrations. Never embeddings or LLM calls."""
import csv
import json

import pyarrow.parquet as pq
import pytest

from .test_manual_pipeline import sandbox
from .test_unified_runner import system
from layer2_processing.preprocessing.adapters import read, write, sha
from scripts import pipeline_coordinator as runner


def setup_sources(root, papers, extra_members=()):
    base=root/'data/layer1_sources/base'
    write(base/'descriptores.json',[dict(id_actividad=p,title='Synthetic '+p,resumen='Synthetic research narrative '+p) for p in ('P1','P2')])
    write(base/'miembros.json',[dict(id_actividad='P1',id_empleado='EMP1',documento='DOC1',nombre_completo='Synthetic One'),
        dict(id_actividad='P2',id_empleado='EMP2',documento='DOC2',nombre_completo='Synthetic Two'),*extra_members])
    write(base/'produccion.json',papers)
    return base


def paper(key='A1',person='DOC1',title='Synthetic article',**extra):
    return dict(source_article_id=key,nombre_producto=title,resumen='Synthetic article evidence',anio=2024,
                cedula=person,investigador_docente='Synthetic researcher',**extra)


def scope(config, ids=('P1',)):
    return config|{'processing_scope':dict(mode='projects',project_ids=list(ids),primary_files=[])}


def rows(run,name):
    return pq.read_table(run/f'workspace/outputs/layer2/canonical/{name}.parquet').to_pylist()


def test_equivalent_publication_occurrences_consolidate_with_all_authors(sandbox):
    root,_,config=sandbox
    setup_sources(root,[paper(),paper(person='DOC2',title='  Synthetic ARTICLE  ')])
    run=root/'outputs/runs/equivalent'
    runner.prepare(root,run,root/'data/layer1_sources','raw',scope(config))
    assert len(rows(run,'proyectos'))==1 and len(rows(run,'articulos'))==1
    refs=json.loads(rows(run,'articulos')[0]['provenance_json'])
    assert len(refs)==2 and {r['source_row'] for r in refs}=={1,2}
    assert len(rows(run,'articulo_investigador'))==2
    projects={r['researcher_id'] for r in rows(run,'proyecto_investigador')}
    authors={r['researcher_id'] for r in rows(run,'articulo_investigador')}
    assert projects & authors
    assert read(run/'preprocess/scope.json')['selected_counts']==dict(proyectos=1,investigadores=1,articulos=2)
    assert runner.graph(root,run)['status']=='VALIDATED_APPROVED_LAYER_2_INPUT'


def test_unrelated_core_conflicts_do_not_enter_selected_etl(sandbox):
    root,_,config=sandbox
    setup_sources(root,[paper(),paper('B1','DOC2','Conflicting first'),paper('B1','DOC2','Conflicting second')])
    run=root/'outputs/runs/unrelated'
    assert runner.prepare(root,run,root/'data/layer1_sources','raw',scope(config))['status']=='PREPARED'
    assert {r['source_article_id'] for r in rows(run,'articulos')}=={'A1'}
    assert read(run/'run.json')['scope_quarantine']['status']=='VALIDATED_SCOPE'
    assert read(run/'preprocess/scope.json')['selected_counts']['articulos']==1


def test_related_conflict_is_quarantined_with_original_error_and_blocks_evaluation(sandbox):
    root,_,config=sandbox
    setup_sources(root,[paper(),paper(person='DOC2',title='Contradictory title'),paper('VALID','DOC1','Other valid article')])
    run=root/'outputs/runs/relevant'
    result=runner.prepare(root,run,root/'data/layer1_sources','raw',scope(config),through='preprocessing')
    assert result['status']=='PREPROCESSED'
    assert {r['source_article_id'] for r in rows(run,'articulos')}=={'VALID'}
    assert {r['article_id'] for r in rows(run,'articulo_investigador')}=={'ART_SRC_VALID'}
    report=read(run/'preprocess/scope_validation.json')
    assert report['affected_projects']=={'P1':['ART_SRC_A1']}
    audit=run/'workspace/outputs/layer2/preprocessing'
    with (audit/'audit/anomalies.csv').open(encoding='utf-8-sig') as stream:
        errors=[r for r in csv.DictReader(stream) if r['severity']=='ERROR']
    assert len(errors)==2 and {r['anomaly_code'] for r in errors}=={'CONFLICTING_SOURCE_ID'}
    rejected=[json.loads(line) for line in (audit/'quality/rejected_records.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(rejected)==2
    assert read(run/'workspace/outputs/layer2/canonical/_manifest.json')['scope_isolation']['quarantined_error_occurrences']==2
    runner.knowledge(root,run)
    assert runner.check(root,run)['status']=='PREPARED'
    docs=pq.read_table(run/'workspace/outputs/layer2/knowledge/source_documents.parquet').to_pylist()
    assert not any(d['source_id']=='ART_SRC_A1' for d in docs)
    with pytest.raises(ValueError,match='Cuarentena relevante'):
        runner.prepare_evaluation(root,run,['P1'])
    assert not (run/'workspace/outputs/layer4').exists()


def test_whole_corpus_keeps_strict_global_failure_and_quarantine(sandbox):
    root,_,config=sandbox
    setup_sources(root,[paper(),paper(title='Contradiction')])
    run=root/'outputs/runs/global'
    with pytest.raises(ValueError,match='ETL rechazo'):
        runner.prepare(root,run,root/'data/layer1_sources','raw',config)
    assert read(run/'run.json')['status']=='FAILED'
    assert not (run/'workspace/outputs/layer2/canonical/_manifest.json').exists()
    assert not list((run/'workspace/outputs/layer2/canonical').glob('*.parquet'))
    assert (run/'workspace/outputs/layer2/preprocessing/quality/production_conflicts.csv').is_file()


def test_scope_does_not_isolate_other_critical_errors(sandbox):
    root,_,config=sandbox
    bad=paper('BAD','DOC1','Invalid year');bad['anio']='not_an_integer'
    setup_sources(root,[paper(),paper(title='Contradiction'),bad])
    run=root/'outputs/runs/critical'
    with pytest.raises(ValueError,match='ETL rechazo'):
        runner.prepare(root,run,root/'data/layer1_sources','raw',scope(config))
    assert read(run/'run.json')['status']=='FAILED'
    latest=read(run/'workspace/outputs/layer2/preprocessing/latest_run.json')
    assert latest['scope_isolation']['blocking_error_occurrences']==1
    assert latest['scope_isolation']['quarantined_error_occurrences']==2
    assert not (run/'workspace/outputs/layer2/canonical/_manifest.json').exists()


def test_non_unique_journal_identifier_never_merges_articles(sandbox):
    root,_,config=sandbox
    one=paper(id_actividad='P1',issn_isbn='1234-5679',doi='10.9999/a');two=paper(title='Different article',id_actividad='P1',issn_isbn='1234-5679',doi='10.9999/b')
    one.pop('source_article_id');two.pop('source_article_id')
    setup_sources(root,[one,two])
    run=root/'outputs/runs/non_unique'
    runner.prepare(root,run,root/'data/layer1_sources','raw',scope(config))
    assert len(rows(run,'articulos'))==2
    assert len({r['article_id'] for r in rows(run,'articulos')})==2


def test_hidden_identity_contradiction_is_retained_as_context_not_false_edge(sandbox):
    root,_,config=sandbox
    setup_sources(root,[paper()],extra_members=[dict(id_actividad='P2',id_empleado='EMP_OTHER',documento='DOC1',nombre_completo='Other occurrence')])
    run=root/'outputs/runs/identity_context'
    runner.prepare(root,run,root/'data/layer1_sources','raw',scope(config))
    assert read(run/'preprocess/scope.json')['identity_context_records']>=1
    assert rows(run,'articulos')==[]
    scope_report=read(run/'preprocess/scope.json')
    assert scope_report['identity_links']['P1']['verified_article_groups']==0
    assert len(scope_report['unverified_production'])==1
    project_ids={r['researcher_id'] for r in rows(run,'proyecto_investigador')}
    article_ids={r['researcher_id'] for r in rows(run,'articulo_investigador')}
    assert not project_ids & article_ids
    assert all(r['identity_status']=='ambiguous' for r in rows(run,'investigadores'))
    main_id=next(iter(project_ids))
    full=root/'outputs/runs/identity_full'
    runner.prepare(root,full,root/'data/layer1_sources','raw',config)
    full_id=next(r['researcher_id'] for r in rows(full,'proyecto_investigador') if r['project_id']=='PROJ_P1')
    assert main_id==full_id


@pytest.mark.parametrize('mode',['projects','file','file_projects','delivery'])
def test_four_runner_modes_use_same_scoped_processing(sandbox,mode):
    root,_,config=sandbox
    setup_sources(root,[paper(),paper('B1','DOC2','Synthetic second')])
    write(root/'config/pipeline_manual.json',config)
    args={}
    if mode=='projects':args['project_ids']=['P1']
    else:
        from tests.test_layer1_intake import official_project_file
        primary=official_project_file(root, records=[dict(id_actividad=p,titulo_proyecto='Synthetic '+p,
            resumen='Synthetic research narrative '+p) for p in ('P1','P2')], relative='incoming/delivery/projects.xlsx')
        args['delivery']='delivery' if mode=='delivery' else None
        if mode!='delivery':args['input_file']=str(primary)
        if mode=='file_projects':args['project_ids']=['P1']
    result=runner.execute_pipeline(root,run_id=mode,through='knowledge',**args)
    assert result['status']=='COMPLETE'
    run=root/'outputs/runs'/mode
    expected={'P1'} if mode in ('projects','file_projects') else {'P1','P2'}
    assert {p['source_project_id'] for p in rows(run,'proyectos')}==expected
    before=sha(run/'workspace/outputs/layer2/canonical/proyectos.parquet')
    runner.execute_pipeline(root,run_id=mode,resume=True,through='knowledge')
    assert sha(run/'workspace/outputs/layer2/canonical/proyectos.parquet')==before


def test_sparse_occurrence_identity_and_raw_hashes_are_preserved(sandbox):
    root,_,config=sandbox
    setup_sources(root,[paper()])
    p=root/'data/layer1_sources/base/miembros.json'
    data=read(p)
    data.insert(0,dict(id_actividad='P2',id_empleado='OTHER',documento='OTHER_DOC',nombre_completo='Outside\n scope'))
    data[1]['id_investigador']='INCOMPATIBLE_ALIAS'
    write(p,data);before=sha(p)
    a=root/'outputs/runs/sparse';b=root/'outputs/runs/full'
    runner.prepare(root,a,root/'data/layer1_sources','raw',scope(config))
    runner.prepare(root,b,root/'data/layer1_sources','raw',config)
    selected=next(r for r in rows(a,'proyecto_investigador') if r['project_id']=='PROJ_P1')
    full=next(r for r in rows(b,'proyecto_investigador') if r['project_id']=='PROJ_P1')
    assert selected['researcher_id']==full['researcher_id']
    assert sha(p)==before and runner.check(root,a)['status']=='PREPARED'


def test_only_unaffected_projects_are_evaluated_and_excel_stays_partial(system,monkeypatch):
    original=runner.knowledge
    def knowledge(root,run):
        original(root,run)
        write(run/'run.json',read(run/'run.json')|{'scope_quarantine':{'affected_projects':{'002':['ART_SRC_BAD']}}})
    monkeypatch.setattr(runner,'knowledge',knowledge)
    result=runner.execute_pipeline(system.root,project_ids=['001','002','003'],through='export',confirm=system.confirm)
    assert result['status']=='PARTIAL' and result['result']['pending_projects']==['002']
    assert [c for c in system.calls if isinstance(c,tuple)]==[('ollama',['001','003'])]
    assert read(system.run()/'execution.json')['project_ids']==['001','002','003']
    runner.execute_pipeline(system.root,run_id=system.run().name,resume=True,confirm=system.confirm)
    assert len([c for c in system.calls if isinstance(c,tuple)])==1


def test_all_affected_projects_block_without_fake_classification(system,monkeypatch):
    original=runner.knowledge
    def knowledge(root,run):
        original(root,run)
        write(run/'run.json',read(run/'run.json')|{'scope_quarantine':{'affected_projects':{'001':['ART_SRC_BAD']}}})
    monkeypatch.setattr(runner,'knowledge',knowledge)
    monkeypatch.setattr(runner,'engine',lambda *a:pytest.fail('Blocked selections must not initialize the LLM engine'))
    result=runner.execute_pipeline(system.root,project_ids=['001'],through='export',confirm=system.confirm)
    assert result['status']=='BLOCKED_QUARANTINE'
    assert not any(isinstance(c,tuple) for c in system.calls)
    assert not (system.run()/'resultado_indicadores.xlsx').exists()


def test_quarantine_audit_and_state_are_part_of_the_checkpoint(sandbox):
    root,_,config=sandbox
    setup_sources(root,[paper(),paper(title='Contradiction')])
    run=root/'outputs/runs/sealed_quarantine'
    runner.prepare(root,run,root/'data/layer1_sources','raw',scope(config))
    assert runner.check(root,run)['status']=='PREPARED'
    state=read(run/'run.json');original=(run/'run.json').read_bytes()
    state['scope_quarantine']['affected_projects']={}
    write(run/'run.json',state)
    with pytest.raises(ValueError,match='informe sellado'):
        runner.check(root,run)
    (run/'run.json').write_bytes(original)
    path=run/'workspace/outputs/layer2/preprocessing/quality/production_conflicts.csv'
    with path.open('a',encoding='utf-8') as stream:stream.write('\n')
    with pytest.raises(ValueError,match='Producto de preprocesamiento modificado'):
        runner.check(root,run)
