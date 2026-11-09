"""Synthetic Codex transport: bounded selection is distinct from assessment."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from layer4_evaluation.indicators import semantic_fallback as sf, assessment_v2 as v2


def profile(iid, category='SYNTHETIC', dimension='WATER'):
    return dict(indicator_id=iid, indicator_name='Decisión conjunta',
        indicator_category=category, indicator_dimension=dimension,
        key_elements=['Mecanismo de decisión'], preferred_evidence_fields=[],
        descripcion_ampliada='Existe un mecanismo compartido de decisión.',
        source_record_json=json.dumps(dict(forma_evaluacion='PRESENCIA')))


def project():
    fields = dict.fromkeys(v2.FIELDS, None)
    fields['summary'] = 'La comunidad y docentes establecieron un comité con decisiones compartidas.'
    return dict(project_id='SYNTH_PROJECT', fields=fields, candidates=[dict(indicator_id='BASE')],
                eligible_candidates=[dict(indicator_id='BASE'), dict(indicator_id='NEW')])


def selection(p, ids=('NEW',), proposed=True):
    return dict(project_id=p['project_id'], assessments=[dict(indicator_id=iid,
        propose_for_assessment=proposed, reason='Relación funcional documentada.' if proposed else 'Sin soporte.',
        evidence=[dict(field='summary', text=p['fields']['summary'], stage='ACTIVITY_EXECUTED')]
        if proposed else []) for iid in ids])


def assessment(p, iid, decision='SUPPORTED'):
    positive = decision == 'SUPPORTED'
    return dict(indicator_id=iid, assessment_version=v2.VERSION, decision=decision,
        support_strength=4 if positive else 0, criterion_assessments=[dict(criterion_id='C01',
        support='CLEAR' if positive else 'NOT_DEMONSTRATED', required_stage='ACTIVITY_EXECUTED',
        evidence_indices=[0] if positive else [], explanation='Juicio sintético.')],
        evidence=[dict(field='summary', text=p['fields']['summary'], stage='ACTIVITY_EXECUTED')] if positive else [],
        explanation='Fixture sintética, no inferencia real.')


def test_pool_uses_actual_family_not_text_words():
    p = project()
    profiles = {iid: profile(iid) for iid in ('BASE', 'NEW', 'OTHER')}
    profiles['UNRELATED'] = profile('UNRELATED', category='OTHER_CATEGORY', dimension='HEALTH')
    profiles['RULE'] = {**profile('RULE'), 'rule_status':'RULE_TEXT'}
    profiles['UNKNOWN'] = {**profile('UNKNOWN'), 'source_record_json':'{"forma_evaluacion":"RULE_TEXT"}'}
    pool = sf.catalog_pool(p, profiles, ['BASE'])
    assert [i['indicator_id'] for i in pool] == ['NEW', 'OTHER']
    assert len(sf.catalog_pool(p, profiles, ['BASE'], 1)) == 1


def test_same_category_other_dimension_allowed_but_null_does_not_join_categories():
    p=project(); profiles={iid:profile(iid) for iid in ('BASE','NEW')}
    profiles['NEW']['indicator_dimension']='ANOTHER_DIMENSION'
    assert [v['indicator_id'] for v in sf.catalog_pool(p,profiles,['BASE'])]==['NEW']
    profiles['BASE']['indicator_dimension']=None
    profiles['NEW'].update(indicator_dimension=None,indicator_category='UNRELATED')
    assert sf.catalog_pool(p,profiles,['BASE'])==[]


@pytest.mark.parametrize('mutation', [
    lambda w: w['assessments'][0].update(indicator_id='UNKNOWN'),
    lambda w: w['assessments'].append(deepcopy(w['assessments'][0])),
    lambda w: w['assessments'][0]['evidence'][0].update(text='Una cita que no existe.'),
    lambda w: w['assessments'][0]['evidence'][0].update(field='title'),
    lambda w: w['assessments'][0].update(evidence=[]),
    lambda w: w['assessments'][0].update(propose_for_assessment=False),
    lambda w: w['assessments'][0].update(decision='SUPPORTED'),
])
def test_selection_integrity(mutation):
    p = project(); wrapper = selection(p); mutation(wrapper)
    with pytest.raises(Exception):
        sf.validate_selection(wrapper, p, [profile('NEW')])


def test_selection_zero_and_cap_not_compliance():
    p = project()
    assert sf.validate_selection(selection(p, proposed=False), p, [profile('NEW')]) == []
    with pytest.raises(ValueError, match='budget'):
        sf.validate_selection(selection(p, ('A', 'B', 'C')), p, [profile(i) for i in ('A','B','C')])
    assert 'decision' not in sf.selection_schema()['properties']['assessments']['items']['properties']


@pytest.mark.parametrize('change', [dict(max_additional=3), dict(pool_limit=48),
    dict(trigger='UNTIL_SUPPORTED'), dict(enabled='yes'), dict(timeout_seconds=0)])
def test_options_bound_the_fallback(change):
    with pytest.raises(ValueError):
        sf.options(change)


@pytest.fixture
def run(tmp_path, monkeypatch):
    p = project(); profiles = {iid:profile(iid) for iid in ('BASE', 'NEW')}
    base = v2.indicator_row(p, profiles['BASE'], {k:v for k,v in assessment(p,'BASE','NOT_SUPPORTED').items() if k != 'indicator_id'})
    item = dict(project=p, initial_rows=[base], correction_ids=[], initial_request=None,
        correction_request=None, pool=[profiles['NEW']], exploration_request=sf.exploration_input(p, [profiles['NEW']], 2))
    runtime = dict(command=['synthetic-codex'], cli_version='SYNTHETIC', executable_hashes={},
                   exec_help_sha256='SYNTHETIC', features_sha256='SYNTHETIC')
    plan = dict(version=sf.VERSION, options=sf.options(dict(enabled=True)), projects=[item], profiles=profiles,
        rules=[], source_hashes={}, code_hashes={}, runtime=runtime, config_model=None, source_execution_id='SYNTHETIC_BASE')
    out = tmp_path/'outputs/layer4/synthetic'; out.mkdir(parents=True)
    sf._write(out/'plan.json', plan)
    sf._write(out/'exploration.schema.json', sf.selection_schema())
    sf._write(out/'assessment.schema.json', v2.schemas()['assessment_batch'])
    sf._write(out/'manifest.json', dict(execution_id='SYNTHETIC_RUN', plan_sha256=sf._sha(out/'plan.json'),
        prepared_hashes={p.name:sf._sha(p) for p in out.iterdir()}))
    auth = dict(scope='semantic_fallback', plan_sha256=sf._sha(out/'plan.json'), institutional_text_authorized=True,
        project_ids=[p['project_id']], phases=sf._phases(plan), authorized_by='SYNTHETIC',
        authorized_at='2026-10-24', authorization_reference='NO_INSTITUTIONAL_TEXT')
    authpath = tmp_path/'auth.json'; sf._write(authpath, auth)
    monkeypatch.setattr(sf, 'inspect_runtime', lambda command:runtime)
    calls=[]
    def runner(args, **kwargs):
        prompt=kwargs['input']; payload=json.loads(prompt.split('INPUT_JSON:\n')[1]); calls.append(prompt)
        if 'propose_for_assessment' in prompt:
            wrapper=selection(p)
        else:
            wrapper=dict(project_id=p['project_id'], assessments=[assessment(p,i['indicator_id']) for i in payload['indicators']])
        Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(wrapper), encoding='utf-8')
        return SimpleNamespace(returncode=0, stderr='', stdout='{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5,"cached_input_tokens":0}}')
    def reseal():
        sf._write(out/'plan.json', plan)
        manifest=sf.read(out/'manifest.json'); manifest['plan_sha256']=sf._sha(out/'plan.json')
        manifest['prepared_hashes']['plan.json']=manifest['plan_sha256']; sf._write(out/'manifest.json',manifest)
        auth['plan_sha256']=manifest['plan_sha256']; auth['phases']=sf._phases(plan)
        sf._write(authpath,auth)
    return SimpleNamespace(root=tmp_path,out=out,auth=authpath,calls=calls,runner=runner,project=p,plan=plan,reseal=reseal)


def test_authorization_blocks_before_runtime_or_inference(run, monkeypatch):
    value=sf.read(run.auth); value['scope']='pilot'; sf._write(run.auth,value)
    monkeypatch.setattr(sf,'inspect_runtime',lambda command:pytest.fail('Must block before runtime'))
    with pytest.raises(ValueError,match='new authorization'):
        sf.execute(run.root,run.out,run.auth,runner=run.runner)
    assert run.calls==[]


def test_fallback_one_round_metrics_provenance_idempotence(run):
    result=sf.execute(run.root,run.out,run.auth,runner=run.runner)
    assert len(run.calls)==2 and result['additional_assessments']==1 and result['proposed_indicators']==1
    assert result['additional_states']=={'SUPPORTED':1}
    assert result['phases']['exploration']['total_tokens']==15
    assert result['phases']['additional_assessment']['total_tokens']==15
    assert result['phases']['correction']['total_tokens'] is None
    rows=sf.effective_rows(run.root,run.out)
    assert len(rows)==2 and {r['candidate_source'] for r in rows}=={'LAYER3_RETRIEVAL','LAYER4_SEMANTIC_FALLBACK'}
    assert rows[1]['confidence_raw_score']==100
    sf.execute(run.root,run.out,run.auth,runner=run.runner)
    assert len(run.calls)==2


def test_raw_response_tamper_blocks(run):
    sf.execute(run.root,run.out,run.auth,runner=run.runner)
    path=sf._phase_path(run.out,'additional_assessment',run.project['project_id'])
    record=sf.read(path); record['wrapper']['assessments'][0]['explanation']='Modified after inference'
    sf._write(path,record)
    with pytest.raises(ValueError):
        sf.verify(run.root,run.out)


def test_uncertain_directory_not_retried(run):
    path=run.out/'exploration/codex_runs'/run.project['project_id']/'attempt_1'; path.mkdir(parents=True)
    with pytest.raises(ValueError,match='UNCERTAIN_OUTCOME'):
        sf.execute(run.root,run.out,run.auth,runner=run.runner)
    assert run.calls==[]


def test_new_policy_does_not_mutate_original_prompt_or_confidence():
    p=project(); profiles=[profile('NEW')]
    original=v2.make_input(dict(project_id=p['project_id'],fields=p['fields']),profiles,[])
    amended=sf.assessment_input(p,profiles,[])
    assert amended['payload']==original['payload'] and amended['prompt'].endswith(original['prompt'])
    assert original.get('semantic_policy_version') is None
    a={k:v for k,v in assessment(p,'NEW').items() if k!='indicator_id'}
    assert v2.confidence(p['fields'],profiles[0],a)['confidence_raw_score']==100


def test_disabled_fallback_does_not_call_codex(run):
    run.plan['options']['enabled']=False; run.reseal()
    result=sf.execute(run.root,run.out,run.auth,runner=run.runner)
    assert run.calls==[] and result['supplemental_projects_completed']==1
    assert result['additional_assessments']==0


def test_existing_supported_does_not_explore(run):
    row=run.plan['projects'][0]['initial_rows'][0]
    row.update(decision='SUPPORTED')  # synthetic trigger fixture only
    run.reseal()
    result=sf.execute(run.root,run.out,run.auth,runner=run.runner)
    assert run.calls==[] and result['additional_assessments']==0


def test_initial_pending_uses_same_versioned_policy_and_skips_when_supported(run):
    item=run.plan['projects'][0]; item['initial_rows']=[]
    item['initial_request']=sf.assessment_input(run.project,[run.plan['profiles']['BASE']],[])
    run.reseal()
    result=sf.execute(run.root,run.out,run.auth,runner=run.runner)
    assert len(run.calls)==1 and result['new_initial_assessments']==1
    assert result['phases']['initial']['total_tokens']==15
    row=sf.effective_rows(run.root,run.out)[0]
    assert row['supplemental_phase']=='initial' and row['candidate_source']=='LAYER3_RETRIEVAL'
    assert row['semantic_policy_version']==sf.POLICY_VERSION


def test_correction_replaces_active_view_only_and_does_not_reprocess_others(run):
    item=run.plan['projects'][0]; item['correction_ids']=['BASE']
    item['correction_request']=sf.assessment_input(run.project,[run.plan['profiles']['BASE']],[])
    run.reseal()
    result=sf.execute(run.root,run.out,run.auth,runner=run.runner)
    assert len(run.calls)==1 and result['corrected_assessments']==1
    assert sf.effective_rows(run.root,run.out)[0]['decision']=='SUPPORTED'
    assert sf.read(run.out/'plan.json')['projects'][0]['initial_rows'][0]['decision']=='NOT_SUPPORTED'


def test_zero_selected_does_not_assess_or_force_supported(run):
    def runner(args,**kwargs):
        run.calls.append(kwargs['input'])
        Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(selection(run.project,proposed=False)),encoding='utf-8')
        return SimpleNamespace(returncode=0,stderr='',stdout='{"type":"turn.completed"}')
    result=sf.execute(run.root,run.out,run.auth,runner=runner)
    assert len(run.calls)==1 and result['additional_assessments']==0
    assert result['phases']['exploration']['total_tokens'] is None
    assert result['phases']['exploration']['local_cpu_seconds'] is not None


def test_not_supported_additional_does_not_loop(run):
    def runner(args,**kwargs):
        if 'propose_for_assessment' in kwargs['input']:
            return run.runner(args,**kwargs)
        run.calls.append(kwargs['input'])
        Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(dict(project_id=run.project['project_id'],
            assessments=[assessment(run.project,'NEW','NOT_SUPPORTED')])),encoding='utf-8')
        return SimpleNamespace(returncode=0,stderr='',stdout='{"type":"turn.completed"}')
    result=sf.execute(run.root,run.out,run.auth,runner=runner)
    assert len(run.calls)==2 and result['additional_states']=={'NOT_SUPPORTED':1}


def test_incomplete_pilot_never_passes_publication(run):
    sf.execute(run.root,run.out,run.auth,runner=run.runner)
    with pytest.raises(ValueError,match='twenty'):
        sf.publication_check(run.root,run.out,{}, {})


def test_completed_marker_cannot_hide_unexecuted_phase(run):
    sf._write(run.out/'completed'/(run.project['project_id']+'.json'),dict(project_id=run.project['project_id'],record_hashes={}))
    with pytest.raises(ValueError,match='missing exploration'):
        sf.verify(run.root,run.out)


@pytest.fixture
def accepted_twenty(run):
    original=run.plan['projects'][0]; run.plan['projects']=[]
    run.plan['options']['enabled']=False
    for i in range(20):
        item=deepcopy(original); pid='SYNTH_'+str(i)
        item['project']['project_id']=pid
        item['initial_rows'][0]['project_id']=pid
        run.plan['projects'].append(item)
    run.reseal()
    for item in run.plan['projects']:
        sf._complete_project(run.out,item['project']['project_id'])
    rows=sf.effective_rows(run.root,run.out)
    review=dict(supplemental_plan_sha256=sf._sha(run.out/'plan.json'),
        effective_results_sha256=sf.canonical_hash(rows), reviewer_id='SYNTHETIC_TEST', reviewed_at='2026-10-24',
        agreements=[dict(project_id=r['project_id'],indicator_id=r['indicator_id'],agreement_1_to_5=1,
                        notes='Synthetic disagreement resolved separately, no inferred class.') for r in rows])
    approval=dict(supplemental_plan_sha256=review['supplemental_plan_sha256'], semantic_policy_version=sf.POLICY_VERSION,
        effective_results_sha256=review['effective_results_sha256'], confidence_version=v2.CONFIDENCE_VERSION,
        supplemental_approved=True,formula_v2_approved=True,candidate_cap_approved=True,approved=True,
        approved_by='SYNTHETIC_TEST',approved_at='2026-10-24',comparison_reference='SYNTHETIC_ONLY',
        human_review_sha256=sf.canonical_hash(review),discrepancies_resolved=True,resolution_reference='SYNTHETIC_RESOLUTION')
    return run,approval,review


def test_agreement_only_acceptance_does_not_infer_labels(accepted_twenty):
    run,approval,review=accepted_twenty
    result=sf.publication_check(run.root,run.out,approval,review)
    assert result['status']=='PASS'
    assert result['human_review_summary']['classification_metrics'] is None
    assert result['human_review_summary']['human_labels_inferred'] is False
    assert len(result['human_review_summary']['low_agreement_pairs'])==20
    assert all(r['decision']=='NOT_SUPPORTED' for r in result['rows'])


@pytest.mark.parametrize('mutation',[
    lambda a,r:a.update(discrepancies_resolved=False),
    lambda a,r:a.update(resolution_reference=''),
    lambda a,r:a.update(formula_v2_approved=False),
    lambda a,r:a.update(supplemental_plan_sha256='OTHER'),
    lambda a,r:r.update(reviewer_id=''),
    lambda a,r:r['agreements'][0].update(agreement_1_to_5=True),
    lambda a,r:r['agreements'].pop(),
])
def test_votes_never_automatically_accept(accepted_twenty,mutation):
    run,approval,review=accepted_twenty; mutation(approval,review)
    approval['human_review_sha256']=sf.canonical_hash(review)
    with pytest.raises(ValueError,match='BLOCKED'):
        sf.publication_check(run.root,run.out,approval,review)
