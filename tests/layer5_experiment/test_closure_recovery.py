"""Localized, inference-free checks for the two closure blockers."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('recovery_control',Path(__file__).resolve().parents[2]/'scripts/run_layer4_definitive_v3_3.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)


@pytest.fixture(autouse=True)
def no_subprocess(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('No subprocess or inference in recovery tests')
    monkeypatch.setattr('subprocess.run',forbidden)


@pytest.fixture
def original():
    plan=s.read(s.OUT/'closure.plan.json')
    raw=s.read(s.OUT/'PROJ_22292/closure_discovery/discovery/codex_runs/PROJ_22292/attempt_1/response.json')
    return raw,plan['projects']['PROJ_22292'],plan['profiles']


def test_only_one_category_changes_and_existing_validator_passes(original):
    raw,project,profiles=original;unchanged=deepcopy(raw)
    with pytest.raises(ValueError,match='category'):s.gd.validate_selection(raw,project,profiles)
    derived,selection=s.canonical_sal05(raw,project,profiles)
    assert raw==unchanged
    corrected=next(x for x in derived['assessments'][0]['rejected'] if x['indicator_id']=='SAL-05')
    assert corrected['indicator_category']=='IMPACTO_MAS_ALLA_ACADEMIA'
    corrected['indicator_category']='IMPACTO_MAS_ALLA_ACMIA'
    assert derived==raw
    assert selection['prioritized_ids']==['AMB-01','ECO-05','TEC-06','TEC-04','COL-02']


@pytest.mark.parametrize('mutation',[
    lambda r,p,c:r.update(project_id='OTHER'),
    lambda r,p,c:r['assessments'][0]['rejected'].append(deepcopy(next(x for x in r['assessments'][0]['rejected'] if x['indicator_id']=='SAL-05'))),
    lambda r,p,c:c['SAL-05'].update(indicator_category='OTHER'),
    lambda r,p,c:r['assessments'][0]['candidates'][0]['evidence'][0].update(text='INVENTED QUOTE'),
])
def test_ambiguity_identity_or_other_validation_failures_not_repaired(original,mutation):
    raw,project,profiles=deepcopy(original);mutation(raw,project,profiles)
    with pytest.raises(Exception):s.canonical_sal05(raw,project,profiles)


def test_historical_full_file_check_still_reports_missing_visual(tmp_path):
    from layer4_evaluation.territorial_consumption import historical_files
    directory=tmp_path/'outputs/layer4/territorios/publicacion';directory.mkdir(parents=True)
    data=b'Exact original fixture bytes';expected=hashlib.sha256(data).hexdigest()
    s.write(directory/'territory_manifest.json',dict(outputs={'qa/METADATA.png':dict(sha256=expected,bytes=len(data))}))
    assert historical_files(directory,s.read(directory/'territory_manifest.json'))['status']=='NOT_PASS'
    (directory/'qa').mkdir();(directory/'qa/METADATA.png').write_bytes(b'WRONG COPY')
    assert historical_files(directory,s.read(directory/'territory_manifest.json'))['status']=='NOT_PASS'
    (directory/'qa/METADATA.png').write_bytes(data)
    assert historical_files(directory,s.read(directory/'territory_manifest.json'))['status']=='FILES_MATCH'


def test_unresolved_territory_blocks_before_budget_or_dispatch(monkeypatch):
    def missing():raise ValueError('Missing mandatory territorial data')
    monkeypatch.setattr(s,'territorial_check',missing)
    with pytest.raises(ValueError,match='Missing mandatory'):s.next_call(dict(projects={'PROJ_22292':{}}),'PROJ_22292')


def test_saved_derivation_preserves_failed_attempt_and_full_budget_cost():
    plan=s.check();out=s.OUT/'PROJ_22292/closure_discovery'
    wrapper,selection=s.recovered_discovery(plan,out)
    assert selection['prioritized_ids']==['AMB-01','ECO-05','TEC-06','TEC-04','COL-02']
    assert s.read(out/'verification.json')['status']=='BLOCKED_ERROR'
    assert s.read(out/'records/discovery/PROJ_22292.json')['status']=='ERROR'
    budget=s.budget_status(plan)
    assert budget[2]==dict(tokens=300110,calls=8)
    state=s.project_status(plan,'PROJ_22292')
    assert state['discovery_complete'] and not state['complete'] and len(state['pending'])==5


def test_other_changes_to_derived_decisions_are_rejected(monkeypatch):
    plan=s.check();out=s.OUT/'PROJ_22292/closure_discovery';original_read=s.read
    def altered_read(path):
        value=original_read(path)
        if Path(path)==out/'response.canonical.json':
            value=deepcopy(value)
            value['assessments'][0]['rejected'][0]['reason']='UNAUTHORIZED SEMANTIC CHANGE'
        return value
    monkeypatch.setattr(s,'read',altered_read)
    with pytest.raises(ValueError,match='more than'):s.recovered_discovery(plan,out)
