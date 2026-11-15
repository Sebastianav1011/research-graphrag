"""Preparation, one explicit manifest authorization, persistent queues and export."""
from run_paths import file_path as run_file
from knowledge_store import knowledge_workspace, evaluation_dir
from concurrent.futures import ThreadPoolExecutor
import getpass
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid

import pyarrow.parquet as pq

from layer4_evaluation import live_execution as live
from layer4_evaluation.indicators import assessment_v3 as v3
from layer4_evaluation.indicators.ollama_provider import OllamaClient, configuration, create_client
from layer4_evaluation.indicators.selection import substantive_fields
from layer4_evaluation.indicators.selection import canonical_hash
from . import policy as p, store as s, scope
from .engine import Worker, identity, result_row, check_result_contract

VERSION='AUTONOMOUS_EXECUTION_V1'
from layer4_evaluation.indicators.performance import measured_run


class HistoryRows:
    """Disposable disk cache of verified legacy rows; never an authorization source."""
    def __init__(self,run):
        import os
        import tempfile
        fd,name=tempfile.mkstemp(prefix='history-index-',suffix='.sqlite',dir=run)
        os.close(fd);self.path=Path(name)
        self.db=sqlite3.connect(self.path)
        self.db.execute('PRAGMA synchronous=OFF')
        self.db.execute('CREATE TABLE accepted(pid TEXT,iid TEXT,value TEXT,PRIMARY KEY(pid,iid))')

    def __setitem__(self,key,value):
        self.db.execute('INSERT OR REPLACE INTO accepted VALUES(?,?,?)',(*key,json.dumps(value,ensure_ascii=False)))

    def __contains__(self,key):
        return self.db.execute('SELECT 1 FROM accepted WHERE pid=? AND iid=?',key).fetchone() is not None

    def __getitem__(self,key):
        return json.loads(self.db.execute('SELECT value FROM accepted WHERE pid=? AND iid=?',key).fetchone()[0])

    def close(self):
        self.db.close();self.path.unlink()


def safe_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):
        raise ValueError('ID de ejecucion, proyecto o sesion invalido')
    return value


def folder(run,session='main'):
    return Path(run)/'autonomous'/safe_id(session)


def parquet_rows(path, batch_size):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size):
        yield from batch.to_pylist()


def index_sources(directory, sources, batch_size):
    """Disk spool: never materialize corpus-wide source/chunk tables in Python."""
    path=Path(directory)/'source_index.sqlite'
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE rows(kind TEXT,pid TEXT,value TEXT)')
    for kind,source in sources.items():
        for row in parquet_rows(source,batch_size):
            db.execute('INSERT INTO rows VALUES(?,?,?)',(kind,row['source_id'],json.dumps(row,ensure_ascii=False)))
    db.execute('CREATE INDEX source_lookup ON rows(kind,pid)')
    db.commit();db.close()
    return path


def rows_for(db,kind,pid):
    return [json.loads(r[0]) for r in db.execute('SELECT value FROM rows WHERE kind=? AND pid=?',(kind,pid))]


def verify_graph(run):
    """Check the published graph binding without loading weights or all vectors."""
    from layer3_graphrag.configuration import load_config
    from layer3_graphrag.embeddings import create_provider, embedding_config_hash
    from layer3_graphrag.manifest import validate_publication
    workspace=knowledge_workspace(run)
    config,_=load_config(workspace)
    provider=create_provider(config['embeddings'])  # Lazy adapter; no encode/_load call.
    manifest=validate_publication(workspace/'outputs/layer3/publication',
        s.sha(workspace/'outputs/layer2/knowledge/_manifest.json'))
    if manifest['embedding_config_hash']!=embedding_config_hash(config['embeddings'],provider):
        raise ValueError('GraphRAG incompatible con BGE-M3/configuracion autorizada')
    if manifest.get('candidate_architecture')!='SOURCE_INDICATOR_V1':
        raise ValueError('Arquitectura de fuentes GraphRAG incompatible')
    return manifest


def graph_policy(run):
    from layer3_graphrag.configuration import load_config
    config,_=load_config(knowledge_workspace(run))
    if config['embeddings'].get('allow_model_download',False):
        raise ValueError('Manifiesto local no permite descargas de modelos')
    return config['embeddings']


def build_graph(root,run):
    import os
    import subprocess
    import sys
    verify(root,run)
    directory=folder(run)
    command=[sys.executable,str(Path(root)/'src/autonomous_execution/graph_worker.py'),'--run-path',Path(run).relative_to(root).as_posix(),
        '--manifest-sha256',s.sha(directory/'manifest.json')]
    options=dict(cwd=str(root),stdin=subprocess.DEVNULL,close_fds=True)
    if os.name=='nt':options['creationflags']=subprocess.CREATE_NO_WINDOW
    with (directory/'graph_build.stdout.log').open('ab') as out,(directory/'graph_build.stderr.log').open('ab') as err:
        result=subprocess.run(command,stdout=out,stderr=err,**options)
    if result.returncode:
        raise ValueError('GRAPH_BUILD_FAILED: revisar logs privados; no iniciar evaluacion')


def historical(root, run):
    """Validate and import only historical PASS calls; keep every source byte intact."""
    accepted=HistoryRows(run);files={};binding=None;catalog=None
    base=evaluation_dir(run)
    for directory in sorted(base.glob('batch_*')):
        plan=live.check(directory)
        if plan.get('request_protocol')!=live.CONTEXT_VERSION:
            raise ValueError('Importacion historica requiere contexto por indicador')
        if catalog and (catalog['profiles']!=plan['profiles'] or catalog['rubrics']!=plan['rubrics']):
            raise ValueError('Catalogos historicos incompatibles')
        catalog=plan
        state=live.verify_run(directory)
        if (directory/'provider.json').exists():
            candidate=s.read(directory/'provider.json')
            if binding and identity(binding)!=identity(candidate):
                raise ValueError('Modelos historicos incompatibles')
            binding=candidate
        # Include errors too: their original usage is audited, never relabelled PASS.
        for path in directory.rglob('*'):
            if path.is_file():
                files[path.relative_to(root).as_posix()]=s.sha(path)
        for key in ('recovery','checkpoint_migration'):
            files.update(plan.get(key,{}).get('archive_hashes',{}))
        for project_state in state['projects']:
            project=next(x for x in plan['projects'] if x['project_id']==project_state['project_id'])
            for row in project_state['rows']:
                key=(row['project_id'],row['indicator_id'])
                wrapper=dict(project_id=key[0],assessments=[dict(indicator_id=key[1],**live.assessment_from_row(row))])
                request=live.request_for(plan,project,'assessment',[key[1]])
                live.validate_context_evidence(request,wrapper)
                if result_row(project,plan['profiles'][key[1]],plan['rubrics'][key[1]],wrapper,plan['runtime']['provider'])!=row:
                    raise ValueError('Confianza historica incompatible')
                accepted[key]=dict(wrapper=wrapper,row=row,request=request,historical=True)
    return accepted,files,binding,catalog


def prepare(root, run, policy, *, runtime=None, evaluator=None, indicator_ids=None, project_indicators=None, discovery=None, batch_size=1):
    from scripts import pipeline_coordinator as coordinator
    root,run=Path(root).resolve(),Path(run).resolve()
    if not run.is_relative_to(root/'outputs/runs'):
        raise ValueError('Autonomia requiere un run aislado en outputs/runs')
    policy=p.validate(policy)
    if type(batch_size) is not int or batch_size not in (1,2,3):raise ValueError('Lote: 1, 2 o 3 indicadores')
    if batch_size>1 and policy['workers']!=1:raise ValueError('Lotes requieren un worker para reservar trabajos sin carreras')
    directory=folder(run)
    from knowledge_store import run_state
    if run_state(run).get('knowledge_build') or run_state(run).get('knowledge_activation_pending'):
        if (directory/'manifest.json').exists():
            raise ValueError('BASE pendiente en un manifiesto autonomo sellado; conservarlo y preparar otro run')
        if not (knowledge_workspace(run)/'outputs/layer3/publication/_manifest.json').is_file():
            raise ValueError('Finalizar BASE con run --through graphrag antes de preparar el manifiesto autonomo')
        coordinator.register_built_knowledge(root, run, s.read(run_file(run, 'execution.json')))
    if discovery is not None:
        if indicator_ids is not None or project_indicators is not None:raise ValueError('No mezclar descubrimiento automatico y seleccion manual')
        project_indicators=discovery['project_indicators']
    elif (directory/'manifest.json').exists():
        previous=s.read(directory/'manifest.json')
        if previous.get('discovery') and indicator_ids is None and project_indicators is None:
            discovery=s.read(run_file(run, 'discovery.json'));project_indicators=discovery['project_indicators']
    if directory.exists():
        if (directory/'manifest.json').exists():
            previous=s.read(directory/'manifest.json')
            same_code=all((root/name).is_file() and s.sha(root/name)==digest for name,digest in previous['code'].items())
            if (previous['policy']==policy and same_code and previous.get('batching',{}).get('size',1)==batch_size and previous.get('evaluator')==evaluator
                    and previous.get('project_indicators')==project_indicators
                    and (indicator_ids is None or set(previous['profiles'])==set(indicator_ids))):
                verify(root,run,require_authorization=False)
                return dict(status='REVIEW_REQUIRED',manifest=str(directory/'manifest.json'),manifest_sha256=s.sha(directory/'manifest.json'))
            if (directory/'authorization.json').exists() or list(directory.rglob('dispatch.claim.json')):
                raise ValueError('Politica/codigo distintos de ejecucion ya autorizada; conservar sesion existente')
            # Only an unsigned, undispatched review may be replaced. Its exact
            # bytes remain archived and the replacement needs its own approval.
        if (directory/'authorization.json').exists() or list(directory.rglob('dispatch.claim.json')):
            raise ValueError('Preparacion incompleta con autorizacion/claim: conservar para diagnostico')
        archive=run/'autonomous/preparation_history'/uuid.uuid4().hex
        archive.parent.mkdir(parents=True,exist_ok=True)
        if not directory.resolve().is_relative_to(run/'autonomous') or not archive.resolve().is_relative_to(run/'autonomous'):
            raise ValueError('Archivo de preparacion fuera de la ejecucion')
        directory.rename(archive)
    state=coordinator.check(root,run)
    if state['status']!='PREPARED':
        raise ValueError('Preparar knowledge antes de crear manifiesto autonomo')
    embedding_settings=graph_policy(run)
    execution=s.read(run_file(run, 'execution.json'))
    selected=coordinator.scope_projects(root,run,execution['selection'],execution.get('project_ids'))
    intake=scope.inventory(root,state,execution['selection'])
    accepted,history_files,binding,catalog=historical(root,run)
    if catalog is None:
        catalog=s.read(live.FROZEN)
        live.verify_hashes(root,catalog['source_hashes'])
    if project_indicators is not None:
        if (not isinstance(project_indicators,dict) or not project_indicators
                or any(not isinstance(ids,list) or (not ids and discovery is None) or len(set(ids))!=len(ids) or
                       any(i not in catalog['profiles'] for i in ids) for ids in project_indicators.values())):
            raise ValueError('Parejas proyecto-indicador invalidas o fuera del alcance')
        union=sorted({i for ids in project_indicators.values() for i in ids})
        if indicator_ids is not None and set(indicator_ids)!=set(union):raise ValueError('Indicadores distintos del alcance por proyecto')
        if discovery is None:indicator_ids=union
        elif discovery['catalog_ids']!=sorted(catalog['profiles']):raise ValueError('Descubrimiento no considero todo el catalogo')
    if indicator_ids is not None:
        if not indicator_ids or len(set(indicator_ids))!=len(indicator_ids) or any(i not in catalog['profiles'] for i in indicator_ids):
            raise ValueError('Indicadores inexistentes o repetidos en el catalogo')
        catalog={**catalog,**{k:{i:catalog[k][i] for i in indicator_ids} for k in ('profiles','rubrics')}}
    if evaluator is not None:
        from .minimal import VERSION as MINIMAL
        if evaluator!=MINIMAL:raise ValueError('Evaluador desconocido')
    llm=configuration(execution.get('llm',state['configuration'].get('llm')))
    if runtime is None:
        runtime=binding
        if runtime is None:
            client = OllamaClient(llm) if llm['provider']=='ollama' else create_client(llm)
            runtime=client.inspect()  # API inspection is offline.
    if runtime['model']!=llm['model'] or runtime['provider']!=llm['provider']:
        raise ValueError('Modelo/proveedor ajeno al alcance')
    directory.mkdir(parents=True)
    workspace=knowledge_workspace(run)/'outputs'
    sources={kind:workspace/'layer2/knowledge'/name for kind,name in
        [('sections','source_sections.parquet'),('chunks','source_chunks.parquet')]}
    index=index_sources(directory,sources,policy['parquet_batch_rows'])
    source_db=sqlite3.connect(index);db=s.connect(directory)
    projects={};histories=[]
    try:
        for canonical in parquet_rows(workspace/'layer2/canonical/proyectos.parquet',policy['parquet_batch_rows']):
            if canonical['source_project_id'] not in selected:
                continue
            pid=safe_id(canonical['project_id'])
            if project_indicators is not None and pid not in project_indicators:raise ValueError('Proyecto sin alcance de indicadores')
            sections=rows_for(source_db,'sections',pid);chunks=rows_for(source_db,'chunks',pid)
            fields={f:next((x['text_original'] or '' for x in sections if x['field_name']==f),'') for f in live.FIELDS}
            fields.update({x['field_name']:x['text_original'] or '' for x in sections if x['field_name'].startswith('text__')})
            provenance={x['field_name']:dict(section_id=x['section_id'],text_hash_original=x['text_hash_original'],
                raw_sources=json.loads(x['provenance_json'])['layer1']) for x in sections}
            project=dict(project_id=pid,siap_id=canonical['source_project_id'],fields=fields,field_provenance=provenance)
            path=directory/'inputs'/(pid+'.json')
            s.write(path,dict(project=project,sections=sections,chunks=chunks))
            projects[pid]=dict(path=path.relative_to(directory).as_posix(),sha256=s.sha(path),siap_id=project['siap_id'])
            db.execute('INSERT INTO projects VALUES(?,?,?,?)',(pid,project['siap_id'],projects[pid]['path'],projects[pid]['sha256']))
            quarantine=state.get('scope_quarantine',{})
            error=('SOURCE_QUARANTINE' if project['siap_id'] in quarantine.get('affected_projects',{}) or
                quarantine.get('primary_article_conflicts') else 'NO_AUTHORIZED_SUBSTANTIVE_TEXT' if not
                any((fields.get(f) or '').strip() for f in substantive_fields(fields)) else None)
            for iid in catalog['profiles']:
                if project_indicators is not None and iid not in project_indicators[pid]:continue
                safe_id(iid)
                db.execute('INSERT INTO jobs(pid,iid,status,error,updated) VALUES(?,?,?,?,?)',
                    (pid,iid,'BLOCKED' if error else 'PENDING',error,s.now()))
                if (pid,iid) in accepted:
                    bundle=accepted[(pid,iid)]
                    row=result_row(project,catalog['profiles'][iid],catalog['rubrics'][iid],bundle['wrapper'],llm['provider'])
                    if evaluator is not None and row.get('confidence_version')!=v3.SK_CONFIDENCE_VERSION:
                        raise ValueError('CONFIDENCE_CONTRACT_INCOMPATIBLE: conservar resultados historicos y preparar otra ejecucion')
                    if row!=bundle['row'] or error:
                        raise ValueError('Evidencia historica fuera del alcance autorizado actual')
                    s.write(directory/'results'/pid/(iid+'.json'),bundle)
                    histories.append((pid,iid))
        if len(projects)!=len(selected):
            raise ValueError('Cobertura de proyectos incompleta')
        if project_indicators is not None and set(project_indicators)!=set(projects):raise ValueError('Proyecto ajeno al alcance')
    finally:
        source_db.close();db.close()
        if hasattr(accepted,'close'):
            accepted.close()
    # Immutable source/preparation and code receipts. Historical manifests are
    # retained verbatim: this opt-in runtime does not rewrite their code hashes.
    files={name:s.sha(root/name) for name in history_files}
    for path in (run_file(run, 'raw_manifest.json'),run_file(run, 'prepared_hashes.json'),run_file(run, 'run.json'),run_file(run, 'execution.json')):
        files[path.relative_to(root).as_posix()]=s.sha(path)
    for name in s.read(run_file(run, 'prepared_hashes.json')):
        path=run/name;files[path.relative_to(root).as_posix()]=s.sha(path)
    if (run_file(run, 'model.binding.json')).exists():files[(run_file(run, 'model.binding.json')).relative_to(root).as_posix()]=s.sha(run_file(run, 'model.binding.json'))
    from .final_output import prepare_projection
    projection,projection_files=prepare_projection(root,run,projects)
    files.update(projection_files)
    if discovery is not None:
        if s.read(run_file(run, 'discovery.json'))!=discovery:raise ValueError('Descubrimiento distinto de su registro')
        publication=knowledge_workspace(run)/'outputs/layer3/publication/_manifest.json'
        if s.sha(publication)!=discovery['graph_manifest_sha256']:raise ValueError('GraphRAG distinto del descubrimiento')
        if s.sha(knowledge_workspace(run)/'outputs/layer2/knowledge/_manifest.json')!=discovery['knowledge_manifest_sha256']:
            raise ValueError('Fuente distinta del descubrimiento')
        if canonical_hash(dict(profiles=catalog['profiles'],rubrics=catalog['rubrics']))!=discovery['catalog_sha256']:
            raise ValueError('Catalogo distinto del descubrimiento')
        if s.sha(run_file(run, 'discovery_candidates.parquet'))!=discovery['candidates_sha256']:raise ValueError('Candidatos modificados')
        for path in (run_file(run, 'discovery.json'),run_file(run, 'discovery_candidates.parquet')):
            files[path.relative_to(root).as_posix()]=s.sha(path)
    publication=knowledge_workspace(run)/'outputs/layer3/publication/_manifest.json'
    if publication.exists():
        verify_graph(run)
        files[publication.relative_to(root).as_posix()]=s.sha(publication)
    code_files=[root/'run.py',*sorted((root/'src/autonomous_execution').glob('*.py'))]
    code={path.relative_to(root).as_posix():s.sha(path) for path in code_files}
    manifest=dict(version=VERSION,execution_id=uuid.uuid4().hex,created_at=s.now(),run_id=run.name,repository_root=str(root),
        selection=dict(mode=execution['selection']['mode'],files=execution['selection'].get('files',[]),project_ids=selected),
        documentary_sources=s.read(run_file(run, 'raw_manifest.json')),files=files,code=code,projects=projects,
        source_inventory=intake,
        profiles=catalog['profiles'],rubrics=catalog['rubrics'],llm=llm,runtime=runtime,policy=policy,
        embeddings=embedding_settings,final_projection=projection,
        prompts=dict(version=p.VERSION,repair=p.REPAIR,shard=p.SHARD,synthesis=p.SYNTHESIS,
            normative=p.NORMATIVE,
            normative_sha256=__import__('hashlib').sha256(p.NORMATIVE.encode()).hexdigest()),
        schema_version=v3.VERSION,context_policy=dict(base=live.CONTEXT_VERSION,adaptive='ADAPTIVE_GRAPH_CONTEXT_V1'),local_only=llm['provider']=='ollama',
        allowed_operations=['LOCAL_GRAPH_BUILD','INDICATOR_EVALUATION','BOUNDED_RETRIES','CRITERION_SHARDS',
            'LLM_SYNTHESIS','BOUNDED_DEFERRED_RECOVERY','PASS_ONLY_EXPORT'],
        graph_build_authorized_by_manifest=True,imported_pass=len(histories))
    manifest['evaluation_contract']=execution.get('evaluation_contract')
    if llm['provider']=='openai' and batch_size!=1:raise ValueError('API requiere evaluacion individual')
    if batch_size>1:
        from .batching import VERSION as BATCH,INSTRUCTIONS as BATCH_PROMPT
        manifest['batching']=dict(version=BATCH,size=batch_size,max_context=6144,instructions=BATCH_PROMPT,
            usage_attribution='OWNER_INDICATOR_ONLY; shared members zero additional tokens')
        tokenizer_config=root/'config/qwen_tokenizer.json'
        if tokenizer_config.exists():
            descriptor=s.read(tokenizer_config);tokenizer_path=root/descriptor['path']
            if not tokenizer_path.is_file():raise ValueError('Preparar tokenizer local: uv run python scripts/prepare_qwen_tokenizer.py')
            if s.sha(tokenizer_path)!=descriptor['sha256']:raise ValueError('Tokenizer local distinto del fijado')
            if descriptor['model_digest']!=runtime['digest'] or descriptor['model_metadata_sha256']!=runtime['model_metadata_sha256']:
                raise ValueError('Tokenizer/plantilla requieren calibracion para este modelo; no adivinar conteos')
            manifest['files'][tokenizer_config.relative_to(root).as_posix()]=s.sha(tokenizer_config)
            manifest['files'][descriptor['path']]=descriptor['sha256']
            manifest['batching'].update(tokenizer=descriptor|dict(path=str(tokenizer_path)),context_margin_tokens=300,
                output_budget='at least max(512, ceil((128 + 80 * criteria)/64)*64); reserve remaining context up to authorized output cap')
    if p.coherent(policy):
        from . import phase1
        manifest['prompts'].update(version=p.PHASE1,concise=p.CONCISE,structured_synthesis=phase1.INSTRUCTIONS,
            synthesis_version=phase1.VERSION,repair_feedback='SAFE_RULE_PATH_IDENTIFIERS_V1')
        manifest['context_policy']['synthesis']=phase1.VERSION
    if policy['version']==p.PHASE11:
        from . import phase11
        manifest['prompts'].update(version=p.PHASE11,catalog_fidelity=phase11.FIDELITY,
            scoped_repair=phase11.REPAIR,repair_feedback=phase11.VERSION)
    if policy['version']==p.PHASE12:
        from . import phase12
        manifest['prompts'].update(version=p.PHASE12,catalog_fidelity=phase12.CLASSIFICATION,
            scoped_repair=phase12.REPAIR,repair_feedback=phase12.VERSION)
        manifest['allowed_operations']+=['AFFECTED_CRITERIA_REEVALUATION']
    if p.preserving(policy):
        manifest['context_policy']['coverage']='NO_LOSS_RETRIEVED_INTERVALS_V1'
        manifest['allowed_operations']+=['SCOPED_RESPONSE_PATCHES','LOSSLESS_CRITERION_SUBDIVISION']
    if evaluator is not None:
        from .minimal import VERSION as MINIMAL,INSTRUCTIONS,SK_INSTRUCTIONS
        manifest.update(evaluator=MINIMAL,prompts=dict(version=MINIMAL,semantic=SK_INSTRUCTIONS),
            schema_version=v3.SK_VERSION,confidence_version=v3.SK_CONFIDENCE_VERSION,
            protocol=dict(normal_calls=1,max_calls_per_evaluation=2,
                stable_contradiction='ONE_TARGETED_CLARIFICATION_THEN_REVIEW',patches=False,shards=False),
            allowed_operations=['LOCAL_GRAPH_BUILD','INDICATOR_EVALUATION','ONE_TARGETED_CLARIFICATION',
                'VALIDATED_AND_REVIEW_EXPORT'])
        if 'batching' in manifest:
            manifest['batching']['instructions']=BATCH_PROMPT.replace(INSTRUCTIONS,SK_INSTRUCTIONS,1)
    if project_indicators is not None:manifest['project_indicators']=project_indicators
    if discovery is not None:
        manifest['discovery']=dict(path='discovery.json',sha256=s.sha(run_file(run, 'discovery.json')),
            candidates='discovery_candidates.parquet',candidate_sha256=discovery['candidates_sha256'],
            considered_per_project=len(discovery['catalog_ids']),settings=discovery['settings'],
            graph_relations=discovery['graph_relations'],compliance_decided=False)
    staging=directory/'manifest.preparing.json'
    s.write(staging,manifest)
    db=s.connect(directory)
    try:
        project_ids=dict(db.execute('SELECT siap,pid FROM projects'))
        ordered=[project_ids[siap] for siap in selected]
        db.execute("INSERT OR REPLACE INTO meta VALUES('project_order',?)",(json.dumps(ordered),))
        for pid,iid in histories:
            path=directory/'results'/pid/(iid+'.json');bundle=s.read(path)
            bundle['manifest_sha256']=s.sha(staging)
            s.write(path,bundle)
            db.execute("UPDATE jobs SET status='PASS',result_path=?,result_hash=?,updated=? WHERE pid=? AND iid=?",
                (path.relative_to(directory).as_posix(),s.sha(path),s.now(),pid,iid))
        # Aggregate original calls, including the rejected response and recovery lineage.
        seen=set()
        for file in history_files:
            path=root/file
            if path.name=='call.json':
                call=s.read(path);key=(call.get('execution_id'),call.get('timestamp'),call.get('prompt_sha256'))
                if key in seen:
                    continue
                seen.add(key)
                pid=call['project_id']; iid='HISTORICAL'
                for ancestor in path.parents:
                    candidate=ancestor/'plan.json'
                    if candidate.is_file():
                        call_plan=s.read(candidate)
                        if len(call_plan.get('indicator_ids',[]))==1:
                            iid=call_plan['indicator_ids'][0];break
                metric=call.get('usage_observations',[{}])[0]
                db.execute('INSERT OR IGNORE INTO usage VALUES(?,?,?,?,?,?,?,?)',(pid,iid,'historical',len(seen),
                    metric.get('input_tokens'),metric.get('output_tokens'),call.get('performance',{}).get('wall_seconds',{}).get('value'),
                    str(call['exit_status']) if call['exit_status'] else None))
        s.event(db,'prepared','REVIEW_REQUIRED')
    finally:
        db.close()
    staging.replace(directory/'manifest.json')
    return dict(status='REVIEW_REQUIRED',manifest=str(directory/'manifest.json'),manifest_sha256=s.sha(directory/'manifest.json'),
        projects=len(projects),indicators=sum(map(len,project_indicators.values())) if project_indicators is not None
            else len(projects)*len(catalog['profiles']),imported_pass=len(histories),inference_calls=0)


def verify(root, run, *, require_authorization=True):
    from scripts import pipeline_coordinator as coordinator
    directory=folder(run);manifest=s.read(directory/'manifest.json')
    if manifest['version']!=VERSION or manifest['run_id']!=Path(run).name:
        raise ValueError('Manifiesto incompatible')
    p.validate(manifest['policy']);configuration(manifest['llm'])
    if manifest['repository_root']!=str(Path(root).resolve()):
        raise ValueError('Raiz de ejecucion distinta de la autorizada')
    scope.check(root,manifest['source_inventory'])
    coordinator.check(root,run)  # Also checks current RAW files and scope quarantine.
    for name,digest in (manifest['files']|manifest['code']).items():
        path=(Path(root)/name).resolve()
        if not path.is_relative_to(Path(root).resolve()) or s.sha(path)!=digest:
            raise ValueError('Alcance, codigo o artefacto autorizado cambiado: '+name)
    if require_authorization:
        auth=s.read(directory/'authorization.json') if (directory/'authorization.json').exists() else {}
        if auth.get('authorized') is not True or auth.get('manifest_sha256')!=s.sha(directory/'manifest.json'):
            raise ValueError('Falta autorizacion explicita del manifiesto actual')
    db=s.connect(directory)
    try:
        pairs=manifest.get('project_indicators')
        expected=sum(map(len,pairs.values())) if pairs is not None else len(manifest['projects'])*len(manifest['profiles'])
        if db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]!=expected:
            raise ValueError('Cobertura de checkpoint modificada')
        for job in db.execute('SELECT pid,iid,status,result_path,result_hash FROM jobs'):
            if job['pid'] not in manifest['projects'] or job['iid'] not in manifest['profiles']:
                raise ValueError('Trabajo fuera del alcance aprobado')
            if pairs is not None and job['iid'] not in pairs.get(job['pid'],[]):raise ValueError('Pareja fuera del alcance aprobado')
            if job['status']=='PASS':
                path=(directory/(job['result_path'] or '')).resolve()
                if not path.is_relative_to(directory.resolve()) or not path.is_file() or s.sha(path)!=job['result_hash']:
                    raise ValueError('Checkpoint PASS modificado o ausente')
                check_result_contract(manifest,s.read(path))
    finally:
        db.close()
    return manifest


def authorize(root,run,digest):
    from scripts.pipeline_coordinator import lock
    directory=folder(run)
    with lock(Path(run).parent), lock(Path(run)):
        verify(root,run,require_authorization=False)
        if digest!=s.sha(directory/'manifest.json'):
            raise ValueError('SHA-256 revisado no coincide con manifiesto')
        path=directory/'authorization.json'
        if path.exists():
            if s.read(path).get('manifest_sha256')!=digest:
                raise ValueError('Autorizacion existente incompatible')
        else:
            s.write(path,dict(authorized=True,manifest_sha256=digest,authorized_at=s.now(),
                authorized_by=getpass.getuser(),reference='Explicit authorize --manifest-sha256 after manifest review'))
    return dict(status='AUTHORIZED',manifest_sha256=digest,inference_calls=0)


def progress(root,run):
    """Fast monitor: no corpus/vector/result scan and no model calls.

    Full source/result checks run before dispatch, on resume and on explicit verify.
    """
    directory=folder(run);manifest=s.read(directory/'manifest.json')
    if manifest['version']!=VERSION or manifest['repository_root']!=str(Path(root).resolve()):
        raise ValueError('Manifiesto incompatible')
    for name,digest in manifest['code'].items():
        if s.sha(Path(root)/name)!=digest:
            raise ValueError('Codigo autorizado modificado: '+name)
    cached={name:(value['size'],value['mtime_ns']) for name,value in manifest['source_inventory']['files'].items()}
    scope.check(root,manifest['source_inventory'],cached)
    digest=s.sha(directory/'manifest.json')
    auth=s.read(directory/'authorization.json') if (directory/'authorization.json').exists() else {}
    if auth and auth.get('manifest_sha256')!=digest:
        raise ValueError('Manifiesto distinto del autorizado')
    return s.status(directory)|dict(run_id=Path(run).name,manifest_sha256=digest,
        authorized=auth.get('authorized') is True,imported_pass=manifest['imported_pass'],
        integrity='MANIFEST_RUNTIME_AND_INTAKE_METADATA; full verification before execution')


def deep_verify(root,run):
    manifest=verify(root,run,require_authorization=False)
    if (knowledge_workspace(run)/'outputs/layer3/publication/_manifest.json').exists():
        verify_graph(run)
    worker=Worker(folder(run),manifest)
    try:
        for job in worker.db.execute("SELECT * FROM jobs WHERE status='PASS'"):
            job=dict(job)
            if not worker.adopt(job,worker.load_project(job['pid']),commit=False):
                raise ValueError('Falta resultado PASS')
    finally:
        worker.close()
    return dict(status='VERIFIED',coverage=s.status(folder(run)),inference_calls=0)


def graph_index(root,run,directory,manifest):
    from scripts import pipeline_coordinator as coordinator
    publication=knowledge_workspace(run)/'outputs/layer3/publication'
    db=s.connect(directory);db.execute("INSERT OR REPLACE INTO meta VALUES('stage','graphrag')");db.close()
    if not (publication/'_manifest.json').exists():
        build_graph(root,run)  # Child exits before Qwen; no retained BGE GPU allocator.
    verify_graph(run)
    candidate=(run_file(run,manifest['discovery']['candidates']) if manifest.get('discovery') else
        publication/'retrieval/source_indicator_candidates.parquet')
    binding=Path(directory)/'graph.binding.json'
    if binding.exists():
        old=s.read(binding)
        if old['manifest_sha256']!=s.sha(publication/'_manifest.json') or old['index_sha256']!=s.sha(Path(directory)/'candidate_index.sqlite'):
            raise ValueError('GraphRAG o indice derivado cambiaron; no continuar')
        return
    temporary=Path(directory)/'candidate_staging'
    if temporary.exists() or (Path(directory)/'candidate_index.sqlite').exists():
        if list((Path(directory)/'attempts').rglob('dispatch.claim.json')):
            raise ValueError('Binding GraphRAG ausente con llamadas previas; no reconstruir silenciosamente')
        archive=Path(directory)/'index_history'/uuid.uuid4().hex
        archive.mkdir(parents=True)
        for orphan in (temporary,Path(directory)/'candidate_index.sqlite'):
            if orphan.exists():
                if not orphan.resolve().is_relative_to(Path(directory).resolve()):
                    raise ValueError('Indice fuera de la ejecucion')
                orphan.rename(archive/orphan.name)
    temporary.mkdir()
    path=index_sources(temporary,{'candidates':candidate},manifest['policy']['parquet_batch_rows'])
    path.rename(Path(directory)/'candidate_index.sqlite')
    temporary.rmdir()
    db=sqlite3.connect(Path(directory)/'candidate_index.sqlite')
    try:
        project_hashes={pid:canonical_hash(rows_for(db,'candidates',pid)) for pid in manifest['projects']}
    finally:
        db.close()
    s.write(binding,dict(manifest_sha256=s.sha(publication/'_manifest.json'),
        index_sha256=s.sha(Path(directory)/'candidate_index.sqlite'),project_sha256=project_hashes))


def evaluation_worker(manifest):
    """Select the authorized adapter, retaining the existing resource scheduler."""
    if 'evaluator' not in manifest:return Worker
    from .minimal import MinimalWorker,VERSION as MINIMAL
    if manifest.get('batching'):
        from .batching import BatchWorker,VERSION as BATCH
        if manifest['batching']['version']!=BATCH:raise ValueError('Version de lotes desconocida')
        MinimalWorker=BatchWorker
    if manifest['evaluator']!=MINIMAL:raise ValueError('Evaluador desconocido')
    if 'resource_wait' in manifest and not hasattr(MinimalWorker,'ram_gate'):
        from .resource_wait import worker_class
        return worker_class(MinimalWorker)
    return MinimalWorker


@measured_run
def execute(root, run, *, client_factory=None, ram=None, sleep=None):
    import os
    from scripts.pipeline_coordinator import lock
    directory=folder(run)
    with lock(Path(run).parent), lock(Path(run)):
        manifest=verify(root,run)
        from run_storage import reopen
        reopen(run)
        # Resume only clears a previous cooperative stop after acquiring execution locks.
        (run_file(Path(run), 'stop.request.json')).unlink(missing_ok=True)
        if manifest['llm']['provider']=='openai':
            from model_access import api_key
            if not api_key(root):raise ValueError('API_KEY_MISSING: configurar clave antes de iniciar')
        process=s.process_info(os.getpid())
        s.write(run_file(directory, 'worker.json'),dict(pid=os.getpid(),creation=process['creation'],state='RUNNING',started_at=s.now()))
        graph_index(root,run,directory,manifest)
        db=s.connect(directory)
        # RUNNING is only a scheduling claim. Each step decides from its durable
        # transport receipt whether to adopt, retry a known error or mark uncertain.
        db.execute("UPDATE jobs SET status='PENDING' WHERE status='RUNNING'")
        s.event(db,'evaluation','RESUMED');db.close()
        stop=threading.Event()
        def work():
            worker=evaluation_worker(manifest)(directory,manifest,stop,client_factory,ram,sleep)
            worker.loop()
        try:
            workers=manifest['policy']['workers']
            if manifest['llm']['provider']=='openai':workers=min(workers,manifest['llm']['api']['max_concurrency'])
            if workers==1:
                work()
            else:
                executor=ThreadPoolExecutor(max_workers=workers)
                try:
                    futures=[executor.submit(work) for _ in range(workers)]
                    for future in futures:
                        future.result()
                finally:
                    if any(not future.done() or future.exception() for future in futures):
                        stop.set()
                    executor.shutdown(wait=True,cancel_futures=True)
        except KeyboardInterrupt:
            stop.set()
            worker=s.read(run_file(directory, 'worker.json'));worker.update(state='INTERRUPTED',finished_at=s.now())
            s.write(run_file(directory, 'worker.json'),worker)
            from run_control import project_states
            project_states(run)
            partial_export=export(root,run,partial=True)
            return dict(s.status(directory),status='INTERRUPTED',export=partial_export)
        except Exception:
            stop.set()
            worker=s.read(run_file(directory, 'worker.json'));worker.update(state='FAILED',finished_at=s.now())
            s.write(run_file(directory, 'worker.json'),worker)
            raise
        result=s.status(directory)
        db=s.connect(directory)
        db.execute("INSERT OR REPLACE INTO meta VALUES('stage',?)",('paused' if stop.is_set() else 'evaluation_complete',))
        s.event(db,'paused' if stop.is_set() else 'evaluation_complete',result['status']);db.close()
        worker=s.read(run_file(directory, 'worker.json'));worker.update(state='FINISHED',finished_at=s.now())
        s.write(run_file(directory, 'worker.json'),worker)
        result=s.status(directory)
        s.write(run_file(directory, 'progress.json'),result)
        from run_control import project_states
        result['project_states']=project_states(run)
        if stop.is_set():
            result['export']=export(root,run,partial=True)
        return result


def retry_pending(root,run,*,acknowledge_uncertain=False):
    from scripts.pipeline_coordinator import lock
    directory=folder(run)
    with lock(Path(run).parent), lock(Path(run)):
        manifest=verify(root,run);db=s.connect(directory)
        try:
            with s.transaction(db):
                statuses=('BLOCKED','UNCERTAIN') if acknowledge_uncertain else ('BLOCKED',)
                marks=','.join('?' for _ in statuses)
                cursor=db.execute(f"UPDATE jobs SET status='PENDING',rounds=rounds+1,error=NULL,updated=? WHERE status IN ({marks}) AND rounds<? AND error NOT IN ('SOURCE_QUARANTINE','NO_AUTHORIZED_SUBSTANTIVE_TEXT','UNAUTHORIZED_PROJECT_TEXT','RUNTIME_DRIFT','INTERNAL_ERROR','SEMANTIC_REVIEW_REQUIRED','CLARIFICATION_UNRESOLVED')",
                    (s.now(),*statuses,manifest['policy']['recovery_rounds']))
                s.event(db,'recovery','UNCERTAIN_ACKNOWLEDGED' if acknowledge_uncertain else 'RETRY_PENDING')
                count=cursor.rowcount
        finally:
            db.close()
    return dict(status='PENDING',requeued=count,inference_calls=0)


def background(root,run,*,through='export',config_path='config/pipeline_manual.json'):
    """Launch only an already authorized immutable manifest; no shell or stdin."""
    import os
    import subprocess
    import sys
    verify(root,run)
    directory=folder(run);logs=directory/'logs';logs.mkdir(exist_ok=True)
    command=[sys.executable,str(Path(root)/'run.py'),'start','--autonomous','--run-id',Path(run).name,
        '--non-interactive','--through',through]
    if config_path!='config/pipeline_manual.json':
        command+=['--config',str(config_path)]
    options=dict(cwd=str(root),stdin=subprocess.DEVNULL,close_fds=True)
    if os.name=='nt':
        options['creationflags']=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    else:
        options['start_new_session']=True
    with (logs/'stdout.log').open('ab') as output,(logs/'stderr.log').open('ab') as errors:
        process=subprocess.Popen(command,stdout=output,stderr=errors,**options)
    receipt=dict(status='STARTED',pid=process.pid,started_at=s.now(),manifest_sha256=s.sha(directory/'manifest.json'),
        stdout=str(logs/'stdout.log'),stderr=str(logs/'stderr.log'))
    s.write(run_file(directory, 'worker.json'),receipt)
    return receipt


def export(root,run,*,partial=False):
    # Projection is read-only with respect to the authorized inference artifacts.
    # Partial coverage is represented in estado_cumplimiento, never extra sheets.
    from .final_output import export as project_final
    return project_final(root,run)
