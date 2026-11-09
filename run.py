"""Console interface for the existing SAD pipeline coordinator."""
import argparse
import json
from pathlib import Path
import sys
from contextlib import contextmanager, ExitStack, redirect_stdout, redirect_stderr

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from run_paths import file_path as run_file
STAGES = ('preprocessing', 'knowledge', 'graphrag', 'evaluation', 'export')


@contextmanager
def visible_work(message):
    """Announce work synchronously; stage callbacks report actual progress.

    A timer must never write over input(), including later provider approvals.
    """
    print(message, flush=True)
    yield


def coordinator():
    sys.path.insert(0, str(ROOT / 'src'))
    from scripts import pipeline_coordinator
    return pipeline_coordinator


def show(value):
    from console_output import compact
    print(json.dumps(compact(value), ensure_ascii=False, indent=2, default=str))


def report_progress(event):
    status=event['status']
    if status=='INPUT_SUMMARY' and event.get('summary',{}).get('blocked_projects'):
        summary=event['summary']
        print('Proyectos bloqueados: '+str(len(summary['blocked_projects']))+'. Detalle: '+summary.get('report','estado del run'),flush=True)
    elif status=='REGISTERED':print('Run registrado: '+event['run_id'],flush=True)
    elif status=='RUNNING':print('Etapa: '+event['stage'],flush=True)
    elif status=='STAGE_REUSED':print('Checkpoint conservado: '+event['stage'],flush=True)
    elif status=='EVALUATION_PROGRESS':
        print(f"Proyectos: {event['projects_evaluated']}/{event['total_projects']} | "
              f"Indicadores evaluados: {event.get('indicators_completed',0)}",flush=True)
    elif status in ('FAILED_OR_BLOCKED','INTERRUPTED','REVIEW_REQUIRED','BUILD_APPROVAL_REQUIRED','BLOCKED_INPUT'):
        print(status+': '+event.get('error',event.get('message','Revisar los registros del run.')),flush=True)
        if event.get('resume_command'):print('Continuar: '+event['resume_command'],flush=True)


def render_result(result):
    status=result.get('status','UNKNOWN')
    if status=='CANCELLED':
        print('Ejecucion cancelada. No se inicio el procesamiento.',flush=True)
        return
    print('Estado: '+status,flush=True)
    if result.get('run_id'):print('Run ID: '+result['run_id'],flush=True)
    if result.get('error'):print('Error: '+result['error'],flush=True)
    if result.get('message'):print(result['message'],flush=True)
    if result.get('blocked_projects'):print('Proyectos bloqueados: '+str(len(result['blocked_projects'])),flush=True)
    excel=result.get('excel') or result.get('result',{}).get('excel')
    if excel:print('Resultados: '+str(Path(excel).parent),flush=True)
    elif result.get('results'):print('Resultados: '+str(result['results']),flush=True)
    if status not in ('COMPLETE','CANCELLED') and result.get('location'):
        print('Registros: '+result['location'],flush=True)


def render_error(exc):
    message=str(exc) or ('Entrada cerrada (EOF).' if isinstance(exc,EOFError) else type(exc).__name__)
    print('Error: '+message,flush=True)
    if getattr(exc,'resume_command',None):print('Continuar: '+exc.resume_command,flush=True)


def execute_with_console(engine, **kwargs):
    """Keep backend diagnostics in the registered run; UI stays on this thread."""
    import logging
    import traceback
    terminal_out,terminal_err=sys.stdout,sys.stderr
    latest={}
    log=None
    def handlers():
        loggers=[logging.getLogger()]+[value for value in logging.Logger.manager.loggerDict.values()
            if isinstance(value,logging.Logger)]
        return {handler for logger in loggers for handler in logger.handlers
            if isinstance(handler,logging.StreamHandler) and not isinstance(handler,logging.FileHandler)}
    with ExitStack() as stack:
        streams={}
        def restore_handlers():
            for handler in handlers():
                if handler.stream is log:
                    handler.setStream(streams.get(handler,terminal_err))
        def notify(event):
            nonlocal log
            latest.update(event)
            with redirect_stdout(terminal_out),redirect_stderr(terminal_err):report_progress(event)
            run=Path(event['location'])
            if (log is None and event['status'] in ('REGISTERED','RUNNING','STAGE_REUSED')
                    and run.is_dir() and run_file(run,'execution.json').is_file()):
                (run/'logs').mkdir(exist_ok=True)
                log=stack.enter_context((run/'logs/terminal.log').open('a',encoding='utf-8',buffering=1))
                stack.enter_context(redirect_stdout(log))
                stack.enter_context(redirect_stderr(log))
                for handler in handlers():
                    streams[handler]=handler.stream
                    handler.setStream(log)
                stack.callback(restore_handlers)
        def confirm(kind,summary):
            with redirect_stdout(terminal_out),redirect_stderr(terminal_err):return confirm_action(kind,summary)
        interactive=kwargs.pop('interactive',True)
        try:
            return engine.execute_pipeline(ROOT,notify=notify,confirm=confirm if interactive else None,**kwargs)
        except BaseException as exc:
            if log is not None:traceback.print_exc(file=log)
            if not getattr(exc,'resume_command',None):exc.resume_command=latest.get('resume_command')
            raise


def confirm_action(kind, summary):
    if kind=='run':
        print('\nRun ID: '+summary['run_id'],flush=True)
        print('Modelo: '+summary['provider']+' | '+summary['model'],flush=True)
        print('Proyectos: '+str(summary['project_count']),flush=True)
        print('Fuentes: '+('base' if all('/base/' in name or '/reference/' in name for name in summary['sources'])
            else ', '.join(summary['sources']))+f" ({len(summary['sources'])} archivos)",flush=True)
        contract=summary.get('contract')
        print('Contrato: '+(f"{contract['contract_id']}.v{contract['version']}" if contract else 'sin contrato'),flush=True)
        print('Procesamiento autonomo: '+' -> '.join(summary['stages']),flush=True)
        print('Destino: '+str(summary.get('destination')),flush=True)
        if summary['provider']=='openai':
            print('Envio externo a OpenAI. Presupuesto maximo: USD '+str(summary['budget_usd']),flush=True)
        else:print('Procesamiento local de los textos seleccionados.',flush=True)
        if not sys.stdin.isatty():
            print('Sin terminal interactiva: no se autoriza automaticamente.')
            return False
        return confirm_start()
    print('\n' + ('Revision de textos para el proveedor seleccionado' if kind == 'llm' else
        'Confirmar procesamiento de toda la base: tiempo y posible costo' if kind=='all' else 'Construccion local de GraphRAG'))
    show(summary)
    if not sys.stdin.isatty():
        print('Sin terminal interactiva: se conserva la revision pendiente; no se autoriza automaticamente.')
        return False
    try:
        return input('Tras revisar el archivo indicado, autorizar y continuar [si/NO]: ').strip().lower() in ('si', 'sí')
    except EOFError:
        return False


def selected_projects(args):
    if args.projects is not None and args.project_id:
        raise ValueError('Usar --projects o --project-id, no ambos')
    ids = args.projects.split(',') if args.projects is not None else args.project_id
    if ids is None:
        return None
    ids = [value.strip() for value in ids]
    if not ids or any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('Los identificadores deben ser unicos y no vacios; no se convierten a numeros')
    return ids


def dispatch(args):
    from experiment_runtime import options
    from model_access import change_model, configure_key
    if args.command=='cleanup':
        from run_storage import cleanup
        if not args.dry_run and not args.apply:raise ValueError('cleanup requiere --dry-run o --apply')
        if args.dry_run and args.apply:raise ValueError('Elegir --dry-run o --apply')
        def confirm_cleanup(rows):
            print(json.dumps(rows,ensure_ascii=False,indent=2))
            return input('Escribir ELIMINAR para borrar solo estos runs cerrados y archivados: ').strip()=='ELIMINAR'
        return cleanup(ROOT,apply=args.apply,confirm=confirm_cleanup)
    if args.command in ('migrate-runs','restore-run'):
        from run_storage import migrate,restore
        if args.command=='migrate-runs':return migrate(ROOT)
        if not args.run_id:raise ValueError('restore-run requiere --run-id')
        return restore(ROOT,args.run_id,args.provider)
    if args.require_evaluable and args.command!='contract-create':raise ValueError('--require-evaluable solo con contract-create; la regla queda congelada en el contrato')
    if args.command=='model':
        if args.provider:
            if args.provider=='openai':configure_key(ROOT)
            from model_access import save_preferences
            save_preferences(ROOT,args.provider)
        else:change_model(ROOT)
        return dict(status='COMPLETE',inference_calls=0)
    if args.command=='run' and not args.dry_run and args.through in (None,'evaluation','export'):
        from model_access import preferences,api_key
        provider=args.provider or preferences(ROOT)['provider']
        if provider=='openai' and not api_key(ROOT):
            if args.non_interactive:
                raise ValueError('API_KEY_MISSING: configurar con uv run python run.py model --provider openai')
            configure_key(ROOT)
    engine=coordinator()
    if args.reuse_run and args.provider:
        _,_,runs=engine.configuration(ROOT,args.config)
        source_run=engine.find_run(ROOT,runs,args.reuse_run)
        original=json.loads((run_file(source_run, 'execution.json')).read_text(encoding='utf-8'))
        if args.provider!=original.get('llm',{}).get('provider','ollama'):
            raise ValueError('--reuse-run conserva modelo y respuestas; para comparar usar --selection-run en un run nuevo')
    if args.command in ('contracts','contract-create'):
        from evaluation_contracts import menu as contract_menu,create,inventory,catalog_hash
        if args.command=='contracts':contract_menu(ROOT,engine,args.config)
        else:
            if not args.contract_name or not args.count:raise ValueError('--contract-name y --count son obligatorios')
            path=create(ROOT,args.contract_name,args.count,args.seed,inventory(ROOT,engine,args.config),catalog_hash(ROOT),require_evaluable=args.require_evaluable)
            return dict(status='COMPLETE',contract=str(path),inference_calls=0)
        return dict(status='COMPLETE',inference_calls=0)
    contract=getattr(args,'contract_metadata',None)
    if args.selection_run:
        if args.command not in ('run','prepare') or any((args.contract,args.projects,args.project_id,args.limit,args.all_projects,args.selection_manifest,args.input_file,args.delivery,args.additional_count,args.reuse_run)):
            raise ValueError('--selection-run requiere run/prepare nuevo sin otros selectores')
        from evaluation_contracts import load,resolve,inventory,catalog_hash
        _,_,runs=engine.configuration(ROOT,args.config)
        previous=engine.find_run(ROOT,runs,args.selection_run)
        stored=json.loads((run_file(previous, 'execution.json')).read_text(encoding='utf-8'))
        old=stored.get('evaluation_contract')
        if not old:raise ValueError('--selection-run requiere una ejecucion con contrato')
        name=old['contract_id'];version=old['version']
        from autonomous_execution.lifecycle import safe_id
        safe_id(name)
        value=load(ROOT/'data/contratos'/f'{name}.v{int(version)}.json')
        contract=resolve(value,inventory(ROOT,engine,args.config),catalog_hash(ROOT),old['additional_limit'])
        if contract!=old or contract['project_ids']!=stored['project_ids']:raise ValueError('Seleccion previa incompatible; no reproducir IDs alterados')
        args.project_id=contract['project_ids'];args.source='base'
    if args.contract:
        if args.command not in ('run','prepare') or any((args.projects,args.project_id,args.limit,args.all_projects,args.selection_manifest,args.input_file,args.delivery)):
            raise ValueError('--contract requiere run/prepare nuevo sin otros selectores')
        from evaluation_contracts import load,resolve,inventory,catalog_hash
        path=engine.within(ROOT,args.contract)
        contract=resolve(load(path),inventory(ROOT,engine,args.config),catalog_hash(ROOT),args.additional_count)
        args.project_id=contract['project_ids'];args.source='base'
    elif args.additional_count:raise ValueError('--additional-count requiere --contract')
    if args.command in ('stop','export'):
        if not args.run_id:raise ValueError('--run-id es obligatorio para stop/export')
        from run_control import request_stop,export_only
        _,_,runs=engine.configuration(ROOT,args.config)
        token=options.set(dict(provider=args.provider))
        try:
            run=engine.find_run(ROOT,runs,args.run_id)
            return request_stop(run) if args.command=='stop' else export_only(ROOT,run,engine)
        finally:options.reset(token)
    token=options.set(dict(provider=args.provider,budget_usd=args.budget_usd,contract=contract))
    try:
        if args.run_id:
            _,_,runs=engine.configuration(ROOT,args.config)
            run=engine.find_run(ROOT,runs,args.run_id)
            if (run_file(run, 'model.binding.json')).exists():
                from experiment_runtime import binding
                binding(ROOT,run,{})
            elif (run_file(run, 'execution.json')).exists() and args.provider:
                original=json.loads((run_file(run, 'execution.json')).read_text(encoding='utf-8'))
                if args.provider!=original.get('llm',{}).get('provider','ollama'):raise ValueError('Proveedor distinto del checkpoint historico; crear otro run')
        try:return dispatch_pipeline(args)
        except (ValueError,FileNotFoundError) as exc:
            if args.command!='status':raise
            from run_storage import status
            return status(ROOT,run,reason=str(exc))
    finally:options.reset(token)


def dispatch_pipeline(args):
    if getattr(args,'batch_size',None) is not None and (args.command!='prepare' or not args.autonomous):
        raise ValueError('--batch-size solo en prepare --autonomous; despues queda congelado')
    if getattr(args,'reuse_run',None) and (args.command!='prepare' or not args.autonomous):
        raise ValueError('--reuse-run solo en prepare --autonomous')
    engine = coordinator()
    sampling = args.limit is not None or args.all_projects or args.selection_manifest is not None
    if sampling and args.command == 'prepare' and args.autonomous and not args.dry_run:
        from autonomous_execution.cli import dispatch as autonomous_dispatch
        return autonomous_dispatch(ROOT,args,engine)
    if sampling or args.dry_run:
        if args.command != 'run':
            raise ValueError('--limit/--all/--dry-run/--selection-manifest se usan con run (o sin comando)')
        return execute_with_console(engine, config_path=args.config, source=args.source, run_id=args.run_id,
            through=args.through, project_ids=selected_projects(args), input_file=args.input_file, delivery=args.delivery,
            limit=args.limit, all_projects=args.all_projects, seed=args.seed, dry_run=args.dry_run,
            selection_manifest=args.selection_manifest, approve_build=args.approve_build, authorize=args.authorize_llm,
            confirm_all=args.confirm_all,
            single_authorization=True,
            interactive=not args.non_interactive)
    if args.command == 'run' and not any((args.projects, args.project_id, args.input_file, args.delivery)):
        raise ValueError('Indicar --limit N, --all o IDs explicitos; nunca se ejecuta toda la base por defecto')
    active_autonomous = False
    if args.run_id:
        _,_,runs=engine.configuration(ROOT,args.config)
        active_autonomous=(engine.find_run(ROOT,runs,args.run_id)/'autonomous/main/manifest.json').exists()
    if active_autonomous and args.command in ('run','stage'):
        raise ValueError('El run tiene un manifiesto autonomo; usar start/resume --autonomous')
    if args.command in ('prepare','authorize','start','export','retry-pending') or active_autonomous and args.command in ('resume','status','verify'):
        from autonomous_execution.cli import dispatch as autonomous_dispatch
        return autonomous_dispatch(ROOT,args,engine)
    if args.background or args.partial or args.acknowledge_uncertain or args.manifest_sha256:
        raise ValueError('Estas opciones requieren el modo autonomo explicito')
    if args.command == 'verify':
        return engine.verify_sources(ROOT, args.config, args.source, args.input_file, args.delivery)
    if args.command == 'status':
        return engine.execution_status(ROOT, args.config, args.run_id)
    if args.command in ('resume', 'stage') and not args.run_id:
        raise ValueError('--run-id es obligatorio para resume y stage')
    return execute_with_console(engine, config_path=args.config, source=args.source,
            run_id=args.run_id, stage=args.stage if args.command == 'stage' else None,
            through=args.through, resume=args.command == 'resume', approve_build=args.approve_build,
            authorize=args.authorize_llm, project_ids=selected_projects(args),
            input_file=args.input_file, delivery=args.delivery,
            single_authorization=True,
            interactive=not args.non_interactive)


def exit_code(result):
    if result['status'] in ('COMPLETE', 'VERIFIED', 'INVENTORY', 'READY_FOR_VALIDATION', 'AUTHORIZED', 'STARTED', 'VALIDATED_SELECTION','STOP_REQUESTED','DRY_RUN','CANCELLED'):
        return 0
    return 3  # Pending configuration, approval, partial results or an explicit block.


def parser():
    result = argparse.ArgumentParser(prog='uv run python run.py', description='GraphRag: ejecucion por capas SAD. Sin comando abre el menu.')
    result.add_argument('command', nargs='?', choices=('run', 'stage', 'resume', 'verify', 'status',
        'prepare','authorize','start','export','retry-pending','stop','model','contracts','contract-create','cleanup','migrate-runs','restore-run'))
    result.add_argument('--apply',action='store_true',help='cleanup: confirmar y aplicar solo eliminaciones verificadas')
    result.add_argument('--confirm-all',action='store_true',help='Confirmacion explicita previa para --all; mantiene las demas autorizaciones')
    result.add_argument('stage', nargs='?', choices=STAGES)
    result.add_argument('--run-id', help='Identificador nuevo o existente; obligatorio para stage/resume')
    result.add_argument('--provider',choices=('ollama','openai'),help='Proveedor; queda congelado por ejecucion')
    result.add_argument('--budget-usd',type=float,help='Presupuesto operativo API explicito; recomendado 15 USD')
    result.add_argument('--contract',help='JSON compartido en data/contratos; requiere ejecucion nueva')
    result.add_argument('--selection-run',help='Repite IDs obligatorios y adicionales de otro run con contrato; sin copiar respuestas')
    result.add_argument('--additional-count',type=int,default=0,help='Limite explicito de proyectos adicionales')
    result.add_argument('--contract-name',help='Nombre para contract-create')
    result.add_argument('--count',type=int,help='Proyectos obligatorios de contract-create')
    result.add_argument('--require-evaluable',action='store_true',help='contract-create: muestrear solo proyectos con texto sustantivo autorizado; regla persistida')
    result.add_argument('--source', help='all, base, incoming o incoming/<entrega>; reanudar conserva la seleccion original')
    result.add_argument('--config', default='config/pipeline_manual.json')
    result.add_argument('--through', choices=STAGES, help='Ultima etapa; run termina en export por defecto')
    result.add_argument('--project-id', action='append', help='Limita la evaluacion PROJECT; repetible, conserva el orden al reanudar')
    selection = result.add_mutually_exclusive_group()
    result.add_argument('--projects', help='IDs institucionales separados por comas; con --file limita la seleccion a ese archivo; sin --file usa base por defecto')
    sampling = result.add_mutually_exclusive_group()
    sampling.add_argument('--limit', type=int, help='Cantidad exacta de proyectos unicos; muestreo estratificado')
    sampling.add_argument('--all', dest='all_projects', action='store_true', help='Seleccion explicita de todos los proyectos')
    sampling.add_argument('--selection-manifest', help='Repite los IDs de un manifiesto con las mismas fuentes')
    result.add_argument('--seed', type=int, default=42, help='Semilla del muestreo (42 por defecto)')
    result.add_argument('--dry-run', action='store_true', help='Valida ETL y relaciones; sin embeddings, GraphRAG ni LLM')
    selection.add_argument('--file', dest='input_file', help='Archivo completo dentro de data/layer1_sources/base o incoming; no requiere IDs')
    selection.add_argument('--delivery', help='Nombre o ruta de una entrega completa dentro de incoming; no requiere IDs')
    result.add_argument('--non-interactive', action='store_true', help='No solicitar permisos por consola; detenerse en revisiones o permisos pendientes')
    result.add_argument('--approve-build', action='store_true', help='Autoriza embeddings locales; no permite descargar modelos')
    result.add_argument('--authorize-llm', action='store_true', help='Autoriza texto previamente revisado para el proveedor congelado del run')
    result.add_argument('--autonomous', action='store_true', help='run/resume ya son autonomos por defecto; prepare/start conservan el flujo avanzado de manifiestos y cola')
    result.add_argument('--json', action='store_true', help='Salida JSON completa para status')
    result.add_argument('--batch-size', type=int, choices=(1,2,3), help='prepare autonomo: maximo de indicadores por llamada (1 por defecto); 2/3 habilitan lotes experimentales')
    result.add_argument('--policy', default='config/autonomous.json', help='Politica para prepare; despues queda congelada')
    result.add_argument('--reuse-run', help='En prepare autonomo: reutiliza un run autorizado validado, sin inferencias')
    result.add_argument('--indicators', help='Solo depuracion/regresion: seleccion manual; omitir en el flujo normal de descubrimiento automatico')
    result.add_argument('--manifest-sha256', help='Hash del manifiesto revisado; obligatorio para authorize')
    result.add_argument('--partial', action='store_true', help='Exportacion explicitamente incompleta del modo autonomo')
    result.add_argument('--background', action='store_true', help='Inicia el worker autonomo autorizado en segundo plano, sin ventana')
    result.add_argument('--acknowledge-uncertain', action='store_true', help='Reencolar resultados inciertos tras comprobar que termino la llamada anterior')
    return result


def menu_selection(root, seed):
    """Collect options only; sampling and contract validation stay in dispatch."""
    while True:
        print('\n1. Seleccionar cantidad de proyectos.\n2. Procesar todos los proyectos.\n'
              '3. Utilizar contrato existente.\n0. Volver.')
        choice=input('Opcion: ').strip()
        if choice=='0':return None
        if choice=='2':return dict(all_projects=True)
        if choice=='1':
            while True:
                value=input('Cantidad de proyectos (0: volver): ').strip()
                if value=='0':break
                if value.isascii() and value.isdigit() and int(value)>0:return dict(limit=int(value),seed=seed)
                print('Ingrese una cantidad entera positiva.')
        elif choice=='3':
            paths=sorted((root/'data/contratos').glob('*.json'))
            if not paths:
                print('No hay contratos disponibles.')
                continue
            for number,path in enumerate(paths,1):print(f'{number}. {path.name}')
            while True:
                value=input('Contrato (0: volver): ').strip()
                if value=='0':break
                if value.isascii() and value.isdigit() and 1<=int(value)<=len(paths):
                    return dict(contract=paths[int(value)-1].relative_to(root).as_posix())
                print('Contrato invalido.')
        else:print('Opcion invalida.')


def menu(base):
    from model_access import label,change_model,preferences
    while True:
        print('\nGraphRAG\nModelo actual: '+label(ROOT,base.provider))
        print('\n1. Ejecutar sistema\n2. Cambiar modelo\n0. Salir')
        try:
            choice=input('Opcion: ').strip()
            if choice=='0':return 0
            if choice=='2':
                change_model(ROOT)
                base.provider=None
                continue
            if choice!='1':
                print('Opcion invalida.')
                continue
            selection=menu_selection(ROOT,base.seed)
            if selection is None:continue
            # A clean CLI request prevents advanced flags leaking into the menu.
            args=parser().parse_args(['run','--source','base','--through','export'])
            args.config=base.config
            args.provider=base.provider or preferences(ROOT)['provider']
            args.budget_usd=base.budget_usd
            args.autonomous=True
            for key,value in selection.items():setattr(args,key,value)
            if args.provider=='openai' and args.budget_usd is None:
                import math
                while True:
                    try:
                        args.budget_usd=float(input('Presupuesto operativo maximo USD (15): ').strip() or '15')
                        if math.isfinite(args.budget_usd) and args.budget_usd>0:break
                    except ValueError:pass
                    print('Presupuesto positivo requerido.')
            render_result(dispatch(args))
        except EOFError:
            print('Entrada cerrada (EOF). No se inicio otra ejecucion.',flush=True)
            return 2
        except Exception as exc:
            render_error(exc)


def confirm_start():
    while True:
        answer=input('¿Iniciar ejecución? (S/N): ').strip().casefold()
        if answer in ('s','si','sí'):return True
        if answer in ('n','no',''):return False
        print('Respuesta invalida. Escribir S o N.')


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if not args.command and (args.limit is not None or args.all_projects or args.selection_manifest or args.dry_run or args.contract or args.selection_run):
        args.command = 'run'
    if args.command == 'stage' and not args.stage:
        cli.error('stage requiere una etapa: ' + ', '.join(STAGES))
    if args.stage and args.command != 'stage':
        cli.error('La etapa posicional solo corresponde al comando stage; usar --through para run/resume')
    if args.command=='run':args.autonomous=True
    try:
        if not args.command:
            return menu(args)
        result = dispatch(args)
        if args.command=='status' and 'progress_scope' in result:
            if args.json:print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
            else:
                from autonomous_execution.monitor import render
                print(render(result))
            return 0
        if args.command in ('run','resume','stage') and not args.json:render_result(result)
        else:show(result)
        return exit_code(result)
    except KeyboardInterrupt:
        print('\nInterrumpido. Consultar status y reanudar el mismo --run-id; no borrar checkpoints.')
        return 130
    except Exception as exc:
        if args.json:show(dict(status='FAILED_OR_BLOCKED',error_type=type(exc).__name__,error=str(exc)))
        else:render_error(exc)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
