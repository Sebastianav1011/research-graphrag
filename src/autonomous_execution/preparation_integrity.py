"""Current runtime receipts, separate from the approved catalog's data lineage.

An additive lifecycle adapter preserves the source bytes pinned by historical
runs. Existing manifests and evaluation batches keep their original verifier.
New runs consume the same approved profiles/rubrics, not an old run's executable
hashes. All dependencies of the resulting release are pinned before approval.
"""
from run_paths import file_path as run_file
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import uuid

from . import store as s

VERSION='CURRENT_RUNTIME_CATALOG_V1'
REFERENCE='outputs/layer4/pruebas/validacion_v3_3/cierre_homogeneo_v3_3/closure.plan.json'
PROFILE_DIRECTORY='outputs/layer4/indicator_profiles'
RUBRICS='outputs/layer4/pruebas/mejora_cobertura_v3/continuacion_prompt_v3_1/rubrics.json'
_preparing=ContextVar('autonomous_catalog_preparation',default=None)


def mismatch(name,expected,actual,origin,*,rule='EXACT_SHA256'):
    return ValueError(f'INTEGRITY_MISMATCH field={name} rule={rule} expected={expected} '
        f'actual={actual} origin={origin}. No se acepta otro codigo ni se actualizan hashes '
        'del checkpoint. Restaurar la version registrada o preparar un run nuevo y autorizarlo.')


def receipt(root,name,expected=None,*,origin):
    from layer2_processing.checkpoints import resolve
    root=Path(root).resolve();path=resolve(root,name)
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise ValueError('Dependencia fuera de la raiz o redirigida: '+str(name))
    actual=s.sha(path) if path.is_file() else 'MISSING'
    if actual=='MISSING' or expected is not None and expected!=actual:
        raise mismatch(name,expected or 'EXISTING_FILE',actual,origin)
    return path.relative_to(root).as_posix(),actual


def runtime_files(root):
    root=Path(root)
    files=set((root/'src').rglob('*.py'))
    files.update(root/name for name in ('run.py','scripts/__init__.py',
        'scripts/pipeline_coordinator.py','scripts/run_pipeline_manual.py'))
    for directory in ('schemas/layer4_assessment','schemas/layer4_assessment_v2','schemas/layer4_assessment_v3'):
        files.update((root/directory).glob('*.json'))
    return {path.relative_to(root).as_posix():s.sha(path) for path in sorted(files) if path.is_file()}


def catalog(root):
    """Validate approved DATA against current profile publication and V3 rules.

    The old closure supplies data provenance only. Its projects, calls, budgets,
    code_hashes and executable source_hashes are never a new runtime contract.
    """
    from layer4_evaluation.indicators import profiles as pr,assessment_v3 as v3
    root=Path(root).resolve();files={}
    def pin(name,expected=None,origin=REFERENCE):
        rel,digest=receipt(root,name,expected,origin=origin)
        files[rel]=digest
        return root/rel
    reference=pin(REFERENCE)
    approved=s.read(reference)
    profile_manifest=pin(PROFILE_DIRECTORY+'/indicator_assessment_profiles_manifest.json')
    manifest=s.read(profile_manifest)
    for name,digest in manifest['outputs'].items():
        if Path(name).name!=name:
            raise ValueError('Nombre de publicacion de perfiles invalido')
        pin(PROFILE_DIRECTORY+'/'+name,digest,str(profile_manifest.relative_to(root)))
    pin(manifest['source_catalog'],manifest['source_hash'],str(profile_manifest.relative_to(root)))
    pin(manifest['source_snapshot'],manifest['source_hash'],str(profile_manifest.relative_to(root)))
    profiles,_=pr.load_profiles(root)  # Existing logical/schema/source checks.
    profiles={item['indicator_id']:item for item in profiles}
    rules=s.read(root/PROFILE_DIRECTORY/'indicator_assessment_rules.json')['rules']
    expected=approved['source_hashes'].get(RUBRICS)
    if expected is None:
        raise ValueError('La publicacion aprobada no identifica el hash de sus rubricas')
    rubrics=s.read(pin(RUBRICS,expected))
    if profiles!=approved['profiles'] or rules!=approved['rules'] or rubrics!=approved['rubrics']:
        raise ValueError('CATALOG_DATA_MISMATCH: perfiles, reglas o rubricas difieren de la '
            'publicacion aprobada; revisar el catalogo, no actualizar hashes de codigo historicos')
    if len(profiles)!=48 or set(profiles)!=set(rubrics):
        raise ValueError('CATALOG_DATA_MISMATCH: se requieren las 48 rubricas del catalogo')
    for iid,profile in profiles.items():
        v3.check_rubric(profile,rubrics[iid])
    for name,digest in files.items():
        receipt(root,name,digest,origin=REFERENCE)
    return dict(profiles=profiles,rubrics=rubrics,rules=rules),files


def historical(root,run,original):
    if (run_file(Path(run), 'reuse.json')).exists():
        accepted,files,binding,previous=reused_history(root,run)
    else:accepted,files,binding,previous=original(root,run)
    context=_preparing.get()
    if previous is not None or context is None:
        return accepted,files,binding,previous
    try:
        current,data=catalog(root)
        code=runtime_files(root)
        release=Path(run)/'autonomous/catalog_releases'/(uuid.uuid4().hex+'.json')
        s.write(release,dict(version=VERSION,created_at=s.now(),reference=REFERENCE,
            profiles=current['profiles'],rubrics=current['rubrics'],rules=current['rules'],
            data=data,code=code))
        context.update(release=release,data=data,code=code)
        return accepted,files|data|{release.relative_to(root).as_posix():s.sha(release)},binding,current
    except BaseException:
        if hasattr(accepted,'close'):
            accepted.close()
        raise


def check_prepared_code(root,run):
    from layer2_processing.checkpoints import verify_expected,resolve
    path=run_file(Path(run), 'run.json')
    if not path.exists():
        return
    for name,expected in s.read(path).get('code_hashes',{}).items():
        try:
            verify_expected(root,name,expected)  # Keep historical migration bindings.
        except ValueError as exc:
            actual_path=resolve(root,name)
            actual=s.sha(actual_path) if actual_path.is_file() else 'MISSING'
            raise mismatch(name,expected,actual,str(path)) from exc


def check_manifest_code(root,run):
    path=Path(run)/'autonomous/main/manifest.json'
    if not path.exists():
        return
    manifest=s.read(path)
    if manifest.get('catalog_binding',{}).get('version')!=VERSION:
        return
    for name,expected in manifest['code'].items():
        receipt(root,name,expected,origin=str(path))


def reusable_result(root,source,manifest,job,data):
    """Revalidate the original model transcript, references and existing score."""
    import json
    from jsonschema import Draft202012Validator
    from . import minimal as m, policy as p
    from .engine import identity,result_row,gate
    version=manifest.get('schema_version',m.v3.VERSION)
    pid,iid=job['pid'],job['iid'];directory=Path(source)/'autonomous/main'
    files={}
    def pin(path,expected):
        name,digest=receipt(root,Path(path).relative_to(root).as_posix(),expected,origin=str(directory/'manifest.json'))
        files[name]=digest
    result=(directory/job['result_path']).resolve()
    if not result.is_relative_to(directory):raise ValueError('RESULT_PATH_OUTSIDE_SOURCE')
    pin(result,job['result_hash']);bundle=s.read(result)
    if bundle['manifest_sha256']!=s.sha(directory/'manifest.json'):raise ValueError('RESULT_FROM_ANOTHER_MANIFEST')
    registry=m.registry(data,iid)
    if registry!=bundle['evidence_registry']:raise ValueError('EVIDENCE_REGISTRY_INCOMPATIBLE')
    for name,digest in bundle['artifact_hashes'].items():
        path=(directory/name).resolve()
        if not path.is_relative_to(directory):raise ValueError('RESULT_TRANSPORT_OUTSIDE_SOURCE')
        pin(path,digest)
    if bundle.get('shared_call') or bundle.get('shared_initial'):
        def artifact(name):
            direct=directory/name
            if direct.is_file():return direct
            for mapped,original in bundle.get('import_origin',{}).get('artifacts',{}).items():
                if original==name:return directory/mapped
            raise ValueError('MISSING_BATCH_ARTIFACT: '+name)
        shared=bundle.get('shared_call') or bundle['shared_initial'];owner=shared['owner_indicator']
        prefix=f'attempts/{pid}/{owner}/{shared["step"]}/1'
        base=directory/prefix;transport=base/'transport'/pid/'attempt_1'
        required=[artifact(prefix+'/step.json'),*[artifact(prefix+f'/transport/{pid}/attempt_1/'+name) for name in ('call.json','request.json','native_response.json','response.raw.txt')]]
        if any(path.relative_to(directory).as_posix() not in bundle['artifact_hashes'] for path in required):raise ValueError('INCOMPLETE_BATCH_RECEIPT')
        step,call,sent,native,raw=map(s.read,required)
        if (call['exit_status'] not in (0,'INVALID_ASSESSMENT') or native.get('done') is not True or native.get('done_reason')!='stop' or
            identity(call['runtime'])!=identity(manifest['runtime']) or json.loads(native['message']['content'])!=raw or
            sent['messages'][0]['content']!=step['request']['prompt'] or sent['format']!=step['schema']):raise ValueError('BATCH_TRANSCRIPT_INCOMPATIBLE')
        # The transport can contain invalid siblings. Reuse requires this member's
        # complete contract, alongside the unchanged original transport hashes.
        if not isinstance(raw,dict) or set(raw)-set(step['schema']['properties']):raise ValueError('BATCH_ENVELOPE_INCOMPATIBLE')
        merged=raw[iid]
        Draft202012Validator(m.schema(manifest['rubrics'][iid],registry,version=version)).validate(merged)
        if bundle.get('shared_initial'):
            prefix=f'attempts/{pid}/{iid}/clarification/1'
            step=s.read(artifact(prefix+'/step.json'))
            t=prefix+f'/transport/{pid}/attempt_1/'
            answer=s.read(artifact(t+'response.json'));call=s.read(artifact(t+'call.json'));native=s.read(artifact(t+'native_response.json'));sent=s.read(artifact(t+'request.json'))
            Draft202012Validator(step['schema']).validate(answer)
            if (call['exit_status']!=0 or native.get('done') is not True or native.get('done_reason')!='stop' or
                identity(call['runtime'])!=identity(manifest['runtime']) or json.loads(native['message']['content'])!=answer or
                sent['messages'][0]['content']!=step['request']['prompt'] or sent['format']!=step['schema'] or
                step['request']['semantic_input']['previous']!=merged):raise ValueError('SHARED_CLARIFICATION_INCOMPATIBLE')
            selected=m.question(manifest['rubrics'][iid],merged,step['request']['semantic_input']['question']['issues'])
            if selected!=step['request']['semantic_input']['requested_criteria']:raise ValueError('SHARED_CLARIFICATION_SCOPE_CHANGED')
            merged=dict(criteria={**merged['criteria'],**answer['criteria']},conclusion=answer['conclusion'],why=answer['why'],
                **({'strength_rubric':answer['strength_rubric']} if version==m.v3.SK_VERSION else {}))
        if merged!=bundle['semantic_answer']:raise ValueError('BATCH_MEMBER_INCOMPATIBLE')
        Draft202012Validator(m.schema(manifest['rubrics'][iid],registry,version=version)).validate(merged)
        if m.assemble(data['project'],iid,manifest['rubrics'][iid],registry,merged,version=version)!=bundle['wrapper']:raise ValueError('BATCH_DECISION_INCOMPATIBLE')
        gate(data['project'],manifest['profiles'][iid],manifest['rubrics'][iid],bundle['request'],bundle['wrapper'])
        if result_row(data['project'],manifest['profiles'][iid],manifest['rubrics'][iid],bundle['wrapper'])!=bundle['row']:raise ValueError('BATCH_SCORE_INCOMPATIBLE')
        return bundle,files
    merged=None
    for stage in (['minimal','clarification'] if bundle['clarification_used'] else ['minimal']):
        base=directory/'attempts'/pid/iid/stage/'1';transport=base/'transport'/pid/'attempt_1'
        required=[base/'step.json',transport/'response.raw.txt',transport/'native_response.json',
            transport/'request.json',transport/'call.json']
        if any(path.relative_to(directory).as_posix() not in bundle['artifact_hashes'] for path in required):
            raise ValueError('INCOMPLETE_TRANSPORT_RECEIPT')
        step=s.read(base/'step.json');call=s.read(transport/'call.json')
        raw=s.read(transport/'response.raw.txt');sent=s.read(transport/'request.json');native=s.read(transport/'native_response.json')
        if (identity(call['runtime'])!=identity(manifest['runtime']) or call['project_id']!=pid or
                call['runtime']['configuration']!=step['settings'] or
                step['settings'] not in [p.settings(manifest['llm'],manifest['policy'],tier) for tier in range(len(manifest['policy']['tiers']))]):
            raise ValueError('RESULT_MODEL_OR_CONTEXT_INCOMPATIBLE')
        if (step['request']['evidence_registry']!=registry or sent['messages'][0]['content']!=step['request']['prompt'] or
                sent['format']!=step['schema'] or json.loads(native['message']['content'])!=raw):
            raise ValueError('RESULT_TRANSCRIPT_INCOMPATIBLE')
        if stage=='minimal':
            if bundle['request']!=step['request']:raise ValueError('RESULT_REQUEST_INCOMPATIBLE')
            merged=raw
        else:merged=dict(criteria={**merged['criteria'],**raw['criteria']},conclusion=raw['conclusion'],why=raw['why'],
            **({'strength_rubric':raw['strength_rubric']} if version==m.v3.SK_VERSION else {}))
    if call['exit_status']!=0 or merged!=bundle['semantic_answer']:raise ValueError('RESULT_RESPONSE_INCOMPATIBLE')
    Draft202012Validator(m.schema(manifest['rubrics'][iid],registry,version=version)).validate(merged)
    project=data['project'];profile=manifest['profiles'][iid];rubric=manifest['rubrics'][iid]
    if m.assemble(project,iid,rubric,registry,merged,version=version)!=bundle['wrapper']:raise ValueError('RESULT_DECISION_INCOMPATIBLE')
    gate(project,profile,rubric,bundle['request'],bundle['wrapper'])
    if result_row(project,profile,rubric,bundle['wrapper'],manifest['llm']['provider'])!=bundle['row']:raise ValueError('RESULT_SCORE_INCOMPATIBLE')
    return bundle,files


def reuse_run(root,source_id,new_id,policy,*,batch_size=1):
    """Reuse sealed data through normal preparation/import; never authorize or infer."""
    import shutil
    import sqlite3
    import tempfile
    from copy import deepcopy
    import pyarrow.parquet as pq
    from jsonschema import ValidationError
    from scripts import pipeline_coordinator as coordinator
    from layer2_processing.pipeline import code_hashes
    from layer3_graphrag.configuration import load_config
    from layer3_graphrag.validate_inputs import validate_inputs
    from layer3_graphrag.source_context import SourceContextResolver
    from layer3_graphrag.quality import validate_retrieval
    from layer3_graphrag.pipeline import load_artifacts
    from layer3_graphrag.embeddings import create_provider
    from layer4_evaluation.indicators import assessment_v3 as v3
    from layer4_evaluation.indicators.selection import canonical_hash
    from . import lifecycle as l,discovery,minimal,scope,policy as p
    from .engine import JobError
    root=Path(root).resolve();l.safe_id(source_id);l.safe_id(new_id)
    source=coordinator.find_run(root,root/'outputs/runs',source_id);run=coordinator.find_run(root,root/'outputs/runs',new_id)
    if source.resolve()!=source or run.resolve()!=run or run.exists():raise ValueError('Reuse requiere origen local y destino nuevo')
    directory=l.folder(source);manifest=s.read(directory/'manifest.json');auth=s.read(directory/'authorization.json')
    worker=run_file(directory, 'worker.json')
    if worker.exists():
        previous=s.read(worker);current=s.process_info(previous['pid'])
        if current['alive'] and current['creation']==previous.get('creation'):raise ValueError('SOURCE_WORKER_ACTIVE')
    digest=s.sha(directory/'manifest.json')
    if (manifest['run_id']!=source_id or manifest['repository_root']!=str(root) or manifest['version']!=l.VERSION or
            auth.get('authorized') is not True or auth.get('manifest_sha256')!=digest):raise ValueError('SOURCE_AUTHORIZATION_MISMATCH')
    scope.check(root,manifest['source_inventory']);current_catalog,catalog_files=catalog(root)
    if (manifest['profiles']!=current_catalog['profiles'] or manifest['rubrics']!=current_catalog['rubrics'] or
            manifest['schema_version']!=v3.SK_VERSION or manifest.get('confidence_version')!=v3.SK_CONFIDENCE_VERSION or manifest.get('evaluator')!=minimal.VERSION or
            manifest['prompts']!=dict(version=minimal.VERSION,semantic=minimal.SK_INSTRUCTIONS) or
            manifest['policy']!=p.validate(policy)):
        raise ValueError('SOURCE_CATALOG_SCHEMA_POLICY_INCOMPATIBLE')
    origins=dict(manifest['files'])|catalog_files
    for path in (directory/'manifest.json',directory/'authorization.json'):
        origins[path.relative_to(root).as_posix()]=s.sha(path)
    for name,expected in origins.items():receipt(root,name,expected,origin=source_id)
    # Historical orchestration may differ; data/graph/scoring implementations may not.
    drift={}
    for name,expected in manifest['code'].items():
        actual=s.sha(root/name)
        if actual!=expected:
            budget_files={'src/layer4_evaluation/indicators/context_budget.py','src/layer4_evaluation/indicators/ollama_provider.py'}
            if name!='run.py' and not name.startswith('src/autonomous_execution/') and name not in budget_files:
                raise mismatch(name,expected,actual,source_id,rule='REUSE_COMPUTATION_UNCHANGED')
            drift[name]=dict(previous=expected,current=actual)
    state=s.read(run_file(source, 'run.json'))
    if state['status']!='PREPARED' or s.read(run_file(source, 'raw_manifest.json'))!=manifest['documentary_sources']:
        raise ValueError('SOURCE_PREPARATION_INCOMPATIBLE')
    from layer4_evaluation.indicators.ollama_provider import configuration
    execution=s.read(run_file(source, 'execution.json'))
    if configuration(execution.get('llm',state['configuration'].get('llm')))!=manifest['llm']:
        raise ValueError('SOURCE_MODEL_CONFIGURATION_INCOMPATIBLE')
    prepared=s.read(run_file(source, 'prepared_hashes.json'))
    for name,expected in prepared.items():receipt(root,(source/name).relative_to(root).as_posix(),expected,origin=source_id)
    config,_=load_config(source/'workspace')
    if config['embeddings']!=manifest['embeddings']:raise ValueError('SOURCE_EMBEDDINGS_INCOMPATIBLE')
    snapshot=validate_inputs(source/'workspace',config)
    graph_manifest,_,graph=load_artifacts(source/'workspace',snapshot,config,create_provider(config['embeddings']))
    if not (run_file(source, 'discovery.json')).is_file():raise ValueError('SOURCE_DISCOVERY_MISSING')
    audit=discovery.validate_saved(source)
    if (audit['graph_manifest_sha256']!=s.sha(source/'workspace/outputs/layer3/publication/_manifest.json') or
            audit['knowledge_manifest_sha256']!=snapshot.manifest_hash or
            audit['catalog_sha256']!=canonical_hash(dict(profiles=current_catalog['profiles'],rubrics=current_catalog['rubrics'])) or
            audit['project_indicators']!=manifest['project_indicators'] or
            audit['settings']!=discovery.admission_settings(config)):
        raise ValueError('SOURCE_DISCOVERY_INCOMPATIBLE')
    if set(manifest['projects'])!=set(audit['project_indicators']):raise ValueError('SOURCE_PROJECT_SCOPE_MISMATCH')
    candidates=pq.read_table(run_file(source, 'discovery_candidates.parquet')).to_pylist();resolver=SourceContextResolver(snapshot)
    contexts={c['context_package_id']:resolver.reconstruct(c['source_type'],c['source_id'],c['document_id'],c['layer3_run_id']) for c in candidates}
    quality_config=deepcopy(config);quality_config['retrieval'].update(max_chunks_per_source=max(1,len(snapshot.tables['source_chunks'])),
        final_candidates_per_indicator=max(1,len(snapshot.tables['source_documents'])))
    if not graph.validate()['valid']:raise ValueError('SOURCE_GRAPH_INCOMPATIBLE')
    quality,issues,anomalies,_=validate_retrieval(snapshot,graph,candidates,list(contexts.values()),quality_config,
        considered_indicators=audit['catalog_ids'])
    if quality['status']!='PASS':raise ValueError('SOURCE_RETRIEVAL_INCOMPATIBLE: '+str(issues+anomalies))
    # SQLite WAL readers can create/update sidecars even with mode=ro. Read a
    # private snapshot of the stopped queue, preserving every original byte.
    with tempfile.TemporaryDirectory(prefix='graphrag-reuse-') as temporary:
        queue=Path(temporary)/'queue.sqlite'
        for suffix in ('','-wal'):
            origin=directory/('queue.sqlite'+suffix)
            if origin.exists():shutil.copyfile(origin,str(queue)+suffix)
        db=sqlite3.connect(queue);db.row_factory=sqlite3.Row
        try:jobs=[dict(row) for row in db.execute('SELECT * FROM jobs ORDER BY pid,iid')]
        finally:db.close()
    expected={(pid,iid) for pid,ids in audit['project_indicators'].items() for iid in ids}
    if {(j['pid'],j['iid']) for j in jobs}!=expected or len(jobs)!=len(expected):raise ValueError('SOURCE_QUEUE_SCOPE_MISMATCH')
    if any(j['status'] not in ('PASS','PENDING','BLOCKED') or j['status']=='PENDING' and j['attempts'] for j in jobs):
        raise ValueError('SOURCE_OUTCOME_UNCERTAIN: resolver llamadas previas antes de reutilizar')
    data={}
    for pid,ref in manifest['projects'].items():
        path=directory/ref['path'];receipt(root,path.relative_to(root).as_posix(),ref['sha256'],origin=source_id)
        origins[path.relative_to(root).as_posix()]=ref['sha256'];data[pid]=s.read(path)
        data[pid]['candidates']=[c for c in candidates if c['source_id']==pid]
        if data[pid]['sections']!=[r for r in snapshot.tables['source_sections'] if r['source_id']==pid] or data[pid]['chunks']!=[r for r in snapshot.tables['source_chunks'] if r['source_id']==pid]:
            raise ValueError('SOURCE_PROJECT_KNOWLEDGE_MISMATCH')
        for candidate in data[pid]['candidates']:minimal.registry(data[pid],candidate['indicator_id'])
    accepted=[];rejected=[]
    for job in jobs:
        if job['status']!='PASS':continue
        try:
            _,files=reusable_result(root,source,manifest,job,data[job['pid']])
            origins.update(files);accepted.append(job)
        except (ValueError,KeyError,JobError,ValidationError) as exc:
            rejected.append(dict(project_id=job['pid'],indicator_id=job['iid'],reason=type(exc).__name__))
    paths=dict(prepared)
    for name in ('raw_manifest.json','execution.json','prepared_hashes.json','discovery.json','discovery_candidates.parquet'):
        paths[name]=s.sha(run_file(source,name))
    publication='workspace/outputs/layer3/publication'
    paths[publication+'/_manifest.json']=s.sha(source/publication/'_manifest.json')
    paths.update({publication+'/'+name:sha for name,sha in graph_manifest['output_hashes'].items()})
    # Copy only validated immutable artifacts. No queues, authorizations or GPU caches.
    run.mkdir(parents=True)  # Reserve the new ID atomically; never overwrite an existing run.
    for name,expected_hash in paths.items():
        src=run_file(source,name).resolve();target=run_file(run,name).resolve()
        if not src.is_relative_to(source) or not target.is_relative_to(run):raise ValueError('REUSE_PATH_ESCAPE')
        receipt(root,src.relative_to(root).as_posix(),expected_hash,origin=source_id)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
        if s.sha(target)!=expected_hash:raise ValueError('REUSE_COPY_MISMATCH')
        origins[src.relative_to(root).as_posix()]=expected_hash
    state.update(run_id=new_id,code_hashes=code_hashes(root),reused_from=dict(run_id=source_id,manifest_sha256=digest))
    s.write(run_file(run, 'run.json'),state)
    blocked=[j for j in jobs if j['status']=='BLOCKED' and not (j['error']=='EVIDENCE_SOURCE_MISMATCH' and j['attempts']==0)
             and not (batch_size>1 and j['error'] in ('CONTEXT_TOO_LONG','STATIC_CONTEXT_TOO_LONG','EVIDENCE_COVERAGE_BUDGET'))]
    s.write(run_file(run, 'reuse.json'),dict(version='VALIDATED_AUTONOMOUS_REUSE_V1',source_run=source_id,source_manifest_sha256=digest,
        source_files=origins,reused_artifacts=paths,code_changes=drift,accepted=accepted,rejected=rejected,
        blocked=blocked,original_job_counts={status:sum(j['status']==status for j in jobs) for status in sorted({j['status'] for j in jobs})},
        validation=dict(retrieval=quality,graph_counts=graph_manifest['counts'],projects=len(data),catalog_size=len(current_catalog['profiles']),
            inference_calls=0,embeddings_generated=0,graph_built=False)))
    result=l.prepare(root,run,policy,runtime=manifest['runtime'],evaluator=minimal.VERSION,discovery=discovery.prepare(root,run),batch_size=batch_size)
    reviewed=s.read(l.folder(run)/'manifest.json')
    if any(reviewed[key]!=manifest[key] for key in ('llm','context_policy','schema_version','profiles','rubrics','prompts','protocol')):
        raise ValueError('REUSED_EVALUATION_CONTRACT_CHANGED')
    for job in accepted:
        bundle=s.read(l.folder(run)/job['result_path'])
        for name,origin in bundle['import_origin']['artifacts'].items():
            target=l.folder(run)/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(directory/origin,target)
            if s.sha(target)!=bundle['artifact_hashes'][name]:raise ValueError('IMPORTED_TRANSPORT_COPY_MISMATCH')
    db=s.connect(l.folder(run))
    try:
        for job in blocked:
            db.execute("UPDATE jobs SET status='BLOCKED',error=?,attempts=?,rounds=?,updated=? WHERE pid=? AND iid=? AND status='PENDING'",
                (job['error'],job['attempts'],job['rounds'],s.now(),job['pid'],job['iid']))
    finally:db.close()
    l.verify(root,run,require_authorization=False)
    return result|dict(run_id=new_id,reused_from=source_id,pending=len(jobs)-len(accepted)-len(blocked),blocked=len(blocked),rejected_imports=len(rejected))


def reused_history(root,run):
    """Feed validated autonomous receipts to the existing historical importer."""
    import pyarrow.parquet as pq
    from . import lifecycle as l
    from scripts.pipeline_coordinator import find_run
    info=s.read(run_file(Path(run), 'reuse.json'));source=find_run(Path(root),Path(root)/'outputs/runs',l.safe_id(info['source_run']))
    previous=s.read(l.folder(source)/'manifest.json');accepted=l.HistoryRows(run)
    files=info['source_files']|{(run_file(Path(run), 'reuse.json')).relative_to(root).as_posix():s.sha(run_file(Path(run), 'reuse.json'))}
    try:
        auth=s.read(l.folder(source)/'authorization.json')
        if (s.sha(l.folder(source)/'manifest.json')!=info['source_manifest_sha256'] or auth.get('authorized') is not True or
                auth.get('manifest_sha256')!=info['source_manifest_sha256'] or
                any(files.get(name)!=digest for name,digest in previous['files'].items())):
            raise ValueError('REUSE_ORIGIN_RECEIPT_MISMATCH')
        for name,expected in files.items():receipt(root,name,expected,origin=info['source_run'])
        candidates=pq.read_table(run_file(Path(run), 'discovery_candidates.parquet')).to_pylist();inputs={}
        for job in info['accepted']:
            pid=job['pid']
            if pid not in inputs:
                inputs[pid]=s.read(l.folder(source)/previous['projects'][pid]['path'])
                inputs[pid]['candidates']=[c for c in candidates if c['source_id']==pid]
            data=inputs[pid]
            bundle,_=reusable_result(root,source,previous,job,data);mapped={};origins={}
            for name,digest in bundle['artifact_hashes'].items():
                target=Path(run)/'autonomous/main/imports'/info['source_run']/name
                if target.name=='dispatch.claim.json':target=target.with_name('dispatch.receipt.json')
                relative=target.relative_to(l.folder(run)).as_posix()
                mapped[relative]=digest;origins[relative]=name
            bundle['artifact_hashes']=mapped
            bundle['import_origin']=dict(run_id=info['source_run'],manifest_sha256=info['source_manifest_sha256'],
                result=job['result_path'],result_sha256=job['result_hash'],artifacts=origins)
            accepted[(job['pid'],job['iid'])]=bundle
        return accepted,files,previous['runtime'],None
    except BaseException:
        accepted.close();raise


def install():
    from . import lifecycle as l
    if getattr(l.prepare,'_current_catalog',False):
        return
    original_prepare=l.prepare;original_historical=l.historical;original_verify=l.verify
    @wraps(original_historical)
    def history(root,run):
        return historical(root,run,original_historical)
    @wraps(original_prepare)
    def prepare(root,run,policy,**kwargs):
        check_manifest_code(root,run)
        check_prepared_code(root,run)
        context={};token=_preparing.set(context)
        try:
            result=original_prepare(root,run,policy,**kwargs)
            if not context:
                return result  # Existing manifest or imported historical evaluations.
            root=Path(root).resolve();path=l.folder(run)/'manifest.json'
            manifest=s.read(path)
            if (path.parent/'authorization.json').exists() or list(path.parent.rglob('dispatch.claim.json')):
                raise ValueError('La preparacion nueva tiene autorizacion/dispatch; no reescribir')
            for name,digest in (context['data']|context['code']).items():
                receipt(root,name,digest,origin=str(context['release']))
            manifest['code'].update(context['code'])
            manifest['catalog_binding']=dict(version=VERSION,
                release=context['release'].relative_to(root).as_posix(),
                sha256=s.sha(context['release']),reference=REFERENCE)
            reuse=run_file(Path(run), 'reuse.json')
            if reuse.exists():manifest['reuse']=dict(path='reuse.json',sha256=s.sha(reuse),source_run=s.read(reuse)['source_run'])
            s.write(path,manifest)
            # Only new, unsigned copies are rebound; original results stay intact.
            if manifest['imported_pass']:
                db=s.connect(path.parent)
                try:
                    for row in db.execute("SELECT result_path FROM jobs WHERE status='PASS'").fetchall():
                        target=path.parent/row['result_path'];bundle=s.read(target)
                        bundle['manifest_sha256']=s.sha(path);s.write(target,bundle)
                        db.execute('UPDATE jobs SET result_hash=? WHERE result_path=?',(s.sha(target),row['result_path']))
                finally:db.close()
            return result|dict(manifest_sha256=s.sha(path))
        finally:
            _preparing.reset(token)
    @wraps(original_verify)
    def verify(root,run,**kwargs):
        check_manifest_code(root,run)
        return original_verify(root,run,**kwargs)
    prepare._current_catalog=True
    l.prepare=prepare;l.historical=history;l.verify=verify
