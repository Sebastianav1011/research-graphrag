"""Prepare ONE reviewed corrective attempt, offline. Never dispatch inference.

This deliberately supports only a batch whose first and only call was a complete
invalid assessment. Successful, uncertain, or already recovered batches fail closed.
Original bytes and authorizations are archived and checked on every later resume.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from run_paths import file_path as run_file
sys.path.insert(0, str(ROOT))
from layer4_evaluation import live_execution as live
from layer4_evaluation.indicators import assessment_v3 as v3
from layer4_evaluation.indicators.context_budget import estimate
from layer4_evaluation.indicators.ollama_provider import strict_json
from layer4_evaluation.indicators.selection import canonical_hash
from layer4_evaluation.indicators.validation_diagnostics import semantic_issues
from jsonschema import Draft202012Validator
from layer2_processing.checkpoints import resolve, registry, verify_expected

# Exact pre-fix versions supported by this narrow checkpoint migration.
BASELINE = {
    'src/layer4_evaluation/live_execution.py': 'ad9b3bdb527fdede6ef56903383659b8a6725bd5bad2e08cb420703703db7217',
    'src/layer4_evaluation/indicators/ollama_provider.py': 'b31fc51aef63077f2beea87629de9bddd5750cd2f3c1a39009f99d76e3cf4e97',
    'src/layer4_evaluation/indicators/assessment_v3.py': 'e5586ae13d5942e5f3588888edc3c7fc1ec11c5023bbeb898c682d883138b867',
}
CORRECTION = '''
REINTENTO: evidence_indices usa indices base cero de evidence: con 2 citas solo
existen 0 y 1. Verifica cada indice. NOT_SUPPORTED exige todos NOT_DEMONSTRATED;
CLEAR/PARTIAL contradicen esa decision. Reevalua segun rubrica, sin inventar citas.
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(root, directory, *, apply=False):
    root, directory = root.resolve(), directory.resolve()
    live.require(directory.is_relative_to(root/'outputs/runs') and not directory.is_symlink(), 'Lote fuera de outputs/runs')
    live.require(not (directory/'recovery.pending.json').exists(), 'Recuperacion incompleta; conservar archivos para revision')
    plan = live.read(directory/'plan.json')
    live.require(not plan.get('recovery'), 'Limite de un reintento correctivo alcanzado')
    manifest = live.read(directory/'manifest.json')
    live.require(digest(directory/'plan.json') == manifest['plan_sha256'], 'Plan modificado')
    live.verify_hashes(directory, manifest['files'])
    def migrated_hashes(hashes):
        result = dict(hashes)
        bindings = registry(root).get('runtime_bindings', {})
        for name, old in hashes.items():
            path = resolve(root, name)
            canonical = path.relative_to(root).as_posix()
            if canonical not in BASELINE:
                verify_expected(root, name, old)
                continue
            binding = bindings.get(name, bindings.get(canonical, {}))
            snapshots = binding.get('snapshots', [binding.get('snapshot')])
            original_verified = (old == BASELINE[canonical] or
                binding.get('after_sha256') == BASELINE[canonical] and any(
                    s and (root/s).is_file() and digest(root/s) == old for s in snapshots))
            live.require(original_verified or digest(path) == old, 'Cambio de codigo no permitido: '+name)
            result[name] = digest(path)
        return result
    new_sources = migrated_hashes(plan['source_hashes'])
    run = directory.parents[3]
    run_state = live.read(run_file(run, 'run.json'))
    new_code = migrated_hashes(run_state['code_hashes'])
    siblings = []
    for other in directory.parent.glob('batch_*'):
        if other == directory:
            continue
        old_plan = live.read(other/'plan.json')
        old_manifest = live.read(other/'manifest.json')
        live.require(not (other/'recovery.pending.json').exists() and
            not (other/'authorization.json').exists() and not list((other/'calls').rglob('dispatch.claim.json')) and
            not live.read(other/'cache.json'), 'Otro lote con autorizacion/llamadas requiere migracion independiente: '+other.name)
        live.require(digest(other/'plan.json') == old_manifest['plan_sha256'], 'Plan vecino modificado')
        live.verify_hashes(other, old_manifest['files'])
        old_plan['source_hashes'] = migrated_hashes(old_plan['source_hashes'])
        siblings.append((other, old_plan, old_manifest))
    live.require(not live.read(directory/'cache.json'), 'No migrar cache previo')
    claims = list((directory/'calls').rglob('dispatch.claim.json'))
    live.require(len(claims) == 1, 'Recuperacion puntual requiere exactamente una llamada previa')
    out = claims[0].parent
    cp = live.read(out/'plan.json')
    live.require(cp['phase'] == 'assessment' and len(cp['indicator_ids']) == 1, 'Solo assessment individual')
    pid, ids = cp['project_id'], cp['indicator_ids']
    record = live.read(out/'records/assessment'/(pid+'.json'))
    live.verify_hashes(out, record['artifact_hashes'])
    verification = live.read(out/'verification.json')
    live.require(record['status'] == 'ERROR' and verification['status'] == 'BLOCKED_ERROR' and len(record['calls']) == 1, 'Resultado previo no recuperable')
    call = record['calls'][0]
    live.require(call['exit_status'] == 'INVALID_ASSESSMENT', 'No reintentar transporte, interrupciones o resultado incierto')
    attempt = out/'assessment/ollama_runs'/pid/'attempt_1'
    live.require(live.read(attempt/'call.json') == call, 'Metadatos diferentes')
    native = live.read(attempt/'native_response.json')
    live.require(native.get('done') is True and native.get('done_reason') == 'stop', 'Respuesta incompleta')
    project = next(p for p in plan['projects'] if p['project_id'] == pid)
    request = live.request_for(plan, project, 'assessment', ids)
    live.require(cp['run_plan_sha256'] == digest(directory/'plan.json') and
        cp['request_sha256'] == record['request_sha256'] == canonical_hash(request), 'Request/plan incompatibles')
    live.require((attempt/'prompt.txt').read_text(encoding='utf-8') == request['prompt'] and
        call['prompt_sha256'] == hashlib.sha256(request['prompt'].encode()).hexdigest() and
        call['schema_sha256'] == digest(out/'schema.json'), 'Prompt/schema diferentes')
    auth = live.read(directory/'authorization.json')
    live.require(auth['authorized'] is True and auth['max_retries'] == 0 and
        auth['run_plan_sha256'] == digest(directory/'plan.json') and
        auth['review_sha256'] == digest(directory/'review.json'), 'Autorizacion original incompatible')
    used = live.read(out/'authorization.used.json')
    live.require(used['authorized'] is True and used['plan_sha256'] == digest(out/'plan.json') and
        used['request_sha256'] == cp['request_sha256'] and
        live.read(claims[0])['authorization_sha256'] == digest(out/'authorization.used.json'), 'Claim/autorizacion incompatibles')
    live.require(call['runtime'] == cp['runtime'] == live.read(directory/'provider.json') and
        cp['provider_binding_sha256'] == digest(directory/'provider.json'), 'Proveedor incompatible')
    raw = (attempt/'response.raw.txt').read_text(encoding='utf-8')
    live.require(raw == native['message']['content'], 'Respuesta nativa diferente')
    wrapper = strict_json(raw)
    Draft202012Validator(live.read(out/'schema.json')).validate(wrapper)
    v3.validate_wrapper(wrapper, pid, ids, project['fields'])
    live.validate_context_evidence(request, wrapper)
    item = wrapper['assessments'][0]
    assessment = {k:v for k,v in item.items() if k != 'indicator_id'}
    issues = semantic_issues(v3.validate(project['fields'], plan['profiles'][ids[0]], assessment,
        plan['rubrics'][ids[0]]), assessment, ids[0])
    live.require(bool(issues), 'No hay error semantico reproducible; no repetir inferencia')
    new = deepcopy(plan)
    revised = new['context_requests'][pid][ids[0]]
    revised['prompt'] += CORRECTION
    settings = plan['runtime']['configuration']
    revised['context_budget'] = estimate(revised['prompt'], live.read(out/'schema.json'), settings)
    live.require(revised['context_budget']['fits'], 'Correccion no cabe: requiere nueva configuracion y revision; no truncar')
    if not apply:
        return dict(status='RECOVERABLE', inference_calls=0, project_id=pid, indicator_ids=ids,
            issues=issues, revised_budget=revised['context_budget'], max_retries=1)
    # Nothing above this line mutates the run or contacts a model.
    archive = directory.parent/'assessment_recovery_history'/directory.name/digest(directory/'plan.json')
    live.require(archive.is_relative_to(root/'outputs/runs') and not archive.exists(), 'Archivo de recuperacion ya existe')
    shutil.copytree(directory, archive)
    shutil.copy2(run_file(run, 'run.json'), archive/'run.checkpoint.original.json')
    for other, _, _ in siblings:
        shutil.copytree(other, archive/'pending_batches'/other.name)
    hashes = {p.relative_to(root).as_posix():digest(p) for p in archive.rglob('*') if p.is_file()}
    new['recovery'] = dict(version='INVALID_ASSESSMENT_CORRECTION_V1', retry=1, max_retries=1,
        project_id=pid, indicator_ids=ids, issues=issues, archive_hashes=hashes,
        previous_usage=[verification], original_request_sha256=canonical_hash(request),
        revised_request_sha256=canonical_hash(revised), requires_new_authorization=True)
    new['source_hashes'] = new_sources
    new['source_hashes'].update({name:digest(root/name) for name in BASELINE})
    for name in ('src/layer4_evaluation/indicators/validation_diagnostics.py', 'scripts/recover_invalid_assessment.py'):
        new['source_hashes'][name] = digest(root/name)
    new['maximum_calls'] += 1
    new['total_token_reservation_cap'] += plan['budgets']['assessment_reservation']
    review = live.read(directory/'review.json')
    review['requests'] = new['context_requests']
    review['recovery'] = {k:v for k,v in new['recovery'].items() if k != 'archive_hashes'}
    report = live.read(directory/'context_selection.json')
    for r in report['requests']:
        if r['project_id'] == pid and r['indicator_id'] == ids[0]:
            r.update(request_sha256=canonical_hash(revised), budget=revised['context_budget'], prompt_bytes=len(revised['prompt'].encode()))
    review['context_selection'] = report
    live.write(directory/'recovery.pending.json', dict(archive=str(archive), status='UPDATING_REVIEW'))
    for other, sibling_plan, sibling_manifest in siblings:
        snapshot = archive/'pending_batches'/other.name
        sibling_plan['checkpoint_migration'] = dict(reason='INVALID_ASSESSMENT_VALIDATOR_DIAGNOSTICS',
            archive_hashes={k:v for k,v in hashes.items() if (root/k).is_relative_to(snapshot)})
        sibling_plan['source_hashes']['src/layer4_evaluation/indicators/validation_diagnostics.py'] = digest(root/'src/layer4_evaluation/indicators/validation_diagnostics.py')
        live.write(other/'plan.json', sibling_plan)
        sibling_manifest['plan_sha256'] = digest(other/'plan.json')
        live.write(other/'manifest.json', sibling_manifest)
    (directory/'calls').rename(directory/'rejected_calls')
    (directory/'authorization.json').rename(directory/'authorization.previous.json')
    live.write(directory/'review.json', review)
    (directory/'review.txt').write_text(json.dumps(review, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    live.write(directory/'context_selection.json', report)
    live.write(directory/'plan.json', new)
    new_code.update({name:digest(root/name) for name in BASELINE})
    new_code['src/layer4_evaluation/indicators/validation_diagnostics.py'] = digest(root/'src/layer4_evaluation/indicators/validation_diagnostics.py')
    run_state.update(code_hashes=new_code, assessment_recovery=dict(archive=str(archive), retry=1))
    live.write(run_file(run, 'run.json'), run_state)
    live.write(directory/'manifest.json', dict(plan_sha256=digest(directory/'plan.json'),
        files={name:digest(directory/name) for name in manifest['files']}))
    live.write(directory/'status.json', dict(status='REVIEW_REQUIRED', retries=1, valid_assessments=0))
    (directory/'recovery.pending.json').unlink()
    return dict(status='REVIEW_REQUIRED', inference_calls=0, project_id=pid, indicator_ids=ids,
        issues=issues, review=str(directory/'review.txt'), archive=str(archive), max_retries=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--prepare', action='store_true', help='Archiva el fallo y prepara nueva revision; sin esta opcion solo diagnostica')
    args = parser.parse_args()
    for value in (args.run_id, args.batch):
        live.require(re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value), 'ID invalido')
    directory = ROOT/'outputs/runs'/args.run_id/'workspace/outputs/layer4'/args.batch
    from scripts.pipeline_coordinator import lock
    live.BASE = directory.parent
    with lock(ROOT/'outputs/runs'), live.execution_lock():
        print(json.dumps(prepare(ROOT, directory, apply=args.prepare), ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
