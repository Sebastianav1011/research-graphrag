"""Bounded mock transport; no real institutional data, model or inference."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import json
import subprocess

import pytest
from layer4.indicators.selection import canonical_hash,FIELDS

spec=importlib.util.spec_from_file_location('coverage_control',Path(__file__).resolve().parents[2]/'scripts/run_layer4_coverage_v3.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)


@pytest.fixture
def study(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'ROOT',tmp_path)
    monkeypatch.setattr(c,'OUT',tmp_path/'study');c.OUT.mkdir()
    profiles={}
    for n in range(48):
        iid=f'SYNTH_{n:02d}'
        profiles[iid]=dict(indicator_id=iid,indicator_name='Condición incorporada.',indicator_category='SYNTHETIC',
            indicator_dimension=None,descripcion_ampliada='Una condición de diseño documentada.',key_elements=['Condición'],
            favorable_evidence='Diseño documentado.',insufficient_evidence='Mención nominal.',
            relational_context='Relación sintética.',source_record_json='{"forma_evaluacion":"PRESENCIA"}')
    runtime=dict(command=['synthetic_codex'],cli_version='synthetic',executable_hashes={},exec_help_sha256='H',features_sha256='F')
    plan=dict(execution_id='SYNTHETIC_STUDY',profiles=profiles,rules=[],runtime=runtime,
        projects=[dict(project_id=pid,fields=dict.fromkeys(FIELDS,None),eligible_candidates=[]) for pid in c.IDS],
        source_hashes={},code_hashes={},maximum_new_calls=18,requested_model=None,timeout_seconds=10)
    c.write_json(c.OUT/'plan.json',plan)
    for name,value in [('rubric.schema.json',c.v3.rubric_response_schema()),('discovery.schema.json',c.gd.selection_schema()),('assessment.schema.json',c.v3.schemas()['assessment_batch'])]:
        c.write_json(c.OUT/name,value)
    c.write_json(c.OUT/'manifest.json',dict(plan_sha256=c.sha256(c.OUT/'plan.json'),prepared_hashes={p.name:c.sha256(p) for p in c.OUT.iterdir()}))
    monkeypatch.setattr(c,'inspect_runtime',lambda *args:runtime)
    auth=dict(plan_sha256=c.sha256(c.OUT/'plan.json'),institutional_text_authorized=True,
        project_ids=c.IDS,phases=c.PHASES,maximum_new_calls=18,authorized_by='SYNTHETIC',authorized_at='SYNTHETIC',authorization_reference='SYNTHETIC ONLY')
    c.write_json(c.OUT/'auth.json',auth)
    invoked=[]
    def runner(args,**kwargs):
        invoked.append(args)
        data=json.loads(kwargs['input'].split('INPUT_JSON:\n',1)[1])
        if 'rubric_version' in data:
            rubrics=[]
            for item in data['catalog']:
                p=item['profile'];basis=[dict(profile_field='descripcion_ampliada',text=p['descripcion_ampliada'])]
                rubrics.append(dict(indicator_id=p['indicator_id'],profile_sha256=item['profile_sha256'],
                    indicator_evidence_type='INCORPORATED_APPROACH',indicator_type_basis=basis,indicator_type_rationale='Synthetic transport only.',
                    criteria=[dict(criterion_id=x['criterion_id'],role='REQUIRED',alternative_group=None,
                        temporal_requirement='DESIGN_OR_EXECUTION',basis=basis,rationale='Synthetic transport only.') for x in item['criteria']]))
            result=dict(project_id=c.v3.CATALOG_ID,assessments=[dict(indicator_id=c.v3.CATALOG_ID,rubrics=rubrics)])
        else:
            assert data['catalog_count']==48
            result=dict(project_id=data['project']['project_id'],assessments=[dict(indicator_id=c.gd.MARKER,candidates=[],
                rejected=[dict(indicator_id=p['indicator_id'],indicator_category=p['indicator_category'],reason='Synthetic empty source.') for p in data['catalog']])])
        path=Path(args[args.index('--output-last-message')+1]);path.write_text(json.dumps(result),encoding='utf-8')
        return subprocess.CompletedProcess(args,0,stdout=json.dumps(dict(type='turn.completed',usage=dict(input_tokens=3,output_tokens=2,cached_input_tokens=0)))+'\n',stderr='')
    return auth,invoked,runner


def test_new_study_authorization_is_required_before_any_call(study):
    auth,invoked,runner=study
    auth['institutional_text_authorized']=False;c.write_json(c.OUT/'auth.json',auth)
    with pytest.raises(ValueError,match='new authorization'):c.execute(c.OUT/'auth.json',runner)
    assert not invoked


def test_exactly_three_catalog_calls_five_zero_selections_and_safe_resume(study):
    auth,invoked,runner=study
    result=c.execute(c.OUT/'auth.json',runner)
    assert result['calls']==8 and result['rubric_count']==48 and result['assessments']==0
    assert len(result['projects_completed'])==5 and result['new_calls_this_invocation']==8
    resumed=c.execute(c.OUT/'auth.json',runner)
    assert resumed['new_calls_this_invocation']==0 and len(invoked)==8
    assert result['tokens']['total_tokens']==40 # purely synthetic, never a study measurement


def test_modified_frozen_inputs_block_resume(study):
    auth,invoked,runner=study
    c.execute(c.OUT/'auth.json',runner)
    (c.OUT/'discovery.schema.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError):c.verify()
    assert len(invoked)==8
