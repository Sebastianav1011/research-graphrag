"""Synthetic fixtures and mocked process/provider only. No LLM calls in tests."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest
from layer4.indicators.selection import select_projects,eligible_projects,canonical_hash,FIELDS,METHOD
from layer4.indicators.prompt import make_input
from layer4.indicators.contracts import write_or_check,validate_wrapper
from layer4.indicators.preliminary_output import indicator_row,validate_rows,export_and_verify,distribution,summary,spec
from layer4.indicators.codex_cli import CodexCliAssessmentProvider,CodexCliBlocked


@pytest.fixture
def fixture():
    fields={f:'' for f in FIELDS}
    fields.update(title='Proyecto sintético',summary='Conservar bosques.',objectives='Participación comunitaria.')
    profile={'indicator_id':'I1','indicator_name':'Indicador sintético','indicator_category':'TEST',
             'indicator_dimension':None,'key_elements':['Conservación','Participación','Recuperación','Seguimiento'],
             'preferred_evidence_fields':[]}
    assessment={'decision':'SUPPORTED','support_strength':3,
                'supported_key_elements':profile['key_elements'][:3],
                'evidence':[{'field':'summary','text':'Conservar bosques.'},
                            {'field':'objectives','text':'Participación comunitaria.'}],
                'explanation':'Fixture sintético de prueba, no resultado real.'}
    project={'project_id':'SYNTH_P1','fields':fields}
    return project,profile,assessment


def wrapper(project,profile,assessment):
    return {'project_id':project['project_id'],'assessments':[{'indicator_id':profile['indicator_id'],**assessment}]}


def selected_fixture(project,profile):
    return [{**deepcopy(project),'project_id':f'SYNTH_P{i}','title':project['fields']['title'],
             'selection_order':i+1,
             'candidates':[{'indicator_id':profile['indicator_id'],'hybrid_retrieval_score':.9},
                           {'indicator_id':'I2','hybrid_retrieval_score':.8}]} for i in range(20)]


def test_schemas_current():write_or_check(check=True)


def test_selection_round_robin_reproducible(fixture):
    p,profile,_=fixture
    eligible=selected_fixture(p,profile)
    for i,project in enumerate(eligible):project['candidates'][0]['indicator_id']=f'I{i%4}'
    first=select_projects(eligible)
    assert first==select_projects(list(reversed(eligible)))
    assert len(first)==len({p['project_id'] for p in first})==20
    assert [p['candidates'][0]['indicator_id'] for p in first[:8]]==['I0','I1','I2','I3']*2
    assert all(len(p['candidates'])<=2 for p in first)
    assert all(p['selection_method']==METHOD for p in first)


def test_selection_insufficient(fixture):
    p,profile,_=fixture
    with pytest.raises(ValueError,match='Fewer'):select_projects(selected_fixture(p,profile)[:19])


def test_selection_duplicate(fixture):
    p,profile,_=fixture;s=selected_fixture(p,profile);s[1]['project_id']=s[0]['project_id']
    with pytest.raises(ValueError,match='Duplicate'):select_projects(s)


def eligibility_fixture():
    doc={'document_id':'D','source_id':'P','source_type':'PROJECT'}
    sections=[{'section_id':'S_'+f,'document_id':'D','source_id':'P','source_type':'PROJECT',
               'field_name':f,'text_hash_normalized':'hash_'+f,'text_original':f+' exact original'} for f in FIELDS]
    refs=[{'field_name':s['field_name'],'section_id':s['section_id'],'text_hash':s['text_hash_normalized'],'chunk_ids':[]}
          for s in sections]
    core={'source_type':'PROJECT','source_id':'P','document_id':'D','title_section_id':'S_title',
          'orientation_sections':refs[:2],'substantive_sections':refs[2:],'available_field_names':sorted(FIELDS),
          'context_status':'ASSESSMENT_READY'}
    context={**core,'context_package_id':'C','source_context_hash':canonical_hash(core),'layer3_run_id':'R'}
    candidates=[{**{k:context[k] for k in ('source_type','source_id','document_id','context_status','source_context_hash','layer3_run_id')},
                 'context_package_id':'C','indicator_id':i,'hybrid_retrieval_score':score,'source_rank':rank}
                for i,score,rank in [('I2',.8,1),('I1',.9,40),('I0',.9,50)]]
    return candidates,[context],[doc],sections


def test_actual_score_order_and_id_tiebreak():
    args=eligibility_fixture();result=eligible_projects(*args,run_id='R')
    assert [c['indicator_id'] for c in result[0]['candidates']]==['I0','I1','I2']
    assert result[0]['fields']['methodology']=='methodology exact original'


def test_article_and_discovery_excluded():
    args=eligibility_fixture()
    args[0][0]['source_type']='ARTICLE';args[0][1]['context_status']='DISCOVERY_ONLY'
    result=eligible_projects(*args,run_id='R')
    assert len(result[0]['candidates'])==1


@pytest.mark.parametrize('target',['section','context','candidate'])
def test_invalid_context_rejected(target):
    args=eligibility_fixture()
    if target=='section':args[3][0]['text_hash_normalized']='changed'
    if target=='context':args[1][0]['source_context_hash']='changed'
    if target=='candidate':args[0][0]['document_id']='missing'
    with pytest.raises(ValueError):eligible_projects(*args,run_id='R')


def test_prompt_whitelist_no_rank_or_confidence(fixture):
    project,profile,_=fixture
    profile.update(source_record_json=json.dumps({'tipo':'Producto'}),hybrid_retrieval_score=.99,source_rank=1,
                   confidence_raw_score=100,researcher_email='excluded@example.invalid')
    payload=make_input(project,[profile],[])
    text=json.dumps(payload['payload'])
    assert not any(k in text for k in ('retrieval','source_rank','confidence_raw_score','researcher','example.invalid'))
    assert payload['payload']['indicators'][0]['key_elements']==profile['key_elements']
    assert 'tipo' in payload['payload']['indicators'][0]
    assert 'preferred_evidence_fields' not in payload['payload']['indicators'][0]


def test_prompt_rejects_extra_project_metadata(fixture):
    p,profile,_=fixture;p['researcher']='excluded'
    with pytest.raises(ValueError):make_input(p,[profile],[])


def mock_runner(responses):
    calls=[]
    def run(args,**kwargs):
        calls.append((args,kwargs));response=responses[min(len(calls)-1,len(responses)-1)]
        if isinstance(response,Exception):raise response
        if isinstance(response,dict):
            Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(response),encoding='utf-8')
            return SimpleNamespace(returncode=0,stdout='{"type":"turn.completed"}\n',stderr='')
        return SimpleNamespace(returncode=1,stdout='',stderr=response)
    return run,calls


def provider(tmp_path,fixture,responses):
    p,profile,a=fixture;runner,calls=mock_runner(responses)
    return CodexCliAssessmentProvider(tmp_path/'runs',tmp_path/'schema.json',lambda p,i:make_input(p,i,[]),
                                     command=['SYNTHETIC_CLI_NOT_EXECUTED'],runner=runner),calls


def test_provider_restricted_arguments(fixture,tmp_path):
    p,profile,a=fixture;engine,calls=provider(tmp_path,fixture,[wrapper(p,profile,a)])
    result=engine.evaluate(p,[profile]);args,kwargs=calls[0]
    assert len(calls)==1 and result[0]['assessment']==a
    assert args[args.index('--sandbox')+1]=='read-only'
    assert '--ignore-user-config' in args and '--ignore-rules' in args and '--ephemeral' in args
    assert 'shell_tool' in args and 'multi_agent' in args and 'web_search="disabled"' in args
    assert kwargs['shell'] is False and kwargs['cwd']!=Path.cwd()
    assert engine.calls[0]['retry']==0


def test_retry_once_technical_failure(fixture,tmp_path):
    p,profile,a=fixture;engine,calls=provider(tmp_path,fixture,['temporary process failure',wrapper(p,profile,a)])
    assert engine.evaluate(p,[profile])[0]['assessment']==a
    assert len(calls)==2 and [c['retry'] for c in engine.calls]==[0,1]


def test_retry_once_json_or_wrapper_failure(fixture,tmp_path):
    p,profile,a=fixture;engine,calls=provider(tmp_path,fixture,[{'wrong':'shape'},wrapper(p,profile,a)])
    engine.evaluate(p,[profile]);assert len(calls)==2


def test_no_more_than_one_retry(fixture,tmp_path):
    p,profile,a=fixture;engine,calls=provider(tmp_path,fixture,['temporary failure'])
    with pytest.raises(CodexCliBlocked):engine.evaluate(p,[profile])
    assert len(calls)==2


@pytest.mark.parametrize('error',['Unauthorized','rate limit','permission denied','unexpected argument'])
def test_auth_limits_config_block_immediately(fixture,tmp_path,error):
    p,profile,a=fixture;engine,calls=provider(tmp_path,fixture,[error])
    with pytest.raises(CodexCliBlocked):engine.evaluate(p,[profile])
    assert len(calls)==1


def test_semantic_invalid_not_retried(fixture,tmp_path):
    p,profile,a=fixture;a['evidence'][0]['text']='Cita inexistente'
    engine,calls=provider(tmp_path,fixture,[wrapper(p,profile,a)])
    result=engine.evaluate(p,[profile]);row=indicator_row(p,profile,result[0]['assessment'])
    assert len(calls)==1 and row['assessment_validation_status']=='INVALID_ASSESSMENT'
    assert row['confidence_raw_score'] is None
    assert any('QUOTE_NOT_FOUND' in e for e in row['validation_errors'])
    assert row['evidence_texts'][0]=='Cita inexistente'


def test_wrong_strength_semantic_invalid_not_retry(fixture,tmp_path):
    p,profile,a=fixture;a['support_strength']=2
    engine,calls=provider(tmp_path,fixture,[wrapper(p,profile,a)])
    row=indicator_row(p,profile,engine.evaluate(p,[profile])[0]['assessment'])
    assert len(calls)==1 and row['confidence_status']=='INVALID_ASSESSMENT'


def test_wrapper_exact_ids(fixture):
    p,profile,a=fixture;out=wrapper(p,profile,a)
    out['assessments'].append(deepcopy(out['assessments'][0]))
    with pytest.raises(ValueError):validate_wrapper(out,p['project_id'],['I1'])


def test_reference_87_50_and_retrieval_ignored(fixture):
    p,profile,a=fixture;row=indicator_row(p,profile,a)
    assert row['confidence_raw_score']==87.50
    assert row['field_relevance_score']==1
    assert row['confidence_probability'] is None and row['confidence_level'] is None
    profile['retrieval_score']=0
    assert row==indicator_row(p,profile,a)


@pytest.mark.parametrize('decision,strength',[('INSUFFICIENT_EVIDENCE',2),('NOT_SUPPORTED',0)])
def test_non_supported_null_score(fixture,decision,strength):
    p,profile,a=fixture;a.update(decision=decision,support_strength=strength,supported_key_elements=[])
    row=indicator_row(p,profile,a)
    assert row['confidence_status']=='NOT_APPLICABLE' and row['confidence_raw_score'] is None


def test_real_preliminary_workbook_shape_with_invalid(fixture,tmp_path):
    p,profile,a=fixture
    selected=selected_fixture(p,profile);rows=[];assessments=[];profiles={'I1':profile,'I2':{**profile,'indicator_id':'I2'}}
    for project in selected:
        for c in project['candidates']:
            item=deepcopy(a)
            if project['project_id']=='SYNTH_P0':item['evidence'][0]['text']='Cita inexistente conservada'
            assessments.append({'project_id':project['project_id'],'indicator_id':c['indicator_id'],'assessment':item})
            rows.append(indicator_row(project,profiles[c['indicator_id']],item))
    territories=[{'project_id':'SYNTH_P0','territory_type':'COUNTRY','territory_code':'000','territory_name':'Colombia',
                  'department_code':None,'department_name':None,'code_system':'INTERNAL'}]
    metadata={'project_count':20,'assessment_engine':'CODEX_CLI','confidence_is_probability':False,'country_internal_code':'000',
              'generated_at':'2026-10-17T00:13:44.048790+00:00'}
    assert validate_rows(selected,profiles,assessments,rows,territories,metadata)
    qa=export_and_verify(selected,rows,territories,metadata,tmp_path/'synthetic.xlsx')
    assert qa['status']=='PASS' and qa['sheet_rows']=={'PROYECTOS':20,'INDICADORES':40,'TERRITORIOS':1,'METADATA':5}
    assert summary(selected,rows,territories,[],[])['assessments']['invalid']==2


def test_output_tampering_rejected(fixture):
    p,profile,a=fixture;selected=selected_fixture(p,profile);profiles={'I1':profile,'I2':{**profile,'indicator_id':'I2'}}
    assessments=[{'project_id':p['project_id'],'indicator_id':c['indicator_id'],'assessment':a} for p in selected for c in p['candidates']]
    rows=[indicator_row(p,profiles[c['indicator_id']],a) for p in selected for c in p['candidates']]
    rows[0]['confidence_raw_score']=100
    with pytest.raises(ValueError,match='changed'):validate_rows(selected,profiles,assessments,rows,[],{'project_count':20,'assessment_engine':'CODEX_CLI'})


def test_percentiles_linear():
    assert distribution([10,20,30,40])=={'min':10,'p25':17.5,'median':25,'mean':25,'p75':32.5,'max':40}


def test_pipeline_all20_mocked(fixture,tmp_path,monkeypatch):
    from layer4.indicators import preliminary as pipeline
    p,profile,a=fixture;selected=selected_fixture(p,profile);profiles={'I1':profile,'I2':{**profile,'indicator_id':'I2'}}
    root=tmp_path;out=root/pipeline.OUT;out.mkdir(parents=True)
    for path in ('data/reference/processed','src/layer4/indicators','schemas/layer4_preliminary'):
        (root/path).mkdir(parents=True,exist_ok=True)
    (root/'src/layer4/indicators/codex_cli.py').write_text('synthetic provider')
    pipeline.json_file(root/'data/reference/processed/dane_reference_manifest.json',{'source_sha256':'a'*64})
    pipeline.json_file(out/'integrity_before.json',{})
    pipeline.json_file(out/'preliminary_manifest.json',{'status':'PREPARED_FOR_CODEX_CLI','codex_cli_version':'SYNTHETIC',
                                                     'retrieval_indicator_version':'SYNTHETIC_PREVIOUS'})
    requests=[make_input({'project_id':p['project_id'],'fields':p['fields']},[profiles[c['indicator_id']] for c in p['candidates']],[]) for p in selected]
    data={'selected':selected,'profiles':profiles,'requests':requests,'territories':[],'ambiguous':[]}
    monkeypatch.setattr(pipeline,'inputs',lambda root:data)
    monkeypatch.setattr(pipeline,'check_prepared',lambda *args:None)
    monkeypatch.setattr(pipeline,'validate_test_report',lambda *args:{'passed':1})
    monkeypatch.setattr(pipeline,'export_and_verify',lambda *args:{'status':'PASS','synthetic_test_only':True})
    class MockProvider:
        def __init__(self,*args):self.calls=[];self.raw_outputs=[]
        def evaluate(self,project,indicators):
            self.calls.append({'project_id':project['project_id'],'retry':0,'successful_transport':True})
            self.raw_outputs.append({'project_id':project['project_id'],'technical_error':None,
                'raw_output':json.dumps({'project_id':project['project_id'],
                    'assessments':[{'indicator_id':i['indicator_id'],**deepcopy(a)} for i in indicators]})})
            return [{'indicator_id':i['indicator_id'],'assessment':deepcopy(a)} for i in indicators]
    result=pipeline.execute(root,provider_factory=MockProvider)
    assert result['status']=='PRELIMINARY_LAYER4_20_PROJECTS_READY'
    assert result['codex']['calls']==20 and result['assessments']['returned']==40
    assert len(pipeline.lines(out/'assessments.jsonl'))==40
