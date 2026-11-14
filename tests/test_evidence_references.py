"""Offline reference transport, strict academic gates and checkpoint continuity."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, ValidationError

from tests.test_ollama_provider import sample, live_run, runtime, response, provider_case
from tests.test_context_budget import corpus, install_plan, planner
from tests.layer5_experiment.test_assessment_v3 import case, sk_case
from layer4_evaluation import live_execution as live
from layer4_evaluation.indicators import context_budget as cb, evidence_references as refs
from layer4_evaluation.indicators import assessment_v3 as v3, ollama_provider as transport
from layer4_evaluation.indicators.selection import canonical_hash
from layer2_processing.preprocessing.adapters import read, write, sha
from scripts import pipeline_coordinator as coordinator


def pack(corpus):
    return cb.prepare_contexts([corpus.project], corpus.profiles, corpus.rubrics, corpus.settings,
        corpus.hits, corpus.chunks, corpus.sections, evidence_references=True)[0]


def selection(sample, pid='TEST_PROJECT', iid='I00'):
    item = deepcopy(sample['assessment'])
    item.pop('evidence')
    judgments = item['criterion_assessments'] + ([item['strength_rubric']] if 'strength_rubric' in item else [])
    for criterion in judgments:
        indices = criterion.pop('evidence_indices')
        criterion['evidence_refs'] = [dict(fragment_id='F000', stage='DESIGN_DOCUMENTED') for _ in indices]
    return dict(project_id=pid, assessments=[dict(indicator_id=iid, **item)])


def test_partial_coverage_policy_is_python_owned_and_survives_saved_row(sk_case):
    p,r,f,a=[sk_case[k] for k in ('profile','rubric','fields','assessment')]
    project=dict(project_id='TEST_PROJECT',fields=f)
    request=cb.make_request(project,p,r,f,evidence_references=True,assessment_version=v3.SK_VERSION)
    answer=selection(sk_case,iid=p['indicator_id'])
    fid=next(item['fragment_id'] for item in request['payload']['project']['fragments'] if item['field']=='methodology')
    for item in answer['assessments'][0]['criterion_assessments']+[answer['assessments'][0]['strength_rubric']]:
        for ref in item['evidence_refs']:ref['fragment_id']=fid
    schema=refs.response_schema(request,f)
    assert 'coverage_policy' not in schema['properties']['assessments']['items']['properties']
    Draft202012Validator(schema).validate(answer)
    assessment=refs.materialize(request,answer)['assessments'][0]
    assessment.pop('indicator_id')
    row=v3.indicator_row(project,p,assessment,r)
    assert row['conceptual_coverage_version']==v3.PARTIAL_COVERAGE
    restored=live.assessment_from_row(row)
    assert restored['coverage_policy']==v3.PARTIAL_COVERAGE
    assert v3.confidence(f,p,restored,r)['confidence_raw_score']==row['confidence_raw_score']


def test_full_descriptor_prospective_uses_same_literal_and_sk_validators(corpus,sample):
    from tests.test_context_budget import descriptor_fixture
    descriptor_fixture(corpus)
    corpus.rubrics,_=v3.catalog_for_mode(corpus.profiles,corpus.rubrics,v3.PROSPECTIVE)
    requests,_=cb.prepare_contexts([corpus.project],corpus.profiles,corpus.rubrics,corpus.settings,[],[],corpus.sections,
        evidence_references=True,assessment_version=v3.SK_VERSION,evaluation_mode=v3.PROSPECTIVE,context_mode=v3.FULL_CONTEXT)
    request=requests['TEST_PROJECT']['I00']
    mock=deepcopy(sample)
    a=mock['assessment'];a['assessment_version']=v3.SK_VERSION
    a['strength_rubric']=dict(directness=3,specificity=2,clarity=4,temporal_alignment=3,
        evidence_indices=[0],explanation='Contribucion futura concreta, con alguna salvedad.')
    for c in a['criterion_assessments']:c['coverage']=4 if c['support']=='CLEAR' else 0
    answer=selection(mock)
    fid=next(f['fragment_id'] for f in request['payload']['project']['fragments'] if f['field']=='methodology')
    for item in answer['assessments'][0]['criterion_assessments']+[answer['assessments'][0]['strength_rubric']]:
        for ref in item['evidence_refs']:ref.update(fragment_id=fid,stage='ACTIVITY_PROPOSED')
    Draft202012Validator(refs.response_schema(request,corpus.project['fields'])).validate(answer)
    canonical=refs.materialize(request,answer)
    live.validate_context_evidence(request,canonical)
    assessment={k:v for k,v in canonical['assessments'][0].items() if k!='indicator_id'}
    result=v3.confidence(corpus.project['fields'],corpus.profiles['I00'],assessment,corpus.rubrics['I00'])
    assert result['confidence_raw_score']==86.25
    quote=assessment['evidence'][0]
    assert quote['text'] in corpus.project['fields'][quote['field']]
    broken=deepcopy(answer);broken['assessments'][0]['criterion_assessments'][0]['evidence_refs'][0]['fragment_id']='INVENTED'
    with pytest.raises(ValueError,match='FRAGMENT_ID_NOT_FOUND'):refs.materialize(request,broken)
    broken=deepcopy(canonical);broken['assessments'][0]['evidence'][0]['text']='Invented literal'
    with pytest.raises(ValueError):live.validate_context_evidence(request,broken)


def test_references_extract_only_original_literals_and_keep_confidence(corpus, sample):
    request = pack(corpus)['TEST_PROJECT']['I00']
    wrapper = selection(sample)
    Draft202012Validator(refs.response_schema(request, corpus.project['fields'])).validate(wrapper)
    canonical = refs.materialize(request, wrapper)
    assessment = canonical['assessments'][0]
    assert assessment['evidence'] == sample['assessment']['evidence']
    assert assessment['criterion_assessments'] == sample['assessment']['criterion_assessments']
    assert 'evidence_refs' in wrapper['assessments'][0]['criterion_assessments'][0]
    assert not v3.validate(corpus.project['fields'], corpus.profiles['I00'],
        {k:v for k,v in assessment.items() if k!='indicator_id'}, corpus.rubrics['I00'])
    row = live.indicator_row(dict(profiles=corpus.profiles, rubrics=corpus.rubrics), corpus.project, assessment)
    assert row['confidence_raw_score'] == v3.confidence(sample['fields'], sample['profile'],
        sample['assessment'], sample['rubric'])['confidence_raw_score']
    assert request['prompt'].count(corpus.chunks[0]['text']) == 1
    assert request['context_budget']['fits']


@pytest.mark.parametrize('mutation', ['unknown','quote','index','criterion','project'])
def test_schema_rejects_unknown_references_and_invented_quote_fields(corpus, sample, mutation):
    request = pack(corpus)['TEST_PROJECT']['I00']
    value = selection(sample)
    criterion = value['assessments'][0]['criterion_assessments'][0]
    if mutation == 'unknown': criterion['evidence_refs'][0]['fragment_id'] = 'MISSING'
    if mutation == 'quote': criterion['evidence_refs'][0]['text'] = 'Invented quote'
    if mutation == 'index': criterion['evidence_indices'] = [99]
    if mutation == 'criterion': criterion['criterion_id'] = 'MISSING'
    if mutation == 'project': value['project_id'] = 'OTHER'
    with pytest.raises(ValidationError):
        Draft202012Validator(refs.response_schema(request, corpus.project['fields'])).validate(value)


@pytest.mark.parametrize('mutation,code', [('missing','POSITIVE_SUPPORT_REQUIRES_QUOTE'),
    ('stage','CLEAR_REQUIRES_COMPATIBLE_SUBSTANTIVE_EVIDENCE'),
    ('negative','CANNOT_CLAIM_POSITIVE_CONCEPTUAL_SUPPORT'), ('required','REQUIRED_CRITERION_NOT_CLEAR')])
def test_canonical_semantic_validators_remain_strict(corpus, sample, mutation, code):
    request = pack(corpus)['TEST_PROJECT']['I00']
    value = selection(sample)
    item = value['assessments'][0]
    criterion = item['criterion_assessments'][0]
    if mutation == 'missing': criterion['evidence_refs'] = []
    if mutation == 'stage': criterion['evidence_refs'][0]['stage'] = 'RESULT_EXPECTED'
    if mutation == 'negative': item.update(decision='NOT_SUPPORTED', support_strength=0)
    if mutation == 'required': criterion.update(support='NOT_DEMONSTRATED', evidence_refs=[])
    canonical = refs.materialize(request, value)['assessments'][0]
    errors = v3.validate(corpus.project['fields'], corpus.profiles['I00'],
        {k:v for k,v in canonical.items() if k!='indicator_id'}, corpus.rubrics['I00'])
    assert any(code in e for e in errors)


def test_duplicate_exact_references_are_idempotent_without_semantic_changes(corpus,sample):
    request=pack(corpus)['TEST_PROJECT']['I00'];value=selection(sample)
    expected=refs.materialize(request,value)
    value['assessments'][0]['criterion_assessments'][0]['evidence_refs'] *= 2
    original=deepcopy(value)
    assert refs.materialize(request,value)==expected and value==original


def test_different_temporal_stages_are_never_deduplicated(corpus,sample):
    request=pack(corpus)['TEST_PROJECT']['I00'];value=selection(sample)
    criterion=value['assessments'][0]['criterion_assessments'][0]
    criterion['evidence_refs'].append(dict(fragment_id='F000',stage='ACTIVITY_EXECUTED'))
    item=refs.materialize(request,value)['assessments'][0]
    assert criterion['support']==item['criterion_assessments'][0]['support']
    assert item['criterion_assessments'][0]['evidence_indices']==[0,1]
    assert [e['stage'] for e in item['evidence']]==['DESIGN_DOCUMENTED','ACTIVITY_EXECUTED']


def test_ambiguous_fragment_ids_are_rejected(corpus,sample):
    request=deepcopy(pack(corpus)['TEST_PROJECT']['I00'])
    request['payload']['project']['fragments'].append(request['payload']['project']['fragments'][0] | dict(text='Otro texto.'))
    with pytest.raises(ValueError,match='DUPLICATE_FRAGMENT_ID'):
        refs.materialize(request,selection(sample))


@pytest.mark.parametrize('quote,valid', [
    ('El diseño vigente.',True),('El disen\u0303o\n vigente.',True),
    ('el diseño vigente.',False),('El diseno vigente.',False),
    ('El diseño nuevo.',False),('El diseño…',False),('',False),('  ',False)])
def test_sent_context_uses_same_conservative_quote_normalization(quote,valid):
    request=dict(input_version=live.CONTEXT_VERSION,payload=dict(project=dict(fields={'methodology':'El diseño\u00a0 vigente.'})))
    wrapper=dict(assessments=[dict(indicator_id='SYNTH',evidence=[dict(field='methodology',text=quote)])])
    original=deepcopy(wrapper)
    if valid:live.validate_context_evidence(request,wrapper)
    else:
        with pytest.raises(ValueError,match='QUOTE_NOT_IN_SENT_GRAPHRAG_CONTEXT'):
            live.validate_context_evidence(request,wrapper)
    assert wrapper==original


def test_quotes_cannot_cross_keyword_items_or_use_unsent_text():
    request=dict(input_version=live.CONTEXT_VERSION,payload=dict(project=dict(fields={'keywords':['A','B'],'methodology':'Enviado.'})))
    for field,text in [('keywords','A B'),('methodology','No enviado.')]:
        with pytest.raises(ValueError,match='QUOTE_NOT_IN_SENT_GRAPHRAG_CONTEXT'):
            live.validate_context_evidence(request,dict(assessments=[dict(evidence=[dict(field=field,text=text)])]))


@pytest.mark.parametrize('failure',['timeout','json','schema','internal','index','quote'])
def test_sk_technical_failures_never_create_a_computable_assessment(provider_case,sk_case,monkeypatch,failure):
    from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError, semantic_issues
    provider,client,project,profile,request,wrapper=provider_case
    assessment=deepcopy(sk_case['assessment'])
    wrapper['assessments']=[dict(indicator_id=profile['indicator_id'],**assessment)]
    write(provider.schema,v3.schemas(project['fields'],v3.SK_VERSION)['assessment_batch'])
    if failure=='index':wrapper['assessments'][0]['criterion_assessments'][0]['evidence_indices']=[99]
    if failure=='quote':wrapper['assessments'][0]['evidence'][0]['text']='Inventado.'
    if failure=='schema':del wrapper['assessments'][0]['strength_rubric']
    client.request.return_value=response(wrapper)
    if failure=='timeout':client.request.side_effect=transport.OllamaError('TIMEOUT','Simulado')
    if failure=='json':client.request.return_value['message']['content']='{'
    def gate(value,pid,ids):
        if failure=='internal':raise TypeError('Simulado')
        value={k:v for k,v in value['assessments'][0].items() if k!='indicator_id'}
        errors=v3.validate(project['fields'],profile,value,sk_case['rubric'])
        if errors:raise AssessmentValidationError(semantic_issues(errors,value,profile['indicator_id']))
    provider.wrapper_validator=gate
    from unittest.mock import Mock
    calculate=Mock(side_effect=AssertionError('No hay evaluacion valida'))
    monkeypatch.setattr(v3,'confidence',calculate)
    with pytest.raises(transport.OllamaError):provider.evaluate(project,[profile])
    assert provider.last_output is None and not provider.calls[0]['successful_transport']
    assert provider.calls[0]['exit_status'] and client.request.call_count==1
    calculate.assert_not_called()


def test_sk_unknown_strength_reference_reports_the_correct_path(corpus,sk_case):
    corpus.settings=transport.configuration(corpus.settings|{'num_ctx':16384})
    requests,_=cb.prepare_contexts([corpus.project],corpus.profiles,corpus.rubrics,corpus.settings,
        corpus.hits[:1],corpus.chunks,corpus.sections,evidence_references=True,assessment_version=v3.SK_VERSION)
    wrapper=selection(sk_case)
    wrapper['assessments'][0]['strength_rubric']['evidence_refs'][0]['fragment_id']='MISSING'
    with pytest.raises(ValueError) as error:refs.materialize(requests['TEST_PROJECT']['I00'],wrapper)
    assert error.value.issues[0]['path']=='$.strength_rubric.evidence_refs'


@pytest.mark.parametrize('scenario',[
    'context_only','context_with_distractor','planned_activity','executed_activity','demonstrated_result','partial',
    'absent','invalid_reference','unsupported_global','invalid_stage'])
def test_criterion_first_response_preserves_context_without_claiming_impact(provider_case,sk_case,scenario):
    from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError, semantic_issues
    provider,client,project,_,_,_=provider_case
    profile=deepcopy(sk_case['profile'])
    profile.update(key_elements=['Poblacion identificada.','Actividad realizada.',
        'Mejora fisica alcanzada.','Impacto demostrado.'],
        descripcion_ampliada='Identifica poblacion, actividad realizada, mejora fisica e impacto del proyecto.')
    candidate=deepcopy(sk_case['wrapper'])
    rubric_input=candidate['assessments'][0]['rubrics'][0]
    rubric_input.update(profile_sha256=canonical_hash(profile),
        indicator_type_basis=[dict(profile_field='descripcion_ampliada',text=profile['descripcion_ampliada'])])
    for c,stage in zip(rubric_input['criteria'],[
            'CONTEXT_ONLY','EXECUTED_ACTIVITY','DEMONSTRATED_RESULT','DEMONSTRATED_RESULT']):
        c.update(role='REQUIRED',alternative_group=None,temporal_requirement=stage,
            basis=[dict(profile_field='descripcion_ampliada',text=profile['descripcion_ampliada'])],
            rationale='Identificar poblacion es contextual; actividad, mejora e impacto requieren su propio respaldo.')
    rubric=v3.validate_rubric_wrapper(candidate,[profile])[profile['indicator_id']]
    # Faithful SAL-01 regression: a defined study population is not evidence of improved health.
    text=('Poblacion del estudio: pacientes con condiciones geneticas o sus cuidadores en Bogota. '
          'Se realizaran entrevistas para explorar sus necesidades. ')
    if scenario in ('executed_activity','demonstrated_result'):
        text+='Se realizaron diez entrevistas a esa poblacion. '
    if scenario=='demonstrated_result':
        text+='Se reporto una mejora fisica en esa poblacion atribuida a la intervencion. '
    if scenario=='absent':text='No se documenta poblacion, actividades, mejoras ni impactos del proyecto. '
    if scenario=='context_with_distractor':
        text='La genetica ha transformado la medicina moderna. '+text
    project['fields']['methodology']=text
    request=cb.make_request(project,profile,rubric,project['fields'],evidence_references=True,
        assessment_version=v3.SK_VERSION)
    fragments=request['payload']['project']['fragments']
    a=deepcopy(sk_case['assessment'])
    a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=0 if scenario=='absent' else 2)
    a.pop('evidence')
    for c in a['criterion_assessments']:
        c.pop('evidence_indices')
        c.update(support='NOT_DEMONSTRATED',coverage=0,evidence_refs=[],
            explanation='Condicion exigida sin respaldo; falta evidencia propia, no se deduce de otro criterio.')
    def support(index,fragment,stage,grade=4):
        a['criterion_assessments'][index].update(support='CLEAR' if grade==4 else 'PARTIAL',coverage=grade,
            evidence_refs=[dict(fragment_id=fragments[fragment]['fragment_id'],stage=stage)],
            explanation='Condicion: '+profile['key_elements'][index]+' Respaldo: '+fragments[fragment]['fragment_id']+
                ('; sin brecha en este criterio.' if grade==4 else '; brecha: falta acreditar el requisito completo.'))
    population_fragment=1 if scenario=='context_with_distractor' else 0
    if scenario!='absent':support(0,population_fragment,'CONTEXT',2 if scenario=='partial' else 4)
    if scenario=='planned_activity':support(1,1,'ACTIVITY_PROPOSED',1)
    if scenario in ('executed_activity','demonstrated_result'):support(1,2,'ACTIVITY_EXECUTED')
    if scenario=='demonstrated_result':support(2,3,'RESULT_DEMONSTRATED')
    a['strength_rubric'].pop('evidence_indices')
    a['strength_rubric'].update({k:0 if scenario=='absent' else 3 for k in v3.STRENGTH_DIMENSIONS},
        evidence_refs=[] if scenario=='absent' else [dict(fragment_id=fragments[population_fragment]['fragment_id'],stage='CONTEXT')],
        explanation='Respaldo de criterios individuales; no acredita el impacto obligatorio ausente.')
    if scenario=='invalid_reference':a['criterion_assessments'][0]['evidence_refs'][0]['fragment_id']='INVENTED'
    if scenario=='unsupported_global':a.update(decision='SUPPORTED',support_strength=3)
    if scenario=='invalid_stage':support(1,1,'ACTIVITY_PROPOSED')
    wrapper=dict(project_id=project['project_id'],assessments=[dict(indicator_id=profile['indicator_id'],**a)])
    schema=refs.response_schema(request,project['fields'])
    provider.settings=transport.configuration(provider.settings|{'num_ctx':16384})
    client.inspect.return_value=runtime(provider.settings)
    provider.runtime=None
    request['context_budget']=cb.estimate(request['prompt'],schema,provider.settings)
    assert request['context_budget']['fits'] and request['prompt'].count(text.split('. ')[0])==1
    assert request['prompt'].startswith(cb.CRITERION_INSTRUCTIONS)
    write(provider.schema,schema)
    provider.input_factory=lambda p,i:request
    def gate(value,pid,ids):
        item={k:v for k,v in value['assessments'][0].items() if k!='indicator_id'}
        errors=v3.validate(project['fields'],profile,item,rubric)
        if errors:raise AssessmentValidationError(semantic_issues(errors,item,profile['indicator_id']))
    provider.wrapper_validator=gate
    client.request.return_value=response(wrapper)
    if scenario in ('invalid_reference','unsupported_global','invalid_stage'):
        with pytest.raises(transport.OllamaError,match='INVALID_ASSESSMENT'):provider.evaluate(project,[profile])
        assert provider.last_output is None
    else:
        item=provider.evaluate(project,[profile])[0]['assessment']
        assert item['decision']=='INSUFFICIENT_EVIDENCE'
        assert item=={k:v for k,v in refs.materialize(request,wrapper)['assessments'][0].items() if k!='indicator_id'}
        assert item['criterion_assessments'][3]['support']=='NOT_DEMONSTRATED'
        result=v3.confidence(project['fields'],profile,item,rubric)
        assert result['confidence_status']=='COMPUTED' and result['conceptual_coverage']==0
        assert result['confidence_raw_score']==(0 if scenario=='absent' else 41.25)
        if scenario!='absent':
            assert item['criterion_assessments'][0]['support']==('PARTIAL' if scenario=='partial' else 'CLEAR')
            assert item['evidence'][0]['text']==fragments[population_fragment]['text']
        if scenario=='context_with_distractor':
            assert 'Poblacion del estudio' in item['evidence'][0]['text']
            assert all(e['text']!=fragments[0]['text'] for e in item['evidence'])
            assert fragments[population_fragment]['fragment_id'] in item['criterion_assessments'][0]['explanation']
        if scenario=='planned_activity':assert item['criterion_assessments'][1]['support']=='PARTIAL'
        if scenario=='demonstrated_result':assert item['criterion_assessments'][2]['support']=='CLEAR'
    assert client.request.call_count==1


def test_completed_sk_assessment_without_references_has_valid_schema_and_zero(corpus,sk_case):
    from autonomous_execution import minimal as m
    rubric=corpus.rubrics['I00']
    schema=m.schema(rubric,{},version=v3.SK_VERSION)
    Draft202012Validator.check_schema(schema)
    answer=dict(criteria={c['criterion_id']:dict(judgment='NOT_DEMONSTRATED',coverage=0,evidence_ids=[],why='Sin respaldo verificable.')
        for c in rubric['criteria']},conclusion='INSUFFICIENT_EVIDENCE__0',why='Analisis completado sin respaldo.',
        strength_rubric={key:0 for key in v3.STRENGTH_DIMENSIONS}|dict(evidence_ids=[],why='Sin respaldo en las cuatro dimensiones.'))
    Draft202012Validator(schema).validate(answer)
    wrapper=m.assemble(corpus.project,'I00',rubric,{},answer,version=v3.SK_VERSION)
    assessment={k:v for k,v in wrapper['assessments'][0].items() if k!='indicator_id'}
    result=v3.confidence(corpus.project['fields'],corpus.profiles['I00'],assessment,rubric)
    assert result['confidence_status']=='COMPUTED' and result['confidence_raw_score']==0
    answer['strength_rubric']['evidence_ids']=['INVENTED']
    with pytest.raises(ValidationError):Draft202012Validator(schema).validate(answer)


def test_sk_prompts_and_corrections_only_propose_the_two_main_states(corpus):
    from autonomous_execution import minimal as m, batching as b
    for protocol in (False,True):
        request=cb.make_request(corpus.project,corpus.profiles['I00'],corpus.rubrics['I00'],
            corpus.project['fields'],evidence_references=protocol,assessment_version=v3.SK_VERSION)
        assert 'NOT_SUPPORTED' not in request['prompt'].split('INPUT_JSON:\n')[0]
        schema=refs.response_schema(request,corpus.project['fields'])
        corrected=transport.corrective_request(request,schema,corpus.settings)
        assert 'NOT_SUPPORTED' not in corrected['prompt'].split('INPUT_JSON:\n')[0]
    assert 'NOT_SUPPORTED' not in m.SK_INSTRUCTIONS
    data=dict(project=corpus.project,sections=corpus.sections,chunks=corpus.chunks,candidates=corpus.hits)
    manifest=dict(schema_version=v3.SK_VERSION,profiles=corpus.profiles,rubrics=corpus.rubrics)
    items=[b.item_for(data,manifest,iid,corpus.settings) for iid in ('I00','I01')]
    request,_=b.request_for(items,corpus.settings)
    assert 'NOT_SUPPORTED' not in request['prompt'].split('INPUT_JSON:\n')[0]


def test_sentence_fragments_preserve_unicode_whitespace_and_repetition():
    text = 'Una\u200b frase.\n\nUna\u200b frase. Otra  frase.'
    units = refs.fragments({'text__methods':text})
    assert ''.join(f['text'] for f in units) == text
    assert [f['fragment_id'] for f in units] == ['F000','F001','F002']
    assert units[0]['text'] == 'Una\u200b frase.\n\n'


def test_full_context_leaves_room_for_specific_corrective_errors(corpus):
    text='A documented mechanism operates here. '*200
    corpus.chunks[0].update(text=text,char_end=len(text))
    corpus.sections[0]['text_original']=text
    corpus.project['fields']['methodology']=text
    request=pack(corpus)['TEST_PROJECT']['I00']
    assert request['context_selection']['status']=='READY'
    budget=request['context_budget']
    assert budget['input_budget']-budget['estimated_input_tokens']>=refs.CORRECTIVE_INPUT_RESERVE
    schema=refs.response_schema(request,corpus.project['fields'])
    issues=[dict(category='INVALID_FIELD_VALUE',rule='V3_CRITERION:POSITIVE_SUPPORT_REQUIRES_QUOTE',
        path=f'$.criterion_assessments[{i}].evidence_indices',criterion_id=f'C{i:02d}') for i in range(48)]
    corrective=transport.corrective_request(request,schema,corpus.settings,issues)
    assert corrective['context_budget']['fits']
    assert corrective['payload']==request['payload']
    assert 'POSITIVE_SUPPORT_REQUIRES_QUOTE' in corrective['prompt']
    assert 'Otros errores pendientes:' in corrective['prompt']


@pytest.mark.parametrize('provider', ['ollama','openai'])
@pytest.mark.parametrize('failure', ['unknown','missing','inconsistent','exhausted'])
def test_corrective_feedback_is_bounded_and_other_indicators_projects_continue(
        live_run, corpus, sample, monkeypatch, provider, failure):
    directory, client = live_run
    corpus.settings = transport.configuration(dict(provider='openai', api=dict(budget_usd=15))) if provider=='openai' else corpus.settings
    corpus.hits = corpus.hits[:2]
    requests = pack(corpus)
    install_plan(directory, corpus, requests)
    plan = read(directory/'plan.json')
    plan['runtime']['provider'] = provider
    second = deepcopy(corpus.project)
    second.update(project_id='NEXT_PROJECT', siap_id='NEXT')
    corpus.project = second
    for hit in corpus.hits: hit['source_id']='NEXT_PROJECT'
    corpus.chunks[0]['source_id']='NEXT_PROJECT'
    corpus.sections[0]['source_id']='NEXT_PROJECT'
    plan['projects'].append(second)
    plan['context_requests']['NEXT_PROJECT'] = pack(corpus)['NEXT_PROJECT']
    plan.update(isolate_indicator_errors=True, corrective_retries=2, token_limit_retries=2 if provider=='ollama' else 0,
        maximum_calls=288, total_token_reservation_cap=288*8192,
        budgets=dict(assessment_reservation=3*8192, assessment_postcall_review_threshold=3*8192))
    write(directory/'plan.json', plan)
    manifest=read(directory/'manifest.json');manifest['plan_sha256']=sha(directory/'plan.json');write(directory/'manifest.json',manifest)
    binding=runtime(corpus.settings) if provider=='ollama' else dict(runtime(), provider='openai',
        model=corpus.settings['model'], configuration=corpus.settings, configuration_sha256=canonical_hash(corpus.settings))
    client.inspect.return_value=binding
    monkeypatch.setattr(live,'create_client',lambda _:client)
    attempts=[]
    def reply(method,path,payload):
        prompt=payload['messages'][0]['content']
        body=json.loads(prompt.split('INPUT_JSON:\n')[1])
        pid,iid=body['project']['project_id'],body['indicators'][0]['indicator_id']
        value=selection(sample,pid,iid)
        if (pid,iid)==('TEST_PROJECT','I00'):
            attempts.append(prompt)
            if len(attempts)==1 or failure=='exhausted':
                criterion=value['assessments'][0]['criterion_assessments'][0]
                if failure=='unknown': criterion['evidence_refs'][0]['fragment_id']='MISSING'
                elif failure=='inconsistent': value['assessments'][0].update(decision='NOT_SUPPORTED',support_strength=0)
                else: criterion['evidence_refs']=[]
        elif iid=='I01':
            # A legitimate negative is VALID, never a synthetic error fallback.
            item=value['assessments'][0];item.update(decision='NOT_SUPPORTED',support_strength=0)
            for c in item['criterion_assessments']:c.update(support='NOT_DEMONSTRATED',evidence_refs=[])
        return response(value)|dict(model=corpus.settings['model'])
    client.request.side_effect=reply
    result=live.execute(SimpleNamespace(run='batch_test',authorize=True))
    exhausted_calls=2 if provider=='ollama' else 3
    assert len(attempts)==(exhausted_calls if failure=='exhausted' else 2)
    assert client.request.call_count==(3+exhausted_calls if failure=='exhausted' else 5)
    assert 'REFERENCE_CORRECTION:' not in attempts[0]
    assert 'REFERENCE_CORRECTION:' in attempts[1]
    assert ('enum' if failure=='unknown' else 'CANNOT_CLAIM_POSITIVE' if failure=='inconsistent' else
        'POSITIVE_SUPPORT_REQUIRES_QUOTE') in attempts[1]
    assert 'criterion_assessments[0]' in attempts[1] or failure=='inconsistent'
    state=live.verify_run(directory)
    assert not state['blocking_errors']
    assert len(state['projects'][1]['rows'])==2
    first=state['projects'][0]
    assert first['blocked_indicators']==({'I00':'BLOCKED_ERROR'} if failure=='exhausted' else {})
    assert next(r for r in first['rows'] if r['indicator_id']=='I01')['decision']=='NOT_SUPPORTED'
    saved={p:p.read_bytes() for p in directory.rglob('assessment.rows.json')}
    count=client.request.call_count
    live.execute(SimpleNamespace(run='batch_test',authorize=False))
    assert all(p.read_bytes()==data for p,data in saved.items())
    assert client.request.call_count==count+(3 if failure=='exhausted' and provider!='ollama' else 0)


@pytest.mark.parametrize('provider',['ollama','openai'])
def test_shared_menu_cli_planner_enables_references_and_two_corrections(planner, corpus, provider):
    root,run,module=planner
    config=transport.configuration(dict(provider='openai',api=dict(budget_usd=15))) if provider=='openai' else corpus.settings
    write(run/'execution.json',dict(llm=config))
    name=coordinator.prepare_evaluation(root,run,['TEST'])
    plan=read(module.BASE/name/'plan.json')
    assert plan['corrective_retries']==2 and plan['maximum_calls']==48*3
    assert plan['budgets']['assessment_reservation']==config['num_ctx']*3
    assert all(refs.active(r) for r in plan['context_requests']['TEST_PROJECT'].values())
    assert plan['assessment_version'] == v3.SK_VERSION
    assert plan['confidence_version'] == v3.SK_CONFIDENCE_VERSION
    request = plan['context_requests']['TEST_PROJECT']['I00']
    assert request['assessment_version'] == v3.SK_VERSION
    assert 'strength_rubric' in refs.response_schema(request,corpus.project['fields'])['properties']['assessments']['items']['properties']


@pytest.mark.parametrize('policy_mode',[None,v3.DEMONSTRATED,v3.PROSPECTIVE])
def test_sk_confidence_reference_roundtrip_and_checkpoint_reuse(live_run,corpus,sk_case,policy_mode):
    directory,client = live_run
    corpus.settings=transport.configuration(corpus.settings|{'num_ctx':16384})
    corpus.hits = corpus.hits[:1]
    mode_args={}
    derivation=None
    if policy_mode:
        corpus.rubrics,derivation=v3.catalog_for_mode(corpus.profiles,corpus.rubrics,policy_mode)
        mode_args=dict(evaluation_mode=policy_mode,context_mode=v3.GRAPHRAG_CONTEXT)
    requests,_ = cb.prepare_contexts([corpus.project],corpus.profiles,corpus.rubrics,corpus.settings,
        corpus.hits,corpus.chunks,corpus.sections,evidence_references=True,assessment_version=v3.SK_VERSION,**mode_args)
    request = requests['TEST_PROJECT']['I00']
    assert request['context_selection']['status'] == 'READY'
    assert request['context_budget']['fits']
    assert request['prompt'].count(corpus.chunks[0]['text']) == 1
    install_plan(directory,corpus,requests)
    plan = read(directory/'plan.json')
    plan.update(assessment_version=v3.SK_VERSION,confidence_version=v3.SK_CONFIDENCE_VERSION,
        budgets=dict(assessment_reservation=corpus.settings['num_ctx'],assessment_postcall_review_threshold=corpus.settings['num_ctx']))
    if policy_mode:
        plan.update(evaluation_policy=v3.evaluation_policy(policy_mode,v3.GRAPHRAG_CONTEXT),catalog_derivation=derivation)
    write(directory/'plan.json',plan)
    manifest = read(directory/'manifest.json'); manifest['plan_sha256'] = sha(directory/'plan.json')
    if policy_mode:manifest['evaluation_policy_sha256']=plan['evaluation_policy']['sha256']
    write(directory/'manifest.json',manifest)
    binding = client.inspect.return_value
    binding.update(configuration=corpus.settings,configuration_sha256=canonical_hash(corpus.settings))
    wrapper = selection(sk_case)
    schema = refs.response_schema(request,corpus.project['fields'])
    Draft202012Validator(schema).validate(wrapper)
    client.request.return_value = response(wrapper)
    live.execute(SimpleNamespace(run='batch_test',authorize=True))
    state = live.verify_run(directory)
    row = state['projects'][0]['rows'][0]
    assert row['confidence_version'] == v3.SK_CONFIDENCE_VERSION
    assert row['confidence_raw_score'] == 86.25
    original = refs.materialize(request,wrapper)['assessments'][0]
    assert live.assessment_from_row(row) == {k:v for k,v in original.items() if k!='indicator_id'}
    saved = {p:p.read_bytes() for p in directory.rglob('assessment.rows.json')}
    count = client.request.call_count
    live.execute(SimpleNamespace(run='batch_test',authorize=False))
    assert client.request.call_count == count == 1
    assert all(p.read_bytes()==data for p,data in saved.items())
    if policy_mode:
        policy=plan['evaluation_policy']
        saved_call=read(next((directory/'calls').glob('*/*/plan.json')))
        assert saved_call['evaluation_policy_sha256']==policy['sha256']
        # Even a newly sealed request cannot silently switch temporal meaning.
        plan['context_requests']['TEST_PROJECT']['I00']['evaluation_mode']=(v3.DEMONSTRATED if policy_mode==v3.PROSPECTIVE else v3.PROSPECTIVE)
        write(directory/'plan.json',plan);manifest['plan_sha256']=sha(directory/'plan.json');write(directory/'manifest.json',manifest)
        with pytest.raises(ValueError,match='Modos de request'):live.execute(SimpleNamespace(run='batch_test',authorize=False))
        assert client.request.call_count==count


@pytest.mark.parametrize('mode',['single','batch','clarification'])
@pytest.mark.parametrize('state',['sufficient','weak','partial','absent','legacy_alias','duplicate_refs','context_only'])
def test_active_autonomous_adapter_uses_sk_and_recovers_synthetic_response(tmp_path,corpus,sk_case,mode,state):
    from autonomous_execution import minimal as m, batching as b, store as s
    # Exercise the current 16384-token configuration, not the old 8192 fixture.
    corpus.settings=transport.configuration(corpus.settings|{'num_ctx':16384})
    if state=='context_only':
        for iid in ('I00','I01'):
            wrapper=deepcopy(sk_case['wrapper']);candidate=wrapper['assessments'][0]['rubrics'][0]
            candidate.update(indicator_id=iid,profile_sha256=canonical_hash(corpus.profiles[iid]))
            candidate['criteria'][0].update(temporal_requirement='CONTEXT_ONLY',
                rationale='Identificacion contextual del mecanismo; no exige que se haya ejecutado ni producido impacto.')
            candidate['criteria'][1].update(role='REQUIRED',alternative_group=None)
            candidate['criteria'][2].update(role='COMPLEMENTARY',alternative_group=None)
            corpus.rubrics[iid]=v3.validate_rubric_wrapper(wrapper,[corpus.profiles[iid]])[iid]
    data = dict(project=corpus.project,sections=corpus.sections,chunks=corpus.chunks,candidates=corpus.hits)
    policy = s.read(Path(__file__).resolve().parents[1]/'config/autonomous.json')
    policy['cooldown_seconds'] = 0
    manifest = dict(execution_id='SYNTHETIC',schema_version=v3.SK_VERSION,
        confidence_version=v3.SK_CONFIDENCE_VERSION,policy=policy,llm=corpus.settings,
        runtime=runtime(corpus.settings),profiles=corpus.profiles,rubrics=corpus.rubrics)
    s.write(tmp_path/'manifest.json',manifest)
    eid = next(iter(m.registry(data,'I00')))
    a = sk_case['assessment']
    if state=='context_only':
        a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=1)
        a['evidence'][0]['stage']='CONTEXT'
        for c in a['criterion_assessments'][1:]:c.update(support='NOT_DEMONSTRATED',coverage=0,evidence_indices=[])
    if state in ('weak','partial'):
        a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=1 if state=='weak' else 2)
        for c in a['criterion_assessments']:
            if c['support']!='NOT_DEMONSTRATED':c.update(support='PARTIAL',coverage=1 if state=='weak' else 2)
    if state in ('absent','legacy_alias'):
        a.update(decision='INSUFFICIENT_EVIDENCE',support_strength=0)
        for c in a['criterion_assessments']:c.update(support='NOT_DEMONSTRATED',coverage=0,evidence_indices=[])
        a['strength_rubric'].update({key:0 for key in v3.STRENGTH_DIMENSIONS},evidence_indices=[])
    expected=v3.confidence(corpus.project['fields'],corpus.profiles['I00'],a,corpus.rubrics['I00'])['confidence_raw_score']
    assert expected is not None
    conclusion=f"{a['decision']}__{a['support_strength']}" if state!='legacy_alias' else 'NOT_SUPPORTED__0'
    answer = dict(criteria={c['criterion_id']:dict(
        judgment=c['support']+('__CONTEXT' if state=='context_only' else '__DESIGN_DOCUMENTED') if c['support']!='NOT_DEMONSTRATED' else 'NOT_DEMONSTRATED',
        evidence_ids=[eid] if c['support']!='NOT_DEMONSTRATED' else [],why=c['explanation'],coverage=c['coverage'])
        for c in a['criterion_assessments']},conclusion=conclusion,why=a['explanation'],
        strength_rubric={key:a['strength_rubric'][key] for key in v3.STRENGTH_DIMENSIONS}
            |dict(evidence_ids=[eid] if a['support_strength'] else [],why=a['strength_rubric']['explanation']))
    if state=='duplicate_refs':
        for c in answer['criteria'].values():c['evidence_ids'] *= 2
        answer['strength_rubric']['evidence_ids'] *= 2
    Draft202012Validator(m.schema(corpus.rubrics['I00'],m.registry(data,'I00'),version=v3.SK_VERSION)).validate(answer)
    if mode == 'batch':
        items=[b.item_for(data,manifest,iid,corpus.settings) for iid in ('I00','I01')]
        request,schema = b.request_for(items,corpus.settings)
        Draft202012Validator(schema).validate(dict(I00=answer,I01=answer))
        rows=[b.validate_item(data,item,answer)['row'] for item in items]
        assert all(row['confidence_raw_score']==expected and row['decision']==a['decision'] for row in rows)
        assert request['prompt'].count(corpus.chunks[0]['text']) == 1
        assert request['context_budget']['fits']
        assert request['prompt'].count(cb.CRITERION_INSTRUCTIONS)==1
        assert all(item['request']['semantic_input']['indicator']['rubric']['criteria'][0]['rationale']==manifest['rubrics'][item['iid']]['criteria'][0]['rationale'] for item in items)
        if state=='context_only':assert all(row['decision']=='INSUFFICIENT_EVIDENCE' and row['conceptual_coverage']==0 for row in rows)
        return
    calls=[]
    def factory(settings):
        from unittest.mock import Mock
        client = Mock(spec=transport.OllamaClient)
        client.inspect.return_value = runtime(settings)
        def reply(method,path,payload):
            calls.append(payload)
            value = deepcopy(answer)
            body = json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n')[1])
            assert payload['messages'][0]['content'].count(cb.CRITERION_INSTRUCTIONS)==1
            assert body['indicator']['rubric']['criteria'][0]['rationale']==corpus.rubrics['I00']['criteria'][0]['rationale']
            if mode=='clarification' and len(calls)==1:
                value['criteria']['C01']['judgment'] = 'REVIEW_REQUIRED'
            if 'requested_criteria' in body:
                value['criteria'] = {cid:c for cid,c in value['criteria'].items() if cid in body['requested_criteria']}
            Draft202012Validator(payload['format']).validate(value)
            return response(value)
        client.request.side_effect = reply
        return client
    worker = m.MinimalWorker(tmp_path,manifest,client_factory=factory,ram=lambda:99999,sleep=lambda _:None)
    try:
        result = worker.evaluate(data,'I00',0)
        assert result['row']['confidence_raw_score'] == expected
        assert result['row']['decision']==a['decision'] and result['row']['assessment_validation_status']=='VALID'
        assert result['row']['confidence_version'] == v3.SK_CONFIDENCE_VERSION
        assert result['wrapper']['assessments'][0]['strength_rubric'] == a['strength_rubric']
        if state=='context_only':
            assert result['row']['conceptual_coverage']==0
            assert result['wrapper']['assessments'][0]['criterion_assessments'][0]['support']=='CLEAR'
            assert result['row']['confidence_raw_score']<50
        assert worker.evaluate(data,'I00',0) == result
        assert len(calls) == (2 if mode=='clarification' else 1)
    finally:
        worker.close()
