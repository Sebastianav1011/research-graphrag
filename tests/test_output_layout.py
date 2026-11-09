"""Canonical outputs, relocated immutable inputs, and disposable test workspaces."""
from pathlib import Path
import hashlib
import json

from layer2_processing.checkpoints import destination,locate,resolve,run_directory,verify_expected
from autonomous_execution import store

ROOT=Path(__file__).resolve().parents[1]


def test_only_four_global_output_directories():
    assert {p.name for p in (ROOT/'outputs').iterdir()}=={'layer2','layer3','layer4','runs'}


def test_canonical_destinations_never_redirect_back_to_old_names():
    for old,new in [('layer2_processing','layer2'),('layer3_graphrag','layer3'),('layer4_evaluation','layer4')]:
        assert destination(ROOT,'outputs/'+old+'/resource')==ROOT/'outputs'/new/'resource'
        assert destination(ROOT,'outputs/'+new+'/resource')==ROOT/'outputs'/new/'resource'


def test_relocated_authorized_input_keeps_exact_hash_and_manifest(tmp_path):
    old='outputs/layer4_evaluation/indicator_profiles/data.json'
    target=tmp_path/'outputs/layer4/indicator_profiles/data.json'
    target.parent.mkdir(parents=True);target.write_bytes(b'{"original":true}')
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    manifest=json.dumps({'files':{old:digest}}).encode()
    pinned=tmp_path/'manifest.json';pinned.write_bytes(manifest)
    assert resolve(tmp_path,old)==target
    assert locate(tmp_path/old)==target
    assert store.read(tmp_path/old)=={'original':True}
    verify_expected(tmp_path,old,digest)
    assert pinned.read_bytes()==manifest
    target.write_bytes(b'{"original":false}')
    import pytest
    with pytest.raises(ValueError,match='Fingerprint mismatch'):verify_expected(tmp_path,old,digest)


def test_all_persistent_builds_use_identified_runs(tmp_path):
    assert run_directory(tmp_path,'layer3_build')==tmp_path/'outputs/runs/layer3_build'
    import pytest
    for invalid in ('..','../escape','nested/run'):
        with pytest.raises(ValueError):run_directory(tmp_path,invalid)


def test_regression_command_uses_current_tests_and_disposable_reports(monkeypatch):
    from layer3_graphrag.operations import regressions
    calls=[]
    monkeypatch.setattr('layer3_graphrag.operations.subprocess.run',lambda args,**kwargs:calls.append(args))
    assert regressions(ROOT)=={'status':'PASS','real_integration':False}
    assert [args[4] for args in calls]==['tests/layer2_preprocessing','tests/layer3_knowledge','tests/layer4_graphrag']
    for args in calls:
        assert (ROOT/args[4]).is_dir()
        report=Path(next(a.split('=',1)[1] for a in args if a.startswith('--junitxml=')))
        assert not report.is_relative_to(ROOT/'outputs') and not report.parent.exists()
        assert not any(a.startswith('--basetemp') for a in args)
