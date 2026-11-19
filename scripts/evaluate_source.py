"""SOURCE_EVALUATION_V1: evaluate one PROJECT or ARTICLE from the active BASE Knowledge.

Only orchestration lives here. Retrieval (published query cache, own passages only),
context packing (V5), transport, localized retry, deterministic decision, validation
and confidence are the existing production components, unchanged:

  scoped_retrieval.from_published_cache -> context_budget.prepare_contexts (V5)
  -> OllamaAssessmentProvider (P2 targeted merge) -> live.resolve_wrapper/check_wrapper
  -> live.indicator_row (unchanged confidence formula)

No embeddings are generated and no evidence is borrowed from other sources:
ARTICLE sources receive no relational context. Ollama calls are preceded by a
free-RAM check; API calls require --authorize-api and an explicit --budget-usd.

Usage (dry run = prepare and seal requests, zero model calls):
  uv run python scripts/evaluate_source.py --source-type article --source-id ART_2-s2.0-... --dry-run
"""
import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import pyarrow.parquet as pq  # noqa: E402

from layer4_evaluation import live_execution as live  # noqa: E402
from layer4_evaluation.indicators import assessment_v3 as v3, prospective_v2 as p2  # noqa: E402
from layer4_evaluation.indicators import context_budget as cb, evidence_references as refs  # noqa: E402
from layer4_evaluation.indicators import scoped_retrieval as sr  # noqa: E402
from layer4_evaluation.indicators.ollama_provider import (OllamaAssessmentProvider, OllamaClient,  # noqa: E402
    OllamaError, P2_TARGETED_VERSION, configuration, create_client)
from layer4_evaluation.indicators.selection import FIELDS, canonical_hash  # noqa: E402

VERSION = 'SOURCE_EVALUATION_V1'
# ARTICLE abstract enters through the existing text__ mechanism (substantive,
# original name kept): same text, same section/chunk IDs, mapping recorded.
from layer4_evaluation.indicators.article_sources import FIELD_MAP as ARTICLE_FIELD_MAP, resolve as resolve_articles  # noqa: E402
MIN_FREE_MIB = 2048
OUT = ROOT / 'outputs/runs/source_evaluation'
CODE = ['scripts/evaluate_source.py', *(f'src/layer4_evaluation/indicators/{n}.py' for n in (
    'prospective_v2', 'context_budget', 'evidence_references', 'ollama_provider', 'retry_review',
    'scoped_retrieval', 'selection', 'assessment_v3')), 'src/layer4_evaluation/live_execution.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def free_mib():
    """Available physical memory (Windows GlobalMemoryStatusEx; /proc/meminfo elsewhere)."""
    import ctypes
    if hasattr(ctypes, 'windll'):
        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total', ctypes.c_ulonglong),
                        ('available', ctypes.c_ulonglong), ('page_total', ctypes.c_ulonglong),
                        ('page_available', ctypes.c_ulonglong), ('virtual_total', ctypes.c_ulonglong),
                        ('virtual_available', ctypes.c_ulonglong), ('extended', ctypes.c_ulonglong)]
        status = Status(); status.length = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError('No se pudo medir la memoria disponible')
        return status.available / 2 ** 20
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) / 1024
    raise OSError('No se pudo medir la memoria disponible')


def knowledge():
    active = json.loads((ROOT / 'outputs/shared/base/active.json').read_text(encoding='utf-8'))
    workspace = ROOT / 'outputs/shared/base/versions' / active['version_id'] / 'artifacts/workspace'
    if not (workspace / 'outputs/layer3/publication/_manifest.json').is_file():
        raise ValueError('Knowledge BASE activo sin publicacion GraphRAG verificada')
    return workspace, active


def load_source(workspace, kind, source_id):
    """Canonical source with its original IDs, sections and field provenance; nothing inferred."""
    canonical, base = workspace / 'outputs/layer2/canonical', workspace / 'outputs/layer2/knowledge'
    if kind == 'project':
        rows = pq.read_table(canonical / 'proyectos.parquet').to_pylist()
        row = next((r for r in rows if source_id in (r['source_project_id'], r['project_id'])), None)
        if row is None:
            raise ValueError('Proyecto inexistente en el Knowledge activo: ' + source_id)
        sid, stype = row['project_id'], 'PROJECT'
        identifiers = dict(siap_id=row['source_project_id'])
    else:
        rows = pq.read_table(canonical / 'articulos.parquet').to_pylist()
        # Same identity rules as the main flow: canonical ID or EID; DOI only when unique.
        resolved = resolve_articles(rows, [source_id])[0]
        row = next(r for r in rows if r['article_id'] == resolved)
        if row is None:
            raise ValueError('Articulo inexistente en el Knowledge activo: ' + source_id)
        sid, stype = row['article_id'], 'ARTICLE'
        identifiers = {k: row.get(k) for k in ('doi', 'eid', 'journal', 'publication_year', 'document_type')}
    sections = pq.read_table(base / 'source_sections.parquet', filters=[('source_id', '=', sid)]).to_pylist()
    if any(s['source_type'] != stype for s in sections):
        raise ValueError('Secciones con tipo de fuente distinto del registro canonico')
    if stype == 'ARTICLE':
        sections = [dict(s, field_name=ARTICLE_FIELD_MAP.get(s['field_name'], s['field_name'])) for s in sections]
    fields = dict.fromkeys(FIELDS, '')
    for s in sections:
        name = s['field_name']
        if name in FIELDS or name.startswith('text__'):
            fields[name] = s['text_original'] or ''
    provenance = {s['field_name']: dict(section_id=s['section_id'], text_hash_original=s['text_hash_original'],
                                        provenance=json.loads(s['provenance_json'] or 'null')) for s in sections}
    source = dict(project_id=sid, source_type=stype, fields=fields)
    meta = dict(source_type=stype, source_id=sid, record_source=row.get('record_source'),
                field_mapping=ARTICLE_FIELD_MAP if stype == 'ARTICLE' else {},
                source_row=row.get('source_row'), field_provenance=provenance, **identifiers)
    return source, sections, meta


def pinned_tokenizer():
    """Same verification as pipeline_coordinator.pinned_tokenizer: SHA-256 pinned, no model loaded."""
    descriptor = json.loads((ROOT / 'config/qwen_tokenizer.json').read_text(encoding='utf-8'))
    path = (ROOT / descriptor['path']).resolve()
    if not path.is_file() or sha(path) != descriptor['sha256']:
        raise ValueError('Tokenizer Qwen fijado ausente o distinto de config/qwen_tokenizer.json')
    return descriptor | dict(path=str(path))


def settings_for(provider, budget):
    llm = json.loads((ROOT / 'config/pipeline_manual.json').read_text(encoding='utf-8'))['llm']
    if provider == 'ollama':
        return configuration(llm)
    if budget is None or budget <= 0:
        raise ValueError('API requiere --budget-usd explicito y positivo')
    local = {k: v for k, v in llm.items() if k not in ('provider', 'model', 'endpoint', 'temperature', 'seed',
                                                      'keep_alive', 'expected_quantization')}
    return configuration(dict(local, provider='openai', api=dict(budget_usd=budget)))


def prepare(args):
    workspace, active = knowledge()
    source, sections, meta = load_source(workspace, args.source_type, args.source_id)
    frozen = json.loads(live.FROZEN.read_text(encoding='utf-8'))
    wanted = sorted(frozen['profiles']) if args.indicators == 'all' else args.indicators.split(',')
    if any(i not in frozen['profiles'] for i in wanted):
        raise ValueError('Indicador fuera del catalogo congelado')
    policy = v3.evaluation_policy('prospective-v2', 'retrieved-graph', base=True)
    rubrics, derivation = v3.catalog_for_mode(frozen['profiles'], frozen['rubrics'], policy['evaluation_mode'])
    profiles = {i: frozen['profiles'][i] for i in wanted}
    rubrics = {i: rubrics[i] for i in wanted}
    if not any(v.strip() for k, v in source['fields'].items() if k in v3.substantive_fields(source['fields'])):
        return dict(source=source, meta=meta, profiles=profiles, rubrics=rubrics, policy=policy, requests={},
                    status='NO_AUTHORIZED_SUBSTANTIVE_TEXT', active=active)
    # Ranking only reads id/type/source/field of foreign chunks; full text is loaded
    # only for this source's own passages (the only possible evidence).
    chunks = sr.load_chunks(workspace, [source['project_id']])
    if source['source_type'] == 'ARTICLE':
        from layer4_evaluation.indicators.article_sources import mapped
        chunks = mapped(chunks, {source['project_id']})
    relational = (sr.project_relations(workspace, [source]) if source['source_type'] == 'PROJECT' else None)
    candidates, retrieval = sr.from_published_cache(workspace, [source], profiles, chunks, relational)
    # Requests are sealed with the local settings for both providers so that the
    # evidence, instructions and schema are identical across Qwen and the API.
    local = settings_for('ollama', None)
    tokenizer = pinned_tokenizer()
    requests, report = cb.prepare_contexts([source], profiles, rubrics, local, candidates, chunks, sections,
        evidence_references=True, assessment_version=p2.VERSION, evaluation_mode=p2.MODE,
        context_mode=v3.RETRIEVED_CONTEXT, relational_contexts=relational, tokenizer=tokenizer, prompt_version=p2.PROMPT)
    return dict(source=source, meta=meta, profiles=profiles, rubrics=rubrics, policy=policy, derivation=derivation,
                requests=requests[source['project_id']], report=report, retrieval=retrieval, status='READY', active=active)


class GuardedOllama(OllamaClient):
    """Refuses a local inference when free RAM is below the reserve; never unloads other apps."""
    def request(self, method, path, payload=None):
        if path == '/api/chat' and free_mib() < MIN_FREE_MIB:
            raise OllamaError('RESOURCE_GUARD', f'Memoria libre {free_mib():.0f} MiB < {MIN_FREE_MIB} MiB; sin envio')
        return super().request(method, path, payload)


def evaluate(args):
    prepared = prepare(args)
    source, meta = prepared['source'], prepared['meta']
    run = OUT / args.run_id
    if (run / 'plan.json').exists() and json.loads((run / 'plan.json').read_text(encoding='utf-8'))['provider'] != args.provider:
        raise ValueError('Run existente con otro proveedor: usar un run separado')
    settings = settings_for(args.provider, args.budget_usd)
    plan = dict(version=VERSION, run_id=args.run_id, created_at=datetime.now(timezone.utc).isoformat(),
        provider=args.provider, settings=settings, source=meta, fields_present=sorted(k for k, v in source['fields'].items() if v),
        knowledge=prepared['active'], evaluation_policy=prepared['policy'], prompt_version=p2.PROMPT,
        component_protocol=p2.DERIVED_PROTOCOL, correction_protocol=P2_TARGETED_VERSION, corrective_retries=1,
        article_source_note_sha256=hashlib.sha256(p2.ARTICLE_SOURCE_NOTE.encode()).hexdigest()
            if source['source_type'] == 'ARTICLE' else None,
        catalog_sha256=canonical_hash(dict(profiles=prepared['profiles'], rubrics=prepared['rubrics'])),
        indicators=sorted(prepared['profiles']), status=prepared['status'],
        request_sha256={i: canonical_hash(r) for i, r in prepared['requests'].items()},
        context_status={i: r['context_selection']['status'] for i, r in prepared['requests'].items()},
        retrieval=prepared.get('retrieval'), code={c: sha(ROOT / c) for c in CODE}, model_calls_planned=0)
    plan['model_calls_planned'] = sum(s == 'READY' for s in plan['context_status'].values())
    write(run / 'plan.json', plan)
    for iid, request in prepared['requests'].items():
        write(run / 'requests' / (iid + '.json'), request)
    if args.dry_run or prepared['status'] != 'READY':
        return plan
    if args.provider == 'openai' and not args.authorize_api:
        raise ValueError('Llamadas API facturables requieren --authorize-api y --budget-usd explicitos')
    model_plan = dict(profiles=prepared['profiles'], rubrics=prepared['rubrics'], assessment_version=p2.VERSION,
                      evaluation_policy=prepared['policy'], runtime=dict(provider=args.provider))
    project = dict(project_id=source['project_id'], fields=source['fields'])
    client = GuardedOllama(settings) if args.provider == 'ollama' else create_client(settings)
    if args.provider == 'ollama' and free_mib() < MIN_FREE_MIB:
        raise ValueError(f'Memoria libre insuficiente antes de iniciar Qwen: {free_mib():.0f} MiB')
    runtime = client.inspect()
    results = {}
    for iid, request in sorted(prepared['requests'].items()):
        target = run / 'results' / (iid + '.json')
        if target.exists():  # Resume: never repeat a persisted evaluation.
            results[iid] = json.loads(target.read_text(encoding='utf-8')); continue
        status = request['context_selection']['status']
        if status != 'READY':
            results[iid] = dict(indicator_id=iid, status='NOT_EVALUATED_' + status, calls=0)
            write(target, results[iid]); continue
        calls = run / 'calls' / iid
        schema = refs.response_schema(request, source['fields'])
        write(calls / 'schema.json', schema)
        provider = OllamaAssessmentProvider(calls / 'runs', calls / 'schema.json', lambda p, ids, r=request: r,
            settings=settings, runtime=runtime, client=client, max_indicators=1, corrective_retries=1,
            token_limit_retries=settings['token_limit_retries'], correction_version=P2_TARGETED_VERSION,
            wrapper_validator=lambda w, pid, ids, r=request: live.check_wrapper(model_plan, project, r, pid, ids, w),
            wrapper_resolver=lambda w, r=request: live.resolve_wrapper(model_plan, project, r, w))
        try:
            provider.evaluate(project, [prepared['profiles'][iid]])
            row = live.indicator_row(model_plan, project, provider.last_output['assessments'][0])
            results[iid] = dict(indicator_id=iid, status=row['decision'], calls=len(provider.calls),
                                row=dict(row, source_type=source['source_type'], source_id=source['project_id']))
        except OllamaError as error:
            if error.code == 'RESOURCE_GUARD':
                raise  # Not an evaluation outcome: stop and keep everything resumable.
            results[iid] = dict(indicator_id=iid, status='BLOCKED_ERROR', calls=len(provider.calls),
                                error_code=error.code, error=str(error)[:500])
        write(target, results[iid])
    summary = dict(plan=plan['run_id'], provider=args.provider, model=settings['model'], source=meta['source_id'],
        source_type=meta['source_type'], counts={s: sum(r['status'] == s for r in results.values())
            for s in sorted({r['status'] for r in results.values()})},
        calls=sum(r['calls'] for r in results.values()), free_mib_after=round(free_mib()))
    write(run / 'summary.json', summary)
    with (run / 'results.csv').open('w', encoding='utf-8', newline='') as stream:
        out = csv.writer(stream)
        out.writerow(['source_type', 'source_id', 'indicator_id', 'status', 'confidence_raw_score', 'calls',
                      'evidence_fields', 'evidence_texts'])
        for iid, r in sorted(results.items()):
            row = r.get('row', {})
            out.writerow([meta['source_type'], meta['source_id'], iid, r['status'], row.get('confidence_raw_score'),
                          r['calls'], '|'.join(row.get('evidence_source_fields', [])),
                          ' || '.join(row.get('evidence_texts', []))])
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--source-type', choices=('project', 'article'), required=True)
    parser.add_argument('--source-id', required=True, help='SIAP/project_id, o article_id/EID/DOI')
    parser.add_argument('--indicators', default='all', help='all o lista separada por comas')
    parser.add_argument('--provider', choices=('ollama', 'openai'), default='ollama')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--dry-run', action='store_true', help='Preparar y sellar solicitudes sin llamadas al modelo')
    parser.add_argument('--budget-usd', type=float)
    parser.add_argument('--authorize-api', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(evaluate(args), ensure_ascii=False, indent=2, default=str)[:4000])


if __name__ == '__main__':
    main()
