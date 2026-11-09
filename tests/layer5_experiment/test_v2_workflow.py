"""Exercise the existing coordinator end to end with V2 and a mocked Codex transport."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from test_experiment import offline  # existing offline publication/runtime fixture
from layer4_evaluation.indicators import experiment as ex, assessment_v2 as v2, closure_audit
from layer4_evaluation.indicators.codex_cli import CodexCliAssessmentProvider
from layer4_evaluation.indicators.performance_report import collect
from layer4_evaluation.indicators.closure_export import publish, comparison
from layer4_evaluation.indicators import closure_export
from layer4_evaluation.indicators.selection import canonical_hash


@pytest.fixture
def workflow(offline):
    f=offline
    config=deepcopy(f.config)
    config.update(version=ex.V2,project_count=20,output_directory='outputs/layer4/experiment_synthetic_v2',
                  sample_source='synthetic_sample.json')
    ex.write_json(f.root/'synthetic_sample.json',{'projects':f.data['eligible'][:20]})
    path=f.root/'config/layer4_v2.synthetic.yaml'
    path.write_text(yaml.safe_dump(config),encoding='utf-8')
    v2.write_contracts(f.root)
    f.monkeypatch.setattr(closure_audit,'closure_snapshot',lambda root:{'fixture.txt':ex.sha256(f.root/'fixture.txt')})
    calls=[];bad=set()
    def runner(args,**kwargs):
        payload=json.loads(kwargs['input'].split('INPUT_JSON:\n')[1])
        project=payload['project'];calls.append(project['project_id'])
        assessments=[]
        for profile in payload['indicators']:
            assessments.append({'indicator_id':profile['indicator_id'],'assessment_version':v2.VERSION,
                'decision':'SUPPORTED','support_strength':3,
                'criterion_assessments':[{'criterion_id':c['criterion_id'],'support':'CLEAR',
                    'required_stage':'ACTIVITY_PROPOSED','evidence_indices':[0],'explanation':'Generic synthetic judgement.'}
                    for c in profile['rubric']['criteria']],
                'evidence':[{'field':'summary','text':'Missing quote' if project['project_id'] in bad else 'Conservar bosques.',
                             'stage':'ACTIVITY_PROPOSED'}], 'explanation':'Synthetic fixture, no institutional inference.'})
        Path(args[args.index('--output-last-message')+1]).write_text(json.dumps({
            'project_id':project['project_id'],'assessments':assessments}),encoding='utf-8')
        return SimpleNamespace(returncode=0,stdout='{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5}}',stderr='')
    f.monkeypatch.setattr(ex,'CodexCliAssessmentProvider',lambda *a,**kw:CodexCliAssessmentProvider(*a,runner=runner,**kw))
    cfg='config/layer4_v2.synthetic.yaml'
    prepared=ex.prepare(f.root,cfg)
    out=f.root/config['output_directory']
    def auth(scope):
        value=ex.read(out/'authorization.example.json')
        value.update(scope=scope,institutional_text_authorized=True,authorized_by='SYNTHETIC_TEST',
                     authorized_at='2026-10-20T00:00:00Z',authorization_reference='SYNTHETIC_NO_REAL_TEXT')
        target=f.root/(scope+'_v2.json');ex.write_json(target,value);return target
    return SimpleNamespace(root=f.root,cfg=cfg,out=out,calls=calls,bad=bad,auth=auth,prepared=prepared,monkeypatch=f.monkeypatch)


def test_v2_preparation_is_not_inference_and_has_metrics(workflow):
    f=workflow
    assert f.prepared['projects_selected']==20 and f.prepared['assessments_returned']==0
    assert f.calls==[]
    assert len(ex.read(f.out/'preparation_metrics.json'))==20
    assert ex.verify(f.root,f.cfg)['status']=='PASS'
    projects,rows,summary=collect(f.root,f.cfg)
    assert len(projects)==20 and not rows and summary['projects_evaluated']==0
    assert all(p['total_tokens'] is None for p in projects)
    assert all(p['completion_status']=='NOT_EXECUTED' for p in projects)
    assert comparison(f.root,f.cfg)['evaluations_compared']==0
    with pytest.raises(ValueError,match='BLOCKED'):
        publish(f.root,f.cfg)
    assert not (f.root/'outputs/layer4/final/resultado_capa4.xlsx').exists()


def test_v2_batches_safe_resume_and_original_consumption(workflow):
    f=workflow
    result=ex.execute_batch(f.root,f.cfg,stage='pilot',authorization=f.auth('pilot'))
    assert result['pilot_complete'] and len(f.calls)==5
    assert ex.verify(f.root,f.cfg)['status']=='PASS'
    again=ex.execute_batch(f.root,f.cfg,stage='pilot',authorization=f.auth('pilot'))
    assert len(f.calls)==5 and again['codex_calls']==5
    projects,rows,summary=collect(f.root,f.cfg)
    assert summary['original_calls_unique']==5 and summary['new_inference_calls']==0
    assert summary['statistics']['input_tokens']['total']==50
    assert summary['statistics']['local_cpu_seconds']['n']==5
    assert summary['statistics']['local_ram_bytes']['n']==5
    assert all(r['input_tokens'] is None for r in rows)
    assert ex.read(f.out/'batches/001.json')['wall_seconds_measured']>0
    approval=f.root/'synthetic_pilot_approval.json'
    ex.write_json(approval,{'selection_sha256':result['selection_sha256'],
        'pilot_results_sha256':result['pilot_results_sha256'],'approved':True,
        'approved_by':'SYNTHETIC_TEST','approved_at':'2026-10-20'})
    for _ in range(3):
        result=ex.execute_batch(f.root,f.cfg,stage='continue',authorization=f.auth('continue'),pilot_approval=approval)
    assert result['execution_complete'] and len(f.calls)==20
    assert ex.verify(f.root,f.cfg)['real_execution_complete']
    # Complete technical execution is still insufficient for human acceptance.
    with pytest.raises(ValueError,match='BLOCKED'):
        publish(f.root,f.cfg)


def test_invalid_semantics_no_retry_no_automatic_reinference(workflow):
    f=workflow
    first=ex.read(f.out/'selection_manifest.json')['projects'][0]['project_id']
    f.bad.add(first)
    result=ex.execute_batch(f.root,f.cfg,stage='pilot',authorization=f.auth('pilot'))
    assert len(f.calls)==5 and result['assessments_invalid']>0
    row=ex.read(f.out/'records'/(first+'.json'))['rows'][0]
    assert row['confidence_raw_score'] is None and row['confidence_status']=='INVALID_ASSESSMENT'
    with pytest.raises(ValueError,match='requires review'):
        ex.execute_batch(f.root,f.cfg,stage='pilot',authorization=f.auth('pilot'))
    assert len(f.calls)==5


def test_uncertain_and_fingerprint_tamper_block_before_inference(workflow):
    f=workflow
    first=ex.read(f.out/'selection_manifest.json')['projects'][0]['project_id']
    (f.out/'codex_runs'/first/'attempt_1').mkdir(parents=True)
    result=ex.execute_batch(f.root,f.cfg,stage='pilot',authorization=f.auth('pilot'))
    assert len(f.calls)==4
    assert any('UNCERTAIN_OUTCOME' in (r['error'] or '') for r in result['errors'])
    inputs=f.out/'assessment_inputs.jsonl'
    inputs.write_text(inputs.read_text(encoding='utf-8')+'\n',encoding='utf-8')
    with pytest.raises(ValueError,match='Fingerprint mismatch'):
        ex.verify(f.root,f.cfg)


def test_final_two_sheet_publication_and_tamper_detection(workflow):
    f=workflow
    result=ex.execute_batch(f.root,f.cfg,stage='pilot',authorization=f.auth('pilot'))
    approval=f.root/'pilot.json'
    ex.write_json(approval,{'selection_sha256':result['selection_sha256'],
        'pilot_results_sha256':result['pilot_results_sha256'],'approved':True,
        'approved_by':'SYNTHETIC_TEST_ONLY','approved_at':'2026-10-20'})
    for _ in range(3):
        ex.execute_batch(f.root,f.cfg,stage='continue',authorization=f.auth('continue'),pilot_approval=approval)
    rows=ex.read_jsonl(f.out/'technical_results.jsonl')
    manifest=ex.read(f.out/'experiment_manifest.json')
    review={'selection_sha256':manifest['selection_sha256'],
        'technical_results_sha256':ex.sha256(f.out/'technical_results.jsonl'),
        'labels':[{'project_id':r['project_id'],'indicator_id':r['indicator_id'],
            'human_label':r['decision'],'reviewer_id':'SYNTHETIC_REVIEWER_NO_HUMAN_REVIEW_CLAIM',
            'reviewed_at':'2026-10-20','independent':True,'evidence_valid':True,
            'conceptual_mapping_valid':True,'temporal_valid':True,'rubric_valid':True} for r in rows]}
    final={'selection_sha256':manifest['selection_sha256'],'technical_results_sha256':review['technical_results_sha256'],
        'human_review_sha256':canonical_hash(review),'confidence_version':v2.CONFIDENCE_VERSION,
        'candidate_limit_per_project':2,'formula_v2_approved':True,'candidate_cap_approved':True,
        'approved':True,'approved_by':'SYNTHETIC_TEST_ONLY','approved_at':'2026-10-20',
        'formula_comparison_reference':'SYNTHETIC_TEST_ONLY','candidate_comparison_reference':'SYNTHETIC_TEST_ONLY'}
    review_path=f.root/'synthetic_review.json';approval_path=f.root/'synthetic_final.json'
    ex.write_json(review_path,review);ex.write_json(approval_path,final)
    # Existing authoring runtime, actual saved-XLSX verification, generic text only.
    scripts=f.root/'scripts';scripts.mkdir(exist_ok=True)
    source=Path(__file__).resolve().parents[2]/'scripts/render_layer4_experiment.mjs'
    (scripts/source.name).write_bytes(source.read_bytes())
    f.monkeypatch.setattr(closure_export,'selected_territories',lambda data,selected:[])
    published=publish(f.root,f.cfg,approval_path,review_path)
    assert published['projects']==20 and published['assessment_count']==len(rows)
    assert set(p.name for p in (f.root/'outputs/layer4/final').iterdir())=={'resultado_capa4.xlsx'}
    assert closure_export.verify_final(f.root,f.cfg)['status']=='PASS'
    assert published['qa']['sheet_rows']=={'RESULTADO_INDICADORES':len(rows),'TERRITORIOS':0}
    # Saved acceptance is itself part of verification, not an unverified claim.
    saved=f.root/published['review_snapshot'];saved.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='Fingerprint mismatch'):
        closure_export.verify_final(f.root,f.cfg)
