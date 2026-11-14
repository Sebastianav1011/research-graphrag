"""Missing or relocated historical runs: explicit errors before writing, never silent gaps.

Synthetic temporary repositories only; real outputs are never touched.
"""
import json
import os

import pytest

from autonomous_execution import comparison, followup, minimal
from tests import historical


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def test_flat_locator_resolves_into_provider_bucket(tmp_path):
    target = tmp_path / 'outputs/runs/local/phase_demo'
    target.mkdir(parents=True)
    assert comparison.historical_run(tmp_path, 'outputs/runs/phase_demo') == target
    assert not (tmp_path / 'outputs/runs/phase_demo').exists()  # Resolution never creates the flat path.


def test_absent_historical_run_is_an_explicit_error(tmp_path):
    with pytest.raises(ValueError, match='Dependencia historica ausente: outputs/runs/missing'):
        comparison.historical_run(tmp_path, 'outputs/runs/missing')


@pytest.mark.parametrize('prepare', [lambda root: minimal.prepare(root, 'three'),
                                     lambda root: followup.prepare(root, 'followup'),
                                     lambda root: followup.prepare(root, 'phase12', phase12=True)])
def test_preparation_fails_before_writing_when_history_is_absent(tmp_path, monkeypatch, prepare):
    (tmp_path / 'outputs/runs').mkdir(parents=True)
    monkeypatch.setattr(comparison, 'location', lambda root, name: tmp_path / 'outputs/runs/local' / name)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob('*'))
    with pytest.raises(ValueError, match='Dependencia historica ausente'):
        prepare(tmp_path)
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob('*')) == before


def test_missing_candidate_index_never_creates_an_empty_sqlite(tmp_path, monkeypatch):
    run = tmp_path / 'outputs/runs/local' / comparison.HISTORY / 'autonomous/main'
    write(run / 'manifest.json', {'projects': {}})
    write(run / 'graph.binding.json', {'index_sha256': 'x'})
    monkeypatch.setattr(comparison, 'location', lambda root, name: tmp_path / 'outputs/runs/local' / name)
    with pytest.raises(ValueError, match='Dependencia historica ausente: .*candidate_index.sqlite'):
        comparison.prepare(tmp_path, 'paired')
    assert not (run / 'candidate_index.sqlite').exists()
    assert not (tmp_path / 'outputs/runs/local/paired').exists()


def test_missing_artifacts_skip_explicitly_instead_of_vanishing(monkeypatch):
    values = historical.params('outputs/runs/__absent_for_test__', lambda path: ['never'], label='demo')
    assert len(values) == 1 and values[0].marks[0].name == 'skip'
    assert 'Artefacto historico ausente' in values[0].marks[0].kwargs['reason']
    with pytest.raises(pytest.skip.Exception, match='Artefacto historico ausente'):
        historical.require('outputs/runs/__absent_for_test__')
    monkeypatch.delenv(historical.OPT_IN, raising=False)
    with pytest.raises(pytest.skip.Exception, match=historical.OPT_IN):
        historical.require('outputs/runs/__absent_for_test__', compacted=True)
    lazy = historical.Lazy(lambda: historical.require('outputs/runs/__absent_for_test__'))
    with pytest.raises(pytest.skip.Exception):
        lazy['anything']  # Reading is deferred to the test that needs it.
