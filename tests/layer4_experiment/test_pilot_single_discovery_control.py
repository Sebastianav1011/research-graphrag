"""Local simulations only. A runner stub replaces every inference invocation."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('single_discovery_control',Path(__file__).resolve().parents[2]/'scripts/run_layer4_pilot_discovery_v3_3.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError('Real subprocess/CLI forbidden in local tests')
    monkeypatch.setattr('subprocess.run',forbidden)


@pytest.fixture
def prepared(tmp_path):
    out=s.prepare('PROJ_20456',tmp_path/'20456')
    plan=s.read(out/'plan.json')
    auth=s.read(out/'authorization.example.json')
    auth.update(authorized=True,authorized_by='LOCAL SIMULATION',authorized_at='SIMULATED',
                authorization_reference='SYNTHETIC TEST ONLY; NOT REAL AUTHORIZATION')
    s.write(out/'authorization.json',auth)
    return out,plan


def response(plan, ids=()):
    project=plan['project'];profiles=plan['profiles'];field='summary'
    candidates=[]
    for n,iid in enumerate(ids,1):
        criterion=s.gd.rubric(profiles[iid])['criteria'][0]
        candidates.append(dict(indicator_id=iid,indicator_category=profiles[iid]['indicator_category'],
            priority='ASSESS',rank=n,reason='Synthetic declaration only; not a semantic quality assessment.',
            relevance_class='PARTIAL_RELEVANT',evidence=[dict(field=field,text=project['fields'][field][:100],stage='CONTEXT')],
            criterion_links=[dict(criterion_id=criterion['criterion_id'],criterion_text=criterion['criterion'],
                evidence_indices=[0],correspondence='Synthetic criterion link for contract testing only.')]))
    return dict(project_id=project['project_id'],selection_version=s.gd.VERSION,assessments=[dict(indicator_id=s.gd.MARKER,
        candidates=candidates,rejected=[dict(indicator_id=iid,indicator_category=p['indicator_category'],
        relevance_class='NO_RELATION',reason='Synthetic rejection only.') for iid,p in profiles.items() if iid not in ids])])


def fake_runner(plan,invoked,*,ids=(),usage=True,invalid=False,error=False,total_input=3):
    def runner(args,**kwargs):
        invoked.append(args)
        assert '--disable' in args and 'multi_agent' in args
        payload=json.loads(kwargs['input'].split('\nINPUT_JSON:\n',1)[1])
        assert payload['project']['project_id']==plan['project_ids'][0]
        assert payload['selection_version']==s.gd.VERSION and len(payload['catalog'])==48
        if error:return SimpleNamespace(returncode=1,stdout='{"type":"turn.failed","error":{"message":"synthetic failure"}}\n',stderr='')
        wrapper=response(plan,ids)
        if invalid:wrapper['project_id']='OTHER_PROJECT'
        Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(wrapper),encoding='utf-8')
        stdout=json.dumps(dict(type='turn.completed',usage=dict(input_tokens=total_input,output_tokens=2,cached_input_tokens=0)))+'\n' if usage else ''
        return SimpleNamespace(returncode=0,stdout=stdout,stderr='')
    return runner


def test_single_call_resume_and_no_assessment_even_with_six_candidates(prepared):
    out,plan=prepared;calls=[]
    historical=s.candidate_rows(plan);ids=list(historical)
    assert len(ids)==6
    runner=fake_runner(plan,calls,ids=ids)
    first=s.execute(out,out/'authorization.json',runner=runner)
    resumed=s.execute(out,out/'authorization.json',runner=runner)
    assert first==resumed and first['status']=='PASS' and len(calls)==1
    assert first['calls']==1 and first['retries']==0 and first['assessments_dispatched']==0
    assert not list(out.glob('assessment*'))
    compared=s.read(out/'reuse_comparison.json')
    assert len(compared['entries'])==6 and all(x['status']=='REUSABLE' for x in compared['entries'])
    assert all(x['assessment']['discovered_by']=='GLOBAL_DISCOVERY_V3' and x['selection_version']=='GLOBAL_DISCOVERY_V3_3' for x in compared['entries'])
    print('SIMULATION PASS: six candidates, one fake call, six deterministic reusable pairs, zero assessments, zero additional calls on resume')


@pytest.mark.parametrize('kind,expected',[('no_usage','BLOCKED_MISSING_METRICS'),('invalid','BLOCKED_ERROR'),('error','BLOCKED_ERROR'),('large','PAUSED_TOKEN_REVIEW'),('over','BLOCKED_TOKEN_BUDGET')])
def test_errors_missing_metrics_and_excess_tokens_stop_without_retry(prepared,kind,expected):
    out,plan=prepared;calls=[]
    runner=fake_runner(plan,calls,usage=kind!='no_usage',invalid=kind=='invalid',error=kind=='error',total_input=81000 if kind=='over' else 61000 if kind=='large' else 3)
    result=s.execute(out,out/'authorization.json',runner=runner)
    assert result['status']==expected and result['assessments_dispatched']==0
    assert s.execute(out,out/'authorization.json',runner=runner)==result and len(calls)==1
    assert not (out/'reuse_comparison.json').exists()


@pytest.mark.parametrize('change',[
    lambda a:a.update(authorized=False),lambda a:a.update(project_ids=['PROJ_21299']),
    lambda a:a.update(maximum_new_calls=2),lambda a:a.update(max_retries=1),
    lambda a:a.update(maximum_assessments=1),lambda a:a.update(token_budget=79999),
    lambda a:a.update(plan_sha256='OTHER'),lambda a:a.update(request_sha256='OTHER')])
def test_authorization_is_project_specific_and_budget_bound(prepared,change):
    out,plan=prepared;auth=s.read(out/'authorization.json');change(auth);s.write(out/'authorization.json',auth);calls=[]
    with pytest.raises(ValueError):s.execute(out,out/'authorization.json',runner=fake_runner(plan,calls))
    assert calls==[] and not (out/'dispatch.claim.json').exists()


def test_uncertain_claim_cannot_be_removed_or_retried_automatically(prepared):
    out,plan=prepared;s.write(out/'dispatch.claim.json',dict(interrupted=True));calls=[]
    with pytest.raises(ValueError,match='already claimed'):
        s.execute(out,out/'authorization.json',runner=fake_runner(plan,calls))
    assert calls==[] and s.read(out/'dispatch.claim.json')==dict(interrupted=True)


def test_reuse_checks_semantics_and_rubric_not_only_indicator_id(prepared):
    out,plan=prepared;selection=s.gd.validate_selection(response(plan,['ASC-01']),plan['project'],plan['profiles'])
    changed=deepcopy(plan);changed['rules'][0]['descripcion']+=' Different semantic input.'
    with pytest.raises(ValueError,match='semantic input differs'):
        s.comparison(changed,selection,'SYNTHETIC_HASH')
    changed=deepcopy(plan);changed['rubric_hashes']['ASC-01']='OTHER'
    with pytest.raises(ValueError,match='Rubric content/version changed'):
        s.comparison(changed,selection,'SYNTHETIC_HASH')


def test_new_pairs_are_not_assessed_and_22027_outside_scope(prepared):
    out,plan=prepared;selection=s.gd.validate_selection(response(plan,['AMB-01']),plan['project'],plan['profiles'])
    result=s.comparison(plan,selection,'SYNTHETIC_HASH')
    assert result['entries'][0]['status']=='NEEDS_ASSESSMENT_NOT_AUTHORIZED'
    assert result['assessments_dispatched']==0
    with pytest.raises(ValueError,match='outside'):
        s.directory('PROJ_22027')


def test_missing_auth_and_changed_project_fingerprint_block(prepared):
    out,plan=prepared;calls=[]
    with pytest.raises(ValueError,match='authorization file required'):
        s.execute(out,None,runner=fake_runner(plan,calls))
    plan['project']['fields']['summary']='Changed project'
    s.write(out/'plan.json',plan)
    with pytest.raises(ValueError,match='Plan fingerprint changed'):
        s.execute(out,out/'authorization.json',runner=fake_runner(plan,calls))
    assert calls==[]


def test_21299_has_its_own_scope_and_unapproved_template(tmp_path):
    out=s.prepare('PROJ_21299',tmp_path/'21299')
    assert s.check(out)['project_ids']==['PROJ_21299']
    assert s.read(out/'authorization.example.json')['authorized'] is False
    assert len(s.candidate_rows(s.check(out)))==6
