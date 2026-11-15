"""Prepare a two-pair pilot offline; inference requires the explicit execute command.

Uses the real live_execution transport, validators, confidence and thesis exports.
Replays the sealed retrieved evidence, not previous model answers. Never builds,
activates or searches Knowledge, and never visits other historical runs.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from layer4_evaluation import live_execution as live, thesis_output as output
from layer4_evaluation.indicators import assessment_v3 as v3, context_budget as cb
from layer4_evaluation.indicators import evidence_references as refs, prospective_v2 as p2
from layer4_evaluation.indicators.experiment_inputs import read, sha256
from layer4_evaluation.indicators.review import evidence_locations
from layer4_evaluation.indicator_csv import write_results

REFERENCE_ID = 'run_20261115_063255_909981'
REFERENCE = ROOT / 'outputs/runs/local' / REFERENCE_ID
KNOWLEDGE_ID = '78420dc8b249600b-9558d0f0'
DEFAULT_OUTPUT = ROOT / 'outputs/pilotos/prospective_v2_tec04'
BATCH = 'batch_pilot_tec04'
PAIRS = (('21869', 'TEC-04'), ('21844', 'TEC-04'))
SOURCE_BATCHES = {'21869': 'batch_3a13cbb2d0f30a20', '21844': 'batch_162fbf47e55a989c'}
PROTOCOL = 'TWO_PAIR_PROSPECTIVE_V2_PILOT_V1'
CODE_FILES = (
    'scripts/pilot_prospective_v2.py', 'src/layer4_evaluation/live_execution.py',
    'src/layer4_evaluation/indicators/assessment_v3.py', 'src/layer4_evaluation/indicators/assessment_v2.py',
    'src/layer4_evaluation/indicators/prospective_v2.py', 'src/layer4_evaluation/indicators/confidence.py',
    'src/layer4_evaluation/indicators/context_budget.py', 'src/layer4_evaluation/indicators/evidence_references.py',
    'src/layer4_evaluation/indicators/ollama_provider.py', 'src/layer4_evaluation/indicators/selection.py',
    'src/layer4_evaluation/indicators/validation_diagnostics.py', 'src/layer4_evaluation/indicators/token_budget.py',
    'src/layer4_evaluation/indicators/review.py', 'src/layer4_evaluation/indicators/performance.py',
    'src/layer4_evaluation/indicators/experiment_inputs.py', 'src/layer4_evaluation/thesis_output.py',
    'src/layer4_evaluation/indicators/prompt.py', 'src/layer4_evaluation/indicators/contracts.py',
    'src/layer4_evaluation/indicator_csv.py', 'config/qwen_tokenizer.json',
)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def checked_output(path):
    path = Path(path).resolve()
    parent = (ROOT / 'outputs/pilotos').resolve()
    if path == parent or not path.is_relative_to(parent):
        raise ValueError('La salida debe ser una subcarpeta de outputs/pilotos; nunca un run historico.')
    return path


def validate_scope(plan):
    actual = {(p['siap_id'], iid) for p in plan['projects']
              for iid in plan['context_requests'][p['project_id']]}
    closure = plan.get('pilot', {}).get('scope') == 'NEGATIVE_CLOSURE_V1'
    pairs = {('21844', 'TEC-04')} if closure else set(PAIRS)
    if (actual != pairs or len(plan['projects']) != (1 if closure else 2) or plan['indicator_selection'] != ['TEC-04'] or
            plan['assessment_version'] != p2.VERSION or plan['evaluation_policy']['evaluation_mode'] != p2.MODE or
            plan['evaluation_policy']['context_mode'] != v3.RETRIEVED_CONTEXT or
            plan['requested_model'] != 'qwen3.5:4b-q4_K_M' or plan['runtime']['provider'] != 'ollama' or
            plan['pilot']['knowledge_ref']['version_id'] != KNOWLEDGE_ID or plan['maximum_calls'] != (2 if closure else 4) or
            plan['corrective_retries'] != 1 or plan['token_limit_retries'] != 1):
        raise ValueError('Alcance/configuracion del piloto alterados; no se despacha.')


def prepare_closure(output_dir):
    """Seal only 21844 from the existing pilot; never revisit historical runs."""
    output_dir = checked_output(output_dir)
    directory = configure(output_dir)
    if directory.exists():
        plan = live.check(directory)
        validate_scope(plan)
        return plan
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError('Salida de cierre no vacia')
    source_path = ROOT / 'outputs/pilotos/prospective_v2_tec04_r2/evaluation' / BATCH / 'plan.json'
    plan = deepcopy(read(source_path))
    project = next(p for p in plan['projects'] if p['siap_id'] == '21844')
    pid = project['project_id']
    old = plan['context_requests'][pid]['TEC-04']
    request = cb.make_request(project, plan['profiles']['TEC-04'], plan['rubrics']['TEC-04'], project['fields'],
        evidence_references=True,
        evidence_units=[dict(field=f['field'], text=f['text']) for f in old['payload']['project']['fragments']],
        assessment_version=p2.VERSION, evaluation_mode=p2.MODE, context_mode=v3.RETRIEVED_CONTEXT,
        prompt_version=p2.PROMPT)
    request['payload']['relational_context'] = deepcopy(old['payload']['relational_context'])
    request['prompt'] = request['prompt'].split('INPUT_JSON:\n', 1)[0] + cb.RELATIONAL_INSTRUCTIONS + 'INPUT_JSON:\n' + cb.compact(request['payload'])
    if request['payload'] != old['payload']:
        raise ValueError('El cierre debe conservar exactamente la evidencia del piloto')
    for key in ('context_selection', 'relational_context_receipt'):
        request[key] = deepcopy(old[key])
    request['context_budget'] = cb.rebudget(request['prompt'], refs.response_schema(request, project['fields']),
        plan['runtime']['configuration'], old['context_budget'])
    if not request['context_budget']['fits']:
        raise ValueError('El cierre no cabe en el presupuesto original')
    plan.update(execution_id=uuid.uuid4().hex, run_id=output_dir.name,
        projects=[project], context_requests={pid: {'TEC-04': request}}, maximum_calls=2,
        total_token_reservation_cap=2 * plan['runtime']['configuration']['num_ctx'],
        evaluation_policy=v3.evaluation_policy('prospective-v2', 'retrieved-graph', base=True),
        source_hashes={f: sha256(ROOT / f) for f in CODE_FILES})
    plan['source_hashes'][source_path.relative_to(ROOT).as_posix()] = sha256(source_path)
    plan['pilot'].update(scope='NEGATIVE_CLOSURE_V1',
        baseline=[b for b in plan['pilot']['baseline'] if b['siap_id'] == '21844'])
    validate_scope(plan)
    review = dict(scope='NEGATIVE_CLOSURE_V1', maximum_native_calls=2,
        evaluation_policy=plan['evaluation_policy'], evidence_unchanged=True)
    for name, value in (('plan.json', plan), ('review.json', review), ('cache.json', {}),
                        ('context_selection.json', request['context_selection'])):
        write(directory / name, value)
    (directory / 'review.txt').write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
    write(directory / 'manifest.json', dict(plan_sha256=sha256(directory / 'plan.json'),
        evaluation_policy_sha256=plan['evaluation_policy']['sha256'], files={f: sha256(directory / f)
            for f in ('review.json', 'review.txt', 'cache.json', 'context_selection.json')}))
    live.check(directory)
    return plan


def configure(output_dir):
    live.BASE = output_dir / 'evaluation'
    return live.BASE / BATCH


def prepare(output_dir):
    """Only local formatting, hashes and token counting. No client is constructed."""
    output_dir = checked_output(output_dir)
    directory = configure(output_dir)
    if directory.exists():
        plan = live.check(directory)
        validate_scope(plan)
        return plan  # A sealed review is never overwritten.
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError('Salida no vacia; elegir otra subcarpeta para conservar comparabilidad.')
    state = read(REFERENCE / 'manifiestos/run.json')
    knowledge = state['knowledge_ref']
    if knowledge['version_id'] != KNOWLEDGE_ID:
        raise ValueError('El run de referencia no utiliza el Knowledge solicitado.')
    registry_path = ROOT / 'outputs/shared/base/versions' / KNOWLEDGE_ID / 'manifest.json'
    registry = read(registry_path)
    if sha256(registry_path) != knowledge['manifest_sha256'] or registry['version_id'] != KNOWLEDGE_ID:
        raise ValueError('Manifiesto de Knowledge distinto del sellado en el run de referencia.')
    builder = (ROOT / registry['location']).resolve()
    # Check only the identified manifest bytes. Do not traverse raw data, graphs,
    # vectors, model weights, incoming, or an unrelated builder/run.
    inputs = [REFERENCE / 'manifiestos/run.json', registry_path]
    for relative, expected in (
        ('workspace/outputs/layer2/knowledge/_manifest.json', knowledge['knowledge_manifest_sha256']),
        ('workspace/outputs/layer3/publication/_manifest.json', knowledge['publication_manifest_sha256'])):
        manifest = builder / relative
        if sha256(manifest) != expected:
            raise ValueError('Manifiesto publicado distinto: ' + relative)
        inputs.append(manifest)
    policy = v3.evaluation_policy('prospective-v2', 'retrieved-graph', base=True)
    projects, requests, baseline, selections = [], {}, [], []
    original = None
    for siap_id, iid in PAIRS:
        source_dir = REFERENCE / 'evaluation' / SOURCE_BATCHES[siap_id]
        source = read(source_dir / 'plan.json')
        if original is None:
            original = source
            rubrics, derivation = v3.catalog_for_mode(source['profiles'], source['rubrics'], p2.MODE)
        elif source['profiles'] != original['profiles'] or source['rubrics'] != original['rubrics']:
            raise ValueError('Los dos lotes no comparten el catalogo congelado.')
        project = deepcopy(next(p for p in source['projects'] if p['siap_id'] == siap_id))
        pid = project['project_id']
        old = source['context_requests'][pid][iid]
        relation = old['payload'].get('relational_context')
        if (old['context_mode'] != v3.RETRIEVED_CONTEXT or old['context_selection']['status'] != 'READY' or
                not relation or relation['knowledge_manifest_sha256'] != knowledge['knowledge_manifest_sha256'] or
                relation['graph_manifest_sha256'] != knowledge['publication_manifest_sha256']):
            raise ValueError('Contexto recuperado no corresponde al Knowledge/politica solicitados.')
        units = [{'field': f['field'], 'text': f['text']} for f in old['payload']['project']['fragments']]
        request = cb.make_request(project, source['profiles'][iid], rubrics[iid], project['fields'],
            evidence_references=True, evidence_units=units, assessment_version=p2.VERSION,
            evaluation_mode=p2.MODE, context_mode=v3.RETRIEVED_CONTEXT, prompt_version=p2.PROMPT)
        if request['payload']['project']['fragments'] != old['payload']['project']['fragments']:
            raise ValueError('El transporte ha cambiado los fragmentos originales; revisar antes de inferir.')
        request['payload']['relational_context'] = deepcopy(relation)
        prefix = request['prompt'].split('INPUT_JSON:\n', 1)[0] + cb.RELATIONAL_INSTRUCTIONS
        request['prompt'] = prefix + 'INPUT_JSON:\n' + cb.compact(request['payload'])
        schema = refs.response_schema(request, project['fields'])
        settings = source['runtime']['configuration']
        request['context_budget'] = cb.rebudget(request['prompt'], schema, settings, old['context_budget'])
        if not request['context_budget']['fits']:
            raise ValueError('El contexto V2 no cabe; no se modifica la evidencia para hacerlo caber.')
        request['context_selection'] = deepcopy(old['context_selection'])
        request['context_selection']['replayed_from'] = str(source_dir / 'context_selection.json')
        request['relational_context_receipt'] = deepcopy(old['relational_context_receipt'])
        old_call = source_dir / 'calls' / pid / 'assessment_45'
        old_rows = old_call / 'assessment.rows.json'
        saved = read(old_rows)['rows']
        if len(saved) != 1 or saved[0]['indicator_id'] != iid:
            raise ValueError('Referencia anterior ambigua.')
        baseline.append(dict(siap_id=siap_id, indicator_id=iid, row=saved[0],
            call_directory=str(old_call), old_rows_sha256=sha256(old_rows)))
        inputs.extend([source_dir / 'plan.json', old_rows])
        inputs.extend(old_call.glob('assessment/ollama_runs/*/attempt_*/response.raw.txt'))
        inputs.extend(old_call.glob('assessment/ollama_runs/*/attempt_*/validation.json'))
        requests[pid] = {iid: request}
        projects.append(project)
        selections.append(dict(project_id=pid, indicator_id=iid, status='READY',
            evidence_unchanged=True, relations_unchanged=True, budget=request['context_budget']))
    settings = original['runtime']['configuration']
    for path in inputs:
        if not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('Referencia fuera del repositorio.')
    hashes = {f: sha256(ROOT / f) for f in CODE_FILES}
    hashes.update({p.relative_to(ROOT).as_posix(): sha256(p) for p in inputs})
    reservation = settings['num_ctx'] * 2  # Initial response + at most one retry.
    plan = dict(version='MANUAL_RAW_V3_3_OLLAMA_V1', execution_id=uuid.uuid4().hex,
        run_id=output_dir.name, projects=projects, profiles=deepcopy(original['profiles']), rubrics=rubrics,
        rules=deepcopy(original['rules']), observed_character_ratio=original['observed_character_ratio'],
        discovery_version=original['discovery_version'], assessment_version=p2.VERSION,
        confidence_version=v3.SK_CONFIDENCE_VERSION, coverage_policy=v3.PARTIAL_COVERAGE,
        request_protocol=cb.VERSION, context_requests=requests, indicator_selection=['TEC-04'],
        isolate_indicator_errors=True, corrective_retries=1, correction_protocol=p2.CORRECTION,
        token_limit_retries=1, runtime=deepcopy(original['runtime']), requested_model=settings['model'],
        maximum_calls=4, total_token_reservation_cap=4 * settings['num_ctx'], timeout_seconds=settings['timeout_seconds'],
        source_hashes=hashes, territories=[], evaluation_policy=policy, catalog_derivation=derivation,
        budgets=dict(assessment_reservation=reservation, assessment_postcall_review_threshold=reservation),
        pilot=dict(version=PROTOCOL, reference_run=REFERENCE_ID, knowledge_ref=deepcopy(knowledge),
            evidence_policy='EXACT_REPLAY_OF_VERIFIED_RETRIEVED_FRAGMENTS_AND_RELATIONS',
            baseline=baseline, inference_performed=False))
    validate_scope(plan)
    review = dict(pairs=list(PAIRS), policy=policy, contexts=selections,
        maximum_native_calls=4, maximum_retries_per_pair=1, inference_performed=False,
        note='Preparacion local; solo execute inicia Qwen. No se reconstruye ni vuelve a recuperar evidencia.')
    write(directory / 'plan.json', plan)
    write(directory / 'review.json', review)
    (directory / 'review.txt').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    write(directory / 'cache.json', {})
    write(directory / 'context_selection.json', dict(requests=selections))
    write(directory / 'manifest.json', dict(plan_sha256=sha256(directory / 'plan.json'),
        evaluation_policy_sha256=policy['sha256'], files={f: sha256(directory / f)
            for f in ('review.json', 'review.txt', 'cache.json', 'context_selection.json')}))
    live.check(directory)
    write(output_dir / 'preparacion.json', dict(status='PREPARED_NOT_EXECUTED', version=PROTOCOL,
        pairs=list(PAIRS), knowledge_id=KNOWLEDGE_ID, evaluation_mode=p2.MODE,
        plan_sha256=sha256(directory / 'plan.json'), maximum_native_calls=4))
    (output_dir / 'comparacion.md').write_text('# Piloto preparado, sin ejecutar\n\n'
        'No existen resultados nuevos de Qwen. El comando execute generara aqui la comparacion con el run de referencia.\n', encoding='utf-8')
    return plan


def criterion_summary(row, rubric):
    if row is None:
        return None
    judgments = {c['criterion_id']: c for c in row['criterion_assessments']}
    levels = {s: [cid for cid, c in judgments.items() if c['support'] == s]
              for s in ('CLEAR', 'PARTIAL', 'NOT_DEMONSTRATED')}
    blocked = [c['criterion_id'] for c in rubric['criteria'] if c['role'] == 'REQUIRED'
               and judgments[c['criterion_id']]['support'] != 'CLEAR']
    groups = {c['alternative_group'] for c in rubric['criteria'] if c['role'] == 'ALTERNATIVE'}
    blocked_groups = [g for g in groups if not any(c['alternative_group'] == g and
        judgments[c['criterion_id']]['support'] == 'CLEAR' for c in rubric['criteria'])]
    criteria = {c['criterion_id']: c for c in rubric['criteria']}
    return dict(levels=levels, required_blockers=blocked, alternative_blockers=blocked_groups,
        judgments=[dict(c, criterion=criteria[c['criterion_id']]['criterion'], role=criteria[c['criterion_id']]['role'])
            for c in row['criterion_assessments']], decision=row['decision'], confidence=row['confidence_raw_score'])


def compare(old, new, rubric):
    before, after = criterion_summary(old, rubric), criterion_summary(new, rubric)
    if new is None:
        interpretation = 'SIN_RESULTADO_VALIDO: no atribuir un fallo tecnico a rechazo semantico.'
    else:
        unchanged = before['levels'] == after['levels'] and old['decision'] == new['decision']
        interpretation = ('MISMOS_JUICIOS_Y_DECISION: comprobar si las justificaciones repiten la exigencia de ejecucion.' if unchanged
            else 'CAMBIO_DE_JUICIO_O_DECISION: verificar citas, mecanismo, destinatarios y etapas; no implica correccion demostrada.')
    return dict(previous=before, new=after, interpretation=interpretation,
        documentary_correctness='PENDING_HUMAN_REVIEW')


def report(output_dir, execution_error=None):
    directory = configure(checked_output(output_dir))
    plan = live.check(directory)
    validate_scope(plan)
    state = live.verify_run(directory)  # Persisted transports; no client or inference.
    results, records, coverage = [], [], []
    text = ['# Comparación del piloto PROSPECTIVE_V2', '',
        'Pares sellados: ' + ', '.join(p['siap_id'] + '/TEC-04' for p in plan['projects']) + '. Misma evidencia del piloto. ',
        'NONE se muestra como NOT_DEMONSTRATED. Un cambio a SUPPORTED no demuestra corrección documental.', '']
    if execution_error:
        text += ['Error de ejecución: ' + execution_error, '']
    for baseline in plan['pilot']['baseline']:
        siap_id, iid = baseline['siap_id'], baseline['indicator_id']
        project = next(p for p in plan['projects'] if p['siap_id'] == siap_id)
        verified = next(s for s in state['projects'] if s['project_id'] == project['project_id'])
        row = next((r for r in verified['rows'] if r['indicator_id'] == iid), None)
        calls = directory / 'calls' / project['project_id']
        attempts = []
        for call_dir in sorted(calls.glob('assessment_*')):
            for attempt in sorted((call_dir / 'assessment/ollama_runs' / project['project_id']).glob('attempt_*')):
                attempts.append(dict(directory=str(attempt),
                    response_original=str(attempt / 'response.raw.txt'),
                    native_response=str(attempt / 'native_response.json'),
                    validation=read(attempt / 'validation.json') if (attempt / 'validation.json').exists() else None))
        comparison = compare(baseline['row'], row, plan['rubrics'][iid])
        usage = [u for u in state['usage'] if u['project_id'] == project['project_id'] and iid in u.get('indicator_ids', [])]
        technical = ('VALID' if row else verified['blocked_indicators'].get(iid) or
            verified.get('context_limits', {}).get(iid) or 'PENDING')
        item = dict(siap_id=siap_id, indicator_id=iid, technical_status=technical,
            **comparison, applicability=row.get('applicability') if row else None,
            evidence=[dict(field=f, text=t, stage=s) for f, t, s in zip(row['evidence_source_fields'],
                row['evidence_texts'], row['evidence_stages'])] if row else [],
            baseline_directory=baseline['call_directory'], attempts=attempts,
            usage=usage,
            previous_evidence=[dict(field=f, text=t, stage=s) for f, t, s in zip(
                baseline['row']['evidence_source_fields'], baseline['row']['evidence_texts'], baseline['row']['evidence_stages'])],
            explanation=row['evidence_explanation'] if row else None)
        results.append(item)
        coverage.append(dict(siap_id=siap_id, indicator_id=iid, status=technical,
            decision=row['decision'] if row else None, confidence=row['confidence_raw_score'] if row else None))
        if row:
            assessment = live.assessment_from_row(row)
            records.append(output.indicator_record(project, iid, row=row, locations=evidence_locations(project, assessment)))
        text += [f'## {siap_id}/{iid}', '',
            f"Anterior: {baseline['row']['decision']}; confianza {baseline['row']['confidence_raw_score']}.",
            f"Nuevo: {row['decision'] if row else technical}; confianza {row['confidence_raw_score'] if row else 'N/A (sin evaluacion valida)'}.",
            comparison['interpretation'], '']
        for title, key in (('Anterior', 'previous'), ('Nuevo', 'new')):
            value = comparison[key]
            if value:
                text += [f"{title}: CLEAR={value['levels']['CLEAR']}; PARTIAL={value['levels']['PARTIAL']}; NONE={value['levels']['NOT_DEMONSTRATED']}.",
                    f"Esenciales sin CLEAR: {value['required_blockers']}; grupos alternativos bloqueados: {value['alternative_blockers']}."]
                text += [f"- {c['criterion_id']} ({c['role']}, {c['support']}) — {c['criterion']}: {c['explanation']}" for c in value['judgments']]
        text += ['', 'Aplicabilidad: ' + json.dumps(item['applicability'], ensure_ascii=False),
            'Justificación nueva: ' + (item['explanation'] or 'Sin evaluación válida.'), '']
        for title, evidence in (('Evidencia utilizada antes', item['previous_evidence']), ('Evidencia utilizada ahora', item['evidence'])):
            text += [title + ':']
            for e in evidence:
                text += [f"- [{e['field']} / {e['stage']}] {e['text']}"]
        text += ['', f"Respuesta anterior y trazas: [{baseline['call_directory']}]({Path(baseline['call_directory']).as_posix()}).", '']
        for original in ([] if plan['pilot'].get('scope') == 'NEGATIVE_CLOSURE_V1' else
                         sorted(Path(baseline['call_directory']).glob('assessment/ollama_runs/*/attempt_*/response.raw.txt'))):
            text += [f'- Respuesta anterior original: [{original.parent.name}]({original.as_posix()}).']
        text += ['', 'Llamadas, reintentos y errores técnicos: ' + json.dumps(usage, ensure_ascii=False), '']
        for attempt in attempts:
            text += [f"- Respuesta original: [{Path(attempt['response_original']).parent.name}]({Path(attempt['response_original']).as_posix()}).",
                '  Validación: ' + json.dumps(attempt['validation'], ensure_ascii=False)]
        text += ['', 'Revisión humana pendiente: confirmar que las citas pertenecen al proyecto, describen un mecanismo y respaldan los criterios; no basta la etiqueta o confianza.', '']
    result = dict(version=PROTOCOL, status=state['status'], execution_error=execution_error,
        reference_run=REFERENCE_ID, knowledge_id=KNOWLEDGE_ID, comparisons=results,
        native_calls=state['new_calls'], maximum_native_calls=plan['maximum_calls'],
        documentary_correctness='PENDING_HUMAN_REVIEW')
    write(output_dir / 'comparacion.json', result)
    (output_dir / 'comparacion.md').write_text('\n'.join(text) + '\n', encoding='utf-8')
    write(output_dir / 'resultados/estado_indicadores.json', dict(status=state['status'], indicators=coverage))
    write(output_dir / 'resultados/evaluaciones_validas.json', dict(status=state['status'], assessments=[
        dict(r, siap_id=p['siap_id']) for p in plan['projects'] for s in state['projects'] if s['project_id'] == p['project_id'] for r in s['rows']]))
    output.render(ROOT, output_dir / 'resultados/resultado_indicadores.xlsx', records, contract=output.PROSPECTIVE_CONTRACT)
    write_results(output_dir, output.GENERAL_COLUMNS, records, {})
    return result


def execute(output_dir):
    directory = configure(checked_output(output_dir))
    plan = live.check(directory)
    validate_scope(plan)
    # The manual command is the only authority to start inference. Preparation
    # creates neither authorization.json nor provider.json nor dispatch claims.
    error = None
    try:
        live.execute(SimpleNamespace(run=BATCH, authorize=True))
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    result = report(output_dir, error)
    return 0 if result['status'] == 'COMPLETE' and error is None else 3


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'prepare-closure', 'execute', 'report'))
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    destination = checked_output(args.output)
    if args.command == 'prepare-closure':
        if destination == DEFAULT_OUTPUT:
            raise ValueError('El cierre requiere otra carpeta mediante --output')
        prepare_closure(destination)
        print('CLOSURE_PREPARED_NOT_EXECUTED: ' + str(destination))
        return 0
    if args.command == 'prepare':
        prepare(destination)
        print('PREPARED_NOT_EXECUTED: ' + str(destination))
        return 0
    if args.command == 'report':
        report(destination)
        print(str(destination / 'comparacion.md'))
        return 0
    return execute(destination)


if __name__ == '__main__':
    raise SystemExit(main())
