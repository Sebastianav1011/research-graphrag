from pathlib import Path
import json
import pytest
from layer4_evaluation.paths import resolve,legacy,verify_expected

ROOT=Path(__file__).resolve().parents[2]


def test_old_new_paths_and_original_fingerprints():
    old='outputs/layer4/pruebas/mejora_cobertura_v3/continuacion_prompt_v3_1/rubrics.json'
    path=resolve(ROOT,old)
    assert path.is_file() and 'validacion_v3_3' in str(path)
    assert legacy(ROOT,path)==ROOT/old
    verify_expected(ROOT,old,'031cf0eae9b7a4ce8c998f0be0662e7fd8a4258fbd7cd5bfc48a9a1abc6353da')


def test_wrong_hash_still_fails():
    with pytest.raises(ValueError,match='Fingerprint mismatch'):
        verify_expected(ROOT,'outputs/layer4/final/resultado_capa4.xlsx','0'*64)


def test_migration_binding_does_not_accept_changed_runtime(tmp_path):
    folder=tmp_path/'outputs/layer4/auditoria';folder.mkdir(parents=True)
    (tmp_path/'code.py').write_text('changed')
    (folder/'rutas.json').write_text(json.dumps(dict(runtime_bindings={'code.py':dict(after_sha256='WRONG',snapshot='old.py')})))
    with pytest.raises(ValueError):verify_expected(tmp_path,'code.py','0'*64)


def test_binding_for_relocated_document_keeps_original_hash(tmp_path):
    import hashlib
    folder=tmp_path/'outputs/layer4/auditoria';folder.mkdir(parents=True)
    (tmp_path/'new.md').write_bytes(b'updated documentation')
    (tmp_path/'original.md').write_bytes(b'original documentation')
    current=hashlib.sha256((tmp_path/'new.md').read_bytes()).hexdigest()
    original=hashlib.sha256((tmp_path/'original.md').read_bytes()).hexdigest()
    (folder/'rutas.json').write_text(json.dumps(dict(prefixes={'old.md':'new.md'},
        runtime_bindings={'new.md':dict(after_sha256=current,snapshot='original.md')})))
    verify_expected(tmp_path,'old.md',original)
    (tmp_path/'new.md').write_bytes(b'unreviewed change')
    with pytest.raises(ValueError):verify_expected(tmp_path,'old.md',original)
