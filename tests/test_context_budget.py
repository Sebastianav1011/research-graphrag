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
        assert r['context_budget']['fits'] and r['context_budget']['input_budget']==2560
        assert [i['indicator_id'] for i in r['payload']['indicators']]==[iid]
        assert r['payload']['project']['fields']['methodology']==corpus.chunks[0]['text']
        assert r['context_selection']['selected'][0]['chunk_id']=='CHUNK'
        assert r['context_selection']['selected'][0]['char_start']==0
        assert 'catalog' not in r['payload'] and 'graph' not in r['payload']
        assert r['payload']['indicators'][0]['rubric']['criteria'][0]['role']=='REQUIRED'


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
    text='A documented synthetic mechanism operates here. '*80
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
    assert transport.context_guard(r['prompt'],schema,corpus.settings,budget=r['context_budget'])<=4096
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


def install_plan(directory,corpus,requests):
    plan=read(directory/'plan.json')
    plan.update(request_protocol=cb.VERSION,context_requests=requests,projects=[corpus.project],
        profiles=corpus.profiles,rubrics=corpus.rubrics,runtime={'provider':'ollama','configuration':corpus.settings},
        maximum_calls=48,total_token_reservation_cap=48*4096,
        budgets={'assessment_reservation':4096,'assessment_postcall_review_threshold':4096})
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
    directory,client=live_run
    requests,_=packed(corpus);install_plan(directory,corpus,requests)
    write(directory/'authorization.json',dict(authorized=True,run_plan_sha256='OLD_PROMPTS',review_sha256=sha(directory/'review.json'),max_retries=0))
    with pytest.raises(ValueError,match='Autorizacion no coincide'):
        live.execute(SimpleNamespace(run='batch_test',authorize=False))
    client.request.assert_not_called()


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
def planner(tmp_path,monkeypatch,corpus):
    root=tmp_path;run=root/'outputs/runs/synthetic'
    settings=dict(profiles=corpus.profiles,rubrics=corpus.rubrics,rules=[],budgets={},
        observed_character_ratio=.1,discovery_version=live.gd.VERSION,assessment_version=v3.VERSION,source_hashes={})
    frozen=root/'frozen.json';write(frozen,settings)
    for name in ('src/layer4_evaluation/live_execution.py','src/layer4_evaluation/indicators/ollama_provider.py',
                 'src/layer4_evaluation/indicators/context_budget.py','outputs/runs/synthetic/prepared_hashes.json',
                 'outputs/runs/synthetic/workspace/outputs/layer3/publication/_manifest.json'):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}',encoding='utf-8')
    module=SimpleNamespace(BASE=run/'evaluation',FROZEN=frozen,check=lambda d:read(d/'plan.json'))
    monkeypatch.setattr(runner,'engine',lambda *a:module)
    monkeypatch.setattr(runner,'check',lambda *a:{'configuration':{'llm':corpus.settings},'code_hashes':{}})
    monkeypatch.setattr(runner,'evaluation_settings',lambda *a:(settings,{}))
    monkeypatch.setattr(runner,'validated_graph',lambda *a:{})
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
    assert read(directory/'plan.json')['maximum_calls']==48
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
