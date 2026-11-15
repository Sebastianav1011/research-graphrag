"""One storage resolver for current runs and immutable legacy locators."""
from pathlib import Path
import json
import re

BUCKETS=('local','api','anteriores')
FILES={
    **{name:'estado/'+name for name in ('execution.json','progress.json','.execution.lock','stop.request.json',
        'failure.json','worker.json','project_states.json','evaluation_readiness.json','discovery.json','discovery.binding.json')},
    **{name:'manifiestos/'+name for name in ('run.json','raw_manifest.json','prepared_hashes.json','model.binding.json',
        'runtime.manifest.json','reuse.json','export.json','evidence_lineage.json')},
    **{name:'grafo/'+name for name in ('graph_result.json','graph_validation.json','graph_configuration.json','discovery_candidates.parquet')},
    **{name:'logs/'+name for name in ('discovery.stdout.log','discovery.stderr.log')},
    **{name:'resultados/'+name for name in ('resultado_final.xlsx','resultado_final_indicadores.xlsx',
        'resultado_indicadores.xlsx','resultado_indicadores.pending.xlsx','resultado_final.receipt.json',
        'resultado_final_indicadores.receipt.json')},
}


def read_json(path,default=None):
    path=Path(path)
    if not path.exists():return {} if default is None else default
    return json.loads(path.read_text(encoding='utf-8-sig'))


def bucket(provider):
    return {'ollama':'local','openai':'api'}.get(provider,'anteriores')


def provider_of(run):
    values=set()
    for name in ('model.binding.json','execution.json','run.json','runtime.manifest.json','autonomous/main/manifest.json','manifest.json','corrected/manifest.json'):
        path=file_path(run,name)
        if not path.is_file():continue
        data=read_json(path)
        if not isinstance(data,dict):raise ValueError('Metadatos de proveedor invalidos')
        for item in (data,data.get('llm',{}),data.get('runtime',{}),data.get('configuration',{}).get('llm',{})):
            if item.get('provider'):values.add(item['provider'])
    if len(values)>1:raise ValueError('Proveedores contradictorios en el run')
    return next(iter(values),None)


def repo_of(run):
    for parent in [Path(run),*Path(run).parents]:
        if parent.name=='outputs':return parent.parent
    raise ValueError('Run fuera de outputs')


def relocate(path):
    """Apply only recorded, workspace-contained prefixes; never rewrite payloads."""
    path=Path(path).absolute()
    for parent in path.parents:
        if parent.name!='outputs':continue
        try:original_parts=path.relative_to(parent/'runs').parts
        except ValueError:continue
        if not original_parts or original_parts[0] in BUCKETS or original_parts[0].startswith('.'):continue
        root=parent.parent;registry=parent/'runs/.relocations.json'
        data=read_json(registry)
        for old,new in sorted(data.get('prefixes',{}).items(),key=lambda item:len(item[0]),reverse=True):
            old_path=root/old;new_path=(root/new).resolve()
            if not new_path.is_relative_to((parent/'runs').resolve()):raise ValueError('Relocacion fuera de runs')
            if not new_path.exists():continue
            if path==old_path or path.is_relative_to(old_path):
                path=new_path/path.relative_to(old_path)
                break
        # Safe fallback for code retaining a flat locator for a new unique ID.
        try:parts=path.relative_to(parent/'runs').parts
        except ValueError:continue
        if parts and parts[0] not in BUCKETS and not parts[0].startswith('.') and not (parent/'runs'/parts[0]).exists():
            matches=[parent/'runs'/group/parts[0] for group in BUCKETS if (parent/'runs'/group/parts[0]).is_dir()]
            if len(matches)>1:raise ValueError('Localizador legado ambiguo; indicar proveedor')
            if matches:path=matches[0].joinpath(*parts[1:])
    return path


def structured(run):
    run=Path(run)
    # Shared checkpoints retain the metadata layout of their sealed builder.
    if (run.parent.name == 'staging' and run.parent.parent.parts[-3:] == ('outputs', 'shared', 'base')):
        return True
    if (run.name == 'artifacts' and run.parent.parent.name == 'versions' and
            run.parent.parent.parent.parts[-3:] == ('outputs', 'shared', 'base')):
        return True
    return run.parent.name in BUCKETS and run.parent.parent.name=='runs' and run.parent.parent.parent.name=='outputs'


def file_path(run,name):
    run=relocate(run);name=str(name)
    target=run/(FILES.get(name,name) if structured(run) else name)
    legacy=run/name
    return legacy if target!=legacy and not target.exists() and legacy.is_file() else target


def resolve_file(path):
    path=relocate(path)
    # Some callers retain a complete historical root/file locator.
    if path.name in FILES and structured(path.parent):return file_path(path.parent,path.name)
    return path


def list_runs(root,runs=None):
    root=Path(root);runs=Path(runs) if runs is not None else root/'outputs/runs'
    found=[]
    if runs.exists():
        for path in sorted(runs.iterdir()):
            if not path.is_dir() or path.is_symlink():continue
            if path.name in BUCKETS:
                found.extend(p for p in sorted(path.iterdir()) if p.is_dir() and not p.name.startswith('.') and not p.is_symlink())
            elif not path.name.startswith('.'):found.append(path)
    previous=root/'outputs/pipeline_manual'
    if previous.exists():found.extend(p for p in sorted(previous.iterdir()) if p.is_dir() and not p.is_symlink())
    return found


def find_run(root,runs,name,provider=None):
    root=Path(root);runs=Path(runs)
    if not name or not re.fullmatch(r'[A-Za-z0-9_.+\-]{1,160}',name) or name in ('.','..'):
        raise ValueError('Identificador de ejecucion invalido')
    if provider is None:
        from experiment_runtime import options
        provider=options.get().get('provider')
    matches=[p for p in list_runs(root,runs) if p.name==name]
    if provider is not None:matches=[p for p in matches if provider_of(p)==provider]
    if len(matches)>1:raise ValueError('Run ID ambiguo; indicar --provider ollama u openai')
    if matches:return matches[0]
    if provider is None:
        from model_access import preferences
        provider=preferences(root)['provider']
    return runs/bucket(provider)/name


def runs_root(run):
    run=Path(run)
    return run.parent.parent if structured(run) else run.parent


def pinned_hash(root,files,path):
    """A relocation changes a locator, never the checksum accepted by a seal."""
    root=Path(root).resolve();path=resolve_file(path)
    exact=files.get(path.relative_to(root).as_posix())
    if exact is not None:return exact
    matches={value for name,value in files.items() if resolve_file(root/name)==path}
    if len(matches)>1:raise ValueError('Sellos contradictorios para la misma ruta')
    return next(iter(matches),None)
