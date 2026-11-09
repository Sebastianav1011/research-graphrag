"""Interactive preparation adapter over the existing autonomous lifecycle.

Registration from scripts preserves entry points pinned by historical runs.
Only a new, interactive ``prepare --autonomous`` without source selectors is
handled here. Explicit commands and every existing run retain their dispatcher.
"""
from run_paths import file_path as run_file
from argparse import Namespace
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
import sys
from project_menu import select_projects, SelectionCancelled


Cancelled = SelectionCancelled


def choose(title, labels):
    if not labels:
        raise ValueError('No hay opciones disponibles: '+title)
    while True:
        print('\n'+title)
        for number,label in enumerate(labels,1):
            print(f'{number}. {label}')
        print('0. Cancelar')
        try:
            answer=input('Opcion: ').strip()
        except EOFError:
            raise Cancelled() from None
        if answer=='0':
            raise Cancelled()
        if answer.isascii() and answer.isdigit() and 1<=int(answer)<=len(labels):
            return int(answer)-1
        print('Opcion invalida; elija un numero de la lista.')


def select_indicators():
    """Historical regression helper; never invoked by the normal prepare menu."""
    return ('ASC-01,ECO-01,TEC-03' if choose('Indicadores a evaluar',[
        'Catalogo completo (48 indicadores)',
        'Prueba institucional pequena: ASC-01, ECO-01 y TEC-03'])==1 else None)


def incoming_entries(root):
    """Existing reader formats; refuse links, junction escapes and hidden paths."""
    from layer2_processing.preprocessing.adapters import READERS
    incoming=Path(root)/'data/layer1_sources/incoming'
    if incoming.is_symlink() or getattr(incoming,'is_junction',lambda:False)() or not incoming.is_dir() or not incoming.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('incoming no existe o esta redirigido fuera del repositorio')
    formats=set(READERS)|{'.docx','.pdf','.txt','.md'}
    files=[];folders=[]
    def visit(directory):
        found=[]
        for path in sorted(directory.iterdir(),key=lambda p:p.name.casefold()):
            if path.name.startswith(('.', '~$')) or path.is_symlink() or getattr(path,'is_junction',lambda:False)():
                continue
            if not path.resolve().is_relative_to(incoming.resolve()):
                continue
            if path.is_dir():
                children=visit(path)
                if children:
                    folders.append(path)
                    found.extend(children)
            elif path.is_file() and path.suffix.lower() in formats and path.name.lower()!='readme.md':
                found.append(path)
        return found
    files=visit(incoming)
    return incoming,sorted(files),sorted(folders)


def browse_file(root):
    incoming,files,_=incoming_entries(root)
    if not files:
        raise ValueError('No hay archivos compatibles en data/layer1_sources/incoming/')
    current=incoming
    while True:
        folders=sorted({current/relative.parts[0] for file in files
            if file.is_relative_to(current) and len((relative:=file.relative_to(current)).parts)>1})
        direct=[file for file in files if file.parent==current]
        entries=folders+direct
        labels=['[Carpeta] '+p.name for p in folders]+[p.name for p in direct]
        if current!=incoming:
            entries=[current.parent]+entries;labels=['[..] Subir carpeta']+labels
        selected=entries[choose('Archivo en incoming/'+current.relative_to(incoming).as_posix(),labels)]
        if selected.is_dir():
            current=selected
        else:
            return selected.relative_to(Path(root)).as_posix()


def select_source(root):
    mode=choose('Fuente documental',[
        'Base institucional completa','Archivo especifico','Entrega completa'])
    if mode==0:
        return dict(source='base',input_file=None,delivery=None)
    if mode==1:
        return dict(source=None,input_file=browse_file(root),delivery=None)
    incoming,_,folders=incoming_entries(root)
    # A delivery is an immediate child; descendants are included recursively.
    deliveries=[p for p in folders if p.parent==incoming]
    index=choose('Entregas disponibles en incoming', [p.name for p in deliveries])
    return dict(source=None,input_file=None,delivery=deliveries[index].relative_to(incoming).as_posix())


def available_projects(root,args,source,coordinator):
    """Read declared project IDs with native mappings and normalization only.

    No fuzzy association or new identity resolver. Canonical scope is checked
    again after preprocessing, before any manifest is produced.
    """
    from layer2_processing.preprocessing.adapters import discover_sources
    from layer2_processing.preprocessing.normalize import identifier
    config,raw,_=coordinator.selected_configuration(root,args.config,**source)
    discovery=discover_sources(root,config,raw)
    if discovery['status']!='READY_FOR_VALIDATION':
        invalid=[item['file']+': '+'; '.join(str(d) for d in item['diagnostics'])
                 for item in discovery['files'] if item['status']!='READY_FOR_VALIDATION']
        raise ValueError('Fuentes pendientes o invalidas; revisar los datos de: '+', '.join(invalid))
    projects=set()
    for item in discovery['files']:
        columns=item.get('mapping',{}).get('source_project_id',[])
        for record in item['records']:
            if item.get('project_contract'):
                projects.add(str(record['original_values']['id_actividad']))
                continue
            projects.update(value for column in columns
                if (value:=identifier(record['original_values'].get(column))))
    if not projects:
        raise ValueError('La fuente no contiene identificadores explicitos de proyectos evaluables; no se inventan asociaciones')
    return sorted(projects)


def review(manifest,digest,run):
    projects=list(manifest['selection']['project_ids'])
    indicators=list(manifest['profiles'])
    mode=manifest['selection']['mode']
    source={'file':'Archivo especifico','delivery':'Entrega completa'}.get(mode,'Base institucional completa')
    lines=['Resumen de ejecucion autonoma', 'Run: '+run.name, 'Fuente: '+source,
        'Archivos autorizables (SHA-256):']
    lines.append('  Cantidad: '+str(len(manifest['source_inventory']['files'])))
    lines.extend(['Proyectos seleccionados: '+str(len(projects)),
        f'Evaluaciones previstas: {len(projects)} x {len(indicators)} = {len(projects)*len(indicators)}',
        f'Catalogo: {len(indicators)} indicadores',
        'Modelo: '+manifest['llm']['model']+' mediante '+manifest['runtime']['provider'],
        'Politica: '+manifest['policy']['version']+'; GraphRAG y BGE-M3 locales; contexto adaptativo,',
        '  reintentos limitados, control de recursos, checkpoints por indicador y auditoria.',
        '  Una autorizacion cubre los proyectos y reintentos previstos; cambios de alcance se bloquean.',
        '  Los fallos pendientes se identifican; las exportaciones parciales se marcan incompletas.',
        'Prompts: '+manifest['prompts']['version']+'; esquema: '+manifest['schema_version'],
        'Resultados y exportacion: '+str(run),
        'Manifiesto: '+str(run/'autonomous/main/manifest.json'),
        'SHA-256: '+digest])
    if manifest.get('project_indicators'):
        lines=[line for line in lines if not line.startswith('Evaluaciones previstas:')]
        lines.insert(3,'Evaluaciones previstas: '+str(sum(map(len,manifest['project_indicators'].values()))))
    if manifest.get('discovery'):
        discovery=manifest['discovery']
        lines.insert(-1,'Descubrimiento automatico BGE-M3: '+str(discovery['considered_per_project'])+
            ' indicadores considerados por proyecto; admision PROVISIONAL, pendiente de revision humana.')
        lines.insert(-1,'Relaciones disponibles del grafo: '+str(discovery['graph_relations'])+
            '; seleccion y exclusiones documentadas en discovery.json. Seleccion no implica cumplimiento.')
    if manifest.get('evaluator'):
        lines.insert(-1,'Evaluador simplificado: una llamada; como maximo una aclaracion pertinente. Inconsistencias pendientes de revision, sin confianza ni PASS.')
    if manifest.get('batching'):
        lines.insert(-1,f"Lotes de hasta {manifest['batching']['size']} indicadores; contexto maximo 6144; validacion individual y llamadas compartidas contabilizadas una vez.")
    return '\n'.join(lines)+'\n'


def prepare(root,args,coordinator,original_dispatch):
    from . import lifecycle as l,store as s
    root=Path(root).resolve()
    source=select_source(root)
    _,_,runs=coordinator.configuration(root,args.config)
    name=args.run_id or ('run_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    l.safe_id(name);run=coordinator.find_run(root,runs,name)
    if run.exists():
        raise ValueError('El menu crea una ejecucion nueva; no modifica runs existentes')
    sampling=select_projects(getattr(args,'seed',42),root=root,coordinator=coordinator,config_path=args.config,
        allow_contracts=source.get('source')=='base')
    contract=sampling.pop('contract_metadata',None)
    if contract:
        from experiment_runtime import options
        options.set(dict(options.get(),contract=contract))
    indicator_ids=getattr(args,'indicators',None)
    print('\nPreparando datos locales. Run: '+name,flush=True)
    print('Si se interrumpe, conservar este ID y sus checkpoints.',flush=True)
    # Local ETL/BGE discovery precedes review. Qwen remains behind the explicit
    # manifest authorization; the normal menu never asks for indicator IDs.
    coordinator.execute_pipeline(root,config_path=args.config,run_id=name,through='knowledge',
        confirm=lambda kind,summary: input('Toda la base: '+str(summary)+'\nConfirmar [si/NO]: ').strip().lower()=='si',**sampling,**source)
    if not run_file(run,'run.json').exists():return dict(status='REVIEW_REQUIRED',note='Procesamiento de toda la base no confirmado')
    execution=s.read(run_file(run, 'execution.json'))
    selected=execution['project_ids']
    with coordinator.lock(run.parent),coordinator.lock(run):
        # This is a new run with no manifest/authorization/inferences yet. Bind
        # the evaluation subset using the same scope resolver as the CLI.
        execution['project_ids']=coordinator.scope_projects(root,run,execution['selection'],selected)
        execution['scope_resolved']=True
        s.write(run_file(run, 'execution.json'),execution)
    prepared_args=Namespace(**vars(args))
    prepared_args.run_id=name
    prepared_args.non_interactive=True
    prepared_args.indicators=indicator_ids
    prepared_args.limit=None
    prepared_args.all_projects=False
    result=original_dispatch(root,prepared_args,coordinator)
    directory=l.folder(run);manifest=s.read(directory/'manifest.json')
    digest=result['manifest_sha256']
    if s.sha(directory/'manifest.json')!=digest:
        raise ValueError('El manifiesto cambio antes de su revision')
    summary=review(manifest,digest,run)
    (directory/'review_summary.txt').write_text(summary,encoding='utf-8')
    print('\n'+summary)
    print('Puede conservar esta revision y autorizarla mas tarde con:')
    print(f'python run.py authorize --run-id {name} --manifest-sha256 {digest}')
    try:
        approval=input('Autorizar este manifiesto e iniciar en segundo plano [AUTORIZAR/Enter para dejar pendiente]: ').strip()
    except EOFError:
        approval=''
    if approval.casefold()!='autorizar':
        return result
    l.authorize(root,run,digest)
    return l.background(root,run,through='export',config_path=args.config)


def install():
    """Register the additive console adapter without changing pinned dispatchers."""
    from . import cli
    if getattr(cli.dispatch,'_prepare_menu',False):
        return
    original=cli.dispatch
    @wraps(original)
    def dispatch(root,args,coordinator):
        interactive=(args.command=='prepare' and args.autonomous and not args.non_interactive
            and not any(getattr(args,key) is not None for key in
                ('source','input_file','delivery','projects','project_id','limit','selection_manifest'))
            and not getattr(args,'all_projects',False)
            and not args.run_id and sys.stdin.isatty())
        if not interactive:
            return original(root,args,coordinator)
        # Let the existing dispatcher reject invalid flag combinations first.
        if args.approve_build or args.authorize_llm or args.background or args.partial or args.acknowledge_uncertain or args.manifest_sha256:
            return original(root,args,coordinator)
        try:
            return prepare(root,args,coordinator,original)
        except Cancelled:
            return dict(status='CANCELLED',note='Preparacion cancelada; no se autoriza ni inicia una ejecucion.')
    dispatch._prepare_menu=True
    cli.dispatch=dispatch
