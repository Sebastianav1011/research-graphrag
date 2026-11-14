"""CLI orchestration; existing layer implementations operate inside a private root."""
from run_paths import file_path as run_file
from knowledge_store import knowledge_workspace, evaluation_dir
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import uuid

import openpyxl
import pyarrow.parquet as pq
import yaml
from layer4_evaluation.indicators.performance import measured_pipeline, timed, project_states, observe_projects


from layer2_processing.preprocessing.adapters import PROJECT_FIELDS, read, sha, write
from layer4_evaluation.indicators.selection import substantive_fields
from layer2_processing import pipeline as processing
from layer2_processing.pipeline import check, same_configuration, layer_config, seal

ROOT = Path(__file__).resolve().parents[1]
from layer4_evaluation.thesis_output import COLUMNS
TERRITORY_COLUMNS = ['siap_id', 'territory_type', 'territory_code', 'code_system']


def within(root, relative):
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError('Ruta fuera de la raiz permitida: ' + str(relative))
    return path


def configuration(root, path):
    config = read(within(root, path))
    raw = within(root, config['raw_base'])
    runs = within(root, config['runs_base'])
    if raw == runs or raw.is_relative_to(runs) or runs.is_relative_to(raw):
        raise ValueError('RAW y ejecuciones deben estar separados')
    # Never permit an alternate config to publish over the historical stores/code.
    allowed_raw = {(root / 'data/layer1_sources').resolve()}
    if not any(runs.is_relative_to(root / p) for p in ('outputs/runs', 'outputs/pipeline_manual')) or not any(raw.is_relative_to(p) for p in allowed_raw):
        raise ValueError('Fuentes en data/layer1_sources y ejecuciones nuevas en outputs/runs')
    reference = within(root, config['reference_catalog'])
    if not reference.is_relative_to(root / 'data/layer1_sources/reference/indicadores'):
        raise ValueError('Catalogo VRI debe permanecer en data/layer1_sources/reference/indicadores, separado de RAW')
    return config, raw, runs


@contextmanager
def lock(folder):
    from run_paths import BUCKETS
    folder=Path(folder)
    if folder.name in BUCKETS and folder.parent.name=='runs':folder=folder.parent
    folder.mkdir(parents=True, exist_ok=True)
    run_file(folder,'.execution.lock').parent.mkdir(parents=True,exist_ok=True)
    with (run_file(folder, '.execution.lock')).open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def graph_configuration(root, run):
    """Bind GraphRAG to a prepared knowledge checkpoint without building embeddings."""
    if read(run_file(run, 'run.json')).get('knowledge_ref'):
        return  # Shared versions are sealed with their own GraphRAG configuration.
    workspace = run / 'workspace'
    if not (workspace / 'config/layer3.yaml').exists():
        layer3 = yaml.safe_load(layer_config(root, 4).read_text(encoding='utf-8'))
        layer3['readiness']['approved_layer2_manifest_sha256'] = sha(workspace / 'outputs/layer2/knowledge/_manifest.json')
        layer3['execution']['allow_real_build'] = False
        (workspace / 'config/layer3.yaml').write_text(yaml.safe_dump(layer3), encoding='utf-8')
        seal(run)


@timed('preparacion')
def prepare(root, run, raw, dataset, config, through='knowledge'):
    result = processing.prepare(root, run, raw, dataset, config, through=through)
    if through == 'knowledge':
        graph_configuration(root, run)
    return result


@timed('preparacion')
def knowledge(root, run):
    result = processing.knowledge(root, run)
    graph_configuration(root, run)
    return result


def graph(root, run, build=False):
    if check(root, run)['status'] != 'PREPARED':
        raise ValueError('Ejecutar knowledge antes de GraphRAG')
    from layer3_graphrag.pipeline import run as graphrag
    workspace = knowledge_workspace(run)
    graph_configuration(root, run)
    config_path = workspace / 'config/layer3.yaml'
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    if build:
        from layer3_graphrag.manifest import validate_publication
        published = workspace / 'outputs/layer3/publication'
        if (published / '_manifest.json').exists():
            return validated_graph(root, run)
        config['execution']['allow_real_build'] = True
        config_path = workspace / 'config/layer3.build.yaml'
        config_path.write_text(yaml.safe_dump(config), encoding='utf-8')
    # The existing provider deliberately locates pinned weights at the code root.
    # Everything it writes (cache, graph, indexes, reports) uses this private workspace.
    result = graphrag(workspace, config_path=str(config_path.relative_to(workspace)), mode='build' if build else 'validate')
    write(run_file(run, 'graph_result.json' if build else 'graph_validation.json'), result)
    return result


def validated_graph(root, run):
    """Reject another run's graph, corrupt vectors, or a test/changed embedding provider."""
    from layer3_graphrag.configuration import load_config
    from layer3_graphrag.embeddings import create_provider
    from layer3_graphrag.pipeline import load_artifacts
    from layer3_graphrag.validate_inputs import validate_inputs
    workspace = knowledge_workspace(run)
    config, _ = load_config(workspace)
    snapshot = validate_inputs(workspace, config)
    manifest, _, _ = load_artifacts(workspace, snapshot, config, create_provider(config['embeddings']))
    return manifest


def register_built_knowledge(root, run, request):
    """After a complete, verified BASE build: register it in place and activate it.

    The previous active version stays active until this point; a failure during
    the build never reaches here. Nothing is copied or moved.
    """
    import knowledge_store
    state = read(run_file(run, 'run.json'))
    if (state.get('configuration', {}).get('knowledge_scope') != 'BASE_GLOBAL_V1' or state.get('knowledge_ref')
            or state.get('global_reuse')):
        return None
    manifest = knowledge_store.register(root, run, activate=True)
    request['knowledge_version'] = dict(version_id=manifest['version_id'], fingerprint=manifest['fingerprint'],
        location=manifest['location'], storage=manifest['storage'])
    write(run_file(run, 'execution.json'), request)
    return manifest


def engine(root, run):
    import importlib
    from layer4_evaluation import live_execution
    module = importlib.reload(live_execution)
    module.BASE = evaluation_dir(run)
    return module


def projects_without_evidence(run, selected):
    """Isolate missing input before batching; never classify title-only projects."""
    base = knowledge_workspace(run) / 'outputs/layer2'
    projects = pq.read_table(base / 'canonical/proyectos.parquet').to_pylist()
    sections = pq.read_table(base / 'knowledge/source_sections.parquet').to_pylist()
    fields = {}
    for section in sections:
        fields.setdefault(section['source_id'], {})[section['field_name']] = section['text_original'] or ''
    unavailable = []
    for project in projects:
        if project['source_project_id'] not in selected:
            continue
        values = fields.get(project['project_id'], {})
        if not any((values.get(f) or '').strip() for f in substantive_fields(values)):
            unavailable.append(project['source_project_id'])
    return unavailable


def evaluation_settings(root, module):
    """Read sealed semantics for a NEW run, not a historical closure execution.

    Historical publication verification still uses the frozen closure checker.
    New calls bind current executable bytes separately from the immutable rubric.
    """
    from layer4_evaluation.indicators.experiment_inputs import verify_hashes
    settings = read(module.FROZEN)
    manifest = read(module.FROZEN.with_name('closure.manifest.json'))
    if sha(module.FROZEN) != manifest['plan_sha256']:
        raise ValueError('Closure plan changed')
    if (settings['discovery_version'] != module.gd.VERSION or settings['assessment_version'] != module.v3.VERSION
            or len(settings['profiles']) != 48 or settings['compact_active'] or settings['proposal_v3_4_active']):
        raise ValueError('Frozen configuration differs')
    resources = {name: digest for name, digest in settings['source_hashes'].items() if not name.endswith('.py')}
    verify_hashes(root, resources)
    for iid, profile in settings['profiles'].items():
        module.v3.check_rubric(profile, settings['rubrics'][iid])
    return settings, resources


def pinned_tokenizer(root):
    """Pinned Qwen tokenizer descriptor, verified by SHA-256; no model is loaded."""
    descriptor=read(root/'config/qwen_tokenizer.json')
    path=(root/descriptor['path']).resolve()
    if not path.is_file():
        raise ValueError('Tokenizer Qwen fijado ausente: uv run python scripts/prepare_qwen_tokenizer.py')
    if sha(path)!=descriptor['sha256']:
        raise ValueError('Tokenizer local distinto del fijado en config/qwen_tokenizer.json')
    return descriptor|dict(path=str(path))


def prepare_evaluation(root, run, selected):
    from layer4_evaluation.indicators.context_budget import VERSION as context_version, prepare_contexts
    from layer4_evaluation.indicators import assessment_v3 as v3
    state = check(root, run)
    from layer4_evaluation.indicators.ollama_provider import configuration as llm_configuration
    request_path = run_file(run, 'execution.json')
    requested = read(request_path) if request_path.is_file() else {}
    policy=requested.get('evaluation_policy',state['configuration'].get('evaluation_policy',{}))
    provider_config = llm_configuration(requested.get('llm', state['configuration'].get('llm')))
    workspace = knowledge_workspace(run)  # Read-only knowledge; evaluation writes under evaluation_dir(run).
    projects = pq.read_table(workspace / 'outputs/layer2/canonical/proyectos.parquet').to_pylist()
    if not selected:
        if len(projects) > 2:
            raise ValueError('Seleccionar uno o dos --project-id; IDs en preprocess/review.json o canonical')
        selected = [p['source_project_id'] for p in projects]
    if not 1 <= len(selected) <= 2 or len(set(selected)) != len(selected):
        raise ValueError('Seleccionar uno o dos identificadores unicos')
    chosen = [p for pid in selected for p in projects if p['source_project_id'] == pid]
    if len(chosen) != len(selected):
        raise ValueError('Identificador no presente en esta ejecucion')
    quarantine=state.get('scope_quarantine',{})
    blocked=[p for p in selected if p in quarantine.get('affected_projects',{}) or quarantine.get('primary_article_conflicts')]
    if blocked:
        write(run_file(run, 'evaluation_readiness.json'),dict(status='BLOCKED_ARTICLE_QUARANTINE',projects=blocked,
            report=str(run/'preprocess/scope_validation.json'),note='Sin inferencias ni clasificacion; cuarentena conservada'))
        raise ValueError('Cuarentena relevante para proyectos seleccionados: '+', '.join(blocked)+'; consultar preprocess/scope_validation.json')
    sections = pq.read_table(workspace / 'outputs/layer2/knowledge/source_sections.parquet').to_pylist()
    unavailable = []
    for project in chosen:
        fields = {s['field_name']: s['text_original'] or '' for s in sections if s['source_id'] == project['project_id']}
        if not any(value.strip() for field, value in fields.items() if field in substantive_fields(fields)):
            unavailable.append(dict(project_id=project['project_id'], source_project_id=project['source_project_id'],
                status='NO_AUTHORIZED_SUBSTANTIVE_TEXT', record_source=project['record_source'], source_row=project['source_row']))
    if unavailable:
        write(run_file(run, 'evaluation_readiness.json'), dict(status='BLOCKED_NO_EVIDENCE', projects=unavailable,
            note='Sin clasificacion de indicadores ni inferencias; conservar metadatos y aportar evidencia autorizada'))
        raise ValueError('Proyectos seleccionados sin evidencia textual sustantiva autorizada: ' +
            ', '.join(p['source_project_id'] for p in unavailable) + '; consultar evaluation_readiness.json. No se asigna un estado de cumplimiento')
    validated_graph(root, run)
    module = engine(root, run)
    batch = batch_name(selected)
    directory = module.BASE / batch
    wanted=requested.get('indicator_ids')
    if directory.exists():
        if read(directory/'plan.json').get('evaluation_policy',{})!=policy:
            raise ValueError('Modos incompatibles con el lote; crear un run nuevo')
        if read(directory/'plan.json').get('indicator_selection')!=(sorted(wanted) if wanted else None):
            raise ValueError('Seleccion de indicadores incompatible con el lote; crear un run nuevo')
        previous = module.check(directory)
        if previous.get('runtime', {}).get('provider') != provider_config['provider']:
            raise ValueError('Lote historico o proveedor/configuracion distinta: no reutilizar respuestas Codex como Qwen; crear otra ejecucion')
        if (previous['runtime']['configuration'] == provider_config and previous.get('request_protocol') == context_version and
                previous.get('source_hashes',{}).get('src/layer4_evaluation/indicators/context_budget.py') ==
                sha(root/'src/layer4_evaluation/indicators/context_budget.py')):
            return batch
        changed = {key for key in provider_config if provider_config[key] != previous['runtime']['configuration'].get(key)}
        if changed - {'num_ctx', 'num_predict', 'timeout_seconds', 'context_margin_tokens'}:
            raise ValueError('Cambiar proveedor/modelo requiere otra ejecucion; no reutilizar respuestas de otra configuracion')
        for other in module.BASE.glob('batch_*'):
            if any((other / 'calls').rglob('*')) or read(other / 'cache.json'):
                raise ValueError('Configuracion LLM distinta con llamadas/cache previos: conservar el run y crear otra ejecucion')
        # Only a review with no inference may be replaced. Keep its exact bytes,
        # authorization and metadata outside the active batch glob.
        base = module.BASE.resolve()
        archive = (base / 'review_versions' / batch / sha(directory / 'plan.json')).resolve()
        if directory.is_symlink() or not directory.resolve().is_relative_to(base) or not archive.is_relative_to(base):
            raise ValueError('Ruta de revision fuera de la ejecucion')
        archive.parent.mkdir(parents=True, exist_ok=True)
        directory.rename(archive)
    for existing in module.BASE.glob('batch_*'):
        if {p['siap_id'] for p in module.check(existing)['projects']} & set(selected):
            raise ValueError('Proyecto ya preparado en otro lote; reanudar la seleccion original para no repetir inferencias')
    settings, semantic_resources = evaluation_settings(root, module)
    derivation=None
    if policy:
        settings=dict(settings)
        settings['rubrics'],derivation=v3.catalog_for_mode(settings['profiles'],settings['rubrics'],policy['evaluation_mode'])
    catalog_ids = {r['indicator_id'] for r in pq.read_table(workspace / 'outputs/layer2/canonical/indicadores.parquet').to_pylist()}
    if catalog_ids != set(settings['profiles']):
        raise ValueError('Catalogo GraphRAG y los 48 perfiles V3.3 no tienen los mismos IDs')
    # Optional subset: the sealed catalog stays complete in the plan; only the
    # selected indicators are retrieved, packed, dispatched and exported.
    if wanted:
        unknown=sorted(set(wanted)-set(settings['profiles']))
        if unknown:raise ValueError('Indicadores fuera del catalogo: '+', '.join(unknown))
    selected_profiles={iid:settings['profiles'][iid] for iid in sorted(wanted)} if wanted else settings['profiles']
    directory.mkdir(parents=True)
    inputs = []
    for p in chosen:
        matches = [s for s in sections if s['source_id'] == p['project_id']]
        fields = {f: next((s['text_original'] or '' for s in matches if s['field_name'] == f), '') for f in PROJECT_FIELDS}
        fields.update({s['field_name']: s['text_original'] or '' for s in matches if s['field_name'].startswith('text__')})
        field_provenance = {s['field_name']: dict(section_id=s['section_id'], text_hash_original=s['text_hash_original'],
            source_file=p['record_source'], source_row=p['source_row'],
            raw_sources=json.loads(s['provenance_json'])['layer1']) for s in matches}
        inputs.append(dict(project_id=p['project_id'], siap_id=p['source_project_id'], identity_type='SIAP_PROPORCIONADO',
            fields=fields, field_provenance=field_provenance, input_path=p['record_source'],
            input_row=p['source_row'], missing_fields=[f for f, v in fields.items() if not v]))
    review = dict(projects=inputs, llm=provider_config,
        warnings=['Una solicitud por indicador, con fragmentos originales recuperados por GraphRAG. Se revisan los 48 indicadores.',
                  'Presupuesto aproximado de entrada incluye esquema; las omisiones y limitaciones constan en context_selection.json. No se truncan citas.'], inference_performed=False)
    if wanted:
        review['warnings'][0]=review['warnings'][0].replace('Se revisan los 48 indicadores.',
            'Validacion acotada: solo se revisan los indicadores seleccionados '+', '.join(sorted(wanted))+'; el catalogo sellado conserva los 48.')
        review['indicator_selection']=sorted(wanted)
    relational_contexts=None
    if policy.get('context_mode') in (v3.FULL_CONTEXT,v3.BASE_CONTEXT):
        source_chunks,scoped_candidates=[],[]
        retrieval_report=dict(context_mode=v3.FULL_CONTEXT,retrieval_used_for_evaluation=False)
        review['warnings'][0]='Una solicitud por indicador con el descriptor completo autorizado; sin recorte ni fallback automatico.'
        if policy['context_mode']==v3.BASE_CONTEXT:
            from layer4_evaluation.indicators.scoped_retrieval import project_relations
            relational_contexts=project_relations(workspace,inputs)
            retrieval_report=dict(context_mode=v3.BASE_CONTEXT,relational_retrieval=True,
                project_ids=sorted(relational_contexts))
            review['warnings'][0]+=' Relaciones verificadas del grafo global como contexto complementario, sin transferir resultados entre proyectos.'
    else:
        from layer4_evaluation.indicators.scoped_retrieval import from_published_cache
        source_chunks=pq.read_table(workspace / 'outputs/layer2/knowledge/source_chunks.parquet').to_pylist()
        if policy.get('context_mode')==v3.RETRIEVED_CONTEXT:
            from layer4_evaluation.indicators.scoped_retrieval import project_relations
            relational_contexts=project_relations(workspace,inputs)
        # Keep existing cached retrieval unchanged in fragment mode.
        scoped_candidates,retrieval_report=from_published_cache(workspace,inputs,selected_profiles,source_chunks,
            **({'relational_contexts':relational_contexts} if relational_contexts is not None else {}))
    # Retrieved contexts are budgeted with the pinned, hash-verified Qwen
    # tokenizer; RUNTIME_DRIFT is enforced by the transport before each call.
    tokenizer=pinned_tokenizer(root) if policy.get('context_mode')==v3.RETRIEVED_CONTEXT else None
    requests, context_report = prepare_contexts(inputs, selected_profiles, settings['rubrics'], provider_config,
        scoped_candidates,source_chunks,sections,
        evidence_references=True, assessment_version=v3.SK_VERSION,
        evaluation_mode=policy.get('evaluation_mode'),context_mode=policy.get('context_mode'),
        relational_contexts=relational_contexts,
        **({'tokenizer':tokenizer} if tokenizer is not None else {}),
        # Prompt text follows the run's sealed policy version (V2 plans stay V2).
        **({'prompt_version':policy['instructions_version']} if policy.get('instructions_version')==v3.PROSPECTIVE_PROMPT_V3 else {}))
    context_report['project_scoped_retrieval']=retrieval_report
    write(directory / 'context_selection.json', context_report)
    review['context_selection'] = context_report
    review['requests'] = requests
    if policy:review.update(evaluation_policy=policy,catalog_derivation=derivation)
    too_long=[dict(project_id=r['project_id'],indicator_id=r['indicator_id']) for r in context_report['requests']
        if r['status']=='FULL_DESCRIPTOR_TOO_LONG']
    if too_long:
        review['warnings'].append('FULL_DESCRIPTOR_TOO_LONG: no se despachan estos indicadores; elegir explicitamente GraphRAG en un run nuevo. Ver context_selection.json.')
        review['full_descriptor_blocked']=too_long
    if (run/'preprocess/scope.json').is_file():
        scoped=read(run/'preprocess/scope.json')
        review['scope_notice']=dict(selected_counts=scoped['selected_counts'],identity_links=scoped['identity_links'],
            unverified_production_records=len(scoped['unverified_production']),report=str(run/'preprocess/scope.json'),
            note='Las asociaciones no corroboradas no aportan evidencia. Esto no demuestra ausencia de produccion.')
    write(directory / 'review.json', review)
    (directory / 'review.txt').write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
    write(directory / 'cache.json', {})
    source_hashes = dict(semantic_resources)
    source_hashes.update(state['code_hashes'])
    for path in (module.FROZEN, root / 'src/layer4_evaluation/live_execution.py', root / 'src/layer4_evaluation/indicators/ollama_provider.py', root / 'src/layer4_evaluation/indicators/context_budget.py', run_file(run, 'prepared_hashes.json'), workspace / 'outputs/layer3/publication/_manifest.json'):
        source_hashes[path.relative_to(root).as_posix()] = sha(path)
    plan = {k: settings[k] for k in ('profiles', 'rubrics', 'rules', 'budgets', 'observed_character_ratio', 'discovery_version', 'assessment_version')}
    for path in (root/'src/layer4_evaluation/indicators/openai_provider.py',
                 root/'src/layer4_evaluation/indicators/evidence_references.py',
                 root/'src/layer4_evaluation/indicators/token_budget.py',root/'config/qwen_tokenizer.json',
                 root/'src/layer4_evaluation/indicators/scoped_retrieval.py',run_file(run, 'model.binding.json')):
        if path.exists():source_hashes[path.relative_to(root).as_posix()]=sha(path)
    plan.update(version='MANUAL_RAW_V3_3_OLLAMA_V1', execution_id=uuid.uuid4().hex, projects=inputs,
        assessment_version=v3.SK_VERSION, confidence_version=v3.SK_CONFIDENCE_VERSION,
        coverage_policy=v3.PARTIAL_COVERAGE,
        request_protocol=context_version, context_requests=requests,
        isolate_indicator_errors=True,
        corrective_retries=2,
        token_limit_retries=provider_config['token_limit_retries'] if provider_config['provider']=='ollama' else 0,
        runtime=dict(provider=provider_config['provider'], configuration=provider_config), requested_model=provider_config['model'],
        maximum_calls=len(selected_profiles) * len(inputs), total_token_reservation_cap=170000 * len(inputs), timeout_seconds=provider_config['timeout_seconds'],
        source_hashes=source_hashes, territories=[], run_id=run.name)
    if policy:plan.update(evaluation_policy=policy,catalog_derivation=derivation)
    if wanted:plan['indicator_selection']=sorted(wanted)
    if policy.get('context_mode') in (v3.FULL_CONTEXT,v3.BASE_CONTEXT):
        resources=read(root/'config/autonomous.json') if (root/'config/autonomous.json').exists() else {}
        plan['resource_policy']=dict(min_free_ram_mb=resources.get('min_free_ram_mb',1536),
            context_ceiling=24576,out_of_memory='BLOCK_WITHOUT_AUTOMATIC_CONTEXT_CHANGE')
    retry_limit=max(plan['token_limit_retries'],plan['corrective_retries'])
    plan['maximum_calls'] *= 1 + retry_limit
    reservation=provider_config['num_ctx'] * (1 + retry_limit)
    plan['budgets'] = dict(plan['budgets'], assessment_reservation=reservation,
        assessment_postcall_review_threshold=reservation)
    plan['total_token_reservation_cap'] = plan['maximum_calls'] * provider_config['num_ctx']
    write(directory / 'plan.json', plan)
    write(directory / 'manifest.json', dict(plan_sha256=sha(directory / 'plan.json'),
        **({'evaluation_policy_sha256':policy['sha256']} if policy else {}),
        files={n: sha(directory / n) for n in ('review.json', 'review.txt', 'cache.json', 'context_selection.json')}))
    return batch


def evaluate(root, run, selected, authorize=False, execute=False):
    batch = prepare_evaluation(root, run, selected)
    module = engine(root, run)
    if not execute:
        return dict(status='REVIEW_REQUIRED', review=str(module.BASE / batch / 'review.txt'), batch=batch, inference_calls=0)
    return module.execute(SimpleNamespace(run=batch, authorize=authorize))


def batch_name(selected):
    return 'batch_' + __import__('hashlib').sha256(json.dumps(sorted(selected)).encode()).hexdigest()[:16]


def evidence_sources(project, location):
    field = location['field']
    refs = project['field_provenance'][field]['raw_sources']
    valid = [r for r in refs if field in r['field_mapping']]
    if not valid:
        raise ValueError('Evidencia sin campo RAW de origen: ' + field)
    return '\n'.join(f'{r["record_source"]}; hoja={r.get("source_sheet")}; registro={r["source_row"]}; campo_RAW={r["field_mapping"][field]}; campo_preprocesado={field}' for r in valid)


def export(root, run, *, offline=False, output_contract=None):
    from layer4_evaluation.indicator_csv import TerritoryCodes, write_results
    from layer4_evaluation.thesis_output import (positive_record, indicator_record, render as render_thesis,
        TEMPLATE, SHEETS, DEFAULT_CONTRACT, POSITIVE_CONTRACT, ALL_CONTRACT, VALID_CONTRACT, GENERAL_COLUMNS, recover_export)
    output_contract=output_contract or DEFAULT_CONTRACT
    if output_contract not in (POSITIVE_CONTRACT,ALL_CONTRACT,VALID_CONTRACT):raise ValueError('Contrato desconocido')
    consumer_columns=GENERAL_COLUMNS if output_contract==VALID_CONTRACT else COLUMNS
    if offline:return recover_export(root,run,contract=output_contract)
    resolve_codes = TerritoryCodes(root)
    codes_by_pair, csv_records = {}, {}
    check(root, run)
    module = engine(root, run)
    if any(module.BASE.glob('batch_*')):
        validated_graph(root, run)
    rows, lineage, processed, selected, errors = [], [], set(), set(), []
    coverage, valid_results=[], []
    evaluated_projects, blocked_results, complete_projects = set(), set(), set()
    export_exclusions=[];indicator_ids=set()
    all_projects = {p['source_project_id'] for p in pq.read_table(knowledge_workspace(run) / 'outputs/layer2/canonical/proyectos.parquet').to_pylist()}
    request = read(run_file(run, 'execution.json')) if (run_file(run, 'execution.json')).exists() else {}
    target_projects = set(request['project_ids']) if request.get('selection') and request.get('project_ids') is not None else all_projects
    if not target_projects or not target_projects <= all_projects:
        raise ValueError('Seleccion de exportacion vacia o ausente del canonical')
    for directory in sorted(module.BASE.glob('batch_*')):
        plan, state = module.check(directory), module.verify_run(directory)
        if plan.get('evaluation_policy',{})!=request.get('evaluation_policy',{}):
            raise ValueError('No mezclar modos de evaluacion/contexto en una exportacion')
        indicator_ids.update(plan.get('indicator_selection') or plan['profiles'])
        errors.extend(state['errors'])
        for s in state['projects']:
            p = next(p for p in plan['projects'] if p['project_id'] == s['project_id'])
            if p['siap_id'] not in target_projects:
                raise ValueError('Evaluacion fuera de la seleccion: no se publica un Excel mezclado')
            selected.add(p['siap_id'])
            if s['rows']:evaluated_projects.add(p['siap_id'])
            if s['blocked_indicators'] or s.get('context_limits'):blocked_results.add(p['siap_id'])
            if any(error.startswith(s['project_id']+':') for error in state['errors']):blocked_results.add(p['siap_id'])
            if s['complete']:
                complete_projects.add(p['siap_id'])
            valid_ids={r['indicator_id'] for r in s['rows']}
            decisions={r['indicator_id']:r['decision'] for r in s['rows']}
            expected_ids=s.get('selected',sorted(plan['profiles']))
            unresolved=set(expected_ids)-valid_ids-set(s['blocked_indicators'])-set(s.get('context_limits',{}))
            if expected_ids and not unresolved and s.get('discovery_complete',True):
                processed.add(p['siap_id'])
            for iid in expected_ids:
                status=('VALID' if iid in valid_ids else s['blocked_indicators'].get(iid) or
                    s.get('context_limits',{}).get(iid) or 'PENDING')
                coverage.append(dict(siap_id=p['siap_id'],indicator_id=iid,status=status,
                    decision=decisions.get(iid),project_complete=s['complete']))
                # Audit only: the prepared context state travels with every
                # indicator, so evidence limits are never hidden behind VALID.
                context=plan.get('context_requests',{}).get(s['project_id'],{}).get(iid,{}).get('context_selection')
                if context:
                    coverage[-1].update(context_status=context.get('status'),evidence_limited=context.get('evidence_limited'),
                        **({'truncation':context['truncation']} if 'truncation' in context else {}))
            for row in s['rows']:
                iid = row['indicator_id']
                assessment = module.assessment_from_row(row)
                if module.v3.validate(p['fields'], plan['profiles'][iid], assessment, plan['rubrics'][iid]):
                    raise ValueError('Assessment guardado invalido')
                valid_results.append(dict(row,siap_id=p['siap_id']))
                if output_contract==POSITIVE_CONTRACT and row['decision']!='SUPPORTED':
                    continue  # Negatives and partial support remain in verified diagnostics.
                locations = module.evidence_locations(p, assessment)
                relevant = any(c['support'] in ('CLEAR', 'PARTIAL') and any(assessment['evidence'][i]['field'] in substantive_fields(p['fields']) for i in c['evidence_indices']) for c in assessment['criterion_assessments'])
                if row['decision']=='SUPPORTED' and (not relevant or not locations or not all(e['match_valid'] and e['section_id'] for e in locations)):
                    if output_contract in (ALL_CONTRACT,VALID_CONTRACT):raise ValueError('SUPPORTED sin evidencia verificada')
                    export_exclusions.append(dict(siap_id=p['siap_id'],indicator_id=iid,reason='UNVERIFIED_OR_NON_SUBSTANTIVE_EVIDENCE'))
                    continue
                value = row['confidence_raw_score']
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
                    raise ValueError('Confianza guardada invalida')
                codes=resolve_codes(p,assessment)
                try:consumer=indicator_record(p,iid,row=row,locations=locations,territory_codes=codes)
                except (ValueError,KeyError,TypeError) as exc:
                    if output_contract in (ALL_CONTRACT,VALID_CONTRACT):raise
                    export_exclusions.append(dict(siap_id=p['siap_id'],indicator_id=iid,reason=str(exc)))
                    continue
                record=[consumer[c] for c in COLUMNS]
                pair = (record[0], record[1])
                previous = next((r for r in rows if (r[0], r[1]) == pair), None)
                if previous and (previous != record or csv_records[pair]['estado_cumplimiento'] != row['decision']):
                    raise ValueError('Resultados contradictorios entre lotes')
                if not previous:
                    rows.append(record)
                    csv_records[pair] = consumer
                    codes_by_pair[pair] = codes
                    context=plan.get('context_requests',{}).get(p['project_id'],{}).get(iid,{}).get('context_selection',{})
                    lineage.append(dict(siap_id=p['siap_id'], indicator_id=iid, batch=directory.name, evidence=locations,
                        raw_fields={e['field']: p['field_provenance'][e['field']]['raw_sources'] for e in locations},
                        context_status=context.get('status'),evidence_limited=context.get('evidence_limited'),
                        **({'truncation':context['truncation']} if 'truncation' in context else {})))
    # Prepared batches may not yet have run when a cooperative interruption occurs.
    covered={(c['siap_id'],c['indicator_id']) for c in coverage}
    for pid in sorted(target_projects):
        for iid in sorted(indicator_ids):
            if (pid,iid) not in covered:
                coverage.append(dict(siap_id=pid,indicator_id=iid,status='PENDING',decision=None,project_complete=False))
    if output_contract==ALL_CONTRACT:
        for item in coverage:
            pair=item['siap_id'],item['indicator_id']
            if item['status']=='VALID':continue
            if pair in csv_records:raise ValueError('Estado contradictorio entre lotes')
            consumer=indicator_record(dict(siap_id=pair[0]),pair[1],status=item['status'])
            csv_records[pair]=consumer;rows.append([consumer[c] for c in COLUMNS])
        if len({(c['siap_id'],c['indicator_id']) for c in coverage})!=len(coverage):
            raise ValueError('Cobertura duplicada entre lotes')
    rows.sort(key=lambda r: (r[0], r[1]))
    if any(isinstance(c, str) and (len(c) > 32767 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', c)) for r in rows for c in r):
        raise ValueError('Texto no representable en Excel; no se trunca evidencia')
    output = run_file(run, 'resultado_indicadores.xlsx')
    render_thesis(root,output,[csv_records[(r[0],r[1])] for r in rows],contract=output_contract)
    csv_result = write_results(run, consumer_columns,
                               [csv_records[(r[0], r[1])] for r in rows], codes_by_pair)
    coverage_path=run/'resultados/estado_indicadores.json'
    write(coverage_path,dict(status='COMPLETE' if target_projects==complete_projects else 'PARTIAL',
        note='VALID identifica evaluaciones verificadas; los demas estados no son evaluaciones completas.',indicators=coverage))
    valid_path=run/'resultados/evaluaciones_validas.json'
    write(valid_path,dict(status='COMPLETE' if target_projects==complete_projects else 'PARTIAL',assessments=valid_results))
    result = dict(status='COMPLETE' if target_projects == complete_projects and not errors and not export_exclusions else 'PARTIAL', excel=str(output),
        preprocessed_projects=len(all_projects), scoped_projects=len(target_projects), pending_projects=sorted(target_projects - processed), errors=errors,
        selected_projects=len(target_projects), processed_projects=len(processed), completed_projects=len(complete_projects), represented_projects=len({r[0] for r in rows}),
        relationships=len(rows), territories=0, excel_sha256=sha(output), power_bi_desktop_tested=False)
    result['csv'] = csv_result
    if request.get('evaluation_policy'):result['evaluation_policy']=request['evaluation_policy']
    result.update(output_contract=output_contract,sheets=SHEETS,columns=consumer_columns,
        template=TEMPLATE.as_posix(),template_sha256=sha(root/TEMPLATE),positive_results_only=output_contract==POSITIVE_CONTRACT)
    result['indicator_statuses']=str(coverage_path)
    result['valid_results']=str(valid_path)
    result['valid_assessments']=sum(c['status']=='VALID' for c in coverage)
    result['blocked_indicators']=[c for c in coverage if c['status'] not in ('VALID','PENDING')]
    result.update(expected_assessments=len(coverage),
        supported=sum(c['decision']=='SUPPORTED' for c in coverage),
        insufficient_evidence=sum(c['decision']=='INSUFFICIENT_EVIDENCE' for c in coverage),
        not_supported=sum(c['decision']=='NOT_SUPPORTED' for c in coverage),
        blocked_assessments=len(result['blocked_indicators']),
        pending_assessments=sum(c['status']=='PENDING' for c in coverage),
        exported_rows=len(rows),export_exclusions=export_exclusions,
        processing_complete=target_projects==processed,results_available=bool(valid_results))
    result['note'] = ('Excel vacio: no hay evaluaciones SUPPORTED; los resultados insuficientes y los errores se conservan en los registros internos.'
        if not result['supported'] else 'Excel vacio: ningun SUPPORTED supero los controles de exportacion; consultar export_exclusions.' if not rows
        else 'Se exportaron todos los positivos verificados, incluidos los de proyectos incompletos.')
    if output_contract==ALL_CONTRACT:result['note']='Cobertura de todos los indicadores seleccionados; decisiones y confianzas originales.'
    if output_contract==VALID_CONTRACT:result['note']='Evaluaciones validas, incluidas confianzas bajas y cero; errores y limites de recuperacion solo en auditoria.'
    if result['status']!='COMPLETE':result['note']+=' Cobertura PARTIAL; consultar indicadores bloqueados y pendientes.'
    write(run_file(run, 'export.json'), result)
    write(run_file(run, 'evidence_lineage.json'), lineage)
    complete=sorted(complete_projects)
    partial=sorted(evaluated_projects-complete_projects)
    blocked=sorted((set(request.get('blocked_projects',{}))|blocked_results)-complete_projects-set(partial))
    write(run_file(run, 'runtime.manifest.json'),dict(run_id=run.name,provider=request.get('llm',{}).get('provider','ollama'),
        **({'evaluation_policy':request['evaluation_policy']} if request.get('evaluation_policy') else {}),
        model=request.get('llm',{}).get('model'),evaluation_contract=request.get('evaluation_contract'),
        project_states=dict(complete=complete,partial=partial,blocked=blocked,
            pending=sorted(target_projects-set(complete)-set(partial)-set(blocked)))))
    from run_storage import archive_export
    return archive_export(root,run,result)


STAGES = ('preprocessing', 'knowledge', 'graphrag', 'evaluation', 'export')


def find_run(root, runs, name):
    from run_paths import find_run as resolve_run
    return resolve_run(root,runs,name)


def selected_configuration(root, config_path, source=None, input_file=None, delivery=None):
    config, raw, runs = configuration(root, config_path)
    if sum(value is not None for value in (source, input_file, delivery)) > 1:
        raise ValueError('Elegir --source, --file o --delivery; no combinarlos')
    if input_file is not None or delivery is not None:
        from layer2_processing.preprocessing.adapters import source_files
        intake = (root / 'data/layer1_sources').resolve()
        value = input_file if input_file is not None else delivery
        if not str(value).strip():
            raise ValueError('Archivo o entrega vacios')
        candidate = Path(value)
        if not candidate.is_absolute():
            if candidate.parts[:2] == ('data', 'layer1_sources'):
                candidate = root / candidate
            elif delivery is not None and candidate.parts[0] != 'incoming':
                candidate = intake / 'incoming' / candidate
            else:
                candidate = intake / candidate
        target = candidate.resolve()
        if candidate.is_symlink() or not any(target.is_relative_to(intake / base) for base in ('base', 'incoming')):
            raise ValueError('Seleccionar originales dentro de base o incoming')
        if delivery is not None and (not target.is_relative_to(intake / 'incoming') or target == intake / 'incoming' or not target.is_dir()):
            raise ValueError('--delivery requiere una entrega existente dentro de incoming')
        if input_file is not None and not target.is_file():
            raise ValueError('--file requiere un archivo existente')
        primary = [target] if input_file is not None else source_files(target)
        if not primary:
            raise ValueError('Entrega sin archivos para procesar')
        config['selected_input_paths'] = sorted(p.relative_to(intake).as_posix() for p in primary)
        config['source_paths'] = list(config['selected_input_paths'])
        # Definitions of indicators are supplied separately by prepare_files.
        # Independent inputs never gain documentary evidence from the base.
        config['documentary_source_policy'] = 'SELECTED_ONLY_V1'
        config['raw_base'] = intake.relative_to(root).as_posix()
        config.pop('source_prefix', None)
        raw = intake
    if source is not None:
        intake = root / 'data/layer1_sources'
        if source == 'all':
            raw = intake
        else:
            raw = within(intake, source)
            if source not in ('base', 'incoming') and not raw.is_relative_to(intake / 'incoming'):
                raise ValueError('Seleccionar all, base, incoming o incoming/<entrega>')
        config['raw_base'] = raw.relative_to(root).as_posix()
        if source=='base':config['knowledge_scope']='BASE_GLOBAL_V1'
    if not raw.is_dir():
        raise ValueError('Carpeta de fuentes inexistente: ' + str(raw))
    prefix = raw.relative_to(root / 'data/layer1_sources').as_posix()
    if prefix != '.':
        config['source_prefix'] = prefix + '/'
    return config, raw, runs


@timed('preparacion')
def verify_sources(root, config_path='config/pipeline_manual.json', source=None, input_file=None, delivery=None):
    """Read-only intake/configuration inspection. No model or provider calls."""
    from layer2_processing.preprocessing.adapters import discover_sources
    config, raw, _ = selected_configuration(root, config_path, source, input_file, delivery)
    from layer4_evaluation.indicators.ollama_provider import configuration as llm_configuration
    llm = llm_configuration(config.get('llm'))
    preview = discover_sources(root, config, raw)
    missing = []
    for path in (config['reference_catalog'], 'config/layer1.yaml', 'config/layer2.yaml', 'config/layer3.yaml'):
        if not within(root, path).is_file():
            missing.append(path)
    for number in (2, 3, 4):
        path = layer_config(root, number)
        if path.is_file():
            from layer2_processing.preprocessing.runtime import read_config
            read_config(path)
    return dict(status=preview['status'] if not missing else 'BLOCKED',
                discovery_status=preview['status'], source=str(raw), missing=missing, llm=llm,
                files=[{k: v for k, v in item.items() if k != 'records'} for item in preview['files']],
                note='Verificacion estructural; identidad, modelos, proveedor y publicaciones se validan en sus etapas')


def execution_status(root, config_path='config/pipeline_manual.json', run_id=None):
    _, _, runs = configuration(root, config_path)
    if not run_id:
        entries = {}
        from run_paths import list_runs
        for location in list_runs(root,runs):
            path=run_file(location,'run.json')
            if path.exists():
                state = read(path)
                entries[str(location)] = dict(run_id=location.name, checkpoint=state.get('status','UNKNOWN'),
                    location=str(location), progress=read(run_file(location,'progress.json')) if run_file(location,'progress.json').exists() else None)
        return dict(status='INVENTORY', runs=list(entries.values()), note='Listado; usar status --run-id para verificar integridad')
    run = find_run(root, runs, run_id)
    initial = read(run_file(run, 'run.json')) if run_file(run, 'run.json').exists() else {}
    if initial.get('status') in ('REGISTERED','PREPARING','FAILED'):
        progress = read(run_file(run, 'progress.json'))
        return dict(status=progress['status'], run_id=run.name, location=str(run),
            checkpoint=initial['status'], checkpoint_available=False, progress=progress,
            execution=read(run_file(run, 'execution.json')),
            failure=read(run_file(run, 'failure.json')) if run_file(run, 'failure.json').exists() else None)
    state = check(root, run)
    stages = dict(preprocessing='VERIFIED', knowledge='VERIFIED' if state['status'] == 'PREPARED' else 'PENDING',
                  graphrag='PENDING', evaluation='PENDING', export='PENDING')
    batches = {}
    publication = knowledge_workspace(run) / 'outputs/layer3/publication/_manifest.json'
    if publication.exists():
        validated_graph(root, run)
        stages['graphrag'] = 'VERIFIED'
        module = engine(root, run)
        for directory in sorted(module.BASE.glob('batch_*')):
            verified = module.verify_run(directory)
            batches[directory.name] = module.summary(verified)
        if batches:
            stages['evaluation'] = 'VERIFIED_SELECTED_BATCHES' if all(b['status'] == 'COMPLETE' for b in batches.values()) else 'PARTIAL_OR_BLOCKED'
    if (run_file(run, 'export.json')).exists():
        saved = read(run_file(run, 'export.json'))
        if sha(run_file(run, 'resultado_indicadores.xlsx')) != saved['excel_sha256']:
            raise ValueError('Excel publicado modificado')
        stages['export'] = saved['status'] + '_HASH_VERIFIED'
    knowledge = dict(storage='SHARED_REFERENCE', reference=state['knowledge_ref'], location=str(knowledge_workspace(run).parent)) \
        if state.get('knowledge_ref') else dict(storage='RUN_LOCAL_COPY' if state.get('global_reuse') else 'RUN_LOCAL_BUILD',
            source_run=state.get('global_reuse', {}).get('source_run'))
    return dict(status='VERIFIED', run_id=run.name, location=str(run), stages=stages, evaluations=batches, knowledge=knowledge,
                sources=state['raw_path'], progress=read(run_file(run, 'progress.json')) if (run_file(run, 'progress.json')).exists() else None,
                limitations=['Evaluacion actual: PROJECT; ARTICLE pendiente', 'Exportador actual: sin puente territorial nuevo verificado'])


def scope_projects(root, run, selection, requested=None):
    """Scope results using canonical identities and explicit field provenance only."""
    folder = knowledge_workspace(run) / 'outputs/layer2/canonical'
    rows = pq.read_table(folder / 'proyectos.parquet').to_pylist()
    selected = [row['source_project_id'] for row in rows]
    if selection['mode'] in ('file', 'delivery'):
        from layer2_processing.checkpoints import resolve
        files = {resolve(root, 'data/layer1_sources/' + name).resolve() for name in selection['files']}
        def originates(row):
            refs = json.loads(row.get('provenance_json', '[]'))
            return any(resolve(root, ref['record_source']).resolve() in files for ref in refs)
        matched = {row['project_id'] for row in rows if originates(row)}
        membership = folder / 'proyecto_investigador.parquet'
        if membership.is_file():
            matched.update(row['project_id'] for row in pq.read_table(membership).to_pylist() if originates(row))
        selected = [row['source_project_id'] for row in rows if row['project_id'] in matched]
    if requested is not None:
        missing = set(requested) - set(selected)
        if missing:
            raise ValueError('Proyectos no presentes en las fuentes seleccionadas: ' + ', '.join(sorted(missing)))
        return list(requested)
    if not selected:
        raise ValueError('Seleccion sin PROJECT o relaciones institucionales explicitas con proyectos. ARTICLE no tiene evaluacion implementada; no se inventan asociaciones')
    return selected


def review_summary(module, directory):
    plan = module.check(directory)
    return dict(review=str(directory / 'review.txt'),
                projects=[p['siap_id'] for p in plan['projects']], indicators=len(plan['profiles']),
                llm=plan.get('runtime', {}), maximum_calls=plan['maximum_calls'],
                review_sha256=sha(directory / 'review.txt'),
                note='Revisar review.txt y autorizar solo estos textos. No se muestran textos institucionales en consola.')


def execution_approval(root, run, config, metadata, model_binding, target, confirm):
    """One exact approval for new execution and identical resumptions, before work."""
    import getpass
    from layer2_processing.pipeline import code_hashes
    from layer2_processing.preprocessing.project_selection import digest
    scope = dict(version='RUN_APPROVAL_V1',run_id=run.name,project_ids=metadata['project_ids'],
        sources=metadata['sources'],llm=model_binding['llm'],contract=model_binding.get('contract'),
        configuration={k:v for k,v in config.items() if k not in ('processing_scope','project_selection')},
        code_and_configuration=code_hashes(root),through=target)
    path=run/'estado/run.authorization.json'
    fingerprint=digest(scope)
    if path.exists():
        saved=read(path)
        if saved.get('authorized') is True and saved.get('scope_sha256')==fingerprint and digest(saved['scope'])==fingerprint:
            verify_execution_approval(root,saved)
            return saved
    llm=scope['llm'];external=llm['provider']=='openai'
    summary=dict(run_id=run.name,provider=llm['provider'],model=llm['model'],project_count=len(scope['project_ids']),
        evaluation_policy=config.get('evaluation_policy'),num_ctx=llm.get('num_ctx'),
        project_ids=list(scope['project_ids']),
        sources=list(scope['sources']),contract=scope['contract'],stages=list(STAGES[:STAGES.index(target)+1]),
        destination='OpenAI API: '+llm.get('api',{}).get('base_url','https://api.openai.com/v1') if external else llm.get('endpoint'),
        budget_usd=llm.get('api',{}).get('budget_usd') if external else None,
        privacy='Autoriza transmitir los textos seleccionados a OpenAI y su presupuesto.' if external else
            'Autoriza ETL, embeddings locales y evaluacion completa de los textos seleccionados mediante Ollama.',
        indicators_per_project=48,through=target,scope_sha256=fingerprint,
        note='Una autorizacion para todo el alcance. Se conservan revisiones, registros por lote y checkpoints.')
    if confirm is None or confirm('run',summary) is not True:return None
    result=dict(authorized=True,scope=scope,scope_sha256=fingerprint,
        authorized_at=datetime.now(timezone.utc).isoformat(),authorized_by=getpass.getuser())
    verify_execution_approval(root,result)
    return result


def verify_execution_approval(root, approval):
    from layer2_processing.preprocessing.project_selection import digest
    scope=approval['scope']
    if approval.get('authorized') is not True or digest(scope)!=approval['scope_sha256']:
        raise ValueError('Autorizacion de ejecucion corrupta; se requiere nueva revision')
    for name,expected in (scope['sources'] | scope['code_and_configuration']).items():
        if sha(root/name)!=expected:
            raise ValueError('Alcance autorizado modificado: '+name+'; detener y revisar antes de autorizar otra ejecucion')


@measured_pipeline
def execute_pipeline(root, *, config_path='config/pipeline_manual.json', source=None, run_id=None,
                     stage=None, through=None, resume=False, approve_build=False, authorize=False,
                     project_ids=None, notify=None, dataset=None, input_file=None, delivery=None, confirm=None,
                     limit=None, all_projects=False, seed=42, dry_run=False, selection_manifest=None,confirm_all=False,
                     single_authorization=False,evaluation_mode=None,context_mode=None,knowledge_action=None,
                     indicator_ids=None):
    """Central reusable orchestration API. Layer checkpoints remain authoritative."""
    root = Path(root).resolve()
    sampling = limit is not None or all_projects or selection_manifest is not None
    if sampling or dry_run:
        if resume or stage or dataset or (sampling and project_ids is not None):
            raise ValueError('Muestreo/dry-run requiere una ejecucion nueva por fuente, sin otros selectores; reanudar conserva los IDs')
        from layer2_processing.preprocessing.project_selection import select
        sampled_source = source or ('base' if input_file is None and delivery is None else None)
        chosen_config, chosen_raw, _ = selected_configuration(root, config_path, sampled_source, input_file, delivery)
        metadata = select(root, chosen_raw, chosen_config, limit=limit, all_projects=all_projects,
                          seed=seed, project_ids=project_ids,
                          replay=within(root, selection_manifest) if selection_manifest else None)
        source = sampled_source
        project_ids = metadata['project_ids']
        if all_projects and not dry_run:
            from evaluation_contracts import evaluable_features
            from model_access import label
            from experiment_runtime import options
            eligible=evaluable_features(root,chosen_raw,chosen_config,metadata['project_features'])
            excluded=[pid for pid in project_ids if pid not in eligible]
            summary=dict(model=label(root,options.get().get('provider')),total_projects=len(project_ids),
                evaluable_projects=len(eligible),blocked_projects=len(excluded),blocked_project_ids=excluded,
                reason='NO_AUTHORIZED_SUBSTANTIVE_TEXT',results='outputs/runs/<proveedor>/<run_id>/resultados',
                history='outputs/historico/<proveedor>/<run_id>',budget_usd=options.get().get('budget_usd'),
                warning='Toda la base puede tardar horas o dias. OpenAI puede generar costos; se conserva su proteccion presupuestaria. No se evaluan proyectos sin texto autorizado.')
            metadata['eligibility_summary']=summary
            if notify:notify(dict(status='ALL_PROJECTS_REVIEW',stage='selection',location=str(chosen_raw),summary=summary))
            if not single_authorization and not confirm_all and (confirm is None or confirm('all',summary) is not True):
                return dict(status='REVIEW_REQUIRED',summary=summary,inference_calls=0,
                    next_step='Confirmar expresamente toda la base; CLI no interactiva requiere --confirm-all. No se inicio procesamiento.')
        if dry_run:
            through = 'preprocessing'
    if project_ids is not None and (not project_ids or any(not isinstance(p, str) or not p.strip() for p in project_ids) or len(project_ids) != len(set(project_ids))):
        raise ValueError('Seleccionar identificadores institucionales unicos y no vacios')
    if project_ids is not None and delivery is not None and not sampling:
        raise ValueError('Elegir proyectos o entrega como modalidad de seleccion; --file admite --projects')
    if dataset is not None and dataset not in ('prueba_controlada', 'prueba_en_vivo'):
        raise ValueError('Conjunto de pruebas desconocido')
    if stage is not None and stage not in STAGES or through is not None and through not in STAGES:
        raise ValueError('Etapa desconocida')
    active_config, _, runs = configuration(root, config_path)
    observe_projects(project_ids,active_config.get('llm',{}).get('model',''))
    if resume and not run_id:
        raise ValueError('Reanudar requiere --run-id')
    name = run_id or ('run_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    run = find_run(root, runs, name)
    from layer4_evaluation.indicators import assessment_v3 as v3
    stored_request=read(run_file(run,'execution.json')) if run_file(run,'execution.json').exists() else None
    stored_state=read(run_file(run,'run.json')) if run_file(run,'run.json').exists() else None
    if knowledge_action not in (None,'reuse','rebuild'):raise ValueError('Opcion de conocimiento BASE invalida')
    if stored_state and knowledge_action is not None and knowledge_action!=stored_state.get('configuration',{}).get('base_knowledge_action'):
        raise ValueError('Resume conserva el conocimiento y la opcion originales; crear otro run')
    frozen=(stored_request or {}).get('evaluation_policy',(stored_state or {}).get('configuration',{}).get('evaluation_policy',{}))
    policy=v3.evaluation_policy(evaluation_mode,context_mode,
        base=source=='base' or (source is None and input_file is None and delivery is None and (project_ids is not None or sampling)),
        configured=active_config.get('evaluation'),saved=frozen if stored_request is not None or stored_state is not None else None)
    if policy:
        active_config['evaluation_policy']=policy
        if policy['context_mode'] in (v3.FULL_CONTEXT,v3.BASE_CONTEXT):
            active_config['llm']=dict(active_config.get('llm',{}),num_ctx=24576)
        elif policy['context_mode']==v3.RETRIEVED_CONTEXT:
            active_config['llm']=dict(active_config.get('llm',{}),num_ctx=16384,context_margin_tokens=1024)
    from experiment_runtime import binding
    model_binding = binding(root, run, active_config.get('llm'),evaluation=policy)
    active_config = dict(active_config, llm=model_binding['llm'])
    current = None
    approval = None
    evaluation_report={}
    target = stage or through or 'export'
    def quoted(value):
        return "'" + str(value).replace("'", "''") + "'"
    config_argument = ' --config ' + quoted(config_path) if config_path != 'config/pipeline_manual.json' else ''
    restart = 'uv run python run.py run' + config_argument
    if input_file is not None:
        restart += ' --file ' + quoted(input_file)
    elif delivery is not None:
        restart += ' --delivery ' + quoted(delivery)
    else:
        if source is not None:
            restart += ' --source ' + quoted(source)
    if project_ids:
        restart += ' --projects ' + quoted(','.join(project_ids))

    def progress(status, **detail):
        checkpoint = False
        if (run_file(run, 'run.json')).exists():
            try:
                checkpoint = read(run_file(run, 'run.json'))['status'] in ('PREPROCESSED', 'PREPARED')
            except (ValueError, KeyError):
                pass
        value = dict(status=status, run_id=name, location=str(run), stage=current,
                     updated_at=datetime.now(timezone.utc).isoformat(),
                     resume_command=('uv run python run.py resume --run-id ' + name + config_argument if run.is_dir() else restart) + ' --through ' + target,
                     checkpoint_available=checkpoint, **detail)
        if run.is_dir():
            write(run_file(run, 'progress.json'), value)
        if notify:
            notify(value)
        return value

    with lock(runs):
        if run.exists() and not resume and not stage:
            raise ValueError('Run ID ya existe; usar resume --run-id ' + name + ' o elegir otro ID')
        if resume and not run.exists():
            raise ValueError('Run no encontrado: ' + name)
        try:
            from run_storage import reopen
            reopen(run)
            if resume:(run_file(run, 'stop.request.json')).unlink(missing_ok=True)
            previous_request = read(run_file(run, 'execution.json')) if (run_file(run, 'execution.json')).exists() else {}
            initial = read(run_file(run, 'run.json')) if run_file(run, 'run.json').exists() else {}
            registered = initial.get('status') == 'REGISTERED'
            if (resume or initial) and not registered:
                state = check(root, run)
                if dataset is not None and dataset != state['dataset']:
                    raise ValueError('Conjunto de pruebas distinto del checkpoint')
                config = state['configuration']
                from layer2_processing.checkpoints import resolve
                raw = resolve(root, state['raw_path'])
                if any(value is not None for value in (source, input_file, delivery)):
                    selected, selected_raw, _ = selected_configuration(root, config_path, source, input_file, delivery)
                    if 'processing_scope' in config:
                        selected['processing_scope']=config['processing_scope']
                    # Data settings stay frozen; LLM changes get their own review
                    # and pre-dispatch compatibility checks in prepare_evaluation.
                    selected_data = {k:v for k,v in selected.items() if k != 'llm'}
                    if policy:selected_data['evaluation_policy']=policy
                    stored_data = {k:v for k,v in config.items() if k != 'llm'}
                    for key in ('base_knowledge_action','base_knowledge_source'):
                        if key in stored_data:selected_data[key]=stored_data[key]
                    if selected_raw.resolve() != raw.resolve() or not same_configuration(root, selected_data, stored_data):
                        raise ValueError('Fuentes/configuracion distintas; crear una ejecucion nueva')
                dataset = state['dataset']
            else:
                if stage and stage != 'preprocessing':
                    raise ValueError('La etapa requiere un checkpoint previo y --run-id')
                if registered:
                    if project_ids is not None and project_ids != previous_request['project_ids']:
                        raise ValueError('Seleccion de proyectos distinta; reanudar los IDs registrados')
                    project_ids = previous_request['project_ids']
                    if not any(value is not None for value in (source,input_file,delivery)):
                        source = previous_request.get('source')
                        input_file = previous_request.get('input_file')
                        delivery = previous_request.get('delivery')
                    dataset = initial['dataset']
                # Registration precedes source discovery and selection validation.
                # REGISTERED is not an ETL checkpoint and is safe to retry on resume.
                if dataset is None and project_ids is not None and source is None and input_file is None and delivery is None:
                    source = 'base'
                if dataset is not None and dataset != 'raw':
                    config, _, runs = configuration(root, config_path)
                    raw = root / 'tests/fixtures' / dataset
                else:
                    config, raw, runs = selected_configuration(root, config_path, source, input_file, delivery)
                if policy:config['evaluation_policy']=policy
                if config.get('knowledge_scope')=='BASE_GLOBAL_V1' and not dry_run:
                    config['base_knowledge_action']=(initial.get('configuration',{}).get('base_knowledge_action','reuse') if registered else knowledge_action or 'reuse')
                    if registered and initial.get('configuration',{}).get('base_knowledge_source'):
                        config['base_knowledge_source']=initial['configuration']['base_knowledge_source']
                if registered and (initial['raw_path'] != raw.relative_to(root).as_posix() or
                        not same_configuration(root,initial['configuration'],dict(config,llm=model_binding['llm']))):
                    raise ValueError('Fuentes/configuracion distintas del registro inicial')
                if not registered:
                    if single_authorization and not dry_run:
                        from layer2_processing.preprocessing.project_selection import select
                        approval_metadata = metadata if sampling else select(root,raw,config,seed=seed,
                            project_ids=project_ids,all_projects=project_ids is None)
                        approval=execution_approval(root,run,dict(config,llm=model_binding['llm']),
                            approval_metadata,model_binding,target,confirm)
                        if approval is None:return dict(status='CANCELLED',inference_calls=0,run_id=name)
                    run.mkdir(parents=True, exist_ok=False)
                    write(run_file(run,'model.binding.json'), model_binding)
                    write(run_file(run,'execution.json'), dict(through=target, project_ids=project_ids,
                        llm=model_binding['llm'], evaluation_contract=model_binding.get('contract'),
                        **({'evaluation_policy':policy} if policy else {}),
                        source=source,input_file=input_file,delivery=delivery,
                        **({'indicator_ids':list(indicator_ids)} if indicator_ids is not None else {})))
                    write(run_file(run,'run.json'), dict(status='REGISTERED',run_id=name,dataset=dataset or 'raw',
                        raw_path=raw.relative_to(root).as_posix(),configuration=dict(config,llm=model_binding['llm']),
                        started_at=datetime.now(timezone.utc).isoformat()))
                    if approval:write(run/'estado/run.authorization.json',approval)
                current = 'preparation'
                progress('REGISTERED', message='Run registrado; validando fuentes y dependencias antes del ETL')
                from layer4_evaluation.indicators.performance import activate_run_measurement
                activate_run_measurement()
                if dataset is not None and dataset != 'raw':
                    from layer2_processing.preprocessing.adapters import discover_sources
                    preview = discover_sources(root, config, raw)
                    preview['discovery_status'] = preview['status']
                else:
                    preview = verify_sources(root, config_path, source, input_file, delivery)
                dataset = dataset or 'raw'
            target = stage or through or previous_request.get('through', 'export')
            saved_ids = previous_request.get('project_ids')
            if saved_ids is not None and project_ids is not None and project_ids != saved_ids:
                raise ValueError('Seleccion de proyectos distinta; reanudar los lotes originales')
            project_ids = saved_ids if project_ids is None else project_ids
            # Optional indicator subset: frozen like the project selection.
            if indicator_ids is not None and (not indicator_ids or len(indicator_ids)!=len(set(indicator_ids))
                    or any(not isinstance(i,str) or not i.strip() for i in indicator_ids)):
                raise ValueError('Seleccion de indicadores vacia o duplicada')
            saved_indicators = previous_request.get('indicator_ids')
            if (resume or previous_request) and indicator_ids is not None and indicator_ids != saved_indicators:
                raise ValueError('Seleccion de indicadores distinta; reanudar con la seleccion original o crear otro run')
            indicator_ids = saved_indicators if indicator_ids is None else indicator_ids
            selection = previous_request.get('selection') or dict(
                mode='file' if input_file is not None else 'delivery' if delivery is not None else 'projects' if project_ids is not None else 'source',
                files=config.get('selected_input_paths', []))
            if selection['mode'] in ('file', 'delivery') and (
                    not selection['files'] or set(config.get('source_paths', [])) != set(selection['files'])):
                raise ValueError('Checkpoint con fuentes externas a la seleccion independiente; conservarlo y crear otra ejecucion con --file o --delivery')
            if previous_request.get('selection') and project_ids is not None and (input_file is not None or delivery is not None):
                # Saved project IDs are the canonical resolution of the same file/delivery.
                if selection['mode'] not in ('file', 'delivery'):
                    raise ValueError('Modalidad distinta de la ejecucion original')
            request = dict(through=target, project_ids=project_ids, selection=selection,
                llm=model_binding['llm'], evaluation_contract=model_binding.get('contract'),
                **({'evaluation_policy':policy} if policy else {}),
                source=source,input_file=input_file,delivery=delivery,
                **({'indicator_ids':list(indicator_ids)} if indicator_ids is not None else {}))
            config['llm'] = model_binding['llm']
            if single_authorization and not dry_run and approval is None:
                from layer2_processing.preprocessing.project_selection import select
                approval_metadata=config.get('project_selection') or select(root,raw,config,seed=seed,
                    project_ids=project_ids,all_projects=project_ids is None)
                approval=execution_approval(root,run,config,approval_metadata,model_binding,target,confirm)
                if approval is None:return progress('REVIEW_REQUIRED',message='Autorizar el alcance completo antes de continuar')
                write(run/'estado/run.authorization.json',approval)
                from layer4_evaluation.indicators.performance import activate_run_measurement
                activate_run_measurement()
            if model_binding['llm']['provider']=='openai' and target in ('evaluation','export'):
                from model_access import api_key
                if not api_key(root):raise ValueError('API_KEY_MISSING: configurar clave antes de ejecutar API')
            prepared = read(run_file(run,'run.json')).get('status') != 'REGISTERED'
            if not prepared and (project_ids is not None or selection['mode'] in ('file','delivery')):
                config['processing_scope']=dict(mode=selection['mode'],project_ids=project_ids,
                    primary_files=config.get('selected_input_paths',[]))
                if model_binding.get('contract') and not (sampling or dry_run):
                    from layer2_processing.preprocessing.project_selection import select
                    metadata=select(root,raw,config,project_ids=project_ids,seed=model_binding['contract'].get('seed',42))
                    # Revalidate after the menu's confirmation, against fresh source
                    # fingerprints, without changing the frozen IDs or resampling.
                    from evaluation_contracts import load, catalog_hash
                    from autonomous_execution.lifecycle import safe_id
                    contract = model_binding['contract']
                    safe_id(contract['contract_id'])
                    value = load(root/'data/contratos'/f"{contract['contract_id']}.v{int(contract['version'])}.json")
                    if (value['sha256'] != contract['sha256'] or
                            value['project_ids'] != contract['mandatory_project_ids'] or
                            contract['mandatory_project_ids'] + contract['additional_project_ids'] != project_ids or
                            contract['sources'] != metadata['sources'] or
                            contract['catalog_sha256'] != catalog_hash(root)):
                        raise ValueError('Contrato, fuentes o catalogo cambiaron tras la seleccion; no se inicia el procesamiento')
                if sampling or dry_run or model_binding.get('contract'):
                    config['project_selection'] = metadata
                if config.get('knowledge_scope')=='BASE_GLOBAL_V1':
                    config.pop('processing_scope',None)
            if not prepared and config.get('base_knowledge_action')=='reuse':
                # Registry of shared versions, not a scan of historical runs.
                candidate=processing.reuse_global_base(root,run,raw,config,dataset,probe=True,require_graph=True)
                if not candidate:
                    reason=getattr(processing.reuse_global_base,'last_reason',None)
                    message=('No hay conocimiento global BASE compatible en outputs/shared/base (fuentes, contratos, embeddings o grafo)'
                        +(f': {reason}' if reason else '')+'. Puede reconstruir con --knowledge-action rebuild.')
                    if confirm is None or confirm('knowledge_rebuild',dict(message=message)) is not True:
                        return progress('KNOWLEDGE_REBUILD_REQUIRED',message=message)
                    config['base_knowledge_action']='rebuild'
                else:config['base_knowledge_source']=candidate
                # Persist the chosen immutable source before any expensive stage.
                registered_state=read(run_file(run,'run.json'))
                registered_state['configuration']=config
                write(run_file(run,'run.json'),registered_state)
            request['base_knowledge_action']=config.get('base_knowledge_action')
            request['base_knowledge_source']=config.get('base_knowledge_source')
            sequence = [stage] if stage else list(STAGES[:STAGES.index(target) + 1])
            if not prepared:
                files = preview.get('files', [])
                primary = set(config.get('selected_input_paths', [item['file'] for item in files]))
                summary = dict(
                    mode=selection['mode'], selected_files=[item['file'] for item in files if item['file'] in primary],
                    supporting_files=[item['file'] for item in files if item['file'] not in primary],
                    input_rows=sum(item.get('record_count', 0) for item in files if item['file'] in primary),
                    records_by_domain={domain:sum(item.get('record_count', 0) for item in files if item['file'] in primary and item.get('domain') == domain)
                        for domain in sorted({item.get('domain', 'pending') for item in files if item['file'] in primary})},
                    requested_projects=project_ids, stages=sequence,
                    note=('Conocimiento global BASE; la seleccion limita solo evaluacion/Excel. Relaciones con procedencia canonica; articulos no evaluados.' if config.get('knowledge_scope')=='BASE_GLOBAL_V1' else 'ETL acotado: preprocess/scope.json. Evaluacion/Excel solo incluyen la seleccion. ARTICLE no evaluado; TERRITORIOS sin filas verificadas.'))
                request['input_summary'] = summary
                progress('INPUT_SUMMARY', summary=summary)
                if preview['status'] != 'READY_FOR_VALIDATION' or preview['discovery_status'] != 'READY_FOR_VALIDATION':
                    details = '; '.join(item['file']+': '+'; '.join(str(d) for d in item.get('diagnostics', []))
                                        for item in preview.get('files', []) if item['status'] != 'READY_FOR_VALIDATION')
                    raise ValueError('Fuentes pendientes/invalidas: '+details)
            else:
                summary = dict(previous_request.get('input_summary', {}), stages=sequence, resumed=True,
                               project_count=len(project_ids) if project_ids is not None else None)
                if not summary.get('selected_files'):
                    summary.update(selected_files=config.get('selected_input_paths', config.get('source_paths', [])),
                        canonical_counts=state.get('counts'),
                        note='Checkpoint verificado; las fuentes/IDs originales se conservan. ARTICLE y territorios por ejecucion mantienen sus limitaciones.')
                request['input_summary'] = summary
                progress('INPUT_SUMMARY', summary=summary)
            for current in sequence:
                if approval:verify_execution_approval(root,approval)
                if run_file(run,'stop.request.json').exists():
                    return progress('INTERRUPTED',message='Detencion solicitada; checkpoints conservados')
                current_state=read(run_file(run,'run.json'))
                reused=current_state.get('global_reuse',{})
                if current in ('knowledge','graphrag') and (current_state.get('knowledge_ref') or
                        reused and (current=='knowledge' or reused.get('graph_reused'))):
                    if current=='graphrag':validated_graph(root,run)
                    progress('STAGE_REUSED')
                    continue
                if resume and not registered and ((current=='preprocessing' and state['status'] in ('PREPROCESSED','PREPARED')) or
                        (current=='knowledge' and state['status']=='PREPARED')):
                    progress('STAGE_REUSED')
                    continue
                if resume and current=='graphrag' and (knowledge_workspace(run)/'outputs/layer3/publication/_manifest.json').exists():
                    validated_graph(root,run)
                    register_built_knowledge(root,run,request)  # Idempotent: completes an interrupted activation.
                    progress('STAGE_REUSED')
                    continue
                # Persist the requested target before a resumable stage can fail.
                if run.is_dir():
                    if not (run_file(run, 'model.binding.json')).exists():write(run_file(run, 'model.binding.json'), model_binding)
                    write(run_file(run, 'execution.json'), request)
                progress('RUNNING')
                if (current in ('knowledge', 'graphrag', 'evaluation') and (
                        selection['mode'] == 'projects' or selection['mode'] == 'file' and project_ids is not None) or
                        current == 'evaluation' and selection['mode'] in ('file', 'delivery')) and not request.get('scope_resolved'):
                    project_ids = scope_projects(root, run, selection, project_ids)
                    request.update(project_ids=project_ids, scope_resolved=True)
                    write(run_file(run, 'execution.json'), request)
                    progress('SCOPE_RESOLVED', project_count=len(project_ids), projects=project_ids)
                if current == 'preprocessing':
                    prepare(root, run, raw, dataset, config, through='preprocessing')
                    if not (run_file(run, 'model.binding.json')).exists():write(run_file(run, 'model.binding.json'), model_binding)
                    check(root, run)
                    if (run/'preprocess/scope.json').is_file():
                        planned=read(run/'preprocess/scope.json')
                        progress('INPUT_SUMMARY',summary=dict({k:planned[k] for k in ('selected_counts','identity_context_records','projects')},
                            identity_links=planned['identity_links'],unverified_production_records=len(planned['unverified_production']),
                            report=str(run/'preprocess/scope.json')))
                elif current == 'knowledge':
                    knowledge(root, run)
                    if check(root, run)['status'] != 'PREPARED':
                        raise ValueError('Conocimiento no preparado')
                elif current == 'graphrag':
                    if not (knowledge_workspace(run) / 'outputs/layer3/publication/_manifest.json').exists() and not approve_build and not approval:
                        write(run_file(run, 'execution.json'), request)
                        approved = confirm is not None and confirm('build', dict(review=str(run / 'preprocess/review.json'),
                            note='Construir embeddings locales BGE-M3 e indices con las fuentes de apoyo; no se descargan modelos')) is True
                        if not approved:
                            return progress('BUILD_APPROVAL_REQUIRED', message='Revisar preprocess/review.json y autorizar embeddings locales')
                    graph(root, run, build=True)
                    validated_graph(root, run)
                    register_built_knowledge(root, run, request)
                else:
                    check(root, run)
                    validated_graph(root, run)
                    if current == 'evaluation':
                        from layer4_evaluation.indicators.ollama_provider import configuration as llm_configuration
                        request['llm'] = llm_configuration(active_config.get('llm'))
                        selected = scope_projects(root, run, selection, project_ids)
                        if not selected or len(selected) != len(set(selected)):
                            raise ValueError('Evaluacion actual requiere proyectos con IDs unicos; ARTICLE no esta implementado')
                        request['project_ids'] = selected
                        quarantine=check(root,run).get('scope_quarantine',{})
                        blocked={p:quarantine.get('affected_projects',{}).get(p,quarantine.get('primary_article_conflicts',[]))
                            for p in selected if p in quarantine.get('affected_projects',{}) or quarantine.get('primary_article_conflicts')}
                        unavailable = projects_without_evidence(run, selected)
                        for pid in unavailable:
                            blocked.setdefault(pid, []).append('NO_AUTHORIZED_SUBSTANTIVE_TEXT')
                        write(run_file(run, 'evaluation_readiness.json'), dict(
                            status='PARTIAL' if blocked else 'READY', blocked_projects=blocked,
                            projects_without_evidence=unavailable,
                            note='No se infieren indicadores ni cumplimiento de proyectos sin texto sustantivo; no se sustituyen IDs'))
                        request['blocked_projects']=blocked
                        write(run_file(run, 'execution.json'), request)
                        eligible=[p for p in selected if p not in blocked]
                        if blocked:
                            progress('INPUT_SUMMARY',summary=dict(blocked_projects=blocked,eligible_projects=eligible,
                                report=str(run_file(run, 'evaluation_readiness.json')),note='No se evaluan proyectos bloqueados ni se asignan estados de cumplimiento; el resultado del conjunto permanecera parcial'))
                        if not eligible:
                            return progress('BLOCKED_INPUT',blocked_projects=blocked,report=str(run_file(run, 'evaluation_readiness.json')))
                        module = engine(root, run)
                        batches = [eligible[i:i+2] for i in range(0, len(eligible), 2)]
                        reviews, pending, authorized_batches = [], [], set()
                        completed_projects=completed_indicators=processed_projects=0
                        evaluation_partial=False
                        batch_states={}
                        for batch in batches:
                            directory = module.BASE / batch_name(batch)
                            review_path = directory / 'review.txt'
                            reviewed = sha(review_path) if review_path.is_file() else None
                            result = evaluate(root, run, batch)
                            verified = module.verify_run(directory)
                            batch_states[directory.name]=verified
                            project_states(verified)
                            if verified.get('blocking_errors',verified['errors']):
                                raise ValueError('Evaluacion bloqueada: ' + '; '.join(verified['errors']))
                            if verified['status']=='COMPLETE':
                                completed_projects+=len(verified['projects'])
                                processed_projects+=len(verified['projects'])
                                completed_indicators+=sum(len(p.get('rows',[])) for p in verified['projects'])
                            if verified['status'] != 'COMPLETE':
                                if approval:
                                    authorized_batches.add(batch_name(batch))
                                elif reviewed != sha(review_path) or not authorize and not (directory / 'authorization.json').exists():
                                    review_hash = sha(review_path)
                                    approved = confirm is not None and confirm('llm', review_summary(module, directory)) is True
                                    if sha(review_path) != review_hash:
                                        raise ValueError('La revision cambio durante la autorizacion; revisar nuevamente')
                                    if approved:
                                        authorized_batches.add(batch_name(batch))
                                    else:
                                        reviews.append(result['review'])
                                pending.append(batch)
                        if reviews:
                            return progress('REVIEW_REQUIRED', reviews=reviews,
                                message='Leer los reviews; reanudar con --authorize-llm para autorizar el proveedor registrado en el run')
                        for batch in pending:
                            if approval:verify_execution_approval(root,approval)
                            if (run_file(run, 'stop.request.json')).exists():
                                partial=export(root,run)
                                return progress('INTERRUPTED',result=partial)
                            if approval:
                                directory=module.BASE/batch_name(batch)
                                write(directory/'run_authorization.reference.json',dict(
                                    scope_sha256=approval['scope_sha256'],authorization=str(run/'estado/run.authorization.json'),
                                    authorization_sha256=sha(run/'estado/run.authorization.json'),
                                    plan_sha256=sha(directory/'plan.json'),review_sha256=sha(directory/'review.txt')))
                            evaluate(root, run, batch, authorize=authorize or batch_name(batch) in authorized_batches, execute=True)
                            verified = module.verify_run(module.BASE / batch_name(batch))
                            batch_states[batch_name(batch)]=verified
                            project_states(verified)
                            completed_projects+=sum(p.get('complete',False) for p in verified['projects'])
                            processed_projects+=sum(p.get('processed',p.get('complete',False)) for p in verified['projects'])
                            evaluation_partial=evaluation_partial or verified['status']!='COMPLETE'
                            completed_indicators+=sum(len(p.get('rows',[])) for p in verified['projects'])
                            if notify:
                                progress('EVALUATION_PROGRESS',projects_in_batch=len(batch),
                                    projects_evaluated=completed_projects,total_projects=len(eligible),
                                    projects_processed=processed_projects,projects_completed=completed_projects,
                                    indicators_completed=completed_indicators)
                            if verified.get('blocking_errors',verified['errors']):
                                if (run_file(run, 'stop.request.json')).exists():
                                    return progress('INTERRUPTED',result=export(root,run))
                                raise ValueError('Lote incompleto/bloqueado; consultar status antes de reanudar')
                        projects_view=[p for batch in batch_states.values() for p in batch['projects']]
                        decisions=[r['decision'] for p in projects_view for r in p['rows']]
                        evaluation_report=dict(selected_projects=len(selected),processed_projects=processed_projects,
                            completed_projects=completed_projects,expected_assessments=sum(len(p.get('selected',p['rows'])) for p in projects_view),
                            valid_assessments=len(decisions),supported=decisions.count('SUPPORTED'),
                            insufficient_evidence=decisions.count('INSUFFICIENT_EVIDENCE'),not_supported=decisions.count('NOT_SUPPORTED'),
                            blocked_assessments=sum(len(set(p.get('blocked_indicators',{}))|set(p.get('context_limits',{}))) for p in projects_view),
                            pending_assessments=sum(len(p.get('pending_indicators',[])) for p in projects_view),
                            processing_complete=processed_projects==len(selected),results_available=bool(decisions))
                        if target=='evaluation' and evaluation_partial:
                            return progress('PARTIAL',**evaluation_report,
                                message='Procesamiento finalizado con cobertura parcial; las evaluaciones validas se conservan.')
                    else:
                        module = engine(root, run)
                        directories = list(module.BASE.glob('batch_*'))
                        if not directories:
                            raise ValueError('Exportacion requiere evaluaciones verificadas')
                        result = export(root, run)
                        if result['status'] != 'COMPLETE':
                            return progress(result['status'], result=result)
                write(run_file(run, 'execution.json'), request)
                progress('STAGE_COMPLETE')
            if request.get('blocked_projects') and 'evaluation' in sequence:
                return progress('PARTIAL',through=target,blocked_projects=request['blocked_projects'],report=str(run/'preprocess/scope_validation.json'))
            if dry_run:
                report = read(run / 'preprocess/selection_manifest.json')
                return progress(report['status'], manifest=str(run / 'preprocess/selection_manifest.json'),
                                selected_count=report['selected_count'], counts=report['counts'],
                                shared_researchers=report['shared_researchers'],
                                warnings=[dict(code=w['code'], count=w.get('count', len(w.get('projects', w.get('groups', [])))))
                                          for w in report['warnings']],
                                inference_calls=0, embeddings_created=0)
            return progress('COMPLETE', through=target, results=str(evaluation_dir(run)),
                            excel=str(run_file(run, 'resultado_indicadores.xlsx')) if target == 'export' else None,
                            **(dict(result=result) if target=='export' else evaluation_report),
                            limitations=['Evaluacion PROJECT; ARTICLE pendiente. Exportacion sin puente territorial nuevo verificado.'])
        except KeyboardInterrupt:
            if any(evaluation_dir(run).glob('batch_*')):
                try:export(root,run)
                except Exception:write(run/'partial_export.pending.json',dict(reason='Reintentar uv run python run.py export --run-id '+name))
            progress('INTERRUPTED', message='Reanudar el mismo run; conservar checkpoints y claims del proveedor')
            raise
        except Exception as exc:
            if run.is_dir():
                write(run_file(run,'failure.json'), dict(stage=current,error=str(exc),error_type=type(exc).__name__))
            if model_binding['llm']['provider']=='openai' and any(evaluation_dir(run).glob('batch_*')):
                try:
                    partial_result=export(root,run)
                    if 'API_BUDGET' in str(exc):return progress('PARTIAL',result=partial_result,reason='API_BUDGET')
                except Exception:write(run/'partial_export.pending.json',dict(reason='Reintentar export explicito; comprobar recibos'))
            progress('FAILED_OR_BLOCKED', error=str(exc), error_type=type(exc).__name__)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='RAW -> PREPROCESSING -> KNOWLEDGE -> GRAPHRAG -> RESULTS -> Power BI')
    parser.add_argument('operation', choices=['raw', 'preprocess', 'knowledge', 'prepare', 'validate', 'graph', 'review', 'evaluate', 'export', 'verify', 'run'])
    parser.add_argument('--dataset', choices=['prueba_controlada', 'prueba_en_vivo'], default=None)
    parser.add_argument('--run-id', help='Nuevo en prepare; obligatorio para las demas operaciones')
    parser.add_argument('--config', default='config/pipeline_manual.json')
    parser.add_argument('--project-id', action='append', help='Identificador institucional; maximo dos por lote')
    parser.add_argument('--approve-build', action='store_true', help='Autoriza embeddings locales, sin descargas')
    parser.add_argument('--authorize', action='store_true', help='Consentimiento explicito para evaluar el texto revisado con Ollama local')
    parser.add_argument('--through', choices=['preprocessing', 'knowledge', 'graphrag', 'results'], default='knowledge', help='Ultima capa para run; results conserva la revision/autorizacion explicita')
    args = parser.parse_args(argv)
    run = None
    try:
        if args.operation in ('run', 'prepare', 'preprocess'):
            target = ('preprocessing' if args.operation == 'preprocess' else
                      'knowledge' if args.operation == 'prepare' else
                      'export' if args.through == 'results' else args.through)
            result = execute_pipeline(ROOT, config_path=args.config, run_id=args.run_id,
                through=target, approve_build=args.approve_build, authorize=args.authorize,
                project_ids=args.project_id, dataset=args.dataset)
            print(json.dumps(result, ensure_ascii=True, default=str))
            return 0 if result['status'] == 'COMPLETE' else 3
        config, rawbase, runs = configuration(ROOT, args.config)
        selected_raw = ROOT / 'tests/fixtures' / args.dataset if args.dataset else rawbase
        dataset = args.dataset or 'raw'
        if args.operation == 'raw':
            from layer2_processing.preprocessing.adapters import inventory, discover_sources
            result = inventory(ROOT, args.dataset, config['raw_base'])
            preview = discover_sources(ROOT, config, selected_raw)
            result['discovery_status'] = preview['status']
            result['discovery'] = [{k:v for k,v in item.items() if k != 'records'} for item in preview['files']]
            print(json.dumps(result, ensure_ascii=True))
            return 0
        if not args.run_id and args.operation not in ('prepare', 'preprocess', 'run'):
            raise ValueError('--run-id es obligatorio para reutilizar la ejecucion seleccionada')
        name = args.run_id or ('run_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', name):
            raise ValueError('--run-id invalido')
        run = runs / name
        previous = ROOT / 'outputs/pipeline_manual' / name
        if not run.exists() and previous.exists():
            run = previous
        # A shared lock prevents concurrent manual analytical executions across runs.
        with lock(runs):
            state = check(ROOT, run)
            if state['dataset'] != dataset or not same_configuration(ROOT, state['configuration'], config):
                raise ValueError('Conjunto/configuracion no corresponde a esta ejecucion')
            from layer2_processing.checkpoints import resolve
            if resolve(ROOT, state['raw_path']).resolve() != selected_raw.resolve():
                raise ValueError('RAW de la ejecucion no corresponde al conjunto configurado')
            if args.operation == 'knowledge':
                result = knowledge(ROOT, run)
            elif args.operation == 'validate':
                result = graph(ROOT, run)
            elif args.operation == 'graph':
                if not args.approve_build:
                    raise ValueError('Revisar preprocess/review.json; graph requiere --approve-build')
                result = graph(ROOT, run, build=True)
            elif args.operation == 'review':
                result = evaluate(ROOT, run, args.project_id)
            elif args.operation == 'evaluate':
                module = engine(ROOT, run)
                # Never create and authorize an unreviewed plan in one operation.
                candidates = [d for d in module.BASE.glob('batch_*') if (d / 'plan.json').exists()]
                if not candidates:
                    raise ValueError('Ejecutar review y leer review.txt antes de evaluate')
                selected = args.project_id or [p['source_project_id'] for p in pq.read_table(knowledge_workspace(run) / 'outputs/layer2/canonical/proyectos.parquet').to_pylist()]
                batch = batch_name(selected)
                if not (module.BASE / batch / 'review.txt').exists():
                    raise ValueError('Falta revision de este lote: ejecutar review con los mismos --project-id')
                result = evaluate(ROOT, run, args.project_id, args.authorize, execute=True)
            elif args.operation == 'export':
                result = export(ROOT, run)
            else:
                result = graph(ROOT, run) if state['status'] == 'PREPARED' else dict(status='PREPROCESSING_VERIFIED', counts=state['counts'])
                if (knowledge_workspace(run) / 'outputs/layer3/publication/_manifest.json').exists():
                    result['graph_manifest'] = validated_graph(ROOT, run)['layer3_run_id']
                module = engine(ROOT, run)
                result['evaluations'] = {d.name: module.summary(module.verify_run(d)) for d in module.BASE.glob('batch_*')}
            check(ROOT, run)
        print(json.dumps(result, ensure_ascii=True, default=str))
        return 0
    except Exception as exc:
        if run is not None and run.exists():
            write(run / 'last_error.json', {'operation': args.operation, 'type': type(exc).__name__, 'error': str(exc)})
        print(json.dumps({'status': 'FAILED_OR_BLOCKED', 'error': str(exc), 'run': str(run)}, ensure_ascii=True), file=sys.stderr)
        return 2
