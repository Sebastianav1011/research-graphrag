"""One-time repair of a sealed existing territorial CSV, without reevaluation.

Normal pipeline exports already use indicator_csv.write_results. This maintenance
entry point preserves the historical row set and verifies every other run file.
"""
import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from layer4_evaluation.indicator_csv import TerritoryCodes, TERRITORIAL_COLUMNS, MEASURE_COLUMNS, write_results
from layer4_evaluation.territories.catalog import load_catalog
from layer4_evaluation.live_execution import assessment_from_row
from layer4_evaluation.thesis_output import persisted_records


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def repair(root, run):
    root, run = Path(root).resolve(), Path(run).resolve()
    if not run.is_relative_to(root/'outputs/runs'):
        raise ValueError('Run outside repository outputs/runs')
    target = run/'resultados/indicadores_territorios.csv'
    before = {p.relative_to(run).as_posix(): digest(p) for p in run.rglob('*') if p.is_file()}
    original = target.read_bytes()
    with target.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter=';')
        columns, rows = reader.fieldnames, list(reader)
    preserved = MEASURE_COLUMNS
    if columns not in (preserved+['codigo_dane'], preserved+['departamento','municipio']):
        raise ValueError('Expected historical eight-column or nine-column territorial CSV')
    # Recover the original two-digit codes from the immutable first backup when
    # repairing the previous name-only projection. Never infer them from project IDs.
    historical_receipt = read(target.parent/'correccion_territorial.receipt.json')
    baseline_path = (root/historical_receipt['backup']).resolve()
    if not baseline_path.is_relative_to(run) or digest(baseline_path) != historical_receipt['original_sha256']:
        raise ValueError('Original departmental-code backup is unverified')
    with baseline_path.open(encoding='utf-8-sig', newline='') as stream:
        baseline = list(csv.DictReader(stream, delimiter=';'))
    if len(baseline) != len(rows) or any([r[c] for c in preserved] != [b[c] for c in preserved] for r,b in zip(rows,baseline)):
        raise ValueError('Historical rows differ from original departmental-code backup')
    original_codes = {(r[preserved[0]],r['indicador_id']):r['codigo_dane'] for r in baseline}
    if any(len(code)!=2 or not code.isascii() or not code.isdigit() for code in original_codes.values()):
        raise ValueError('Original codigo_dane must be a two-digit department code')
    # Reuse the sealed plan/receipt/assessment identity checks. This reader never
    # invokes the model, evaluates criteria or recomputes confidence.
    _, validation = persisted_records(root, run)
    projects = {}
    plans = {}
    for path in sorted((run/'evaluation').glob('batch_*/plan.json')):
        plans[path.relative_to(run).as_posix()] = digest(path)
        for project in read(path)['projects']:
            identity = project['siap_id']
            if identity in projects:
                raise ValueError('Ambiguous source identity')
            projects[identity] = project
    assessments = {}
    for row in read(run/'resultados/evaluaciones_validas.json')['assessments']:
        pair = row['siap_id'], row['indicator_id']
        if pair in assessments:
            raise ValueError('Ambiguous saved assessment')
        assessments[pair] = row
    resolver = TerritoryCodes(root)
    codes = {}
    for row in rows:
        pair = row[preserved[0]], row['indicador_id']
        saved = assessments[pair]
        result = resolver(projects[pair[0]], dict(assessment_from_row(saved), indicator_id=pair[1]))
        if not result:
            raise ValueError('Existing territorial row has no verifiable resolution: '+str(pair))
        # The old departmental code restricts the repair; it cannot invent a town.
        if not all(code.startswith(original_codes[pair]) for code in result):
            raise ValueError('Evidence contradicts original territory: '+str(pair))
        codes[pair] = result
    temp_root = root/'.tmp'
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='territory-repair-', dir=temp_root) as temporary:
        write_results(temporary, preserved, rows, codes, resolver=resolver)
        candidate = Path(temporary)/'resultados'/target.name
        with candidate.open(encoding='utf-8-sig', newline='') as stream:
            fixed = list(csv.DictReader(stream, delimiter=';'))
        if (len(fixed) != len(rows)
                or any([r[c] for c in preserved] != [f[c] for c in preserved] for r,f in zip(rows,fixed))
                or any(f['codigo_dane'] != original_codes[f[preserved[0]],f['indicador_id']] for f in fixed)):
            raise ValueError('Repair would change original evaluations or their order')
        backup = target.with_name(target.name+'.before-dane-v2-'+sha256(original).hexdigest()[:12]+'.bak')
        if backup.exists():
            if backup.read_bytes() != original:
                raise ValueError('Existing backup mismatch')
        else:
            with backup.open('xb') as stream:
                stream.write(original)
        if target.read_bytes() != original:
            raise ValueError('CSV changed during repair')
        changed_names = ('indicadores_territorios_relaciones.csv', 'territorios_auditoria.json', target.name)
        receipt_path = target.parent/'correccion_territorial_dane_v2.receipt.json'
        if receipt_path.exists():
            raise FileExistsError(receipt_path)
        for name in changed_names:
            destination = target.parent/name
            if destination.exists() and name != target.name:
                side_backup = destination.with_name(destination.name+'.before-dane-v2-'+digest(destination)[:12]+'.bak')
                if not side_backup.exists():
                    with side_backup.open('xb') as stream:
                        stream.write(destination.read_bytes())
                if digest(side_backup) != digest(destination):
                    raise ValueError('Sidecar backup mismatch')
        for name in changed_names:
            destination = target.parent/name
            if digest(destination) != before[destination.relative_to(run).as_posix()]:
                raise ValueError('Output changed during repair')
            pending = destination.with_suffix(destination.suffix+'.pending')
            pending.write_bytes((candidate.parent/name).read_bytes())
            pending.replace(destination)
    for name, expected in before.items():
        if name not in {str(Path('resultados')/n).replace('\\','/') for n in changed_names} and digest(run/name) != expected:
            raise ValueError('Unrelated original run file changed: '+name)
    receipt = dict(status='PASS', original_rows=len(rows), corrected_rows=len(fixed),
        original_sha256=sha256(original).hexdigest(), corrected_sha256=digest(target),
        backup=str(backup.relative_to(root)), backup_sha256=digest(backup), preserved_columns=preserved,
        preserved_values_and_order=True, other_original_files_unchanged=True,
        original_department_codes_preserved=True, original_department_backup=str(baseline_path.relative_to(root)),
        original_department_backup_sha256=digest(baseline_path), catalog=load_catalog().manifest,
        updated_output_files=list(changed_names),
        territories=dict(Counter(f"{r[preserved[0]]}: {r['departamento']} / {r['municipio']}" for r in fixed)),
        sealed_plans_sha256=plans, persisted_validation=validation,
        inference_calls=0, confidence_recomputed=False)
    receipt_path = target.parent/'correccion_territorial_dane_v2.receipt.json'
    with receipt_path.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    result = repair(ROOT, args.run)
    print(json.dumps({k:result[k] for k in ('status','corrected_rows','backup','territories')}, ensure_ascii=True, indent=2))
