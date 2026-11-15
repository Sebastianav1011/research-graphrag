"""Small GraphRAG-to-assessment checks; all inference and server calls mocked."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from .test_ollama_provider import sample, live_run, response, provider_case
from layer4_evaluation import live_execution as live
from layer4_evaluation.indicators import context_budget as cb, assessment_v3 as v3, ollama_provider as transport
from layer4_evaluation.indicators.selection import canonical_hash
from layer2_processing.preprocessing.adapters import write, read, sha
from scripts import pipeline_coordinator as runner


@pytest.fixture
def corpus(sample):
    profiles, candidates = {}, []
    for n in range(48):
        profile = deepcopy(sample['profile']); profile['indicator_id'] = f'I{n:02d}'
        candidate = deepcopy(sample['wrapper']['assessments'][0]['rubrics'][0])
        candidate.update(indicator_id=profile['indicator_id'], profile_sha256=canonical_hash(profile))
        profiles[profile['indicator_id']] = profile; candidates.append(candidate)
    rubrics = v3.validate_rubric_wrapper(dict(project_id=v3.CATALOG_ID,
        assessments=[dict(indicator_id=v3.CATALOG_ID,rubrics=candidates)]),profiles)
    project = dict(project_id='TEST_PROJECT',siap_id='TEST',fields=sample['fields'],field_provenance={})
    text = sample['fields']['methodology']
    chunk = dict(chunk_id='CHUNK',section_id='SECTION',source_id='TEST_PROJECT',field_name='methodology',
        text=text,char_start=0,char_end=len(text))
    section = dict(section_id='SECTION',source_id='TEST_PROJECT',field_name='methodology',text_original=text,
        text_hash_original='fixture-hash',provenance_json=json.dumps({'layer1':[dict(record_source='incoming/synthetic.json',source_row=1,field_mapping={'methodology':'methods'})]}))
    hits = [dict(candidate_id='C_'+iid,source_id='TEST_PROJECT',source_type='PROJECT',indicator_id=iid,
        context_package_id='CTX',discovery_chunks=[dict(chunk_id='CHUNK',field_name='methodology',vector_rank=1,
            vector_score=.8,retrieval_origin='HYBRID')]) for iid in profiles]
    return SimpleNamespace(project=project,profiles=profiles,rubrics=rubrics,chunks=[chunk],sections=[section],hits=hits,
        settings=transport.configuration())


def packed(corpus):
    return cb.prepare_contexts([corpus.project],corpus.profiles,corpus.rubrics,corpus.settings,
        corpus.hits,corpus.chunks,corpus.sections)


def test_48_bounded_requests_have_only_their_indicator_and_ranked_evidence(corpus):
    requests, report = packed(corpus)
    assert len(requests['TEST_PROJECT']) == len(report['requests']) == 48
    for iid,r in requests['TEST_PROJECT'].items():
        assert r['context_budget']['fits'] and r['context_budget']['input_budget']==(
            corpus.settings['num_ctx']-corpus.settings['num_predict']-corpus.settings['context_margin_tokens'])
        assert [i['indicator_id'] for i in r['payload']['indicators']]==[iid]
        assert r['payload']['project']['fields']['methodology']==corpus.chunks[0]['text']
        assert r['context_selection']['selected'][0]['chunk_id']=='CHUNK'
        assert r['context_selection']['selected'][0]['char_start']==0
        assert 'catalog' not in r['payload'] and 'graph' not in r['payload']
        assert r['payload']['indicators'][0]['rubric']['criteria'][0]['role']=='REQUIRED'


def test_expanded_run_context_reaches_packing_binding_and_http(provider_case,corpus,sample,tmp_path):
    from pathlib import Path
    from experiment_runtime import binding,options
    root=Path(__file__).resolve().parents[1]
    configured=read(root/'config/pipeline_manual.json')['llm']
    settings=transport.configuration(configured)
    assert settings['num_ctx']==16384
    assert (settings['num_predict'],settings['max_predict'],settings['context_margin_tokens'])==(4096,6144,512)
    token=options.set(dict(provider='ollama'))
    try:
        assert binding(root,tmp_path/'new-run',configured)['llm']==settings
    finally:options.reset(token)
    corpus.settings=settings
    requests,report=cb.prepare_contexts([corpus.project],corpus.profiles,corpus.rubrics,settings,
        corpus.hits,corpus.chunks,corpus.sections,evidence_references=True,assessment_version=v3.SK_VERSION)
    assert all(r['status']=='READY' and r['selected'] for r in report['requests'])
    request=requests[corpus.project['project_id']]['I00']
    assert request['context_budget']['input_budget']==11776
    assert request['context_budget']['estimated_input_tokens']+384<=11776
    provider,client,project,profile,_,wrapper=provider_case
    # Exercise the actual transport with its existing synthetic response contract.
    request=cb.make_request(project,profile,sample['rubric'],project['fields'])
    request['context_budget']=cb.estimate(request['prompt'],read(provider.schema),settings)
    provider.settings=settings
    provider.runtime=None
    client.inspect.return_value=client.inspect.return_value|dict(configuration=settings,configuration_sha256=canonical_hash(settings))
    provider.input_factory=lambda p,i:request
    provider.evaluate(project,[profile])
    payload=client.request.call_args.args[2]
    assert payload['options']['num_ctx']==16384 and payload['options']['num_predict']==4096
    assert payload['truncate'] is False and payload['shift'] is False


def test_exact_duplicates_are_logged_without_duplicate_text(corpus):
    for row in corpus.hits:row['discovery_chunks'] *= 3
    reqs,_=packed(corpus);r=reqs['TEST_PROJECT']['I00']
    assert len(r['context_selection']['selected'])==1
    assert [o['reason'] for o in r['context_selection']['omitted']]==['DUPLICATE_EXACT_FIELD_TEXT']*2
    assert r['prompt'].count(corpus.chunks[0]['text'])==1


def test_long_evidence_is_omitted_intact_and_never_quoted(corpus):
    text='Synthetic indivisible evidence '*3000
    corpus.chunks[0].update(text=text,char_end=len(text))
    corpus.sections[0]['text_original']=text
    corpus.project['fields']['methodology']=text
    reqs,_=packed(corpus);r=reqs['TEST_PROJECT']['I00']
    assert r['context_selection']['status']=='NO_EVIDENCE_FITS'
    assert r['context_budget']['fits'] and r['payload']['project']['fields']['methodology']==''
    assert r['context_selection']['omitted'][0]['reason']=='INPUT_BUDGET_EXCEEDED'
    with pytest.raises(ValueError,match='no pertenece'):
        live.validate_context_evidence(r,{'assessments':[{'evidence':[{'field':'methodology','text':'Synthetic long evidence.'}]}]})


def test_oversized_chunk_uses_whole_sentences_with_exact_original_offsets(corpus):
    text='A documented synthetic mechanism operates here. '*400
    corpus.chunks[0].update(text=text,char_end=len(text))
    corpus.sections[0]['text_original']=text;corpus.project['fields']['methodology']=text
    requests,_=packed(corpus);r=requests['TEST_PROJECT']['I00']
    selected=r['context_selection']['selected'][0]
    assert selected['unit']=='ORIGINAL_SENTENCE_SPAN'
    assert r['payload']['project']['fields']['methodology']==text[selected['char_start']:selected['char_end']]
    assert r['payload']['project']['fields']['methodology'].endswith('. ')
    assert selected['char_end']<len(text) and r['context_budget']['fits']
    assert r['context_selection']['evidence_limited'] is True
    assert r['context_selection']['omitted'][0]['reason']=='PARENT_CHUNK_SUBSPAN_SELECTED'


def test_missing_candidate_records_limit_without_synthetic_evaluation(corpus):
    corpus.hits=[]
    reqs,report=packed(corpus)
    assert len(report['requests'])==48
    assert all(r['context_selection']['status']=='NO_RETRIEVED_EVIDENCE' for r in reqs['TEST_PROJECT'].values())
    assert all(not r['context_selection']['selected'] for r in reqs['TEST_PROJECT'].values())


def test_normalized_chunk_offsets_map_to_literal_original_without_first_match(corpus):
    from layer2_processing.knowledge.text_normalization import normalize
    original = 'Primera  frase.\n\nUna\u200b cita  repetida. Una\u200b cita  repetida.'
    normalized = normalize(original, dict(unicode='NFC', whitespace=True, linebreaks=True, remove_invisible=True))
    text = 'Una cita repetida.'
    start = normalized.rindex(text)
    corpus.sections[0].update(text_original=original, text_normalized=normalized)
    corpus.project['fields']['methodology'] = original
    corpus.chunks[0].update(text=text, char_start=start, char_end=start+len(text))
    requests, _ = packed(corpus)
    request = requests['TEST_PROJECT']['I00']
    selected = request['context_selection']['selected'][0]
    assert selected['char_start'] == original.rindex('Una')
    assert request['payload']['project']['fields']['methodology'] == original[selected['char_start']:selected['char_end']]
    assert request['payload']['project']['fields']['methodology'] == 'Una\u200b cita  repetida.'


def test_new_run_settings_verify_sealed_semantics_and_not_historical_executable(corpus, tmp_path):
    frozen = tmp_path/'closure.plan.json'
    data = tmp_path/'rubrics.source.json'
    data.write_text('{}',encoding='utf-8')
    settings = dict(profiles=corpus.profiles,rubrics=corpus.rubrics,
                    discovery_version=live.gd.VERSION,assessment_version=v3.VERSION,
                    compact_active=False,proposal_v3_4_active=False,
                    source_hashes={'rubrics.source.json':sha(data),'historical_code.py':'historical'})
    write(frozen,settings)
    write(tmp_path/'closure.manifest.json',dict(plan_sha256=sha(frozen)))
    module = SimpleNamespace(FROZEN=frozen,gd=live.gd,v3=v3)
    loaded, resources = runner.evaluation_settings(tmp_path,module)
    assert loaded['profiles']==corpus.profiles and resources=={'rubrics.source.json':sha(data)}
    data.write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='Fingerprint'):
        runner.evaluation_settings(tmp_path,module)


def test_no_evidence_never_initializes_ollama(live_run,corpus):
    directory,client=live_run
    corpus.hits=[]
    requests,_=packed(corpus);install_plan(directory,corpus,requests)
    assert live.execute(SimpleNamespace(run='batch_test',authorize=True))['status']=='PARTIAL'
    client.inspect.assert_not_called();client.request.assert_not_called()


@pytest.mark.parametrize('mutation', ['source','original','field'])
def test_chunk_identity_and_original_provenance_are_strict(corpus,mutation):
    if mutation=='source':corpus.chunks[0]['source_id']='OTHER_PROJECT'
    if mutation=='original':corpus.sections[0]['text_original']='different text'
    if mutation=='field':corpus.chunks[0]['field_name']='summary'
    with pytest.raises(ValueError,match='GraphRAG'):
        packed(corpus)


def test_budget_guard_includes_schema_and_rejects_changed_inputs(corpus):
    requests,_=packed(corpus);r=requests['TEST_PROJECT']['I00']
    schema=v3.schemas(corpus.project['fields'])['assessment_batch']
    assert r['context_budget']['schema_tokens']>0
    assert transport.context_guard(r['prompt'],schema,corpus.settings,budget=r['context_budget'])<=corpus.settings['num_ctx']
    with pytest.raises(transport.OllamaError,match='CONTEXT_BUDGET_MISMATCH'):
        transport.context_guard(r['prompt']+'changed',schema,corpus.settings,budget=r['context_budget'])


def test_native_usage_over_budget_is_technical_error(provider_case):
    provider,client,project,profile,request,wrapper=provider_case
    request['context_budget']=cb.estimate(request['prompt'],read(provider.schema),provider.settings)
    # Capacity is mocked; no inference. Native usage must not silently exceed the reviewed input allowance.
    client.request.return_value=response(wrapper)|{'prompt_eval_count':request['context_budget']['input_budget']+1}
    with pytest.raises(transport.OllamaError,match='CONTEXT_EXHAUSTED'):
        provider.evaluate(project,[profile])
    assert provider.last_output is None


def test_sk_reference_prompt_keeps_each_criterion_label_once_and_full_profile_untouched(corpus):
    profile=corpus.profiles['I00'];rubric=corpus.rubrics['I00'];original=deepcopy(profile);frozen=deepcopy(rubric)
    legacy=cb.make_request(corpus.project,profile,rubric,corpus.project['fields'],evidence_references=True)
    compact=cb.make_request(corpus.project,profile,rubric,corpus.project['fields'],evidence_references=True,assessment_version=v3.SK_VERSION)
    indicator=compact['payload']['indicators'][0]
    assert 'key_elements' not in indicator and profile==original and rubric==frozen
    assert [c['criterion'] for c in indicator['rubric']['criteria']]==profile['key_elements']
    assert indicator['rubric']['criteria']==legacy['payload']['indicators'][0]['rubric']['criteria']
    assert compact['payload']['project']['fragments']==legacy['payload']['project']['fragments']
    assert legacy['payload']['indicators'][0]['key_elements']==profile['key_elements']
    assert [c['rationale'] for c in indicator['rubric']['criteria']]==[c['rationale'] for c in rubric['criteria']]
    assert compact['prompt'].count('"rationale":')==len(rubric['criteria'])
    assert compact['prompt'].count(cb.CRITERION_INSTRUCTIONS)==1
    assert compact['prompt'].startswith(cb.CRITERION_INSTRUCTIONS)
    assert 'condiciones exigidas; respaldo con IDs pertinentes; brecha restante' in compact['prompt']
    assert 'No reescribas juicios para ajustarlos' in compact['prompt']
    assert 'Antes de citar, relee el texto de cada ID' in compact['prompt']
    assert 'Usa en las referencias los mismos IDs que sustentan tu afirmacion' in compact['prompt']
    assert 'no exijas participacion ejecutada, recepcion ni mejoras alcanzadas' in compact['prompt']
    # Replace the previous 1737-byte guidance; avoid growing the evidence budget cost.
    assert len(cb.CRITERION_INSTRUCTIONS.encode('utf-8'))<=1737
    assert all('basis' not in c for c in indicator['rubric']['criteria'])
    distinct=deepcopy(profile);distinct['key_elements']=profile['key_elements']+['Additional institutional detail.']
    # Use the existing rubric checker to ensure no stale profile can sneak in.
    with pytest.raises(ValueError):cb.make_request(corpus.project,distinct,rubric,corpus.project['fields'],evidence_references=True,assessment_version=v3.SK_VERSION)


def install_plan(directory,corpus,requests):
    plan=read(directory/'plan.json')
    plan.update(request_protocol=cb.VERSION,context_requests=requests,projects=[corpus.project],
        profiles=corpus.profiles,rubrics=corpus.rubrics,runtime={'provider':'ollama','configuration':corpus.settings},
        maximum_calls=48,total_token_reservation_cap=48*corpus.settings['num_ctx'],
        budgets={'assessment_reservation':corpus.settings['num_ctx'],'assessment_postcall_review_threshold':corpus.settings['num_ctx']})
    write(directory/'plan.json',plan)
    manifest=read(directory/'manifest.json');manifest['plan_sha256']=sha(directory/'plan.json');write(directory/'manifest.json',manifest)


def test_native_execution_covers_48_accounts_for_missing_and_resumes_without_duplicates(live_run,corpus,sample):
    directory,client=live_run
    corpus.hits=corpus.hits[:2]
    requests,_=packed(corpus);install_plan(directory,corpus,requests)
    binding=client.inspect.return_value
    binding['configuration']=corpus.settings
    binding['configuration_sha256']=canonical_hash(corpus.settings)
    def reply(method,path,payload):
        body=json.loads(payload['messages'][0]['content'].split('INPUT_JSON:\n')[1])
        iid=body['indicators'][0]['indicator_id']
        return response(dict(project_id='TEST_PROJECT',assessments=[dict(indicator_id=iid,**sample['assessment'])]))
    client.request.side_effect=reply
    result=live.execute(SimpleNamespace(run='batch_test',authorize=True))
    assert result['status']=='PARTIAL' and client.request.call_count==2
    state=live.verify_run(directory)['projects'][0]
    assert len(state['selected'])==48 and len(state['rows'])==2 and len(state['context_limits'])==46
    assert state['rows'][0]['confidence_raw_score']==v3.indicator_row(corpus.project,corpus.profiles['I00'],sample['assessment'],corpus.rubrics['I00'])['confidence_raw_score']
    live.execute(SimpleNamespace(run='batch_test',authorize=False))
    assert client.request.call_count==2


def test_changed_plan_invalidates_previous_authorization(live_run,corpus):
    from layer4_evaluation.indicators.evidence_references import response_schema
    directory,client=live_run
    requests,_=packed(corpus);previous=deepcopy(requests)
    for request in previous['TEST_PROJECT'].values():
        prefix=request['prompt'].split('INPUT_JSON:\n')[0].replace(cb.CRITERION_INSTRUCTIONS,'')
        request['prompt']=prefix+'INPUT_JSON:\n'+cb.compact(request['payload'])
    assert previous['TEST_PROJECT']['I00']['payload']==requests['TEST_PROJECT']['I00']['payload']
    assert canonical_hash(previous)!=canonical_hash(requests)
    assert response_schema(previous['TEST_PROJECT']['I00'],corpus.project['fields'])==response_schema(requests['TEST_PROJECT']['I00'],corpus.project['fields'])
    install_plan(directory,corpus,previous);old_hash=sha(directory/'plan.json')
    write(directory/'authorization.json',dict(authorized=True,run_plan_sha256=old_hash,review_sha256=sha(directory/'review.json'),max_retries=0))
    protected=(directory/'authorization.json').read_bytes()
    install_plan(directory,corpus,requests)
    assert sha(directory/'plan.json')!=old_hash
    with pytest.raises(ValueError,match='Autorizacion no coincide'):
        live.execute(SimpleNamespace(run='batch_test',authorize=False))
    client.request.assert_not_called()
    client.inspect.assert_not_called()
    assert (directory/'authorization.json').read_bytes()==protected


def test_incomplete_context_catalog_is_rejected(live_run,corpus):
    directory,_=live_run
    requests,_=packed(corpus);requests['TEST_PROJECT'].pop('I00');install_plan(directory,corpus,requests)
    with pytest.raises(ValueError,match='48 indicadores'):
        live.check(directory)


def test_old_global_cache_is_not_relabelled_as_graph_context(live_run,corpus):
    directory,_=live_run
    requests,_=packed(corpus);install_plan(directory,corpus,requests)
    write(directory/'cache.json',{'TEST_PROJECT':{'provider':'ollama'}})
    manifest=read(directory/'manifest.json');manifest['files']['cache.json']=sha(directory/'cache.json');write(directory/'manifest.json',manifest)
    with pytest.raises(ValueError,match='Cache de descubrimiento global incompatible'):
        live.verify_run(directory)


@pytest.fixture
def planner(tmp_path,monkeypatch,corpus,tokenizer_stub):
    root=tmp_path;run=root/'outputs/runs/synthetic'
    # Retrieved contexts now require the pinned tokenizer; use a hash-pinned stub.
    monkeypatch.setattr(runner,'pinned_tokenizer',lambda root:tokenizer_stub)
    settings=dict(profiles=corpus.profiles,rubrics=corpus.rubrics,rules=[],budgets={},
        observed_character_ratio=.1,discovery_version=live.gd.VERSION,assessment_version=v3.VERSION,source_hashes={})
    frozen=root/'frozen.json';write(frozen,settings)
    for name in ('src/layer4_evaluation/live_execution.py','src/layer4_evaluation/indicators/ollama_provider.py',
                 'src/layer4_evaluation/indicators/prospective_v2.py',
                 'src/layer4_evaluation/indicators/context_budget.py','outputs/runs/synthetic/prepared_hashes.json',
                 'outputs/runs/synthetic/workspace/outputs/layer3/publication/_manifest.json'):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}',encoding='utf-8')
    module=SimpleNamespace(BASE=run/'evaluation',FROZEN=frozen,check=lambda d:read(d/'plan.json'))
    monkeypatch.setattr(runner,'engine',lambda *a:module)
    monkeypatch.setattr(runner,'check',lambda *a:{'configuration':{'llm':corpus.settings},'code_hashes':{}})
    monkeypatch.setattr(runner,'evaluation_settings',lambda *a:(settings,{}))
    monkeypatch.setattr(runner,'validated_graph',lambda *a:{})
    monkeypatch.setattr('layer4_evaluation.indicators.scoped_retrieval.from_published_cache',
        lambda *a:(corpus.hits,{'version':'SYNTHETIC_SCOPED_CACHE'}))
    def table(path):
        name=path.name
        rows=([dict(project_id='TEST_PROJECT',source_project_id='TEST',record_source='incoming/synthetic.json',source_row=1)] if name=='proyectos.parquet' else
              corpus.sections if name=='source_sections.parquet' else corpus.chunks if name=='source_chunks.parquet' else
              corpus.hits if name=='source_indicator_candidates.parquet' else [dict(indicator_id=i) for i in corpus.profiles])
        return SimpleNamespace(to_pylist=lambda:rows)
    monkeypatch.setattr(runner.pq,'read_table',table)
    monkeypatch.setattr(runner.importlib.util,'spec_from_file_location',lambda *a:SimpleNamespace(loader=SimpleNamespace(exec_module=lambda m:None)))
    monkeypatch.setattr(runner.importlib.util,'module_from_spec',lambda spec:SimpleNamespace(check=lambda:settings))
    return root,run,module


def test_coordinator_regenerates_review_and_preserves_old_authorization_in_archive(planner):
    root,run,module=planner
    name=runner.prepare_evaluation(root,run,['TEST']);directory=module.BASE/name
    assert read(directory/'plan.json')['maximum_calls']==48*3
    assert len(read(directory/'context_selection.json')['requests'])==48
    # Simulate a previous, authorized global-discovery plan without a dispatch.
    old=read(directory/'plan.json');old.pop('request_protocol');write(directory/'plan.json',old)
    old_hash=sha(directory/'plan.json');write(directory/'authorization.json',{'fixture':'OLD_AUTHORIZATION'})
    assert runner.prepare_evaluation(root,run,['TEST'])==name
    archived=module.BASE/'review_versions'/name/old_hash
    assert read(archived/'authorization.json')['fixture']=='OLD_AUTHORIZATION'
    assert not (directory/'authorization.json').exists()
    assert read(directory/'plan.json')['request_protocol']==cb.VERSION


def test_coordinator_refuses_migration_after_a_prior_dispatch(planner):
    root,run,module=planner
    name=runner.prepare_evaluation(root,run,['TEST']);directory=module.BASE/name
    old=read(directory/'plan.json');old.pop('request_protocol');write(directory/'plan.json',old)
    write(directory/'calls/TEST/discovery/dispatch.claim.json',{'fixture':'UNCERTAIN_OUTCOME'})
    original=sha(directory/'plan.json')
    with pytest.raises(ValueError,match='llamadas/cache previos'):
        runner.prepare_evaluation(root,run,['TEST'])
    assert sha(directory/'plan.json')==original


def descriptor_fixture(corpus):
    corpus.project['fields']={f:('El proyecto desarrollara una intervencion concreta para la comunidad. '*12
        if f not in ('keywords','title') else '') for f in corpus.project['fields']}
    corpus.sections=[dict(section_id='S_'+f,source_id=corpus.project['project_id'],source_type='PROJECT',
        field_name=f,text_original=text) for f,text in corpus.project['fields'].items()]
    corpus.settings=corpus.settings|dict(num_ctx=24576,num_predict=4096,context_margin_tokens=512)
    return corpus


def relational_fixture(pid):
    return dict(project_id=pid,seed_entity_id=pid,version='PROJECT_RELATIONAL_CONTEXT_V1',
        evidence_role='RELATIONAL_CONTEXT_ONLY',graph_manifest_sha256='synthetic_graph',
        entities=[dict(entity_id=p,canonical_id=p,entity_type='RESEARCHER' if p=='R' else 'PROJECT',label=p)
            for p in (pid,'R','UNSELECTED')],
        relations=[dict(relation_id=rid,source_entity_id=p,target_entity_id='R',
            relation_type='PROJECT_HAS_RESEARCHER',evidence_type='STRUCTURED_CANONICAL',
            provenance={'record_source':'base/members.csv','source_row':i},attributes={})
            for i,(rid,p) in enumerate((('E1',pid),('E2','UNSELECTED')),1)],
        support_paths={pid:[],'R':['E1'],'UNSELECTED':['E1','E2']},metrics={'max_hops':2})


@pytest.mark.parametrize('mode',[v3.PROSPECTIVE,v3.DEMONSTRATED])
@pytest.mark.parametrize('limited',[False,True])
def test_base_combines_complete_descriptor_and_budgeted_global_relations(corpus,mode,limited):
    descriptor_fixture(corpus)
    pid=corpus.project['project_id'];package=relational_fixture(pid)
    if limited:package['relations'][1]['provenance']['large_locator']='x'*100000
    corpus.rubrics,_=v3.catalog_for_mode(corpus.profiles,corpus.rubrics,mode)
    requests,_=cb.prepare_contexts([corpus.project],{'I00':corpus.profiles['I00']},corpus.rubrics,
        corpus.settings,[],[],corpus.sections,evidence_references=True,assessment_version=v3.SK_VERSION,
        evaluation_mode=mode,context_mode=v3.BASE_CONTEXT,relational_contexts={pid:package})
    assert set(requests)=={pid} and len(requests[pid])==1
    request=requests[pid]['I00'];payload=request['payload']
    for field,text in corpus.project['fields'].items():
        assert ''.join(f['text'] for f in payload['project']['fragments'] if f['field']==field)==text
    relation_ids=[r['relation_id'] for r in payload['relational_context']['relations']]
    assert relation_ids==(['E1'] if limited else ['E1','E2'])
    assert len(relation_ids)==len(set(relation_ids))
    assert payload['relational_context']['relations'][0]['provenance']['record_source']=='base/members.csv'
    receipt=request['context_selection']['relational']
    assert receipt['primary_descriptor_preserved']
    assert bool(receipt['omitted_paths'])==limited
    assert request['context_budget']['estimated_input_tokens']+request['context_selection']['corrective_input_reserve_tokens']<=request['context_budget']['input_budget']
    from layer4_evaluation.indicators.evidence_references import response_schema
    assert 'UNSELECTED' not in json.dumps(response_schema(request,corpus.project['fields']))


@pytest.mark.parametrize('corrupt',['project','provenance','path'])
def test_base_rejects_wrong_relational_source_or_unverifiable_paths(corpus,corrupt):
    descriptor_fixture(corpus);pid=corpus.project['project_id'];package=relational_fixture(pid)
    if corrupt=='project':package['project_id']='OTHER'
    if corrupt=='provenance':package['relations'][0]['provenance']={}
    if corrupt=='path':package['support_paths']['UNSELECTED']=['E2']
    with pytest.raises(ValueError,match='relacional|relacion'):
        cb.prepare_contexts([corpus.project],{'I00':corpus.profiles['I00']},corpus.rubrics,
            corpus.settings,[],[],corpus.sections,evidence_references=True,assessment_version=v3.SK_VERSION,
            context_mode=v3.BASE_CONTEXT,relational_contexts={pid:package})


@pytest.mark.parametrize('mode',[v3.PROSPECTIVE,v3.DEMONSTRATED])
@pytest.mark.parametrize('context',[v3.FULL_CONTEXT,v3.GRAPHRAG_CONTEXT])
def test_four_combinations_share_sk_and_original_reference_protocol(corpus,mode,context):
    from layer4_evaluation.indicators import evidence_references as refs
    if context==v3.FULL_CONTEXT:descriptor_fixture(corpus)
    else:corpus.settings=corpus.settings|dict(num_ctx=16384)
    corpus.rubrics,_=v3.catalog_for_mode(corpus.profiles,corpus.rubrics,mode)
    requests,report=cb.prepare_contexts([corpus.project],corpus.profiles,corpus.rubrics,corpus.settings,
        [] if context==v3.FULL_CONTEXT else corpus.hits,corpus.chunks,corpus.sections,
        evidence_references=True,assessment_version=v3.SK_VERSION,evaluation_mode=mode,context_mode=context)
    assert len(requests[corpus.project['project_id']])==48
    for request in requests[corpus.project['project_id']].values():
        assert request['evidence_protocol']==refs.VERSION and request['assessment_version']==v3.SK_VERSION
        assert request['context_selection']['status']=='READY'
        assert request['evaluation_mode']==mode and request['context_mode']==context
        if context==v3.FULL_CONTEXT:
            assert request['context_budget']['input_budget']==19968
            assert request['context_budget']['estimated_input_tokens']+refs.CORRECTIVE_INPUT_RESERVE<=19968
            assert 'fields' not in request['payload']['project']  # Descriptor serialized exactly once.
            fragments=request['payload']['project']['fragments']
            for field,text in corpus.project['fields'].items():
                assert ''.join(f['text'] for f in fragments if f['field']==field)==text
            assert all(r['unit']=='FULL_SECTION' for r in request['context_selection']['selected'])
            assert not request['context_selection']['omitted']


def test_full_descriptor_blocks_without_truncation_or_fallback(corpus):
    descriptor_fixture(corpus)
    field='methodology';text='Extremely long synthetic narrative. '*12000
    corpus.project['fields'][field]=text
    next(s for s in corpus.sections if s['field_name']==field)['text_original']=text
    original=deepcopy(corpus.project)
    requests,_=cb.prepare_contexts([corpus.project],corpus.profiles,corpus.rubrics,corpus.settings,
        [],[],corpus.sections,evidence_references=True,assessment_version=v3.SK_VERSION,
        evaluation_mode=v3.DEMONSTRATED,context_mode=v3.FULL_CONTEXT)
    request=requests[corpus.project['project_id']]['I00']
    assert request['context_selection']['status']=='FULL_DESCRIPTOR_TOO_LONG'
    assert request['context_selection']['selected']==[] and not request['payload']['project']['fragments']
    assert not request['context_selection']['full_descriptor_budget']['fits']
    assert corpus.project==original


@pytest.mark.parametrize('corrupt',['text','project','duplicate'])
def test_full_descriptor_refuses_ambiguous_or_wrong_source(corpus,corrupt):
    descriptor_fixture(corpus)
    if corrupt=='text':corpus.sections[2]['text_original']='changed'
    if corrupt=='project':corpus.sections[2]['source_id']='OTHER'
    if corrupt=='duplicate':corpus.sections.append(deepcopy(corpus.sections[2]))
    with pytest.raises(ValueError,match='Descriptor completo|Secciones ambiguas'):
        cb.prepare_contexts([corpus.project],corpus.profiles,corpus.rubrics,corpus.settings,[],[],corpus.sections,
            context_mode=v3.FULL_CONTEXT)


@pytest.mark.parametrize('mode',['prospective-v1','prospective-v2'])
def test_coordinator_seals_prospective_catalog_and_skips_retrieval_for_full_descriptor(planner,corpus,monkeypatch,mode):
    root,run,module=planner
    policy=v3.evaluation_policy(mode,'full-descriptor')
    settings=corpus.settings|dict(num_ctx=24576)
    write(runner.run_file(run,'execution.json'),dict(llm=settings,evaluation_policy=policy))
    # All original, authorized fields must have an unambiguous section.
    corpus.sections[:]=[dict(section_id='S_'+f,source_id=corpus.project['project_id'],field_name=f,
        text_original=t or '',text_hash_original='fixture',provenance_json=json.dumps({'layer1':[]}))
        for f,t in corpus.project['fields'].items()]
    monkeypatch.setattr('layer4_evaluation.indicators.scoped_retrieval.from_published_cache',lambda *a:pytest.fail('No retrieval in full descriptor evaluation'))
    batch=runner.prepare_evaluation(root,run,['TEST']);directory=module.BASE/batch
    plan=read(directory/'plan.json');manifest=read(directory/'manifest.json')
    assert plan['evaluation_policy']==policy and manifest['evaluation_policy_sha256']==policy['sha256']
    assert plan['runtime']['configuration']['num_ctx']==24576
    assert plan['catalog_derivation']['effective_catalog_sha256']==canonical_hash(plan['rubrics'])
    assert all(r['evaluation_mode']==policy['evaluation_mode'] for r in plan['context_requests']['TEST_PROJECT'].values())
    assert plan['assessment_version']==(v3.P2_VERSION if mode=='prospective-v2' else v3.SK_VERSION)
    before=sha(directory/'plan.json')
    write(runner.run_file(run,'execution.json'),dict(llm=settings,evaluation_policy=v3.evaluation_policy('demonstrated','full-descriptor')))
    with pytest.raises(ValueError,match='Modos incompatibles'):runner.prepare_evaluation(root,run,['TEST'])
    assert sha(directory/'plan.json')==before


def test_coordinator_sends_global_relations_only_for_selected_evaluation(planner,corpus,monkeypatch):
    root,run,module=planner
    policy=v3.evaluation_policy(base=True)
    assert policy['context_mode']==v3.RETRIEVED_CONTEXT
    write(runner.run_file(run,'execution.json'),dict(llm=corpus.settings|dict(num_ctx=16384,context_margin_tokens=1024),evaluation_policy=policy))
    corpus.sections[:]=[dict(section_id='SECTION' if f=='methodology' else 'S_'+f,source_id=corpus.project['project_id'],field_name=f,
        text_original=t or '',text_hash_original='fixture',provenance_json=json.dumps({'layer1':[]}))
        for f,t in corpus.project['fields'].items()]
    calls=[]
    def relations(workspace,projects):
        calls.extend(p['project_id'] for p in projects)
        return {p['project_id']:relational_fixture(p['project_id']) for p in projects}
    monkeypatch.setattr('layer4_evaluation.indicators.scoped_retrieval.project_relations',relations)
    def retrieved(workspace,projects,profiles,chunks,**kwargs):
        assert kwargs['relational_contexts']['TEST_PROJECT']['project_id']=='TEST_PROJECT'
        return [c|dict(relational_context=relational_fixture(c['source_id'])) for c in corpus.hits],{'model_calls':0}
    monkeypatch.setattr('layer4_evaluation.indicators.scoped_retrieval.from_published_cache',retrieved)
    batch=runner.prepare_evaluation(root,run,['TEST']);plan=read(module.BASE/batch/'plan.json')
    assert calls==['TEST_PROJECT'] and len(plan['projects'])==1
    assert len(plan['context_requests']['TEST_PROJECT'])==48
    assert plan['evaluation_policy']==policy
    request=plan['context_requests']['TEST_PROJECT']['I00']
    assert request['context_budget']['estimator']=='PINNED_QWEN_TOKENIZER_AND_CALIBRATED_TEMPLATE_V1'
    assert request['context_budget']['input_cap']==request['context_budget']['input_budget']==8000
    assert request['context_selection']['truncation']['policy']==cb.TRUNCATION_POLICY
    assert any(n['entity_id']=='UNSELECTED' for n in request['payload']['relational_context']['entities'])
    assert request['context_selection']['relational']['graph_manifest_sha256']=='synthetic_graph'


def test_retrieved_base_excludes_unretrieved_descriptor_and_preflights_budget(corpus):
    from layer4_evaluation.indicators.evidence_references import CORRECTIVE_INPUT_RESERVE
    pid=corpus.project['project_id'];literal=corpus.chunks[0]['text']
    corpus.project['fields']['methodology']=literal+'\nNEVER_SEND_DESCRIPTOR_TAIL '*20000
    corpus.sections[0]['text_original']=corpus.project['fields']['methodology']
    settings=corpus.settings|dict(num_ctx=16384,num_predict=4096,context_margin_tokens=1024)
    candidates=[corpus.hits[0]|dict(relational_context=relational_fixture(pid))]
    requests,_=cb.prepare_contexts([corpus.project],{'I00':corpus.profiles['I00']},corpus.rubrics,
        settings,candidates,corpus.chunks,corpus.sections,evidence_references=True,
        assessment_version=v3.SK_VERSION,context_mode=v3.RETRIEVED_CONTEXT)
    request=requests[pid]['I00']
    assert request['context_selection']['status']=='READY'
    assert 'NEVER_SEND_DESCRIPTOR_TAIL' not in request['prompt']
    assert literal in request['prompt'] and 'UNSELECTED' in request['prompt']
    assert request['context_selection']['selected'][0]['char_start']==0
    assert request['context_budget']['estimated_input_tokens']+CORRECTIVE_INPUT_RESERVE<=8000
    transport.context_guard(request['prompt'],{},settings,budget=request['context_budget'])
    oversized='x'*18000
    budget=cb.estimate(oversized,{},settings,conservative=True)
    with pytest.raises(transport.OllamaError,match='CONTEXT_TOO_LONG|entrada'):
        transport.context_guard(oversized,{},settings,budget=budget)


def test_retrieved_context_makes_one_mocked_assessment_call(provider_case,sample):
    provider,client,project,profile,_,wrapper=provider_case
    settings=provider.settings|dict(num_ctx=16384,num_predict=4096,context_margin_tokens=1024)
    request=cb.make_request(project,profile,sample['rubric'],project['fields'],context_mode=v3.RETRIEVED_CONTEXT)
    request['context_budget']=cb.estimate(request['prompt'],{},settings,conservative=True)
    provider.settings=settings;provider.runtime=None;provider.input_factory=lambda *a:request
    client.inspect.return_value=client.inspect.return_value|dict(configuration=settings,configuration_sha256=canonical_hash(settings))
    provider.evaluate(project,[profile])
    assert client.request.call_count==1
    sent=client.request.call_args.args[2]
    assert sent['options']['num_ctx']==16384 and sent['truncate'] is False and sent['shift'] is False
    client.request.reset_mock()
    request['prompt']='x'*18000
    request['context_budget']=cb.estimate(request['prompt'],{},settings,conservative=True)
    with pytest.raises(transport.OllamaError):provider.evaluate(project,[profile])
    assert client.request.call_count==0
