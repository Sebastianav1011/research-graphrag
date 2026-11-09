"""Catalog data lineage versus current runtime, without inference or a pipeline."""
from copy import deepcopy
from pathlib import Path
import shutil

import pytest

import run as console
from autonomous_execution import cli,lifecycle as l,preparation_integrity as i,store as s,prepare_menu
from tests.test_autonomous_execution import environment,stub_discovery
from tests.test_autonomous_prepare_menu import wizard,answers
from tests.test_context_budget import corpus
from tests.test_ollama_provider import sample


@pytest.fixture
def publication(tmp_path):
    from layer2_processing.checkpoints import registry
    real=Path(i.__file__).resolve().parents[2]
    _,receipts=i.catalog(real)
    for name in receipts:
        target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(real/name,target)
    (tmp_path/'config').mkdir(exist_ok=True)
    s.write(tmp_path/'config/sad_relocations.json',registry(real))
    return tmp_path


def test_catalog_checks_data_independently_of_obsolete_executable_hashes(publication):
    path=publication/i.REFERENCE;approved=s.read(path)
    approved['source_hashes']['src/layer4/indicators/assessment_v3.py']='0'*64
    s.write(path,approved)
    current,receipts=i.catalog(publication)
    assert all(current[key]==approved[key] for key in ('profiles','rules','rubrics'))
    assert len(current['profiles'])==48
    assert not any(name.endswith('.py') for name in receipts)
    assert all(s.sha(publication/name)==digest for name,digest in receipts.items())


def test_altered_approved_rubric_file_is_not_accepted(publication):
    from layer2_processing.checkpoints import resolve
    path=resolve(publication,i.RUBRICS);expected=s.sha(path)
    path.write_bytes(path.read_bytes()+b' ');actual=s.sha(path)
    with pytest.raises(ValueError) as error:i.catalog(publication)
    assert all(value in str(error.value) for value in (i.RUBRICS,expected,actual,i.REFERENCE,'EXACT_SHA256'))


@pytest.mark.parametrize('field',['profiles','rubrics','rules'])
def test_catalog_semantics_cannot_change_through_a_new_reference(publication,field):
    path=publication/i.REFERENCE;reference=s.read(path)
    if field=='rules':reference[field]=[]
    else:reference[field].pop(next(iter(reference[field])))
    s.write(path,reference)
    with pytest.raises(ValueError,match='CATALOG_DATA_MISMATCH'):i.catalog(publication)


@pytest.fixture
def fresh(environment,monkeypatch):
    e=environment
    (e.root/'src').mkdir()
    s.write(e.root/'schemas/layer4_assessment_v3/assessment.schema.json',{})
    source=e.root/'src/current_runtime.py';source.write_text('# runtime one',encoding='utf-8')
    old=s.read(e.directory/'manifest.json')
    data=dict(profiles=deepcopy(old['profiles']),rubrics=deepcopy(old['rubrics']),rules=[])
    release=e.root/'approved_catalog.json';s.write(release,data)
    def catalog(root):
        return deepcopy(data),{'approved_catalog.json':s.sha(release)}
    monkeypatch.setattr(i,'catalog',catalog)
    def history(root,run):
        return i.historical(root,run,lambda *a:({}, {},old['runtime'],None))
    monkeypatch.setattr(l,'historical',history)
    monkeypatch.setattr(l,'OllamaClient',lambda *a:pytest.fail('Ollama forbidden'))
    monkeypatch.setattr('layer3_graphrag.embeddings.SentenceTransformersProvider._load',lambda *a:pytest.fail('Embeddings forbidden'))
    def clone(name):
        run=e.root/'outputs/runs'/name;run.mkdir(parents=True)
        for filename in ('run.json','execution.json','raw_manifest.json','prepared_hashes.json'):
            shutil.copyfile(e.run/filename,run/filename)
        shutil.copytree(e.run/'workspace',run/'workspace')
        state=s.read(run/'run.json');state['code_hashes']=i.runtime_files(e.root);s.write(run/'run.json',state)
        return run
    e.clone=clone;e.source=source;e.catalog=catalog
    return e


def test_prepared_checkpoint_recovers_and_pins_current_code_without_reprocessing(fresh):
    e=fresh;run=e.clone('new');state=(run/'run.json').read_bytes()
    prepared=(run/'prepared_hashes.json').read_bytes()
    result=l.prepare(e.root,run,e.policy)
    manifest=l.verify(e.root,run,require_authorization=False)
    assert manifest['catalog_binding']['version']==i.VERSION
    assert manifest['code']['src/current_runtime.py']==s.sha(e.source)
    assert manifest['code']==i.runtime_files(e.root)
    assert s.sha(l.folder(run)/'manifest.json')==result['manifest_sha256']
    assert (run/'run.json').read_bytes()==state and (run/'prepared_hashes.json').read_bytes()==prepared
    assert manifest['imported_pass']==0
    assert not (l.folder(run)/'authorization.json').exists()


def test_changes_after_authorization_report_exact_hashes_and_keep_manifest(fresh):
    e=fresh;run=e.clone('authorized');result=l.prepare(e.root,run,e.policy)
    l.authorize(e.root,run,result['manifest_sha256'])
    path=l.folder(run)/'manifest.json';before=path.read_bytes();expected=s.sha(e.source)
    e.source.write_text('# runtime two',encoding='utf-8');actual=s.sha(e.source)
    with pytest.raises(ValueError) as error:l.verify(e.root,run)
    assert all(word in str(error.value) for word in ('src/current_runtime.py',expected,actual,str(path)))
    assert path.read_bytes()==before
    with pytest.raises(ValueError,match='INTEGRITY_MISMATCH'):l.prepare(e.root,run,e.policy)


def test_next_new_run_uses_updated_code_without_rewriting_previous_run(fresh):
    e=fresh;first=e.clone('first');l.prepare(e.root,first,e.policy)
    previous=(l.folder(first)/'manifest.json').read_bytes()
    e.source.write_text('# new runtime',encoding='utf-8')
    second=e.clone('second');l.prepare(e.root,second,e.policy)
    assert l.verify(e.root,second,require_authorization=False)['code']['src/current_runtime.py']==s.sha(e.source)
    assert (l.folder(first)/'manifest.json').read_bytes()==previous
    with pytest.raises(ValueError,match='INTEGRITY_MISMATCH'):l.verify(e.root,first,require_authorization=False)


def test_actual_code_change_since_preprocessing_requires_new_checkpoint(fresh):
    e=fresh;run=e.clone('interrupted');state=(run/'run.json').read_bytes()
    expected=s.sha(e.source);e.source.write_text('# incompatible',encoding='utf-8')
    with pytest.raises(ValueError) as error:l.prepare(e.root,run,e.policy)
    assert all(value in str(error.value) for value in (expected,s.sha(e.source),str(run/'run.json')))
    assert (run/'run.json').read_bytes()==state
    assert not (l.folder(run)/'manifest.json').exists()


def test_new_code_dependency_is_bound_when_recovering_an_older_prepared_checkpoint(fresh):
    e=fresh;run=e.clone('recoverable')
    (e.root/'src/new_adapter.py').write_text('# additive dependency',encoding='utf-8')
    l.prepare(e.root,run,e.policy)
    manifest=l.verify(e.root,run,require_authorization=False)
    assert manifest['code']['src/new_adapter.py']==s.sha(e.root/'src/new_adapter.py')


def test_changed_schema_and_catalog_are_rejected_after_preparation(fresh):
    e=fresh;run=e.clone('schema');result=l.prepare(e.root,run,e.policy)
    l.authorize(e.root,run,result['manifest_sha256'])
    path=e.root/'schemas/layer4_assessment_v3/assessment.schema.json';original=path.read_bytes()
    path.write_bytes(original+b' ')
    with pytest.raises(ValueError,match='INTEGRITY_MISMATCH'):l.verify(e.root,run)
    path.write_bytes(original)
    (e.root/'approved_catalog.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='artefacto autorizado cambiado'):l.verify(e.root,run)


def test_existing_manifest_never_rebuilds_catalog(environment,monkeypatch):
    e=environment;before=(e.directory/'manifest.json').read_bytes()
    monkeypatch.setattr(i,'catalog',lambda *a:pytest.fail('Existing manifest must be preserved'))
    result=l.prepare(e.root,e.run,e.policy)
    assert result['manifest_sha256']==s.sha(e.directory/'manifest.json')
    assert (e.directory/'manifest.json').read_bytes()==before


def test_noninteractive_prepare_uses_same_current_catalog_binding(fresh,monkeypatch):
    e=fresh;run=e.clone('scripted');s.write(e.root/'config/autonomous.json',e.policy)
    monkeypatch.setattr(e.coordinator,'configuration',lambda root,path:({},root/'data/layer1_sources',root/'outputs/runs'))
    monkeypatch.setattr('builtins.input',lambda *a:pytest.fail('Noninteractive prepare asked a question'))
    monkeypatch.setattr('autonomous_execution.discovery.prepare',lambda root,run:stub_discovery(e,run))
    args=console.parser().parse_args(['prepare','--autonomous','--run-id',run.name,'--non-interactive'])
    result=cli.dispatch(e.root,args,e.coordinator)
    assert result['status']=='REVIEW_REQUIRED'
    assert s.read(l.folder(run)/'manifest.json')['catalog_binding']['version']==i.VERSION


def test_interactive_prepare_uses_same_binding_without_implicit_approval(wizard,monkeypatch):
    e=wizard;old=s.read(e.directory/'manifest.json')
    data=dict(profiles=old['profiles'],rubrics=old['rubrics'],rules=[])
    s.write(e.root/'approved_catalog.json',data)
    monkeypatch.setattr(i,'catalog',lambda root:(data,{'approved_catalog.json':s.sha(root/'approved_catalog.json')}))
    monkeypatch.setattr(l,'historical',lambda root,run:i.historical(root,run,lambda *a:({}, {},old['runtime'],None)))
    answers(monkeypatch,['1','1','1',''])
    result=prepare_menu.prepare(e.root,e.menu_args,e.coordinator,e.original)
    manifest=s.read(l.folder(e.root/'outputs/runs/menu_new')/'manifest.json')
    assert result['status']=='REVIEW_REQUIRED' and manifest['catalog_binding']['version']==i.VERSION
    assert not (l.folder(e.root/'outputs/runs/menu_new')/'authorization.json').exists()


@pytest.fixture
def autonomous_reuse_source(tmp_path,monkeypatch):
    """Disposable copy of the affected run; models/builds are forbidden."""
    import sqlite3
    real=Path(i.__file__).resolve().parents[2];name='run_20261104_005250_337992'
    source=real/'outputs/runs'/name
    if not source.exists():pytest.skip('Affected live run is not available')
    root=tmp_path;run=root/'outputs/runs'/name
    shutil.copytree(source,run)
    original=s.read(l.folder(run)/'manifest.json')
    names=set(original['files'])|set(i.runtime_files(real))|set(i.catalog(real)[1])
    names.update(path.relative_to(real).as_posix() for path in (real/'config').glob('*') if path.is_file())
    names.update(original['source_inventory']['files'])
    for name in names:
        target=root/name
        if target.exists():continue
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(real/name,target)
    from layer2_processing.checkpoints import registry
    s.write(root/'config/sad_relocations.json',registry(real))
    # Keep the original provenance bytes while mapping the copied fixture root.
    from layer2_processing import checkpoints
    original_resolve=checkpoints.resolve
    def resolve(base,path):
        path=Path(path)
        if Path(base).resolve()==root.resolve() and path.is_absolute() and path.is_relative_to(real):
            path=path.relative_to(real)
        return original_resolve(base,path)
    monkeypatch.setattr(checkpoints,'resolve',resolve)
    # This fixture has its own original authorization, never edits the real run.
    original['repository_root']=str(root.resolve())
    # This synthetic authorized copy uses current executable code over historical
    # data. Production still rejects drift; never rewrite the real run's hashes.
    original['code']={name:s.sha(root/name) for name in original['code']}
    s.write(l.folder(run)/'manifest.json',original)
    auth=s.read(l.folder(run)/'authorization.json');auth['manifest_sha256']=s.sha(l.folder(run)/'manifest.json')
    s.write(l.folder(run)/'authorization.json',auth)
    db=sqlite3.connect(l.folder(run)/'queue.sqlite')
    try:
        for row in db.execute("SELECT pid,iid,result_path FROM jobs WHERE status='PASS'").fetchall():
            path=l.folder(run)/row[2];bundle=s.read(path);bundle['manifest_sha256']=auth['manifest_sha256'];s.write(path,bundle)
            db.execute('UPDATE jobs SET result_hash=? WHERE pid=? AND iid=?',(s.sha(path),row[0],row[1]))
        db.commit()
    finally:db.close()
    def forbidden(*args,**kwargs):pytest.fail('Inference, embeddings or pipeline rebuild forbidden')
    monkeypatch.setattr(l.OllamaClient,'inspect',forbidden)
    monkeypatch.setattr('layer3_graphrag.embeddings.SentenceTransformersProvider._load',forbidden)
    monkeypatch.setattr('scripts.pipeline_coordinator.execute_pipeline',forbidden)
    monkeypatch.setattr('scripts.pipeline_coordinator.graph',forbidden)
    return root,run,original


def test_reuse_autonomous_run_imports_pass_and_preserves_source(autonomous_reuse_source):
    from autonomous_execution import minimal
    root,source,old=autonomous_reuse_source
    before={p.relative_to(source).as_posix():s.sha(p) for p in source.rglob('*') if p.is_file()}
    report=i.reuse_run(root,source.name,'recovered',old['policy']);run=root/'outputs/runs/recovered'
    manifest=l.verify(root,run,require_authorization=False)
    assert report['imported_pass']==45 and report['pending']==373 and report['blocked']==3
    assert manifest['profiles']==old['profiles'] and manifest['rubrics']==old['rubrics']
    assert manifest['context_policy']==old['context_policy'] and manifest['llm']==old['llm']
    assert manifest['reuse']['source_run']==source.name
    assert not (l.folder(run)/'authorization.json').exists()
    assert before=={p.relative_to(source).as_posix():s.sha(p) for p in source.rglob('*') if p.is_file()}
    for name in ('source_sections.parquet','source_chunks.parquet'):
        assert s.sha(run/'workspace/outputs/layer2/knowledge'/name)==s.sha(source/'workspace/outputs/layer2/knowledge'/name)
    assert s.sha(run/'discovery_candidates.parquet')==s.sha(source/'discovery_candidates.parquet')
    worker=minimal.MinimalWorker(l.folder(run),manifest)
    try:
        for row in worker.db.execute("SELECT * FROM jobs WHERE status='PASS'"):
            assert worker.adopt(dict(row),worker.load_project(row['pid']),commit=False)
        assert worker.db.execute("SELECT error FROM jobs WHERE pid='PROJ_22344' AND iid='AMB-01'").fetchone()[0] is None
    finally:worker.close()
    with pytest.raises(ValueError,match='autorizacion'):l.verify(root,run)
    # Controlled completed subset: reuse persisted decisions and the normal exporter.
    from autonomous_execution.final_output import render,source_labels
    import openpyxl
    bundle=s.read(l.folder(run)/'results/PROJ_22342/AMB-01.json');project=s.read(l.folder(run)/'inputs/PROJ_22342.json')['project']
    names,locations=source_labels(project,bundle['row']['evidence_source_fields'])
    records=[dict(siap_id=project['siap_id'],investigador_id=None,indicador_id='AMB-01',
        estado_cumplimiento=bundle['row']['decision'],confianza=bundle['row']['confidence_raw_score'],
        parrafo_evidencia=bundle['row']['evidence_explanation'],fuente_evidencia=names,ubicacion_evidencia=locations)]
    target=root/'resultado_final.xlsx';render(root,records,target)
    book=openpyxl.load_workbook(target,read_only=True)
    assert book['INDICADORES'].max_row==2 and book.sheetnames==['INDICADORES','TERRITORIOS'];book.close()


@pytest.mark.parametrize('mutation',['raw','vectors','schema','catalog'])
def test_reuse_rejects_modified_or_incompatible_artifacts(autonomous_reuse_source,mutation):
    root,source,old=autonomous_reuse_source
    names=dict(raw='data/layer1_sources/incoming/PruebaReunion/DescriptoresFinal.xlsx',
        vectors=(source/'workspace/outputs/layer3/publication/indexes/source/vectors.npy').relative_to(root).as_posix(),
        schema='src/layer4_evaluation/indicators/assessment_v3.py',catalog='outputs/layer4/indicator_profiles/indicator_assessment_rules.json')
    path=root/names[mutation];path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):i.reuse_run(root,source.name,'rejected',old['policy'])
    assert not (root/'outputs/runs/rejected/autonomous/main/manifest.json').exists()


def test_reuse_leaves_incompatible_pass_pending(autonomous_reuse_source):
    import sqlite3
    root,source,old=autonomous_reuse_source
    path=l.folder(source)/'results/PROJ_22342/AMB-01.json';bundle=s.read(path)
    bundle['row']['confidence_raw_score']=999;s.write(path,bundle)
    # A self-consistent queue checksum alone must not make an invalid score reusable.
    db=sqlite3.connect(l.folder(source)/'queue.sqlite')
    db.execute("UPDATE jobs SET result_hash=? WHERE pid='PROJ_22342' AND iid='AMB-01'",(s.sha(path),));db.commit();db.close()
    report=i.reuse_run(root,source.name,'rejected_result',old['policy'])
    assert report['imported_pass']==44 and report['pending']==374 and report['rejected_imports']==1
    assert not (root/'outputs/runs/rejected_result/autonomous/main/results/PROJ_22342/AMB-01.json').exists()


def test_reuse_cli_dispatches_existing_preparation_without_authorizing(monkeypatch,tmp_path):
    args=console.parser().parse_args(['prepare','--autonomous','--run-id','new','--reuse-run','old','--non-interactive'])
    s.write(tmp_path/'config/autonomous.json',{})
    seen=[]
    options=[]
    monkeypatch.setattr(i,'reuse_run',lambda *args,**kwargs:seen.append(args) or options.append(kwargs) or dict(status='REVIEW_REQUIRED'))
    from scripts import pipeline_coordinator
    assert cli.dispatch(tmp_path,args,pipeline_coordinator)['status']=='REVIEW_REQUIRED'
    assert seen[0][1:3]==('old','new')
    assert options[0]['batch_size']==1  # Batching needs explicit opt-in until quality review.
    args.authorize_llm=True
    with pytest.raises(ValueError,match='sin cambiar alcance ni autorizar'):cli.dispatch(tmp_path,args,pipeline_coordinator)


def test_reuse_never_requeues_an_uncertain_inference(autonomous_reuse_source):
    import sqlite3
    root,source,old=autonomous_reuse_source
    db=sqlite3.connect(l.folder(source)/'queue.sqlite')
    db.execute("UPDATE jobs SET status='UNCERTAIN' WHERE pid='PROJ_22344' AND iid='AMB-01'");db.commit();db.close()
    with pytest.raises(ValueError,match='SOURCE_OUTCOME_UNCERTAIN'):
        i.reuse_run(root,source.name,'uncertain',old['policy'])
    assert not (root/'outputs/runs/uncertain').exists()
