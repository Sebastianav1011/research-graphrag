"""Use disposable OS temp directories, not accumulated fixtures under outputs."""
from pathlib import Path
import shutil
import tempfile
import pytest


def pytest_configure(config):
    if config.option.basetemp is not None:
        path=Path(config.option.basetemp).resolve()
        outputs=Path(__file__).resolve().parents[1]/'outputs'
        if path==outputs or path.is_relative_to(outputs):
            raise pytest.UsageError('Las pruebas usan temporales fuera de outputs; omitir --basetemp o usar el directorio temporal del sistema.')
    if config.option.basetemp is None:
        path=Path(tempfile.mkdtemp(prefix='graphrag-tests-')).resolve()
        config.option.basetemp=str(path)
        config._graphrag_temp=path


def pytest_sessionfinish(session,exitstatus):
    path=getattr(session.config,'_graphrag_temp',None)
    if path and path.parent==Path(tempfile.gettempdir()).resolve() and path.name.startswith('graphrag-tests-'):
        shutil.rmtree(path,ignore_errors=True)
