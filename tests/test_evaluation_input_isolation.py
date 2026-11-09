"""Missing narrative input must not stop unrelated selected projects."""
import pyarrow as pa
import pyarrow.parquet as pq

from scripts import pipeline_coordinator as runner
from .test_unified_runner import system


def test_missing_text_isolated_without_replacing_selected_ids(tmp_path):
    base = tmp_path/'workspace/outputs/layer2'
    (base/'canonical').mkdir(parents=True)
    (base/'knowledge').mkdir()
    projects = [dict(project_id='PROJ_'+pid, source_project_id=pid) for pid in ['1','2','3']]
    sections = [dict(source_id='PROJ_1',field_name='summary',text_original='Texto sustantivo'),
                dict(source_id='PROJ_2',field_name='title',text_original='Solo titulo'),
                dict(source_id='PROJ_2',field_name='summary',text_original='  '),
                dict(source_id='PROJ_3',field_name='text__resultado',text_original='Resultado autorizado')]
    pq.write_table(pa.Table.from_pylist(projects),base/'canonical/proyectos.parquet')
    pq.write_table(pa.Table.from_pylist(sections),base/'knowledge/source_sections.parquet')
    assert runner.projects_without_evidence(tmp_path,['1','2','3']) == ['2']
    assert runner.projects_without_evidence(tmp_path,['1','3']) == []


def test_other_projects_complete_and_export_remains_partial(system, monkeypatch):
    monkeypatch.setattr(runner, 'projects_without_evidence', lambda run, selected: ['002'])
    result = runner.execute_pipeline(system.root, project_ids=['001','002','003'],
                                     through='export', confirm=system.confirm)
    assert result['status'] == 'PARTIAL'
    evaluated = [pid for call in system.calls if isinstance(call,tuple) and call[0]=='ollama' for pid in call[1]]
    assert evaluated == ['001','003']
    saved = runner.read(system.run()/'export.json')
    assert saved['pending_projects'] == ['002']
    assert saved['csv']['indicator_rows'] == 2
