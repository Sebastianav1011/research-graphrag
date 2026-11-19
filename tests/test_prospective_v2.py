"""Offline methodological regression tests. No Ollama, API or retrieval calls."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import csv
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from layer4_evaluation.indicators import assessment_v3 as v3, prospective_v2 as p2
from layer4_evaluation.indicators import context_budget as cb, evidence_references as refs, ollama_provider as transport
from layer4_evaluation import live_execution as live, thesis_output as output
from layer4_evaluation.indicator_csv import write_results
from tests.layer5_experiment.test_assessment_v3 import case
from tests.test_ollama_provider import provider_case, sample, runtime, response

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT/'outputs/runs/local/run_20261115_063255_909981'


@pytest.fixture
def prospective(case):
    x=deepcopy(case)
    x['rubric']=p2.derive(x['rubric'])
    x['fields']['methodology']='El proyecto implementara una plataforma web para que los vecinos reporten riesgos y decidan acciones preventivas.'
    a=x['assessment'];a['assessment_version']=p2.VERSION
    a['coverage_policy']=v3.PARTIAL_COVERAGE
    a['evidence'][0].update(text=x['fields']['methodology'],stage='ACTIVITY_PROPOSED')
    for c in a['criterion_assessments']:
        c.update(coverage=4 if c['support']=='CLEAR' else 0,
            evidence_relation='PROJECT_CONTRIBUTION' if c['support']=='CLEAR' else 'NO_SUPPORT')
    a['strength_rubric']=dict(directness=4,specificity=3,clarity=4,temporal_alignment=4,
        evidence_indices=[0],explanation='Plataforma, destinatarios, accion y mecanismo preventivo previstos con una laguna especifica.')
    a['applicability']=dict(status='APPLICABLE',basis='RELEVANT_SCOPE',evidence_indices=[0],explanation='El alcance incluye una plataforma instrumental y destinatarios.')
    return x


def errors(x):return v3.validate(x['fields'],x['profile'],x['assessment'],x['rubric'])
def confidence(x):return v3.confidence(x['fields'],x['profile'],x['assessment'],x['rubric'])


def test_specific_future_design_is_supported_without_execution(prospective):
    x=prospective
    assert not errors(x)
    assert confidence(x)['confidence_status']=='COMPUTED'
    assert confidence(x)['confidence_raw_score']==96.56
    assert all(e['stage']=='ACTIVITY_PROPOSED' for e in x['assessment']['evidence'])


def test_vague_intention_is_partial_and_keeps_its_score(prospective):
    x=prospective;a=x['assessment']
    x['fields']['methodology']='Se espera contribuir al bienestar de la comunidad.'
    a['evidence'][0]['text']=x['fields']['methodology']
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=1)
    for c in a['criterion_assessments']:
        if c['support']=='CLEAR':c.update(support='PARTIAL',coverage=1)
    a['strength_rubric'].update(directness=1,specificity=1,clarity=2,temporal_alignment=1)
    assert not errors(x)
    assert 0<confidence(x)['confidence_raw_score']<100


def make_na(x):
    a=x['assessment'];text='El proyecto se limita al analisis teorico de archivos y excluye el desarrollo o uso instrumental de plataformas tecnologicas.'
    x['fields']['methodology']=text;a['evidence'][0].update(text=text,stage='CONTEXT')
    a.update(decision='NOT_APPLICABLE',support_strength=0)
    a['applicability'].update(status='NOT_APPLICABLE',basis='EXPLICIT_EXCLUSION',explanation='El alcance excluye explicitamente la intervencion tecnologica que exige el indicador.')
    for c in a['criterion_assessments']:c.update(support='NOT_DEMONSTRATED',coverage=0,evidence_indices=[],evidence_relation='NO_SUPPORT')
    a['strength_rubric'].update(**dict.fromkeys(v3.STRENGTH_DIMENSIONS,0),evidence_indices=[])
    return x


def test_documented_non_applicability_has_no_compliance_confidence(prospective):
    x=make_na(prospective)
    assert not errors(x)
    result=confidence(x)
    assert result['confidence_status']=='NOT_APPLICABLE'
    assert result['confidence_raw_score'] is None and result['conceptual_coverage'] is None
    Draft202012Validator(v3.schemas(x['fields'],p2.VERSION)['confidence_result']).validate(result)


@pytest.mark.parametrize('mutation',[
    lambda a:a['applicability'].update(evidence_indices=[]),
    lambda a:a['applicability'].update(evidence_indices=[999]),
    lambda a:a['applicability'].update(basis='UNKNOWN'),
    lambda a:a['applicability'].update(status='UNDETERMINED'),
    lambda a:a['evidence'][0].update(text='Una exclusion inventada que no existe en el proyecto.'),
    lambda a:a['strength_rubric'].update(directness=1),
])
def test_na_is_not_an_escape_for_silence_or_invalid_evidence(prospective,mutation):
    x=make_na(prospective);mutation(x['assessment'])
    assert errors(x)
    assert confidence(x)['confidence_status']=='INVALID_ASSESSMENT'
    assert confidence(x)['confidence_raw_score'] is None


@pytest.mark.parametrize('support,grade',[('CLEAR',4),('PARTIAL',2)])
@pytest.mark.parametrize('relation',['CONTEXT_IDENTIFICATION','UNRELATED','NO_SUPPORT'])
def test_context_or_other_domain_cannot_support_a_substantive_criterion(prospective,support,grade,relation):
    x=prospective;x['assessment']['criterion_assessments'][0].update(support=support,coverage=grade,evidence_relation=relation)
    assert 'P2_CRITERION:CONTEXT_OR_UNRELATED_IS_NOT_SUBSTANTIVE_SUPPORT' in errors(x)


def test_context_stage_cannot_be_relabelled_as_substantive_support(prospective):
    prospective['assessment']['evidence'][0]['stage']='CONTEXT'
    assert 'P2_CRITERION:CONTEXT_ONLY_REFERENCES' in errors(prospective)


@pytest.mark.parametrize('dims,coverage',[( (3,2,4,3),2),((1,1,2,1),1),((4,4,4,4),3)])
def test_exact_existing_s_k_and_decimal_formula(prospective,dims,coverage):
    x=prospective;a=x['assessment'];a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=2)
    for c in a['criterion_assessments']:
        if c['support']=='CLEAR':c.update(support='PARTIAL',coverage=coverage)
    a['strength_rubric'].update(dict(zip(v3.STRENGTH_DIMENSIONS,dims)))
    new=confidence(x)
    legacy=v3.confidence(x['fields'],x['profile'],p2.common_assessment(a),x['rubric'])
    assert new==legacy
    expected=100*(Decimal('.55')*Decimal(sum(dims))/16+Decimal('.45')*Decimal(coverage)/4)
    assert new['confidence_raw_score']==float(expected.quantize(Decimal('.01'),rounding=ROUND_HALF_UP))


def test_supported_required_and_reverse_decision_gates(prospective):
    x=prospective;a=x['assessment'];a['criterion_assessments'][0].update(support='PARTIAL',coverage=3)
    assert 'V3_SUPPORTED:REQUIRED_CRITERION_NOT_CLEAR' in errors(x)
    a['criterion_assessments'][0].update(support='CLEAR',coverage=4)
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=2)
    assert 'P2_DECISION:ESSENTIAL_CRITERIA_CLEAR_BUT_INSUFFICIENT' in errors(x)


def test_materialized_refs_keep_applicability_and_original_citations(prospective):
    x=prospective;project=dict(project_id='P',fields=x['fields'])
    request=cb.make_request(project,x['profile'],x['rubric'],x['fields'],evidence_references=True,
        assessment_version=p2.VERSION,evaluation_mode=p2.MODE,prompt_version=p2.PROMPT_CONCISE_V4,context_mode=v3.RETRIEVED_CONTEXT)
    a=deepcopy(x['assessment']);a.pop('coverage_policy');a.pop('evidence')
    for c in [*a['criterion_assessments'],a['strength_rubric'],a['applicability']]:
        c['evidence_refs']=[dict(fragment_id='F000',stage='ACTIVITY_PROPOSED') for i in c.pop('evidence_indices')]
    wrapper=dict(project_id='P',assessments=[dict(indicator_id=x['profile']['indicator_id'],**a)])
    schema=refs.response_schema(request,x['fields']);Draft202012Validator(schema).validate(wrapper)
    restored=refs.materialize(request,wrapper)['assessments'][0];restored.pop('indicator_id')
    assert not v3.validate(x['fields'],x['profile'],restored,x['rubric'])
    assert restored['applicability']['evidence_indices']==[0]
    row=v3.indicator_row(project,x['profile'],restored,x['rubric'])
    assert live.assessment_from_row(row)==restored


def test_na_json_csv_excel_and_legacy_contract_compatibility(prospective,tmp_path):
    import openpyxl
    x=make_na(prospective);project=dict(project_id='P',siap_id='123',fields=x['fields'],field_provenance={
        'methodology':dict(raw_sources=[dict(record_source='original.csv',source_row=2,field_mapping={'methodology':'metodologia'})])})
    row=v3.indicator_row(project,x['profile'],x['assessment'],x['rubric'])
    location=dict(field='methodology',text=x['fields']['methodology'],match_valid=True,section_id='SEC',start=0,
        end=len(x['fields']['methodology']),coordinate_system='original_unicode_codepoints_0_based_half_open')
    record=output.indicator_record(project,row['indicator_id'],row=row,locations=[location])
    assert record['confianza'] is None and record['estado_cumplimiento']=='NOT_APPLICABLE'
    schema=json.loads((ROOT/'schemas/thesis_prospective_assessments.v3.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator(schema).validate({'Proyectos':[{k:record[k] for k in output.GENERAL_COLUMNS}],output.SHEETS[1]:[]})
    assert row['applicability']['explanation'] in record['parrafo_evidencia']
    with pytest.raises(ValueError,match='contrato prospectivo'):output.verify_records([record])
    output.verify_records([record],output.PROSPECTIVE_CONTRACT)
    target=tmp_path/'na.xlsx';output.render(ROOT,target,[record],contract=output.PROSPECTIVE_CONTRACT)
    book=openpyxl.load_workbook(target,read_only=True,data_only=True)
    try:assert book['Proyectos']['G2'].value=='N/A'
    finally:book.close()
    write_results(tmp_path,output.GENERAL_COLUMNS,[record],{})
    with (tmp_path/'resultados/indicadores.csv').open(encoding='utf-8-sig') as f:
        value=next(csv.DictReader(f,delimiter=';'));assert value['confianza']==''
    assert json.loads(json.dumps(row))['confidence_raw_score'] is None


def test_invalid_assessment_never_becomes_semantic_rejection(prospective):
    x=prospective;x['assessment']['criterion_assessments'][0]['evidence_indices']=[999]
    row=v3.indicator_row(dict(project_id='P',fields=x['fields']),x['profile'],x['assessment'],x['rubric'])
    assert row['assessment_validation_status']=='INVALID_ASSESSMENT' and row['confidence_raw_score'] is None
    with pytest.raises(ValueError,match='incompatible'):
        output.indicator_record(dict(siap_id='1'),row['indicator_id'],row=row)


def test_compact_retries_do_not_accumulate_context_or_freeze_invalid_scores(prospective):
    x=prospective;request=cb.make_request(dict(project_id='P',fields=x['fields']),x['profile'],x['rubric'],x['fields'],
        evidence_references=True,assessment_version=p2.VERSION,evaluation_mode=p2.MODE,prompt_version=p2.PROMPT_CONCISE_V4)
    schema=refs.response_schema(request,x['fields']);settings=transport.configuration({'num_ctx':16384,'context_margin_tokens':1024})
    request['context_budget']=cb.estimate(request['prompt'],schema,settings)
    issues=[dict(rule='SK_ZERO_SUPPORT:CANNOT_CLAIM_POSITIVE_CONCEPTUAL_SUPPORT',path='$.decision')]
    revised=transport.corrective_request(request,schema,settings,issues,{'ignored':'previous response'*5000},p2.CORRECTION)
    twice=transport.corrective_request(request,schema,settings,issues,None,p2.CORRECTION)
    assert revised==twice and revised['context_budget']['fits']
    assert revised['payload']==request['payload'] and revised['prompt'].split('INPUT_JSON:\n')[1]==request['prompt'].split('INPUT_JSON:\n')[1]
    assert 'RESPUESTA_ANTERIOR' not in revised['prompt']
    assert len(revised['prompt'])<len(request['prompt'])+1000
    assert p2.CORRECTION not in transport.TARGETED_VERSIONS


def test_new_default_and_saved_v1_are_separate():
    assert v3.evaluation_policy(base=True)['evaluation_mode']==p2.MODE
    old=v3.evaluation_policy('prospective-v1',base=True)
    assert old['evaluation_mode']==v3.PROSPECTIVE
    assert v3.evaluation_policy(saved=old,base=True)==old
    with pytest.raises(ValueError,match='checkpoint'):v3.evaluation_policy('prospective-v2',saved=old)


def test_reference_48_catalog_is_derived_without_mutation():
    path=REFERENCE/'evaluation/batch_162fbf47e55a989c/plan.json'
    if not path.exists():pytest.skip('Historical local run unavailable')
    before=hashlib.sha256(path.read_bytes()).hexdigest();plan=json.loads(path.read_text(encoding='utf-8'))
    original=deepcopy(plan['rubrics']);profiles=deepcopy(plan['profiles'])
    assert v3.evaluation_policy('prospective-v1','retrieved-graph',base=True)==plan['evaluation_policy']
    derived,receipt=v3.catalog_for_mode(profiles,original,p2.MODE)
    assert set(derived)==set(p2.INTERPRETATIONS) and len(derived)==48
    for iid,r in derived.items():
        v3.check_rubric(profiles[iid],r)
        assert [(c['criterion'],c['role'],c['alternative_group']) for c in r['criteria']]==[(c['criterion'],c['role'],c['alternative_group']) for c in original[iid]['criteria']]
        assert all('Interpretacion operativa PROSPECTIVE_V2' in c['rationale'] for c in r['criteria'])
        project=dict(project_id='P',fields=dict.fromkeys(v3.FIELDS,''))
        request=cb.make_request(project,profiles[iid],r,project['fields'],evidence_references=True,
            assessment_version=p2.VERSION,evaluation_mode=p2.MODE,prompt_version=p2.PROMPT_CONCISE_V4)
        assert 'una prevision de uso no satisface' not in request['prompt'].lower()
        assert 'favorable_evidence' not in request['payload']['indicators'][0]
    assert receipt['interpretations']['POL-02']['limitation'] and receipt['interpretations']['DIV-03']['limitation']
    assert plan['rubrics']==original and plan['profiles']==profiles
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before


def reference_answer(x):
    a=deepcopy(x['assessment']);a.pop('coverage_policy');a.pop('evidence')
    for c in [*a['criterion_assessments'],a['strength_rubric'],a['applicability']]:
        c['evidence_refs']=[dict(fragment_id='F000',stage='ACTIVITY_PROPOSED') for i in c.pop('evidence_indices')]
    return dict(project_id='P',assessments=[dict(indicator_id=x['profile']['indicator_id'],**a)])


@pytest.mark.parametrize('correction_fits',[True,False])
def test_invalid_model_response_is_retried_with_full_validation_or_stays_technical(provider_case,prospective,monkeypatch,correction_fits):
    from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError, semantic_issues
    provider,client,_,_,_,_=provider_case;x=prospective
    project=dict(project_id='P',fields=x['fields'])
    request=cb.make_request(project,x['profile'],x['rubric'],x['fields'],evidence_references=True,
        assessment_version=p2.VERSION,evaluation_mode=p2.MODE,prompt_version=p2.PROMPT_V3)
    settings=transport.configuration(provider.settings|dict(num_ctx=16384,context_margin_tokens=1024))
    schema=refs.response_schema(request,x['fields']);provider.schema.write_text(json.dumps(schema),encoding='utf-8')
    request['context_budget']=cb.estimate(request['prompt'],schema,settings)
    provider.settings=settings;provider.runtime=None;provider.corrective_retries=2;provider.correction_version=p2.CORRECTION
    provider.input_factory=lambda p,i:deepcopy(request)
    client.inspect.return_value=runtime(settings)
    valid=reference_answer(x);invalid=deepcopy(valid)
    invalid['assessments'][0].update(support_strength=0,decision='INSUFFICIENT_EVIDENCE')
    client.request.side_effect=[response(invalid),response(valid)]
    def gate(value,pid,ids):
        v3.validate_wrapper(value,pid,ids,x['fields'],p2.VERSION)
        a={k:v for k,v in value['assessments'][0].items() if k!='indicator_id'}
        problems=v3.validate(x['fields'],x['profile'],a,x['rubric'])
        if problems:raise AssessmentValidationError(semantic_issues(problems,a,x['profile']['indicator_id'],x['rubric'],x['fields']))
    provider.wrapper_validator=gate
    if not correction_fits:
        original=transport.corrective_request
        def blocked(*args,**kwargs):
            revised=original(*args,**kwargs);revised['context_budget']['fits']=False;return revised
        monkeypatch.setattr(transport,'corrective_request',blocked)
        with pytest.raises(transport.OllamaError,match='INVALID_ASSESSMENT'):
            provider.evaluate(project,[x['profile']])
        assert client.request.call_count==1 and provider.last_output is None
    else:
        answer=provider.evaluate(project,[x['profile']])[0]['assessment']
        assert not v3.validate(x['fields'],x['profile'],answer,x['rubric'])
        assert answer['decision']=='SUPPORTED' and client.request.call_count==2
    assert provider.calls[0]['exit_status']=='INVALID_ASSESSMENT'


def test_summary_excludes_na_unknown_and_errors_from_applicable_denominator():
    rows=[dict(decision='SUPPORTED',applicability={'status':'APPLICABLE'}),
        dict(decision='INSUFFICIENT_EVIDENCE',applicability={'status':'APPLICABLE'}),
        dict(decision='INSUFFICIENT_EVIDENCE',applicability={'status':'UNDETERMINED'}),
        dict(decision='NOT_APPLICABLE',applicability={'status':'NOT_APPLICABLE'})]
    project=dict(rows=rows,processed=True,complete=False,selected=['a','b','c','d','e'],
        blocked_indicators={'e':'BLOCKED_ERROR'},pending_indicators=[])
    summary=live.summary(dict(projects=[project],evaluation_policy={'evaluation_mode':p2.MODE}))
    assert summary['not_applicable']==1 and summary['support_denominator']==2
    assert summary['applicability_undetermined']==1 and summary['blocked_assessments']==1


@pytest.mark.parametrize('iid',['DIV-03','POL-02'])
def test_external_records_cannot_be_claimed_from_a_plan(prospective,iid):
    x=prospective;x['profile']['indicator_id']=iid
    # Rebind only the synthetic catalog ID, retaining its exact frozen criterion roles.
    r=x['rubric'];r['indicator_id']=iid;r['profile_sha256']=v3.canonical_hash(x['profile'])
    r.pop('rubric_sha256');r['rubric_sha256']=v3.canonical_hash(r)
    assert 'P2_SUPPORTED:EXTERNAL_RECORD_NOT_PROSPECTIVELY_ESTABLISHED' in errors(x)


@pytest.mark.parametrize('rel',[
    'batch_3a13cbb2d0f30a20/calls/PROJ_21869/assessment_45',
    'batch_b23ebabb093e0320/calls/PROJ_21736/assessment_6',
    'batch_162fbf47e55a989c/calls/PROJ_21844/assessment_45'])
def test_reference_evidence_and_correction_fit_without_new_retrieval(rel):
    path=REFERENCE/'evaluation'/rel
    if not path.exists():pytest.skip('Historical local run unavailable')
    load=lambda p:json.loads(p.read_text(encoding='utf-8'))
    plan=load(path.parents[2]/'plan.json');pid=path.parent.name;iid=load(path/'plan.json')['indicator_ids'][0]
    saved=plan['context_requests'][pid][iid];project=next(p for p in plan['projects'] if p['project_id']==pid)
    tokenizer=saved['context_budget'].get('tokenizer')
    if not tokenizer or not Path(tokenizer['path']).exists():pytest.skip('Pinned local tokenizer unavailable')
    rubric=p2.derive(plan['rubrics'][iid])
    units=[dict(field=f['field'],text=f['text']) for f in saved['payload']['project']['fragments']]
    request=cb.make_request(project,plan['profiles'][iid],rubric,project['fields'],evidence_references=True,
        evidence_units=units,assessment_version=p2.VERSION,evaluation_mode=p2.MODE,prompt_version=p2.PROMPT_CONCISE_V4,context_mode=v3.RETRIEVED_CONTEXT)
    schema=refs.response_schema(request,project['fields']);settings=plan['runtime']['configuration']
    request['context_budget']=cb.estimate(request['prompt'],schema,settings,tokenizer=tokenizer,cap=8000)
    assert request['context_budget']['fits'],request['context_budget']['estimated_input_tokens']
    revised=transport.corrective_request(request,schema,settings,
        [dict(rule='SK_ZERO_SUPPORT:CANNOT_CLAIM_POSITIVE_CONCEPTUAL_SUPPORT',path='$.decision')],None,p2.CORRECTION)
    assert revised['context_budget']['fits'],revised['context_budget']['estimated_input_tokens']


def test_observed_external_record_is_not_rejected_as_if_it_were_only_planned():
    path=REFERENCE/'evaluation/batch_162fbf47e55a989c/plan.json'
    if not path.exists():pytest.skip('Historical local run unavailable')
    plan=json.loads(path.read_text(encoding='utf-8'));profile=plan['profiles']['POL-02'];rubric=p2.derive(plan['rubrics']['POL-02'])
    text='El documento oficial Decreto 12 cita expresamente los resultados de este proyecto en su pagina 3; se registra un documento oficial distinto.'
    fields=dict.fromkeys(v3.FIELDS,'');fields['expected_results']=text
    assessment=dict(assessment_version=p2.VERSION,coverage_policy=v3.PARTIAL_COVERAGE,decision='SUPPORTED',support_strength=4,
        applicability=dict(status='APPLICABLE',basis='RELEVANT_SCOPE',explanation='El texto identifica el documento oficial que cita el proyecto.',evidence_indices=[0]),
        criterion_assessments=[dict(criterion_id=c['criterion_id'],support='CLEAR',coverage=4,evidence_indices=[0],
            explanation='La evidencia simulada identifica el registro externo y su relacion con el proyecto.',
            evidence_relation='PROJECT_CONTRIBUTION') for c in rubric['criteria']],
        evidence=[dict(field='expected_results',text=text,stage='RESULT_DEMONSTRATED')],
        strength_rubric=dict(**dict.fromkeys(v3.STRENGTH_DIMENSIONS,4),evidence_indices=[0],explanation='Registro observado documentado; no se deduce desde una expectativa.'),
        explanation='La condicion externa observada no se confunde con una propuesta de incidencia.')
    assert not v3.validate(fields,profile,assessment,rubric)
    assessment['evidence'][0]['stage']='RESULT_EXPECTED'
    assert 'P2_SUPPORTED:EXTERNAL_RECORD_NOT_PROSPECTIVELY_ESTABLISHED' in v3.validate(fields,profile,assessment,rubric)


@pytest.mark.parametrize('rel',[
    'batch_3a13cbb2d0f30a20/calls/PROJ_21869/assessment_45',
    'batch_b23ebabb093e0320/calls/PROJ_21736/assessment_6',
    'batch_162fbf47e55a989c/calls/PROJ_21844/assessment_45'])
def test_reference_v1_criteria_and_confidence_reproduce_without_migration(rel):
    path=REFERENCE/'evaluation'/rel
    if not path.exists():pytest.skip('Historical local run unavailable')
    load=lambda p:json.loads(p.read_text(encoding='utf-8'))
    plan=load(path.parents[2]/'plan.json');row=load(path/'assessment.rows.json')['rows'][0]
    project=next(p for p in plan['projects'] if p['project_id']==row['project_id']);iid=row['indicator_id']
    result=v3.confidence(project['fields'],plan['profiles'][iid],live.assessment_from_row(row),plan['rubrics'][iid])
    assert not result['validation_errors']
    assert result['confidence_raw_score']==row['confidence_raw_score']
    assert result['conceptual_coverage']==row['conceptual_coverage']


def test_published_contracts_match_runtime_schemas():
    for name in ('assessment','assessment_batch','confidence_result'):
        schema=json.loads((ROOT/f'schemas/layer4_prospective_v2/{name}.schema.json').read_text(encoding='utf-8'))
        assert schema==v3.schemas(version=p2.VERSION)[name]
        Draft202012Validator.check_schema(schema)


def test_main_export_keeps_na_and_technical_block_separate(prospective,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from scripts import pipeline_coordinator as runner
    from layer4_evaluation import indicator_csv
    from layer4_evaluation.indicators.review import evidence_locations
    x=make_na(prospective);iid=x['profile']['indicator_id'];run=tmp_path/'run'
    project=dict(project_id='P',siap_id='1',fields=x['fields'],field_provenance={'methodology':dict(
        section_id='SEC',raw_sources=[dict(record_source='original.csv',source_row=2,field_mapping={'methodology':'metodologia'})])})
    row=v3.indicator_row(project,x['profile'],x['assessment'],x['rubric']);policy=v3.evaluation_policy('prospective-v2')
    plan=dict(projects=[project],profiles={iid:x['profile'],'BLOCKED':x['profile']},rubrics={iid:x['rubric']},
        assessment_version=p2.VERSION,evaluation_policy=policy)
    state=dict(errors=['P: BLOCKED_ERROR; INVALID_ASSESSMENT'],usage=[
        dict(project_id='P',indicator_ids=[iid],calls=1,error=None),
        dict(project_id='P',indicator_ids=['BLOCKED'],calls=2,error='INVALID_ASSESSMENT')],
        projects=[dict(project_id='P',rows=[row],complete=False,selected=[iid,'BLOCKED'],
            discovery_complete=True,blocked_indicators={'BLOCKED':'BLOCKED_ERROR'})])
    base=run/'evaluation';(base/'batch_one').mkdir(parents=True)
    module=SimpleNamespace(BASE=base,v3=v3,check=lambda d:plan,verify_run=lambda d:state,
        assessment_from_row=live.assessment_from_row,evidence_locations=evidence_locations)
    monkeypatch.setattr(runner,'engine',lambda *args:module)
    monkeypatch.setattr(runner,'check',lambda *args:None)
    monkeypatch.setattr(runner,'validated_graph',lambda *args:None)
    monkeypatch.setattr(runner,'knowledge_workspace',lambda *args:tmp_path)
    monkeypatch.setattr(runner.pq,'read_table',lambda *args:SimpleNamespace(to_pylist=lambda:[dict(source_project_id='1')]))
    monkeypatch.setattr(indicator_csv,'TerritoryCodes',lambda *args:lambda *a:[])
    request=runner.run_file(run,'execution.json');request.parent.mkdir(parents=True,exist_ok=True)
    request.write_text(json.dumps(dict(project_ids=['1'],selection={'mode':'projects'},evaluation_policy=policy)),encoding='utf-8')
    result=runner.export(ROOT,run)
    assert result['output_contract']==output.PROSPECTIVE_CONTRACT
    assert result['status']=='PARTIAL' and result['exported_rows']==1
    assert result['not_applicable']==1 and result['support_denominator']==0 and result['blocked_assessments']==1
    assert result['processing_complete'] and result['pending_assessments']==0
    states=json.loads((run/'resultados/estado_indicadores.json').read_text(encoding='utf-8'))['indicators']
    blocked=next(r for r in states if r['indicator_id']=='BLOCKED')
    assert blocked['decision'] is None and blocked['processing_status']=='TECHNICALLY_BLOCKED'
    assert blocked['technical_error']=='INVALID_ASSESSMENT' and blocked['llm_calls']==2
    with (run/'resultados/indicadores.csv').open(encoding='utf-8-sig') as stream:
        exported=list(csv.DictReader(stream,delimiter=';'))
    assert len(exported)==1 and exported[0]['estado_cumplimiento']=='NOT_APPLICABLE' and exported[0]['confianza']==''
    with (run/'resultados/indicadores_territorios.csv').open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream,delimiter=';'); territories=list(reader)
    assert reader.fieldnames==indicator_csv.TERRITORIAL_COLUMNS
    assert len(territories)==1 and territories[0]['codigo_dane']==territories[0]['codigo_municipio_dane']==''
