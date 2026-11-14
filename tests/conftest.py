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


@pytest.fixture
def tokenizer_stub(tmp_path):
    """Hash-pinned word-level tokenizer descriptor: one token per word/punctuation, no model."""
    import hashlib
    from tokenizers import Tokenizer, models, pre_tokenizers
    tokenizer=Tokenizer(models.WordLevel(vocab={'[UNK]':0},unk_token='[UNK]'))
    tokenizer.pre_tokenizer=pre_tokenizers.Whitespace()
    path=tmp_path/'tokenizer_stub'/'tokenizer.json';path.parent.mkdir(parents=True,exist_ok=True)
    tokenizer.save(str(path))
    return dict(repository='synthetic/word-level',path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        model_digest='synthetic-digest',model_metadata_sha256='synthetic-metadata',template_tokens=12)


def pytest_sessionfinish(session,exitstatus):
    path=getattr(session.config,'_graphrag_temp',None)
    if path and path.parent==Path(tempfile.gettempdir()).resolve() and path.name.startswith('graphrag-tests-'):
        shutil.rmtree(path,ignore_errors=True)
