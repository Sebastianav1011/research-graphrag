"""Focused integration of reorganized storage with existing fake evaluations."""
from pathlib import Path

from tests.test_autonomous_execution import environment,ClientFactory,authorize,execute
from tests.test_context_budget import corpus
from tests.test_ollama_provider import sample
from tests.test_manual_pipeline import sandbox
from autonomous_execution import lifecycle as l,store as s
from run_storage import migrate,verify_archive
from run_paths import find_run,file_path


def test_authorized_checkpoint_survives_path_migration_and_resumes(environment):
    e=environment;authorize(e)
    assert migrate(e.root)['migrated']==1
    e.run=find_run(e.root,e.root/'outputs/runs','test','ollama');e.directory=l.folder(e.run)
    assert e.run.parent.name=='local'
    factory=ClientFactory(e.sample)
    assert execute(e,factory)['status']=='COMPLETE' and len(factory.calls)==2
    assert execute(e,factory)['status']=='COMPLETE' and len(factory.calls)==2
    report=l.export(e.root,e.run)
    assert report['status']=='COMPLETE' and report['historico']['status'] in ('ARCHIVED','VERIFIED')
    assert verify_archive(report['historico']['path'])['provider']=='ollama'
    assert file_path(e.run,'execution.json').exists()


def test_all_projects_requires_confirmation_before_pipeline(sandbox):
    from scripts import pipeline_coordinator as c
    from tests.test_scoped_identity import setup_sources,paper
    root,_,config=sandbox
    setup_sources(root,[paper()]);s.write(root/'config/pipeline_manual.json',config)
    events=[]
    result=c.execute_pipeline(root,source='base',run_id='all-preview',all_projects=True,
        confirm=lambda kind,summary:events.append((kind,summary)) or False)
    assert result['status']=='REVIEW_REQUIRED' and result['inference_calls']==0
    assert events[0][0]=='all' and events[0][1]['total_projects']==2
    assert events[0][1]['evaluable_projects']==2
    assert not (root/'outputs/runs/local/all-preview').exists()
    # A positive explicit confirmation authorizes only the requested fake ETL stage.
    result=c.execute_pipeline(root,source='base',run_id='all-confirmed',all_projects=True,
        through='preprocessing',confirm_all=True)
    assert result['status']=='COMPLETE'
    run=find_run(root,root/'outputs/runs','all-confirmed','ollama')
    assert s.read(file_path(run,'run.json'))['configuration']['project_selection']['eligibility_summary']['total_projects']==2
