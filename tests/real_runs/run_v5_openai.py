"""Main V5 flow (menu-equivalent) for the 10+10 sample with the OpenAI provider.

Not a pytest module. Two modes:

  --simulate        No network and no credential: the `openai` SDK is replaced in-process by
                    a fake that answers from the request's own strict V5 schema with
                    synthetic, clearly marked responses (SIMULATED). It exercises the real
                    preparation, transport, ledger, validation, Python decision, confidence
                    and Excel export, and records the exact prepared input size (pinned Qwen
                    tokenizer) of every request. Its results are never real evaluations.

  --authorize-paid  Real Responses API calls (gpt-6.1-terra). Requires an explicit
                    --budget-usd, OPENAI_API_KEY (or the existing secure store) and the
                    institutional data authorization acknowledged by the operator.
                    --stop-after N writes the coordinator's stop.request.json after N
                    completed calls (controlled pause; resume with --resume).

Every other confirmation (for example a Knowledge rebuild) is answered NO. Resumable:
the same --run-id continues without repeating completed calls.
"""
import argparse
import hashlib
import json
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT), str(ROOT / 'scripts')]

SIMULATED = 'SIMULATED_RESPONSE_NOT_AN_EVALUATION'
FORCED_MODE = None


def tokenizer():
    from tokenizers import Tokenizer
    descriptor = json.loads((ROOT / 'config/qwen_tokenizer.json').read_text(encoding='utf-8'))
    return Tokenizer.from_file(str(ROOT / descriptor['path']))


def synthetic(schema, mode):
    """A schema-valid V5 answer. mode 0: nothing demonstrated; mode 1: first criterion CLEAR on F000."""
    item = schema['properties']['assessments']['items']
    props = item['properties']
    criteria = props['criterion_assessments']['items']['anyOf']
    ids = criteria[0]['properties']['criterion_id']['enum']
    fragments = criteria[0]['properties']['evidence_refs']['items']['properties']['fragment_id']['enum']
    rows = []
    for n, cid in enumerate(ids):
        if mode == 2 and fragments:
            # Majority CLEAR, remaining PARTIAL: exercises the V2 SUPPORTED export path.
            clear = n < len(ids) // 2 + 1
            rows.append(dict(criterion_id=cid, explanation=SIMULATED, support='CLEAR' if clear else 'PARTIAL',
                             coverage=4 if clear else 2, evidence_refs=[dict(fragment_id=fragments[0], stage='RESULT_EXPECTED')]))
            continue
        if mode == 1 and n == 0 and fragments:
            rows.append(dict(criterion_id=cid, explanation=SIMULATED, support='CLEAR', coverage=4,
                             evidence_refs=[dict(fragment_id=fragments[0], stage='RESULT_DEMONSTRATED')]))
        else:
            rows.append(dict(criterion_id=cid, explanation=SIMULATED, support='NOT_DEMONSTRATED', coverage=0, evidence_refs=[]))
    level = 3 if mode in (1, 2) else 0
    rubric = {k: level for k in ('directness', 'specificity', 'clarity', 'temporal_alignment')} | dict(explanation=SIMULATED)
    rubric = {k: rubric[k] for k in props['strength_rubric']['properties']}
    answer = dict(indicator_id=props['indicator_id']['const'], assessment_version=props['assessment_version']['const'],
                  criterion_assessments=rows, strength_rubric=rubric,
                  scope_exclusion=dict(explanation=SIMULATED, claimed=False, basis='NONE', evidence_refs=[]))
    return dict(project_id=schema['properties']['project_id']['const'], assessments=[{k: answer[k] for k in props}])


def install_fake_sdk(log):
    tok = tokenizer()

    class Responses:
        def create(self, **request):
            schema = request['text']['format']['schema']
            prompt = ''.join(m['content'] for m in request['input'])
            key = schema['properties']['project_id']['const'] + schema['properties']['assessments']['items']['properties']['indicator_id']['const']
            mode = FORCED_MODE if FORCED_MODE is not None else int(hashlib.sha256(key.encode()).hexdigest(), 16) % 2
            text = json.dumps(synthetic(schema, mode), ensure_ascii=False)
            usage = dict(input_tokens=len(tok.encode(prompt).ids) + len(tok.encode(json.dumps(schema, separators=(',', ':'))).ids),
                         output_tokens=len(tok.encode(text).ids), input_tokens_details=dict(cached_tokens=0),
                         output_tokens_details=dict(reasoning_tokens=0))
            log.append(dict(key=key, prompt_tokens=len(tok.encode(prompt).ids), **usage, max_output_tokens=request['max_output_tokens'],
                            reasoning=request['reasoning'], store=request['store'], model=request['model']))
            native = dict(id='sim_' + hashlib.sha256((key + str(len(log))).encode()).hexdigest()[:24], status='completed',
                          model=request['model'], usage=usage, simulated=SIMULATED)
            return SimpleNamespace(model_dump=lambda mode='json': native, output_text=text, id=native['id'], _request_id=None)

    class OpenAI:
        def __init__(self, **kwargs):
            assert kwargs.get('max_retries') == 0 and kwargs.get('base_url') == 'https://api.openai.com/v1'
            self.responses = Responses()

    fake = ModuleType('openai'); fake.OpenAI = OpenAI
    sys.modules['openai'] = fake
    import model_access
    model_access.api_key = lambda root: 'SIMULATED-NOT-A-CREDENTIAL'


def watch_and_stop(run_dir, limit, done):
    """Controlled pause after `limit` completed calls: the coordinator's own stop file."""
    import sqlite3
    ledger = None
    waited = 0
    while not done.is_set():
        if not run_dir.is_dir():
            waited += 2
            if waited > 3600:
                print(json.dumps(dict(stop_watch_error='Directorio del run no encontrado: ' + str(run_dir))), flush=True)
                return
        ledger = ledger or next(iter(run_dir.rglob('api-ledger.sqlite')), None)
        if ledger:
            with sqlite3.connect(ledger) as db:
                count = db.execute("SELECT COUNT(*) FROM requests WHERE state='COMPLETED'").fetchone()[0]
            if count >= limit:
                from run_paths import file_path
                stop = file_path(run_dir, 'stop.request.json')
                stop.parent.mkdir(parents=True, exist_ok=True)
                stop.write_text(json.dumps(dict(reason=f'Pausa controlada tras {count} llamadas completadas')), encoding='utf-8')
                print(json.dumps(dict(stop_requested_after=count)), flush=True)
                return
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--manifest', default='outputs/audits/ejecucion_openai_v5_20261119/manifiesto_muestra.json')
    parser.add_argument('--budget-usd', type=float, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--simulate', action='store_true')
    group.add_argument('--authorize-paid', action='store_true')
    parser.add_argument('--sources', choices=('projects', 'articles', 'all'), default='all',
                        help='Subconjunto del manifiesto a evaluar en este run (el alcance queda congelado en el run)')
    parser.add_argument('--projects', help='IDs de proyecto separados por comas (por defecto, los 10 del manifiesto)')
    parser.add_argument('--articles', help='IDs de articulo (EID original) separados por comas; por defecto, los del manifiesto')
    parser.add_argument('--indicators', help='Subconjunto de indicadores (solo pruebas acotadas)')
    parser.add_argument('--fake-pattern', choices=('mixed', 'majority'), default='mixed', help='Solo simulacion')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--stop-after', type=int)
    parser.add_argument('--log', help='JSON lines with the simulated requests (simulation only)')
    args = parser.parse_args()
    manifest = json.loads((ROOT / args.manifest).read_text(encoding='utf-8'))
    projects = [p['source_project_id'] for p in manifest['projects']]
    articles = [a['article_id'] for a in manifest['articles']]
    if args.sources == 'articles':
        raise SystemExit('El flujo principal evalua articulos junto a proyectos seleccionados; usar --sources all o projects')
    if args.sources == 'projects':
        articles = []
    if args.articles:
        articles = [a.strip() for a in args.articles.split(',') if a.strip()]
    if args.projects:
        wanted = [p.strip() for p in args.projects.split(',') if p.strip()]
        if not wanted or len(set(wanted)) != len(wanted) or any(p not in projects for p in wanted):
            raise SystemExit('--projects debe contener IDs unicos del manifiesto: ' + ', '.join(projects))
        projects = wanted
    log = []
    if args.simulate:
        global FORCED_MODE
        FORCED_MODE = 2 if args.fake_pattern == 'majority' else None
        install_fake_sdk(log)
    else:
        import model_access
        if not model_access.api_key(ROOT):
            raise SystemExit('Falta la clave: definir OPENAI_API_KEY en el entorno (no se imprime ni se guarda).')
    from experiment_runtime import options
    from scripts import pipeline_coordinator as engine
    token = options.set(dict(provider='openai', budget_usd=args.budget_usd))

    def confirm(kind, summary):
        print(json.dumps(dict(confirm=kind, **{k: summary.get(k) for k in ('provider', 'model', 'budget_usd', 'project_count',
                                                                             'article_count', 'destination', 'run_id')}),
                         ensure_ascii=False), flush=True)
        return kind == 'run'

    done = threading.Event()
    if args.stop_after and not args.simulate:
        _, _, runs = engine.configuration(ROOT, 'config/pipeline_manual.json')
        # OpenAI runs live under <runs>/api/<run_id> (run_paths: provider -> 'api').
        threading.Thread(target=watch_and_stop, args=(Path(runs) / 'api' / args.run_id, args.stop_after, done), daemon=True).start()
    started = time.perf_counter()
    try:
        result = engine.execute_pipeline(ROOT, source=None if args.resume else 'base', run_id=args.run_id, through='export',
            resume=args.resume, project_ids=None if args.resume else projects, article_ids=None if args.resume or not articles else articles,
            evaluation_mode=None if args.resume else 'prospective-v2', context_mode=None if args.resume else 'retrieved-graph',
            knowledge_action=None if args.resume else 'reuse', indicator_ids=None if args.resume or not args.indicators else args.indicators.split(','), single_authorization=True, confirm=confirm,
            notify=lambda e: print(json.dumps({k: e.get(k) for k in ('status', 'stage', 'message')}, ensure_ascii=False), flush=True))
    finally:
        done.set(); options.reset(token)
        if args.log and log:
            Path(args.log).write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in log) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=1, default=str)[:4000])
    print('seconds', round(time.perf_counter() - started, 1), 'simulated_calls', len(log))


if __name__ == '__main__':
    main()
