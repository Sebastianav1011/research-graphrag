"""Offline controls only: every real subprocess is forbidden."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
import pytest

spec=importlib.util.spec_from_file_location('definitive_control',Path(__file__).resolve().parents[2]/'scripts/run_layer4_definitive_v3_3.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)


@pytest.fixture
def setup(tmp_path,monkeypatch):
    def forbidden(*a,**k):raise AssertionError('Real subprocess forbidden')
    monkeypatch.setattr('subprocess.run',forbidden)
    monkeypatch.setattr(s,'territorial_check',lambda:None)
    old=s.pilot.check(s.pilot.directory('PROJ_20456'));pid='PROJ_20456'
    comparison=s.read(s.pilot.directory(pid)/'reuse_comparison.json')
    plan=dict(project_ids=[pid],projects={pid:old['project']},profiles=old['profiles'],
        rubrics=s.read(s.pilot.ACTIVE/'rubrics.json'),rules=old['rules'],
        selections={pid:str(s.pilot.directory(pid)/'discovery/codex_runs'/pid/'attempt_1/response.json')},
        reused={pid+'|'+e['indicator_id']:dict(row=e['assessment']) for e in comparison['entries'] if e['status']=='REUSABLE'},
        batches=[dict(batch=1,project_ids=[pid],token_reservation_cap=340000,maximum_new_calls=6)],
        budgets=dict(discovery_reservation=80000,assessment_reservation=45000,discovery_postcall_review_threshold=60000,assessment_postcall_review_threshold=35000),
        total_cap=2890000,maximum_calls=51,observed_character_ratio=.3,execution_id='SYNTHETIC',
        runtime=old['runtime'],requested_model=None,source_hashes={})
    monkeypatch.setattr(s,'OUT',tmp_path)
    monkeypatch.setattr(s,'check',lambda:deepcopy(plan))
    (tmp_path/'closure.plan.json').write_text('synthetic')
    task=s.prepare_call(pid);out=Path(task['out']);auth=s.read(out/'authorization.example.json')
    auth.update(authorized=True,authorized_by='SYNTHETIC',authorized_at='TEST',authorization_reference='LOCAL TEST ONLY')
    s.write(out/'authorization.json',auth)
    return plan,out,auth


def fake(plan,calls,usage=True,invalid=False,input_tokens=3):
    def runner(args,**kwargs):
        calls.append(args)
        assert '--disable' in args and 'multi_agent' in args
        payload=json.loads(kwargs['input'].split('\nINPUT_JSON:\n')[1]);pid=payload['project']['project_id']
        assessments=[]
        for profile in payload['indicators']:
            assessments.append(dict(indicator_id=profile['indicator_id'],assessment_version=s.v3.VERSION,
                decision='NOT_SUPPORTED',support_strength=0,criterion_assessments=[dict(criterion_id=r['criterion_id'],
                support='NOT_DEMONSTRATED',evidence_indices=[],explanation='Synthetic test only.') for r in profile['rubric']['criteria']],
                evidence=[],explanation='Synthetic negative test, no institutional assessment.'))
        wrapper=dict(project_id='WRONG' if invalid else pid,assessments=assessments)
        Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(wrapper))
        stdout=json.dumps(dict(type='turn.completed',usage=dict(input_tokens=input_tokens,output_tokens=2))) if usage else ''
        return SimpleNamespace(returncode=0,stdout=stdout+'\n',stderr='')
    return runner


def test_one_soc02_only_idempotent_no_followup(setup):
    plan,out,auth=setup;calls=[]
    result=s.execute(out,out/'authorization.json',runner=fake(plan,calls))
    assert result['status']=='PASS' and result['indicator_ids']==['SOC-02'] and len(calls)==1
    assert not result['further_dispatch_allowed'] and result['retries']==0
    assert s.execute(out,out/'authorization.json',runner=fake(plan,calls))==result
    assert len(calls)==1 and s.project_status(plan,'PROJ_20456')['complete']


@pytest.mark.parametrize('change',[dict(maximum_new_calls=2),dict(project_ids=['OTHER']),dict(max_retries=1),dict(token_budget=1),dict(authorized=False)])
def test_independent_authorization_required(setup,change):
    plan,out,auth=setup;auth.update(change);s.write(out/'authorization.json',auth);calls=[]
    with pytest.raises(ValueError):s.execute(out,out/'authorization.json',runner=fake(plan,calls))
    assert calls==[] and not (out/'dispatch.claim.json').exists()


@pytest.mark.parametrize('mode,status',[('metrics','BLOCKED_MISSING_METRICS'),('invalid','BLOCKED_ERROR'),('review','PAUSED_TOKEN_REVIEW'),('budget','BLOCKED_TOKEN_BUDGET')])
def test_fail_closed_without_retry(setup,mode,status):
    plan,out,auth=setup;calls=[]
    runner=fake(plan,calls,usage=mode!='metrics',invalid=mode=='invalid',input_tokens=46000 if mode=='budget' else 36000 if mode=='review' else 3)
    result=s.execute(out,out/'authorization.json',runner=runner)
    assert result['status']==status and len(calls)==1
    assert s.execute(out,out/'authorization.json',runner=runner)==result and len(calls)==1
    with pytest.raises(ValueError):s.next_call(plan,'PROJ_20456')


def test_uncertain_claim_never_retried(setup):
    plan,out,auth=setup;(out/'dispatch.claim.json').write_text('{}');calls=[]
    with pytest.raises(ValueError,match='UNCERTAIN_OUTCOME'):s.execute(out,out/'authorization.json',runner=fake(plan,calls))
    assert calls==[]


def test_batch_budget_checked_before_dispatch(setup):
    plan,out,auth=setup;plan['batches'][0]['token_reservation_cap']=1
    with pytest.raises(ValueError,match='Batch token'):s.next_call(plan,'PROJ_20456')
