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


def check(root, run):
    state = read(run_file(run, 'run.json'))
    from .checkpoints import resolve
    raw = resolve(root, state['raw_path'])
    verify_raw(raw, read(run_file(run, 'raw_manifest.json'))['files'], state['configuration'].get('source_paths'))
    selection = state['configuration'].get('project_selection')
    if selection:
        for name, fingerprint in selection['sources'].items():
            if not (root / name).is_file() or sha(root / name) != fingerprint:
                raise ValueError('Fuente del manifiesto de seleccion modificada: ' + name)
    for name, fingerprint in state['code_hashes'].items():
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
    state = dict(run_id=run.name, dataset=dataset, raw_path=raw.relative_to(root).as_posix(),
        status='PREPARING', started_at=datetime.now(timezone.utc).isoformat(), configuration=config, code_hashes=code_hashes(root))
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
