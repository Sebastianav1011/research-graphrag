"""Internal SAD layer 2 pipeline; isolated staging, canonical and knowledge checkpoints."""
from run_paths import file_path as run_file
from pathlib import Path
import json
from datetime import datetime,timezone
import yaml
import pyarrow.parquet as pq
from .preprocessing.adapters import prepare_files, read, sha, verify_raw, write

def code_hashes(root):
    files = list((root / 'src').rglob('*.py'))
    files += [root / 'scripts/run_pipeline_manual.py', root / 'scripts/pipeline_coordinator.py']
    files += [root / ('config/' + n) for n in ('sources.example.yaml', 'layer1.yaml', 'layer2.yaml', 'layer3.yaml')]
    files += [layer_config(root, number) for number in (2, 3, 4)]
    return {p.relative_to(root).as_posix(): sha(p) for p in files}


def seal(run):
    files = [p for prefix in ('workspace/outputs/layer2/canonical', 'workspace/outputs/layer2/knowledge', 'workspace/outputs/layer2/preprocessing/audit', 'workspace/outputs/layer2/preprocessing/quality', 'workspace/data/canonical', 'workspace/data/knowledge', 'workspace/config', 'preprocess') for p in (run / prefix).rglob('*') if p.is_file()]
    write(run_file(run, 'prepared_hashes.json'), {p.relative_to(run).as_posix(): sha(p) for p in files})


def check(root, run, *, knowledge_only=False):
    state = read(run_file(run, 'run.json'))
    from .checkpoints import resolve
    raw = resolve(root, state['raw_path'])
    if state.get('global_catalog_sha256') is not None and sha(resolve(root,state['configuration']['reference_catalog']))!=state['global_catalog_sha256']:
        raise ValueError('Catalogo global BASE modificado')
    verify_raw(raw, read(run_file(run, 'raw_manifest.json'))['files'], state['configuration'].get('source_paths'))
    selection = state['configuration'].get('project_selection')
    if selection:
        for name, fingerprint in selection['sources'].items():
            if not (root / name).is_file() or sha(root / name) != fingerprint:
                raise ValueError('Fuente del manifiesto de seleccion modificada: ' + name)
    for name, fingerprint in state['code_hashes'].items():
        if knowledge_only and not name.startswith(('src/layer2_processing/preprocessing/','src/layer2_processing/knowledge/','src/layer3_graphrag/','config/')):
            continue  # UI/evaluation changes do not alter stored knowledge.
        from .checkpoints import verify_expected
        verify_expected(root, name, fingerprint)
    if state['status'] not in ('PREPROCESSED', 'PREPARED'):
        raise ValueError('Preparacion incompleta; revisar failure.json y usar otra ejecucion')
    for name, fingerprint in read(run_file(run, 'prepared_hashes.json')).items():
        if sha(run / name) != fingerprint:
            raise ValueError('Producto de preprocesamiento modificado: ' + name)
    scope_validation=run/'preprocess/scope_validation.json'
    if scope_validation.is_file() and state.get('scope_quarantine')!=read(scope_validation):
        raise ValueError('Estado de cuarentena distinto del informe sellado')
    if state.get('knowledge_ref'):
        # Shared knowledge is verified where it lives: exact version pin plus
        # its sealed checkpoint (RAW, knowledge code and every sealed file).
        from knowledge_store import resolve_reference
        resolve_reference(root,state['knowledge_ref'])
    if state.get('knowledge_build'):
        from knowledge_store import knowledge_root
        built = check(root, knowledge_root(run), knowledge_only=knowledge_only)
        if built['status'] != state['status']:
            # A completed stage may precede its small evaluation receipt after interruption.
            state = dict(state, status=built['status'], counts=built.get('counts'),
                         knowledge_counts=built.get('knowledge_counts'))
    return state


def _shared_selection(root, run, builder):
    """Run the unchanged selection validator on a disposable canonical snapshot."""
    if not read(run_file(run, 'run.json'))['configuration'].get('project_selection'):
        return
    import shutil
    import tempfile
    import knowledge_store as store
    from .preprocessing.project_selection import validate_selection
    parent = store.shared_root(root) / 'validation'
    parent.mkdir(parents=True, exist_ok=True)
    canonical = builder / 'workspace/outputs/layer2/canonical'
    required = sum(p.stat().st_size for p in canonical.rglob('*') if p.is_file())
    if shutil.disk_usage(parent).free < required + (64 << 20):
        raise OSError('Espacio insuficiente para validar seleccion')
    with tempfile.TemporaryDirectory(prefix='selection-', dir=parent) as name:
        temporary = Path(name)
        shutil.copytree(canonical, temporary / 'workspace/outputs/layer2/canonical')
        write(run_file(temporary, 'run.json'), read(run_file(run, 'run.json')))
        report = validate_selection(root, temporary)
        write(run / 'preprocess/selection_manifest.json', report)


def _sync_shared_build(root, run, builder):
    import shutil
    state = read(run_file(run, 'run.json'))
    built = read(run_file(builder, 'run.json'))
    for name in ('status', 'counts', 'knowledge_counts', 'global_catalog_sha256', 'scope_quarantine'):
        if name in built:
            state[name] = built[name]
    run_file(run, 'raw_manifest.json').parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(run_file(builder, 'raw_manifest.json'), run_file(run, 'raw_manifest.json'))
    write(run_file(run, 'run.json'), state)
    for name in ('review.json', 'scope_validation.json'):
        source = builder / 'preprocess' / name
        if source.is_file():
            target = run / 'preprocess' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    if built['status'] in ('PREPROCESSED', 'PREPARED'):
        _shared_selection(root, run, builder)
    seal(run)


def restore_lineage(workspace, lineage):
    """Replace adapter locators with exact RAW occurrences before knowledge generation."""
    from layer2_processing.preprocessing.canonicalize import write_parquet
    folder = workspace / 'outputs/layer2/canonical'
    manifest = read(folder / '_manifest.json')
    for path in sorted(folder.glob('*.parquet')):
        rows = pq.read_table(path).to_pylist()
        for row in rows:
            refs = json.loads(row['provenance_json'])
            for index, ref in enumerate(refs):
                occurrences = lineage.get(ref['record_source'])
                if occurrences:
                    from copy import deepcopy
                    # An occurrence may back a paper, author and relation. Do
                    # not mutate their shared lists when adding narrative fields.
                    raw = deepcopy(occurrences[str(ref['source_row'])])
                    translated = {}
                    for field, column in ref['field_mapping'].items():
                        columns = column if isinstance(column, list) else [column]
                        originals = []
                        for col in columns:
                            names = raw['field_mapping'].get(col, col)
                            originals.extend(names if isinstance(names, list) else [names])
                        translated[field] = originals[0] if len(originals) == 1 else originals
                    translated.update({f: raw['field_mapping'][f] for f in raw.get('extra_text_fields', [])})
                    refs[index] = ref | raw | {'field_mapping': translated}
            # One section per original occurrence: never concatenate distinct rows
            # merely because their column names coincide after a canonical join.
            from collections import Counter
            import hashlib
            from .preprocessing.adapters import key
            # Canonical representatives remain unchanged. Keep other explicitly
            # mapped narrative occurrences available as independent evidence too.
            for ref in refs:
                for field in ('summary', 'abstract', 'methodology', 'objectives', 'expected_results'):
                    column = ref.get('field_mapping', {}).get(field)
                    original = ref.get('original_values', {}).get(column) if isinstance(column, str) else None
                    if isinstance(original, str) and original.strip() and original.strip() != (row.get(field) or '').strip():
                        locator = [ref['record_source'], ref.get('source_sheet'), ref['source_row'], column]
                        extra = 'text__' + key(column).replace(' ', '_') + '__' + hashlib.sha256(json.dumps(locator, ensure_ascii=False).encode()).hexdigest()[:16]
                        if extra not in ref.setdefault('extra_text_fields', []):
                            ref['extra_text_fields'].append(extra)
                        ref['field_mapping'][extra] = column
                        if field in ref.get('knowledge_fields', {}):
                            ref['knowledge_fields'][extra] = dict(ref['knowledge_fields'][field])
            counts = Counter(f for ref in refs for f in ref.get('extra_text_fields', []))
            for ref in refs:
                fields = []
                for field in ref.get('extra_text_fields', []):
                    unique = field
                    if counts[field] > 1:
                        locator = [ref['record_source'], ref.get('source_sheet'), ref['source_row'], ref['field_mapping'][field]]
                        unique = field + '__' + hashlib.sha256(json.dumps(locator, ensure_ascii=False).encode()).hexdigest()[:16]
                        ref['field_mapping'][unique] = ref['field_mapping'].pop(field)
                        if field in ref.get('knowledge_fields', {}):
                            ref['knowledge_fields'][unique] = ref['knowledge_fields'].pop(field)
                    fields.append(unique)
                if fields:
                    ref['extra_text_fields'] = fields
            row.update(record_source=refs[0]['record_source'], source_row=refs[0]['source_row'],
                       provenance_json=json.dumps(refs, ensure_ascii=False, default=str))
        write_parquet(path, rows, path.stem)
        manifest['canonical_files'][path.stem]['sha256'] = sha(path)
    manifest['manual_adapter'] = 'RAW lineage restored before knowledge build; original ETL audit retained'
    write(folder / '_manifest.json', manifest)


def same_configuration(root, left, right):
    left, right = dict(left), dict(right)
    from .checkpoints import destination
    for field in ('raw_base', 'runs_base', 'reference_catalog'):
        left[field] = str(destination(root, left[field]))
        right[field] = str(destination(root, right[field]))
    return left == right


def layer_config(root, number):
    # Configuration names are frozen contracts, not alternate implementations.
    return root / 'config' / {2: 'layer1.yaml', 3: 'layer2.yaml', 4: 'layer3.yaml'}[number]


def reuse_global_base(root,run,raw,config,dataset,*,probe=False,require_graph=False):
    """Reuse verified shared BASE knowledge by reference; never reuse evaluations/selection.

    The shared registry (knowledge_store) is the ordinary mechanism: the run
    stores a stable version reference and reads the artifacts in place, without
    copying them. Only an explicit historical source (a run locator recorded by
    an earlier version of this code) still uses the legacy copy, for resume.
    """
    if config.get('knowledge_scope')!='BASE_GLOBAL_V1':return False
    import knowledge_store as store
    source=config.get('base_knowledge_source')
    if source and not source.startswith(store.REFERENCE_PREFIX):
        from .checkpoints import resolve
        matches = [item for item in store.status(root)['versions']
                   if store.location(root, store.load_version(root, item['version_id'])[0]) == resolve(root, source).resolve()]
        if len(matches) != 1:
            reuse_global_base.last_reason = 'Fuente historica sin una version registrada unica'
            return False
        source = store.REFERENCE_PREFIX + matches[0]['version_id']
    from jsonschema.exceptions import ValidationError
    reuse_global_base.last_reason=None
    try:
        manifest,manifest_sha=store.compatible(root,raw,config,dataset,
            version_id=source[len(store.REFERENCE_PREFIX):] if source else None)
    except (store.KnowledgeUnavailable,OSError,ValueError,KeyError,RuntimeError,ValidationError) as exc:
        reuse_global_base.last_reason=str(exc)  # Reported to the user; never a silent rebuild.
        return False
    if probe:return store.REFERENCE_PREFIX+manifest['version_id']
    if (run/'workspace').exists() or run_file(run,'prepared_hashes.json').exists():
        raise ValueError('No sobrescribir un checkpoint existente para referenciar BASE')
    import shutil
    builder=store.location(root,manifest)
    builder_state=read(run_file(builder,'run.json'))
    run_file(run,'raw_manifest.json').parent.mkdir(parents=True,exist_ok=True)
    # Small run-local RAW receipt so check() verifies the sources of this run.
    shutil.copyfile(run_file(builder,'raw_manifest.json'),run_file(run,'raw_manifest.json'))
    state=dict(run_id=run.name,dataset=dataset,raw_path=raw.relative_to(root).as_posix(),status='PREPARED',
        started_at=datetime.now(timezone.utc).isoformat(),configuration=config,code_hashes=code_hashes(root),
        global_catalog_sha256=builder_state.get('global_catalog_sha256'),counts=builder_state.get('counts'),
        knowledge_counts=builder_state.get('knowledge_counts'),storage_layout=store.RUN_LAYOUT,
        knowledge_ref=store.reference(manifest,manifest_sha))
    if 'scope_quarantine' in builder_state:state['scope_quarantine']=builder_state['scope_quarantine']
    write(run_file(run,'run.json'),state)
    _shared_selection(root, run, builder)
    seal(run)
    return True


def _legacy_copy_reuse(root,run,raw,config,dataset,*,probe=False,require_graph=False):
    """Historical behaviour, kept only for an explicitly recorded run locator."""
    from .checkpoints import resolve
    from jsonschema.exceptions import ValidationError
    catalog_hash=sha(resolve(root,config['reference_catalog']))
    from run_paths import list_runs
    import shutil
    ignored={'llm','evaluation','evaluation_policy','project_selection','processing_scope','runs_base','base_knowledge_action','base_knowledge_source'}
    data_config=lambda value:{k:v for k,v in value.items() if k not in ignored}
    for candidate in sorted(list_runs(root),reverse=True):
        if candidate.resolve()==run.resolve():continue
        if config.get('base_knowledge_source') and candidate.relative_to(root).as_posix()!=config['base_knowledge_source']:continue
        try:
            state=read(run_file(candidate,'run.json'))
            if (state.get('status')!='PREPARED' or state.get('dataset')!=dataset or
                    state.get('configuration',{}).get('knowledge_scope')!='BASE_GLOBAL_V1' or
                    data_config(state['configuration'])!=data_config(config) or
                    (root/state['raw_path']).resolve()!=raw.resolve()):continue
            if state.get('global_catalog_sha256')!=catalog_hash:continue
            check(root,candidate,knowledge_only=True)  # RAW, data contracts and sealed files.
            knowledge=candidate/'workspace/outputs/layer2/knowledge/_manifest.json'
            if not knowledge.is_file():continue
            graph=candidate/'workspace/outputs/layer3/publication'
            if require_graph and not (graph/'_manifest.json').is_file():continue
            if (graph/'_manifest.json').exists():
                from layer3_graphrag.manifest import validate_publication
                validate_publication(graph,sha(knowledge))
                if require_graph:
                    from layer3_graphrag.configuration import load_config
                    from layer3_graphrag.validate_inputs import validate_inputs
                    from layer3_graphrag.pipeline import load_artifacts
                    from layer3_graphrag.embeddings import create_provider
                    graph_config,_=load_config(candidate/'workspace')
                    snapshot=validate_inputs(candidate/'workspace',graph_config)
                    load_artifacts(candidate/'workspace',snapshot,graph_config,create_provider(graph_config['embeddings']))
        except (OSError,ValueError,KeyError,RuntimeError,ValidationError):continue
        if probe:return candidate.relative_to(root).as_posix()
        if (run/'workspace').exists():raise ValueError('No sobrescribir un workspace existente para reutilizar BASE')
        for relative in ('workspace/config','workspace/data','workspace/outputs/layer2','preprocess'):
            source=candidate/relative
            if source.is_dir():
                shutil.copytree(source,run/relative,ignore=shutil.ignore_patterns('selection_manifest.json'))
        run_file(run,'raw_manifest.json').parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(run_file(candidate,'raw_manifest.json'),run_file(run,'raw_manifest.json'))
        if (graph/'_manifest.json').exists():
            shutil.copytree(graph,run/'workspace/outputs/layer3/publication')
            queries=candidate/'workspace/outputs/layer3/query_cache'
            if queries.is_dir():shutil.copytree(queries,run/'workspace/outputs/layer3/query_cache')
        fresh=dict(state,run_id=run.name,configuration=config,code_hashes=code_hashes(root),
            started_at=datetime.now(timezone.utc).isoformat(),
            global_reuse=dict(source_run=candidate.name,knowledge_manifest_sha256=sha(knowledge),
                graph_reused=(graph/'_manifest.json').exists()))
        write(run_file(run,'run.json'),fresh)
        seal(run)
        if config.get('project_selection'):
            from .preprocessing.project_selection import validate_selection
            validate_selection(root,run)
            seal(run)
        return True
    return False


def prepare(root, run, raw, dataset, config, through='knowledge'):
    import knowledge_store as store
    # BASE builders live in shared staging from their first byte. Evaluation
    # runs own only configuration, selection/review and stable version receipts.
    shared = store.shared_root(root).resolve()
    if config.get('knowledge_scope') == 'BASE_GLOBAL_V1' and not Path(run).resolve().is_relative_to(shared):
        existing = read(run_file(run, 'run.json')) if run_file(run, 'run.json').is_file() else {}
        if existing.get('knowledge_ref'):
            return dict(status='ALREADY_PREPARED', run=str(run))
        if existing and existing.get('status') != 'REGISTERED' and not existing.get('knowledge_build'):
            return _prepare_checkpoint(root, run, raw, dataset, config, through)
        if not existing.get('knowledge_build') and config.get('base_knowledge_action', 'auto') != 'rebuild':
            run.mkdir(parents=True, exist_ok=True)
            if reuse_global_base(root, run, raw, config, dataset, require_graph=True):
                return dict(status='REUSED_GLOBAL_BASE', run=str(run), inference_calls=0, embeddings_created=0)
            if config.get('base_knowledge_action') == 'reuse':
                raise ValueError('No existe conocimiento global BASE compatible: ' + str(reuse_global_base.last_reason))
        if not existing.get('knowledge_build'):
            import uuid
            if existing and existing.get('status') != 'REGISTERED':
                # Existing historical checkpoints retain their original lifecycle.
                return _prepare_checkpoint(root, run, raw, dataset, config, through)
            builder = shared / 'staging' / ('build-' + uuid.uuid4().hex)
            state = dict(run_id=run.name, dataset=dataset, raw_path=raw.relative_to(root).as_posix(),
                status='REGISTERED', started_at=datetime.now(timezone.utc).isoformat(), configuration=config,
                code_hashes=code_hashes(root), storage_layout=store.RUN_LAYOUT,
                knowledge_build=builder.relative_to(root).as_posix())
            write(run_file(run, 'run.json'), state)
        builder = store.knowledge_root(run)
        build_config = dict(config, base_knowledge_action='rebuild')
        build_config.pop('project_selection', None)
        build_config.pop('base_knowledge_source', None)
        result = _prepare_checkpoint(root, builder, raw, dataset, build_config, through)
        _sync_shared_build(root, run, builder)
        return dict(result, run=str(run))
    return _prepare_checkpoint(root, run, raw, dataset, config, through)


def _prepare_checkpoint(root, run, raw, dataset, config, through='knowledge'):
    registered = (run_file(run, 'run.json')).exists() and read(run_file(run, 'run.json')).get('status') == 'REGISTERED'
    if (run_file(run, 'run.json')).exists() and not registered:
        state = check(root, run)
        if state['dataset'] != dataset or not same_configuration(root, state['configuration'], config):
            raise ValueError('La ejecucion pertenece a otro conjunto/configuracion')
        if state['status'] == 'PREPROCESSED' and through == 'knowledge':
            return knowledge(root, run)
        return dict(status='ALREADY_PREPARED', run=str(run))
    if registered:
        initial = read(run_file(run, 'run.json'))
        if initial['dataset'] != dataset or initial['raw_path'] != raw.relative_to(root).as_posix():
            raise ValueError('Registro inicial incompatible con la preparacion')
    elif run.exists():
        raise ValueError('Directorio existente/incompleto: utilizar otro --run-id')
    run.mkdir(parents=True, exist_ok=registered)
    action=config.get('base_knowledge_action','auto')
    if action!='rebuild' and reuse_global_base(root,run,raw,config,dataset,require_graph=action=='reuse'):
        return dict(status='REUSED_GLOBAL_BASE',run=str(run),inference_calls=0,embeddings_created=0)
    if action=='reuse':raise ValueError('No existe conocimiento global BASE compatible; elegir reconstruir o --knowledge-action rebuild'
        +(f' ({reuse_global_base.last_reason})' if getattr(reuse_global_base,'last_reason',None) else ''))
    state = dict(run_id=run.name, dataset=dataset, raw_path=raw.relative_to(root).as_posix(),
        status='PREPARING', started_at=datetime.now(timezone.utc).isoformat(), configuration=config, code_hashes=code_hashes(root))
    if config.get('knowledge_scope')=='BASE_GLOBAL_V1':
        from .checkpoints import resolve
        state['global_catalog_sha256']=sha(resolve(root,config['reference_catalog']))
    write(run_file(run, 'run.json'), state)
    try:
        sources, lineage = prepare_files(root, raw, run, config)
        workspace = run / 'workspace'
        (workspace / 'config').mkdir(parents=True)
        registry = root / 'config/sad_relocations.json'
        if registry.is_file():
            (workspace / 'config/sad_relocations.json').write_bytes(registry.read_bytes())
        (workspace / 'config/sources.yaml').write_text(yaml.safe_dump(sources, allow_unicode=True), encoding='utf-8')
        settings = yaml.safe_load(layer_config(root, 2).read_text(encoding='utf-8'))
        settings['errors']['fail_on_error'] = True
        scope_path=run/'preprocess/scope.json'
        if scope_path.is_file():
            settings['scope_identity_context']=str(run/'preprocess/identity_context.json')
            settings['errors']['scoped_article_quarantine']='PROJECT_SCOPE_V1'
        if config.get('knowledge_scope')=='BASE_GLOBAL_V1':
            settings['errors']['scoped_article_quarantine']='PROJECT_SCOPE_V1'
        (workspace / 'config/layer1.yaml').write_text(yaml.safe_dump(settings), encoding='utf-8')
        from layer2_processing.preprocessing.pipeline import run as etl
        result = etl(workspace)
        if result['status'] != 'SUCCESS':
            raise ValueError('ETL rechazo la entrada: workspace/outputs/layer2/preprocessing/audit/anomalies.csv')
        restore_lineage(workspace, lineage)
        if scope_path.is_file():
            import csv
            with (workspace/'outputs/layer2/preprocessing/audit/anomalies.csv').open(encoding='utf-8-sig',newline='') as stream:
                conflict_events=[e for e in csv.DictReader(stream) if e['domain']=='articulos' and e['anomaly_code']=='CONFLICTING_SOURCE_ID' and e['severity']=='ERROR']
            conflicts={e['source_object_id'] for e in conflict_events}
            scope=read(scope_path)
            affected={p:sorted(set(keys)&conflicts) for p,keys in scope['project_article_keys'].items() if set(keys)&conflicts}
            optional_conflicts = affected if config.get('project_selection') else {}
            if config.get('project_selection'):
                # These are authors' papers, not declared project outputs.
                # Quarantine them without blocking unrelated project evidence.
                affected = {}
            primary=sorted(set(scope['primary_article_keys'])&conflicts)
            state['scope_quarantine']=dict(status='BLOCKED_RELEVANT_QUARANTINE' if affected or primary else 'VALIDATED_SCOPE',
                affected_projects=affected,primary_article_conflicts=primary,conflict_groups=sorted(conflicts),
                relationship_confirmation='Project production scope corroborated by the existing identity resolver; graph edges still require native canonical validation',
                sources=[dict(article_id=e['source_object_id'],record_source=lineage[e['source_file']][e['source_row']]['record_source'],
                    source_row=lineage[e['source_file']][e['source_row']]['source_row'],
                    source_sheet=lineage[e['source_file']][e['source_row']].get('source_sheet'),
                    raw_sha256=lineage[e['source_file']][e['source_row']]['raw_sha256']) for e in conflict_events])
            write(run/'preprocess/scope_validation.json',state['scope_quarantine'])
            if optional_conflicts:
                state['scope_quarantine']['optional_author_production_conflicts'] = optional_conflicts
                write(run/'preprocess/scope_validation.json',state['scope_quarantine'])
        if config.get('project_selection'):
            from .preprocessing.project_selection import validate_selection
            validate_selection(root, run)
        state.update(status='PREPROCESSED', counts=result['records_canonical'])
        seal(run)
        write(run_file(run, 'run.json'), state)
        if through == 'preprocessing':
            return dict(status='PREPROCESSED', run=str(run), counts=state['counts'], review=str(run / 'preprocess/review.json'), inference_calls=0)
        return knowledge(root, run)
    except Exception as exc:
        # Knowledge failures preserve a valid preprocessing checkpoint for resumption.
        if state.get('status') != 'PREPROCESSED':
            state.update(status='FAILED', error=str(exc))
            write(run_file(run, 'run.json'), state)
        write(run_file(run, 'failure.json'), {'stage': 'prepare', 'error': str(exc)})
        raise


def knowledge(root, run):
    import knowledge_store as store
    if store.run_state(run).get('knowledge_build'):
        builder = store.knowledge_root(run)
        result = knowledge(root, builder)
        _sync_shared_build(root, run, builder)
        return dict(result, run=str(run))
    state = check(root, run)
    if state['status'] == 'PREPARED':
        return dict(status='ALREADY_PREPARED', run=str(run))
    workspace = run / 'workspace'
    try:
        layer2 = yaml.safe_load(layer_config(root, 3).read_text(encoding='utf-8'))
        if state['configuration'].get('knowledge_scope')=='BASE_GLOBAL_V1':
            layer2['datasets']['articulos']['required_fields']=[f for f in layer2['datasets']['articulos']['required_fields'] if f!='title']
        # Append only fields explicitly selected by preprocessing, never arbitrary RAW keys.
        for dataset in ('proyectos', 'articulos'):
            for row in pq.read_table(workspace / f'outputs/layer2/canonical/{dataset}.parquet').to_pylist():
                for ref in json.loads(row['provenance_json']):
                    for field in ref.get('extra_text_fields', []):
                        if field not in layer2['datasets'][dataset]['text_fields']:
                            layer2['datasets'][dataset]['text_fields'].append(field)
        layer2['readiness']['approved_layer1_manifest_sha256'] = sha(workspace / 'outputs/layer2/canonical/_manifest.json')
        # Same approved transformations and thresholds; new snapshot is run-local.
        (workspace / 'config/layer2.yaml').write_text(yaml.safe_dump(layer2), encoding='utf-8')
        from layer2_processing.knowledge.pipeline import run as build_knowledge
        result = build_knowledge(workspace)
        state.update(status='PREPARED', counts=result['input_row_counts'], knowledge_counts={n: result[n + '_created'] for n in result['output_hashes']})
        seal(run)
        write(run_file(run, 'run.json'), state)
        return dict(status='PREPARED', run=str(run), counts=state['counts'], review=str(run / 'preprocess/review.json'), inference_calls=0)
    except Exception as exc:
        write(run_file(run, 'failure.json'), {'stage': 'knowledge', 'error': str(exc)})
        raise
