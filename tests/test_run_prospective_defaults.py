"""Default entry point and frozen metadata, offline with disposable inputs only."""
from types import SimpleNamespace

import pytest

import run as console
from scripts import pipeline_coordinator as coordinator
from layer2_processing.preprocessing.adapters import read, write
from layer4_evaluation.indicators import assessment_v3 as v3, prospective_v2 as p2
from tests.test_python_runner import environment
from tests.test_context_budget import corpus, planner, sample


@pytest.mark.parametrize('base',[False,True])
def test_new_run_defaults_and_legacy_policy(base):
    policy=v3.evaluation_policy(base=base)
    assert policy['evaluation_mode']==p2.MODE
    assert policy['decision_policy']==p2.DECISION_POLICY
    assert policy['instructions_version']==p2.PROMPT
    assert policy['confidence_version']==v3.SK_CONFIDENCE_VERSION
    v3.verify_evaluation_policy(policy)
    assert policy['context_mode']==(v3.RETRIEVED_CONTEXT if base else v3.GRAPHRAG_CONTEXT)
    assert v3.evaluation_policy(saved={})=={}
    old=v3.evaluation_policy('prospective-v1',base=base)
    assert v3.evaluation_policy(saved=old)==old


@pytest.mark.parametrize('source',['base','incoming'])
def test_coordinator_records_default_policy_in_all_run_metadata(environment,source):
    root,run,calls=environment
    result=coordinator.execute_pipeline(root,run_id='demo',source=source,through='knowledge',
        knowledge_action='rebuild' if source=='base' else None)
    assert result['status']=='COMPLETE'
    policy=read(coordinator.run_file(run,'execution.json'))['evaluation_policy']
    assert policy['evaluation_mode']==p2.MODE
    assert policy['decision_policy']==p2.DECISION_POLICY
    assert read(coordinator.run_file(run,'run.json'))['configuration']['evaluation_policy']==policy
    assert read(coordinator.run_file(run,'model.binding.json'))['evaluation_policy']==policy
    assert calls==['preprocessing','knowledge']


def test_no_argument_entrypoint_passes_defaults_without_methodology_menu(monkeypatch,tmp_path,capsys):
    calls=[]
    def execute(root,**kwargs):
        calls.append(kwargs)
        policy=v3.evaluation_policy(kwargs['evaluation_mode'],kwargs['context_mode'],base=True)
        assert policy['evaluation_mode']==p2.MODE
        assert policy['decision_policy']==p2.DECISION_POLICY
        assert kwargs['through']=='export' and kwargs['indicator_ids'] is None
        return dict(status='CANCELLED')
    monkeypatch.setattr(console,'ROOT',tmp_path)
    monkeypatch.setattr(console,'coordinator',lambda:SimpleNamespace(execute_pipeline=execute))
    # Existing menus: execute, BASE, select count, count, reuse knowledge, exit.
    answers=iter(['1','2','1','1','','0'])
    monkeypatch.setattr('builtins.input',lambda _:next(answers))
    monkeypatch.setattr(console.sys,'argv',['run.py'])
    assert console.main()==0 and len(calls)==1
    output=capsys.readouterr().out
    assert 'MODO DE EVALUACION' not in output and 'MODO DE CONTEXTO' not in output


def test_console_lists_three_semantic_states_and_separate_errors(capsys):
    console.render_result(dict(status='PARTIAL',result=dict(
        selected_projects=1,processed_projects=1,completed_projects=0,
        expected_assessments=48,valid_assessments=47,supported=10,
        insufficient_evidence=30,not_applicable=7,blocked_assessments=1,
        pending_assessments=0,exported_rows=47)))
    output=capsys.readouterr().out
    for text in ('SUPPORTED: 10','INSUFFICIENT_EVIDENCE: 30','NOT_APPLICABLE: 7','Bloqueados: 1'):
        assert text in output


@pytest.mark.parametrize('base',[False,True])
def test_default_policy_reaches_real_planner_and_all_48_requests(planner,corpus,monkeypatch,base):
    from layer4_evaluation import live_execution as live
    from layer4_evaluation.indicators import scoped_retrieval
    monkeypatch.setattr(live,'OllamaClient',lambda *a,**kw:pytest.fail('No model calls'))
    monkeypatch.setattr(scoped_retrieval,'project_relations',lambda *a:{})
    monkeypatch.setattr(scoped_retrieval,'from_published_cache',
        lambda *a,**kw:(corpus.hits,{'version':'SYNTHETIC_SCOPED_CACHE'}))
    root,run,module=planner
    policy=v3.evaluation_policy(base=base)
    write(coordinator.run_file(run,'execution.json'),dict(evaluation_policy=policy,llm=corpus.settings))
    batch=coordinator.prepare_evaluation(root,run,['TEST'])
    plan=read(module.BASE/batch/'plan.json')
    assert plan['evaluation_policy']==policy
    assert plan['assessment_version']==p2.VERSION
    assert plan['isolate_indicator_errors'] is True
    assert len(plan['profiles'])==len(plan['rubrics'])==48
    requests=plan['context_requests']['TEST_PROJECT']
    assert len(requests)==48
    for request in requests.values():
        assert request['decision_policy']==p2.DECISION_POLICY
        assert request['evaluation_mode']==p2.MODE
        assert request['prompt_version']==p2.PROMPT
        assert request['context_mode']==policy['context_mode']
    manifest=read(module.BASE/batch/'manifest.json')
    assert manifest['evaluation_policy_sha256']==policy['sha256']
