"""Internal SAD layer 2 pipeline; isolated staging, canonical and knowledge checkpoints."""
from run_paths import file_path as run_file
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
    return state


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
    """Reuse an immutable compatible checkpoint; never reuse evaluations/selection."""
    if config.get('knowledge_scope')!='BASE_GLOBAL_V1':return False
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
    if action=='reuse':raise ValueError('No existe conocimiento global BASE compatible; elegir reconstruir o --knowledge-action rebuild')
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
