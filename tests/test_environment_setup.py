"""Read-only bootstrap checks, no model downloads or inference."""
from pathlib import Path
import subprocess
import sys
from scripts import check_environment

ROOT=Path(__file__).resolve().parents[1]


def test_python_requirements_are_present_without_loading_models():
    report=check_environment.inspect(external=False)
    assert not report['errors']
    assert set(check_environment.PACKAGES)==set(report['packages'])


def test_missing_packages_are_errors(monkeypatch):
    def missing(name):raise check_environment.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(check_environment.metadata,'version',missing)
    result=check_environment.inspect(external=False)
    assert result['status']=='ERROR' and len(result['errors'])==len(check_environment.PACKAGES)


def test_legacy_powershell_entrypoint_imports_from_foreign_directory(tmp_path):
    result=subprocess.run([sys.executable,str(ROOT/'scripts/run_pipeline_manual.py'),'--help'],
                          cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr


def test_generated_files_and_secrets_are_ignored():
    ignored=['.venv/example','.venv-cpu/example','.tmp/example','.aws/credentials',
             '.env','weights.gguf','weights.safetensors','outputs/runs/example/resultados/indicadores.csv']
    result=subprocess.run(['git','-c','safe.directory='+ROOT.as_posix(),'check-ignore','-z','--stdin'],
                          input=('\0'.join(ignored)+'\0').encode(),cwd=ROOT,capture_output=True)
    assert result.returncode==0 and result.stdout.decode().rstrip('\0').split('\0')==ignored
