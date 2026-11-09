"""Metadata-only source records never become technical failures or fake evidence."""
import csv
import json

import pyarrow.parquet as pq
import pytest
import yaml

from .test_manual_pipeline import sandbox
from scripts import pipeline_coordinator as runner
from layer2_processing.preprocessing.adapters import prepare_files, read, sha, tabular


def source(root, rows):
    path=root/'data/layer1_sources/base/descriptores-test.csv'
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    return path


def test_unselected_metadata_record_is_preserved_without_empty_document(sandbox):
    root,_,config=sandbox
    path=source(root,[dict(id_actividad='21736',resumen='Synthetic authorized research narrative',convocatoria_codigo='TEST'),
        dict(id_actividad='20006',resumen='',convocatoria_codigo='TEST')])
    fingerprint=sha(path);run=root/'outputs/runs/metadata_support'
    assert runner.prepare(root,run,root/'data/layer1_sources','raw',config)['status']=='PREPARED'
    folder=run/'workspace/outputs/layer2'
    canonical=pq.read_table(folder/'canonical/proyectos.parquet').to_pylist()
    assert {r['source_project_id'] for r in canonical}=={'21736','20006'}
    metadata=next(r for r in canonical if r['source_project_id']=='20006')
    ref=json.loads(metadata['provenance_json'])[0]
    assert ref['original_values']['convocatoria_codigo']=='TEST'
    assert ref['text_status']=='NO_AUTHORIZED_SUBSTANTIVE_TEXT'
    docs=pq.read_table(folder/'knowledge/source_documents.parquet').to_pylist()
    assert {r['source_id'] for r in docs}=={'PROJ_21736'}
    entities=pq.read_table(folder/'knowledge/entities.parquet').to_pylist()
    assert any(e['canonical_id']=='PROJ_20006' for e in entities)
    report=read(folder/'knowledge_artifacts/quality/summary.json')
    assert report['status']=='PASS' and report['documents']['canonical_records_without_document']==1
    assert report['reports']['non_document_records']==1
    settings=yaml.safe_load((run/'workspace/config/layer2.yaml').read_text(encoding='utf-8'))
    assert settings['quality']['max_empty_document_ratio']==0.001
    assert runner.scope_projects(root,run,{'mode':'projects'},['21736'])==['21736']
    assert runner.graph(root,run)['status']=='VALIDATED_APPROVED_LAYER_2_INPUT'
    assert sha(path)==fingerprint
    # Omitting a document with real text must still fail, rather than being
    # relabeled as an acceptable metadata-only record.
    from layer2_processing.knowledge.contracts import SCHEMAS
    from layer2_processing.knowledge.validate_inputs import validate_inputs, load_config
    from layer2_processing.knowledge.pipeline import context_for
    from layer2_processing.knowledge.quality import evaluate
    workspace=run/'workspace'
    settings,digest=load_config(workspace,'config/layer2.yaml')
    snapshot=validate_inputs(workspace,settings)
    manifest=read(folder/'knowledge/_manifest.json')
    context=context_for(snapshot,settings,digest,manifest['layer2_run_id'])
    package={name:pq.read_table(folder/f'knowledge/{name}.parquet').to_pylist() for name in SCHEMAS}
    for name in ('source_documents','source_sections','source_chunks'):package[name]=[]
    bad,_=evaluate(package,snapshot['datasets'],settings,context)
    assert bad['status']=='FAIL' and 'MISSING_TEXT_DOCUMENT' in bad['failures']


@pytest.mark.parametrize('title',['','Synthetic orientation title'])
def test_selected_without_evidence_is_blocked_before_provider_or_graph(sandbox,monkeypatch,title):
    root,_,config=sandbox
    source(root,[dict(id_actividad='21736',titulo=title,resumen='',convocatoria_codigo='TEST')])
    run=root/'outputs/runs/selected_no_evidence'
    assert runner.prepare(root,run,root/'data/layer1_sources','raw',config)['status']=='PREPARED'
    monkeypatch.setattr(runner,'validated_graph',lambda *a:pytest.fail('No graph is needed to detect missing evidence'))
    monkeypatch.setattr(runner,'engine',lambda *a:pytest.fail('No LLM engine may run without evidence'))
    with pytest.raises(ValueError,match='sin evidencia textual sustantiva autorizada.*21736'):
        runner.prepare_evaluation(root,run,['21736'])
    report=read(run/'evaluation_readiness.json')
    assert report['status']=='BLOCKED_NO_EVIDENCE'
    assert report['projects'][0]['status']=='NO_AUTHORIZED_SUBSTANTIVE_TEXT'
    assert not (run/'workspace/outputs/layer4').exists()
    assert runner.check(root,run)['status']=='PREPARED'


def test_warning_uses_the_readers_original_multiline_csv_locator(sandbox):
    root,_,config=sandbox
    path=source(root,[dict(id_actividad='21736',resumen='Synthetic multiline\nresearch evidence'),dict(id_actividad='20006',resumen='')])
    _,rows,_=tabular(path)
    expected=next(n for n,r in rows if r['id_actividad']=='20006')
    run=root/'outputs/runs/locator'
    prepare_files(root,root/'data/layer1_sources',run,config)
    warnings=[d for d in read(run/'preprocess/diagnostics.json') if d['code']=='NO_AUTHORIZED_SUBSTANTIVE_TEXT']
    assert expected==4 and warnings[0]['row']==expected and warnings[0]['project_id']=='20006'
    assert warnings[0]['severity']=='WARNING'


@pytest.mark.parametrize('kind',['missing_id','conflicting_id','structure'])
def test_critical_identity_and_structure_still_reject_every_publication(sandbox,kind):
    root,_,config=sandbox
    if kind=='missing_id':
        source(root,[dict(id_actividad='',resumen='Synthetic text')])
    elif kind=='conflicting_id':
        source(root,[dict(id_actividad='21736',siap_id='CONFLICT',resumen='Synthetic text')])
    else:
        path=root/'data/layer1_sources/base/descriptores-test.csv'
        path.write_text('id_actividad,resumen\n21736,text,unexpected\n',encoding='utf-8')
    run=root/'outputs/runs/critical'
    with pytest.raises(ValueError,match='Entrada rechazada'):
        runner.prepare(root,run,root/'data/layer1_sources','raw',config)
    assert read(run/'run.json')['status']=='FAILED'
    assert any(d['code']=='INPUT_REJECTED' and d['severity']=='ERROR' for d in read(run/'preprocess/diagnostics.json'))
    assert not (run/'workspace/outputs/layer2/canonical').exists()


@pytest.mark.parametrize('authorized',[False,True])
def test_flexible_column_only_becomes_evidence_after_authorization(sandbox,authorized):
    root,_,config=sandbox
    incoming=root/'data/layer1_sources/incoming/test';incoming.mkdir(parents=True)
    path=incoming/'findings.json'
    path.write_text(json.dumps([dict(id_actividad='21736',hallazgos_principales='Synthetic finding retained verbatim')]),encoding='utf-8')
    if authorized:config['text_columns']['authorized_categories']=['findings']
    run=root/'outputs/runs/flexible'
    assert runner.prepare(root,run,root/'data/layer1_sources','raw',config)['status']=='PREPARED'
    sections=pq.read_table(run/'workspace/outputs/layer2/knowledge/source_sections.parquet').to_pylist()
    assert any(s['text_original']=='Synthetic finding retained verbatim' for s in sections)==authorized
    refs=read(run/'preprocess/lineage.json')
    ref=next(iter(next(iter(refs.values())).values()))
    assert ref['original_values']['hallazgos_principales']=='Synthetic finding retained verbatim'
    assert ref['text_status']==('AUTHORIZED_SUBSTANTIVE_TEXT' if authorized else 'NO_AUTHORIZED_SUBSTANTIVE_TEXT')
