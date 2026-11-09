"""Consumption contract checks; no territorial build, rendering or inference."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
import pandas  # Initialize Windows platform metadata before forbidding subprocesses.

from layer4_evaluation import territorial_consumption as t

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def forbid_process(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('No subprocess allowed')
    monkeypatch.setattr('subprocess.run',forbidden)


@pytest.fixture
def bare(tmp_path,monkeypatch):
    pub=tmp_path/'outputs/layer4/territorios/publicacion';pub.mkdir(parents=True)
    outputs={}
    for name in t.REQUIRED:
        data=b'Original accepted fixture bytes';(pub/name).write_bytes(data)
        outputs[name]=dict(bytes=len(data),sha256=t.sha256(pub/name))
    outputs.update({name:dict(bytes=1,sha256='0'*64) for name in t.OPTIONAL_PNGS})
    manifest=dict(status='SUCCESS',architecture='PROJECT_TERRITORY_V1',build_id='FIXTURE',reference_id='REF',summary={},outputs=outputs)
    acceptance=dict(status='LAYER4_TERRITORY_V1_READY',build_id='FIXTURE',reference_id='REF',summary={})
    mp=pub/'territory_manifest.json';mp.write_text(json.dumps(manifest))
    ap=tmp_path/'outputs/layer4/territorios/aceptacion/final_acceptance.json';ap.parent.mkdir();ap.write_text(json.dumps(acceptance))
    contract=dict(version=t.VERSION,required_files=list(t.REQUIRED),optional_visual_files=list(t.OPTIONAL_PNGS),validator_sha256=t.sha256(Path(t.__file__)),historical_manifest_sha256=t.sha256(mp),historical_acceptance_sha256=t.sha256(ap))
    cp=tmp_path/t.CONTRACT_PATH;cp.parent.mkdir();cp.write_text(json.dumps(contract))
    def forbidden(*a,**k):raise AssertionError('Invalid mandatory inputs must fail before upstream reads')
    monkeypatch.setattr(t,'load_projects',forbidden)
    return tmp_path,pub,manifest


def test_explicit_ten_required_six_optional_only():
    manifest=dict(outputs={name:{} for name in (*t.REQUIRED,*t.OPTIONAL_PNGS)})
    required,optional=t.partition_outputs(manifest)
    assert len(required)==10 and len(optional)==6 and not set(required)&set(optional)
    manifest['outputs']['qa/unknown.png']={}
    with pytest.raises(ValueError,match='contract differs'):t.partition_outputs(manifest)


def test_required_missing_fails_before_any_processing(bare):
    root,pub,_=bare;(pub/'project_territories.parquet').unlink()
    with pytest.raises(ValueError,match='Missing mandatory'):t.verify_consumption(root)


def test_required_same_size_tampering_fails_hash(bare):
    root,pub,_=bare;path=pub/'project_territories.parquet';path.write_bytes(b'X'*path.stat().st_size)
    with pytest.raises(ValueError,match='checksum differs'):t.verify_consumption(root)


def test_historical_manifest_cannot_be_rebased(bare):
    root,pub,manifest=bare;manifest['build_id']='CHANGED';(pub/'territory_manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='manifest changed'):t.verify_consumption(root)


def test_optional_absence_never_claims_historical_pass(bare):
    _,pub,manifest=bare;before=t.sha256(pub/'territory_manifest.json')
    report=t.historical_files(pub,manifest)
    assert report['status']=='NOT_PASS' and len(report['issues'])==6
    assert {x['path'] for x in report['issues']}==set(t.OPTIONAL_PNGS)
    assert t.sha256(pub/'territory_manifest.json')==before


def test_real_consumption_with_missing_metadata_png_and_four_key_projection():
    plan=t.read(ROOT/'outputs/layer4/pruebas/validacion_v3_3/cierre_homogeneo_v3_3/closure.plan.json')
    report=t.verify_consumption(ROOT,selected=list(plan['projects'].values()))
    assert report['status']=='PASS' and report['mandatory_files_verified']==10
    assert report['quality']['bridge_unique'] and report['quality']['evidence_offsets_verified']
    assert report['resolved_relationships']==2654 and report['selected_projects']==20
    assert report['selected_territory_rows']==13
    assert report['historical_full_verification']['status']=='NOT_PASS'
    assert report['historical_full_verification']['issues']==[dict(path='qa/METADATA.png',status='MISSING')]
    assert report['inference_calls']==0 and not report['extraction_performed'] and not report['territorial_data_modified']


def test_closure_dispatch_gate_uses_new_consumption_contract(tmp_path,monkeypatch):
    import importlib.util
    spec=importlib.util.spec_from_file_location('consumption_gate',ROOT/'scripts/run_layer4_definitive_v3_3.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.OUT=tmp_path;module.ROOT=ROOT
    selected=[dict(project_id='SYNTHETIC',siap_id='001')]
    module.write(tmp_path/'closure.plan.json',dict(projects={'SYNTHETIC':selected[0]}))
    observed=[]
    def verify(root,selected=None):observed.append((root,selected));return dict(status='PASS',contract=t.VERSION)
    monkeypatch.setattr(t,'verify_consumption',verify)
    assert module.territorial_check()['contract']==t.VERSION
    assert observed==[(ROOT,selected)]
