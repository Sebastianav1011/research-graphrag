"""V2 contracts and gates with generic synthetic text; never institutional inference."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from layer4_evaluation.indicators import assessment_v2 as v2
from layer4_evaluation.indicators import experiment as ex
from layer4_evaluation.indicators.closure_export import consumer_rows, acceptance_gate
from layer4_evaluation.indicators.performance import Measurement, interval_union, usage_metrics, describe
from layer4_evaluation.indicators.selection import canonical_hash
from layer4_evaluation.indicators.codex_cli import CodexCliAssessmentProvider
from layer4_evaluation.indicators.performance_report import projections_from_completed


@pytest.fixture
def case():
    fields=dict.fromkeys(v2.FIELDS,'')
    fields.update(summary='Se realizaron encuentros entre habitantes y docentes para decidir el manejo del agua.',
                  objectives='Se propone crear un comité para conservar el río.',
                  expected_results='Se espera reducir la contaminación.')
    profile={'indicator_id':'SYNTH_I','indicator_name':'Gobernanza participativa',
             'indicator_category':'SYNTHETIC','indicator_dimension':None,
             'key_elements':['Participación comunitaria','Decisión colectiva'],
             'preferred_evidence_fields':[],'descripcion_ampliada':'Participación ejecutada en decisiones sobre recursos.',
             'source_record_json':'{}'}
    assessment={'assessment_version':v2.VERSION,'decision':'SUPPORTED','support_strength':4,
        'criterion_assessments':[{'criterion_id':f'C{i:02d}','support':'CLEAR','required_stage':'ACTIVITY_EXECUTED',
            'evidence_indices':[0],'explanation':'Equivalencia semántica, sin igualdad de palabras.'} for i in (1,2)],
        'evidence':[{'field':'summary','text':fields['summary'],'stage':'ACTIVITY_EXECUTED'}],
        'explanation':'Una sola evidencia sustantiva demuestra los conceptos.'}
    return fields,profile,assessment


def test_equivalent_concepts_single_quote_full_confidence(case):
    fields,p,a=case
    assert not any(label in fields['summary'] for label in p['key_elements'])
    assert v2.validate(fields,p,a)==[]
    assert v2.confidence(fields,p,a)['confidence_raw_score']==100
    r=v2.indicator_row({'project_id':'SYNTH_P','fields':fields},p,a)
    assert r['v1_comparison_score']==94
    assert r['corroboration_score']==.7
    assert r['confidence_raw_score']==100


@pytest.mark.parametrize('decision,strength,levels,expected',[
    ('SUPPORTED',3,['CLEAR','CLEAR'],86.25),
    ('INSUFFICIENT_EVIDENCE',2,['PARTIAL','NOT_DEMONSTRATED'],38.75),
    ('INSUFFICIENT_EVIDENCE',1,['NOT_DEMONSTRATED','NOT_DEMONSTRATED'],13.75),
    ('NOT_SUPPORTED',0,['NOT_DEMONSTRATED','NOT_DEMONSTRATED'],0),
])
def test_all_valid_decisions_score_without_reclassification(case,decision,strength,levels,expected):
    fields,p,a=case
    a.update(decision=decision,support_strength=strength)
    for c,level in zip(a['criterion_assessments'],levels):
        c.update(support=level,evidence_indices=[] if level=='NOT_DEMONSTRATED' else [0])
    result=v2.confidence(fields,p,a)
    assert result['confidence_status']=='COMPUTED'
    assert result['confidence_raw_score']==expected
    assert a['decision']==decision
    assert result['confidence_probability'] is None


@pytest.mark.parametrize('mutation',[
    lambda a:a['evidence'][0].update(text='Una cita inexistente.'),
    lambda a:a['evidence'][0].update(field='title'),
    lambda a:a['criterion_assessments'][0].update(evidence_indices=[8]),
    lambda a:a['criterion_assessments'][0].update(evidence_indices=[]),
    lambda a:a['criterion_assessments'][0].update(criterion_id='UNKNOWN'),
    lambda a:a['criterion_assessments'].append(deepcopy(a['criterion_assessments'][0])),
    lambda a:a.update(support_strength=True),
    lambda a:a.update(support_strength=2),
    lambda a:a.update(confidence=100),
])
def test_invalid_is_null_never_zero(case,mutation):
    fields,p,a=case;mutation(a)
    result=v2.confidence(fields,p,a)
    assert result['confidence_status']=='INVALID_ASSESSMENT'
    assert result['confidence_raw_score'] is None


def test_empty_information_valid_not_supported_zero(case):
    fields,p,a=case
    fields=dict.fromkeys(fields,None)
    a.update(decision='NOT_SUPPORTED',support_strength=0,evidence=[])
    for c in a['criterion_assessments']:
        c.update(support='NOT_DEMONSTRATED',evidence_indices=[])
    assert v2.confidence(fields,p,a)['confidence_raw_score']==0
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=1)
    assert v2.confidence(fields,p,a)['confidence_raw_score'] is None


@pytest.mark.parametrize('required,evidence_stage',[
    ('ACTIVITY_EXECUTED','ACTIVITY_PROPOSED'),('RESULT_DEMONSTRATED','RESULT_EXPECTED'),
    ('RESULT_DEMONSTRATED','ACTIVITY_EXECUTED')])
def test_plans_and_expected_results_do_not_demonstrate_outcomes(case,required,evidence_stage):
    fields,p,a=case
    a['evidence'][0]['stage']=evidence_stage
    for c in a['criterion_assessments']:c['required_stage']=required
    assert 'CRITERION:TEMPORAL_REQUIREMENT_NOT_DEMONSTRATED' in v2.validate(fields,p,a)


def test_distributed_evidence_not_rewarded_for_count(case):
    fields,p,a=case
    before=v2.confidence(fields,p,a)['confidence_raw_score']
    fields['methodology']=fields['summary']
    a['evidence'].append({**a['evidence'][0],'field':'methodology'})
    for c in a['criterion_assessments']:c['evidence_indices']=[0,1]
    assert v2.confidence(fields,p,a)['confidence_raw_score']==before


def test_thematic_mentions_not_automatically_conceptual_support(case):
    fields,p,a=case
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=1)
    for c in a['criterion_assessments']:c.update(support='NOT_DEMONSTRATED',evidence_indices=[])
    assert v2.confidence(fields,p,a)['conceptual_coverage']==0
    assert v2.confidence(fields,p,a)['confidence_raw_score']==13.75
    a.update(decision='NOT_SUPPORTED',support_strength=0)
    a['criterion_assessments'][0].update(support='PARTIAL',evidence_indices=[0])
    assert v2.confidence(fields,p,a)['confidence_raw_score'] is None


def test_nfc_whitespace_quotes_but_no_paraphrase(case):
    fields,p,a=case
    a['evidence'][0]['text']=a['evidence'][0]['text'].replace(' ','\n  ')
    assert not v2.validate(fields,p,a)
    a['evidence'][0]['text']='La comunidad participó activamente.'
    assert v2.confidence(fields,p,a)['confidence_raw_score'] is None


def test_wrapper_and_schema_versioning(case,tmp_path):
    fields,p,a=case
    wrapper={'project_id':'SYNTH_P','assessments':[{'indicator_id':p['indicator_id'],**a}]}
    assert v2.validate_wrapper(wrapper,'SYNTH_P',[p['indicator_id']])==wrapper
    with pytest.raises(ValueError):v2.validate_wrapper(wrapper,'OTHER',[p['indicator_id']])
    v2.write_contracts(tmp_path);v2.write_contracts(tmp_path,check=True)
    result=v2.confidence(fields,p,a)
    Draft202012Validator(v2.schemas()['confidence_result']).validate(result)
    a['evidence'][0]['text']='Not present'
    Draft202012Validator(v2.schemas()['confidence_result']).validate(v2.confidence(fields,p,a))


def test_native_schema_excludes_unsupported_uniqueitems_but_python_enforces_it(case):
    fields,p,a=case
    assert 'uniqueItems' not in json.dumps(v2.schemas()['assessment_batch'])
    assert 'uniqueItems' in json.dumps(v2.schemas()['assessment'])
    a['criterion_assessments'][0]['evidence_indices']=[0,0]
    assert v2.confidence(fields,p,a)['confidence_status']=='INVALID_ASSESSMENT'


def test_invalid_schema_is_fatal_without_futile_retry(case,tmp_path):
    fields,p,a=case
    schema=tmp_path/'schema.json';schema.write_text(json.dumps(v2.schemas()['assessment_batch']))
    from layer4_evaluation.indicators.codex_cli import CodexCliBlocked
    calls=[]
    def runner(*args,**kwargs):
        calls.append(1)
        return SimpleNamespace(returncode=1,stdout=json.dumps({'type':'error','message':
            'Invalid schema for response_format: invalid_json_schema'}),stderr='')
    provider=CodexCliAssessmentProvider(tmp_path/'run',schema,lambda project,indicators:v2.make_input(project,indicators,[]),
        command=['SYNTHETIC_NEVER_EXECUTE'],runner=runner,wrapper_validator=v2.validate_wrapper)
    with pytest.raises(CodexCliBlocked):provider.evaluate({'project_id':'SYNTH_P','fields':fields},[p])
    assert len(calls)==1


def test_metric_missing_tokens_and_cache_subset():
    assert usage_metrics({})['total_tokens']=={'value':None,'status':'NOT_AVAILABLE','scope':'INPUT_PLUS_OUTPUT_CACHED_IS_SUBSET'}
    metrics=usage_metrics({'usage_observations':[{'input_tokens':100,'output_tokens':20,'cached_input_tokens':40}]})
    assert metrics['total_tokens']['value']==120
    assert metrics['cached_tokens']['value']==40
    assert usage_metrics({'usage_observations':[{},{}]})['input_tokens']['status']=='NOT_AVAILABLE'
    assert usage_metrics({'usage_observations':[{'input_tokens':True}]})['input_tokens']['value'] is None


def test_intervals_not_summed_as_concurrent_wall():
    assert interval_union([(0,10),(5,15),(20,22)])==17
    assert interval_union([])==0
    assert describe([])['mean'] is None
    assert describe([0,10])['median']==5
    with Measurement() as measurement:
        sum(range(100))
    assert measurement.result['wall_seconds']['value']>=0
    assert measurement.result['cpu_seconds']['scope']=='PYTHON_COORDINATOR_ONLY'
    assert measurement.result['remote_ram']['status']=='NOT_AVAILABLE'


def test_timeouts_cannot_be_projected_as_completed_throughput():
    failed={'completion_status':'ERROR','indicators_evaluated':0,
            'inference_seconds':600,'inference_seconds_status':'MEASURED'}
    assert all(p['estimated_serial_seconds'] is None for p in projections_from_completed([failed]))
    valid={**failed,'completion_status':'VALID','indicators_evaluated':2,'inference_seconds':10}
    assert projections_from_completed([failed,valid])[0]['estimated_serial_seconds']==500


def test_existing_adapter_handles_v2_and_pins_usage(case,tmp_path):
    fields,p,a=case
    schema=tmp_path/'schema.json';schema.write_text(json.dumps(v2.schemas()['assessment_batch']))
    def runner(args,**kwargs):
        Path(args[args.index('--output-last-message')+1]).write_text(json.dumps({
            'project_id':'SYNTH_P','assessments':[{'indicator_id':p['indicator_id'],**a}]}),encoding='utf-8')
        return SimpleNamespace(returncode=0,stdout='{"type":"turn.completed","usage":{"input_tokens":2,"output_tokens":3}}',stderr='')
    provider=CodexCliAssessmentProvider(tmp_path/'run',schema,lambda project,indicators:v2.make_input(project,indicators,[]),
        command=['SYNTHETIC_NEVER_EXECUTE'],runner=runner,wrapper_validator=v2.validate_wrapper,max_indicators=5,
        execution_id='SYNTH_EXEC')
    results=provider.evaluate({'project_id':'SYNTH_P','fields':fields},[p])
    assert results[0]['assessment']['assessment_version']==v2.VERSION
    assert provider.calls[0]['execution_id']=='SYNTH_EXEC'
    assert provider.calls[0]['performance']['wall_seconds']['value']>=0
    assert len(provider.calls)==1


def test_consumer_preserves_low_confidence_all_states(case):
    fields,p,a=case
    projects=[];records={}
    for i,(decision,strength) in enumerate((('SUPPORTED',4),('INSUFFICIENT_EVIDENCE',1),('NOT_SUPPORTED',0))):
        aa=deepcopy(a);aa.update(decision=decision,support_strength=strength)
        if decision!='SUPPORTED':
            for c in aa['criterion_assessments']:c.update(support='NOT_DEMONSTRATED',evidence_indices=[])
        project={'project_id':f'SYNTH_{i}','siap_id':f'00{i}','fields':fields,
            'field_provenance':{f:{'section_id':'SYNTH_SEC_'+f} for f in fields}}
        row=v2.indicator_row(project,p,aa)
        projects.append(project);records[project['project_id']]={'rows':[row],
            'wrapper':{'assessments':[{'indicator_id':p['indicator_id'],**aa}]}}
    rows=consumer_rows(projects,records)
    assert [r['confianza'] for r in rows]==[100,13.75,0]
    assert len(rows)==3 and rows[-1]['siap_id']=='002'


def test_final_gate_rejects_incomplete_and_fake_acceptance(case):
    fields,p,a=case
    projects=[{'project_id':f'SYNTH_{i}','siap_id':f'{i:03d}',
               'candidates':[{'indicator_id':p['indicator_id']}]} for i in range(20)]
    with pytest.raises(ValueError,match='incomplete'):
        acceptance_gate({},projects,{}, {},{},'')
    records={project['project_id']:{'rows':[{'project_id':project['project_id'],'indicator_id':p['indicator_id'],
        'decision':'SUPPORTED','assessment_validation_status':'VALID'}]} for project in projects}
    manifest={'selection_sha256':'SEL','config':{'candidate_limit_per_project':2}}
    review={'selection_sha256':'SEL','technical_results_sha256':'TECH','labels':[]}
    with pytest.raises(ValueError,match='human review'):
        acceptance_gate(manifest,projects,records,review,{},'TECH')
