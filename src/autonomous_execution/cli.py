"""Explicit lifecycle commands, no interactive prompts or implicit authorization."""
from run_paths import file_path as run_file
from datetime import datetime, timezone
from pathlib import Path

from . import lifecycle as l, store as s


def dispatch(root,args,coordinator):
    root=Path(root).resolve()
    # The advanced adaptive manifest protocol remains historically compatible.
    # New orthogonal modes use the current run/resume per-indicator pipeline.
    if (getattr(args,'evaluation_mode',None) not in (None,'demonstrated') or
            getattr(args,'context_mode',None) not in (None,'graphrag')):
        raise ValueError('Los modos prospectivo/descriptor completo se seleccionan con run y se conservan con resume; prepare/start mantiene el protocolo adaptativo historico')
    reuse=getattr(args,'reuse_run',None)
    if reuse:
        if args.command!='prepare' or not args.autonomous or not args.run_id or any((args.source,args.input_file,
                args.delivery,args.projects,args.project_id,getattr(args,'indicators',None),args.approve_build,
                args.authorize_llm,args.background,args.partial,args.acknowledge_uncertain,args.manifest_sha256,args.through)):
            raise ValueError('--reuse-run requiere prepare --autonomous --run-id nuevo, sin cambiar alcance ni autorizar')
        from .preparation_integrity import reuse_run
        policy=s.read(coordinator.within(root,args.policy))
        if policy.get('extends'):policy=s.read(coordinator.within(root,policy['extends']))
        return reuse_run(root,reuse,args.run_id,policy,batch_size=getattr(args,'batch_size',None) or 1)
    if args.authorize_llm or args.approve_build:
        raise ValueError('En modo autonomo se autoriza exclusivamente con authorize --manifest-sha256')
    if args.command not in ('prepare','authorize','start','resume','status','verify','export','retry-pending'):
        raise ValueError('Comando autonomo no admitido')
    if args.background and args.command not in ('start','resume'):
        raise ValueError('--background requiere start o resume autonomo')
    if args.manifest_sha256 and args.command!='authorize' or args.acknowledge_uncertain and args.command!='retry-pending' or args.partial and args.command!='export':
        raise ValueError('Opcion de autorizacion, recuperacion o exportacion en comando incorrecto')
    if args.policy!='config/autonomous.json' and args.command!='prepare':
        raise ValueError('La politica queda congelada en prepare; no se cambia al ejecutar')
    if args.command!='prepare' and not args.run_id:
        raise ValueError('--run-id obligatorio')
    indicators=getattr(args,'indicators',None)
    if indicators and args.command!='prepare':raise ValueError('--indicators solo en prepare; alcance congelado')
    if args.command in ('start','resume') and args.through not in (None,'evaluation','export'):
        raise ValueError('start/resume autonomo admite --through evaluation o export')
    _,_,runs=coordinator.configuration(root,args.config)
    name=args.run_id or ('run_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    l.safe_id(name);run=coordinator.find_run(root,runs,name)
    if args.command=='prepare':
        ids=args.projects.split(',') if args.projects is not None else args.project_id
        if ids is not None:
            ids=[value.strip() for value in ids]
            if not ids or any(not value for value in ids) or len(ids)!=len(set(ids)):
                raise ValueError('Proyectos unicos y no vacios requeridos')
        if args.projects is not None and args.project_id:
            raise ValueError('Usar --projects o --project-id')
        if not (run_file(run, 'run.json')).exists():
            sampling=dict(limit=getattr(args,'limit',None),all_projects=getattr(args,'all_projects',False),
                          seed=getattr(args,'seed',42),selection_manifest=getattr(args,'selection_manifest',None))
            if ids is None and not sampling['limit'] and not sampling['all_projects'] and not sampling['selection_manifest'] and not args.input_file and not args.delivery:
                raise ValueError('Seleccion explicita requerida: --limit N o --all')
            coordinator.execute_pipeline(root,config_path=args.config,source=args.source,run_id=name,
                through='knowledge',project_ids=ids,input_file=args.input_file,delivery=args.delivery,confirm=None,
                confirm_all=getattr(args,'confirm_all',False),evaluation_mode='demonstrated',context_mode='graphrag',**sampling)
            if not run_file(run,'run.json').exists():
                return dict(status='REVIEW_REQUIRED',note='Toda la base requiere --confirm-all; no se inicio preparacion')
        else:
            if getattr(args,'batch_size',None) is not None or getattr(args,'limit',None) is not None or getattr(args,'all_projects',False) or getattr(args,'selection_manifest',None):
                raise ValueError('Checkpoint existente: no cambiar muestreo ni tamano de lote; crear un run nuevo')
            state=coordinator.check(root,run)
            original=s.read(run_file(run, 'execution.json'))
            if ids is not None and ids!=original.get('project_ids'):
                raise ValueError('Seleccion distinta del checkpoint')
            if any(x is not None for x in (args.source,args.input_file,args.delivery)):
                chosen,raw,_=coordinator.selected_configuration(root,args.config,args.source,args.input_file,args.delivery)
                from layer2_processing.checkpoints import resolve
                if raw.resolve()!=resolve(root,state['raw_path']).resolve() or chosen.get('source_paths')!=state['configuration'].get('source_paths'):
                    raise ValueError('Fuentes distintas del checkpoint; no ampliar alcance')
            if state['status']!='PREPARED':
                coordinator.knowledge(root,run)
        discovered=None
        if indicators is None and not (l.folder(run)/'manifest.json').exists():
            from .discovery import prepare as discover
            discovered=discover(root,run)
        with coordinator.lock(run.parent), coordinator.lock(run):
            from .minimal import VERSION as MINIMAL
            return l.prepare(root,run,s.read(coordinator.within(root,args.policy)),evaluator=MINIMAL,
                indicator_ids=[i.strip() for i in indicators.split(',')] if indicators else None,
                discovery=discovered,batch_size=getattr(args,'batch_size',None) or 1)
    if any(x is not None for x in (args.source,args.input_file,args.delivery,args.projects,args.project_id)):
        raise ValueError('El alcance procede del manifiesto; no aceptar nuevos selectores al continuar')
    if args.command=='authorize':
        if not args.manifest_sha256:
            raise ValueError('Revisar manifest.json y proporcionar --manifest-sha256 exacto')
        return l.authorize(root,run,args.manifest_sha256)
    if args.command=='status':
        from .monitor import progress
        return progress(root,run)
    if args.command=='verify':
        return l.deep_verify(root,run)
    if args.command=='retry-pending':
        return l.retry_pending(root,run,acknowledge_uncertain=args.acknowledge_uncertain)
    if args.command=='export':
        return l.export(root,run,partial=args.partial)
    if args.background:
        return l.background(root,run,through=args.through or 'export',config_path=args.config)
    result=l.execute(root,run)
    if args.through in (None,'export') and 'export' not in result:
        result['export']=l.export(root,run,partial=result['status']!='COMPLETE')
    return result
