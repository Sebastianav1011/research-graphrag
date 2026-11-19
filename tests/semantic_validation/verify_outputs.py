"""Final artifact and source-integrity checks; not semantic adjudication."""
import subprocess
from .harness import *
def main():
    initial=read(OUT/'integridad_inicial.json');changes=[]
    for path,h in initial['files'].items():
        p=ROOT/path
        if not p.is_file() or filehash(p)!=h:changes.append(path)
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    integrity=dict(status='PASS' if not changes and head==initial['head'] and branch==initial['branch'] else 'FAIL',protected_files=len(initial['files']),changed_files=changes,branch=branch,head=head,branch_unchanged=branch==initial['branch'],head_unchanged=head==initial['head'])
    write(OUT/'integridad_final.json',integrity);assert integrity['status']=='PASS',integrity
    csv.field_size_limit(20_000_000)
    def rows(name):
        with (OUT/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f,delimiter=';'))
    matrix=rows('matriz_pruebas.csv');history=rows('regresion_run_original.csv');human=rows('validacion_humana.csv');results=rows('resultados_pruebas.csv');summary=read(OUT/'resumen_validacion.json')
    assert len(matrix)==len({r['case_id'] for r in matrix})==404
    assert len({r['indicador'] for r in matrix})==48
    assert len(history)==len({r['case_id'] for r in history})==240
    assert len(human)==len({r['case_id'] for r in human})==644
    assert all(r['resultado']=='NOT_EXECUTED' for r in matrix) if summary['local_calls']==0 else True
    for r in history:assert filehash(ROOT/r['snapshot'])==r['snapshot_sha256']
    required=['README.md','matriz_pruebas.csv','resultados_pruebas.csv','regresion_run_original.csv','metricas_validacion.md','errores_detectados.md','plan_correcciones.md','validacion_humana.csv']
    assert all((OUT/n).is_file() for n in required)
    assert summary['pytest_count']==summary['pytest_passed']+summary['pytest_failed']
    assert summary['existing_tests']==summary['existing_passed']+summary['existing_failed']
    assert summary['attempts_replayed']==536 and summary['replay_failures']==0 and summary['formula_failures']==0
    assert read(OUT/'recuperacion_real.json')['status']=='EXECUTED_FROM_VERIFIED_CACHE'
    metrics=read(OUT/'metricas.json');assert metrics['citation_count']==metrics['literal_matches']==603
    if summary['human_confirmed']==0:assert metrics['real_human_validated']['precision'] is None
    validation=dict(status='PASS_ARTIFACTS_WITH_KNOWN_TEST_FAILURES',integrity=integrity,matrix_cases=len(matrix),historical_unique=len(history),human_template=len(human),results_rows=len(results),new_model_calls=summary['local_calls'],
        new_pytest=dict(passed=summary['pytest_passed'],failed=summary['pytest_failed']),existing_bounded=dict(passed=summary['existing_passed'],failed=summary['existing_failed']),model_inference_status='NOT_EXECUTED_RESOURCE_PREFLIGHT' if summary['local_calls']==0 else 'EXECUTED',
        artifact_hashes={n:filehash(OUT/n) for n in required},test_source_hashes={str(p.relative_to(ROOT)):filehash(p) for p in Path(__file__).parent.glob('*') if p.is_file()})
    write(OUT/'validacion_entregables.json',validation);print(json.dumps({k:v for k,v in validation.items() if k not in ('artifact_hashes','test_source_hashes')},ensure_ascii=True,indent=2))
if __name__=='__main__':main()
