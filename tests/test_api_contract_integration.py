"""Small offline checks only: fake SDK, synthetic IDs, no embeddings or models."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from layer4_evaluation.indicators.ollama_provider import configuration, OllamaAssessmentProvider, OllamaError
from layer4_evaluation.indicators.openai_provider import OpenAIClient, Ledger, cost
from layer2_processing.preprocessing.project_selection import digest
from evaluation_contracts import create,load,resolve


def settings():
    return configuration(dict(provider='openai',api=dict(budget_usd=15,retry_seconds=0)))


def test_model_preferences_and_frozen_binding(tmp_path):
    from model_access import save_preferences,preferences
    from experiment_runtime import binding,options
    save_preferences(tmp_path,'openai')
    assert preferences(tmp_path)=={'provider':'openai'}
    run=tmp_path/'run';run.mkdir()
    saved={'llm':settings(),'contract':{'sha256':'synthetic'}}
    (run/'model.binding.json').write_text(json.dumps(saved))
    assert binding(tmp_path,run,{})==saved
    token=options.set({'provider':'ollama'})
    try:
        with pytest.raises(ValueError,match='Proveedor distinto'):binding(tmp_path,run,{})
    finally:options.reset(token)


def test_credentials_are_reused_without_network(tmp_path,monkeypatch):
    import model_access as m
    vault={}
    monkeypatch.setitem(sys.modules,'keyring',SimpleNamespace(get_password=lambda *a:vault.get('key'),
        set_password=lambda *a:vault.update(key=a[-1]),get_keyring=lambda:SimpleNamespace()))
    monkeypatch.setattr('builtins.input',lambda _: 'S')
    monkeypatch.setattr(m.getpass,'getpass',lambda _:'synthetic-credential')
    m.configure_key(tmp_path)
    assert m.api_key(tmp_path)=='synthetic-credential'
    monkeypatch.setattr('builtins.input',lambda _:'1')
    monkeypatch.setattr(m.getpass,'getpass',lambda _:pytest.fail('Existing credential must be reused'))
    m.configure_key(tmp_path)
    assert not list(tmp_path.rglob('*'))


def test_contract_versions_replay_and_additions(tmp_path):
    features={str(i):['area'+str(i%2),'2026','active','4'] for i in range(12)}
    pop=dict(project_features=features,sources={'synthetic.csv':'hash'},population_sha256=digest(features))
    path=create(tmp_path,'shared',4,42,pop,'catalog')
    original=path.read_bytes();contract=load(path)
    selected=resolve(contract,pop,'catalog',3)
    assert selected['project_ids'][:4]==contract['project_ids']
    assert len(set(selected['project_ids']))==7
    assert resolve(contract,pop,'catalog')['project_ids']==contract['project_ids']
    reversed_pop=pop|dict(project_features=dict(reversed(list(features.items()))))
    assert resolve(contract,reversed_pop,'catalog',3)==selected
    assert create(tmp_path,'shared',4,42,pop,'catalog').name=='shared.v2.json'
    assert path.read_bytes()==original
    with pytest.raises(ValueError):resolve(contract,pop,'changed')
    with pytest.raises(ValueError):resolve(contract,pop,'catalog',-1)


def test_budget_reservation_actual_usage_and_uncertainty(tmp_path):
    api=settings()['api'];ledger=Ledger(tmp_path/'ledger.sqlite',api)
    usage=dict(input_tokens=1_000_000,output_tokens=1_000_000,reasoning_tokens=500_000,cached_tokens=12)
    assert cost(usage,api)==6 # reasoning is included in output
    ledger.reserve('one','P',10)
    with pytest.raises(OllamaError):ledger.reserve('concurrent','Q',1)
    ledger.finish('one',usage,'response')
    ledger.reserve('two','P',8);ledger.finish('two')
    with pytest.raises(OllamaError,match='API_BUDGET'):ledger.reserve('three','Q',2)
    assert ledger.summary()['available_usd']==1
    assert ledger.summary()['reserved_uncertain_usd']==8


class FakeResponse:
    id='synthetic-response'
    _request_id='synthetic-request'
    def __init__(self,text):self.output_text=text
    def model_dump(self,**_):
        return dict(id=self.id,status='completed',usage=dict(input_tokens=10,output_tokens=20,
            output_tokens_details=dict(reasoning_tokens=5),input_tokens_details=dict(cached_tokens=2)))


@pytest.mark.parametrize('valid',[True,False])
def test_responses_use_existing_validation_and_do_not_repeat(tmp_path,valid):
    payload=dict(project_id='P',assessments=[dict(indicator_id='I',answer=1 if valid else 'bad')])
    schema={'type':'object','properties':{'project_id':{'type':'string'},'assessments':{'type':'array','items':{
        'type':'object','properties':{'indicator_id':{'type':'string'},'answer':{'type':'integer'}},
        'required':['indicator_id','answer'],'additionalProperties':False}}},'required':['project_id','assessments'],'additionalProperties':False}
    schema_path=tmp_path/'schema.json';schema_path.write_text(json.dumps(schema))
    calls=[]
    def send(**kwargs):calls.append(kwargs);return FakeResponse(json.dumps(payload))
    client=OpenAIClient(settings(),sdk=SimpleNamespace(responses=SimpleNamespace(create=send)),root=tmp_path)
    provider=OllamaAssessmentProvider(tmp_path/'transport',schema_path,lambda *_:{'prompt':'synthetic only'},
        settings=settings(),client=client,wrapper_validator=lambda *_:None,max_indicators=1)
    if valid:
        assert provider.evaluate({'project_id':'P'},[{'indicator_id':'I'}])[0]['assessment']['answer']==1
    else:
        with pytest.raises(OllamaError,match='INVALID_ASSESSMENT'):provider.evaluate({'project_id':'P'},[{'indicator_id':'I'}])
    assert len(calls)==1 and calls[0]['model']=='gpt-6.1-terra'
    assert calls[0]['reasoning']=={'effort':'low'} and calls[0]['store'] is False
    assert calls[0]['text']['format']['strict'] is True
    assert provider.calls[0]['provider']=='openai'
    assert provider.calls[0]['api_usage']['reasoning_tokens']==5
    with pytest.raises(FileExistsError):provider.evaluate({'project_id':'P'},[{'indicator_id':'I'}])
    assert len(calls)==1


@pytest.mark.parametrize('status,code,expected',[(401,None,'API_AUTHENTICATION'),(403,None,'API_PERMISSIONS'),
    (429,'insufficient_quota','API_BALANCE'),(429,None,'API_RATE_LIMIT'),(503,None,'API_SERVER_UNCERTAIN')])
def test_errors_never_persist_sdk_messages(tmp_path,status,code,expected):
    class SDKError(Exception):pass
    def send(**_):
        exc=SDKError('DO_NOT_LOG_SYNTHETIC_SECRET');exc.status_code=status;exc.code=code;raise exc
    cfg=settings();cfg['api']['max_rate_retries']=0
    client=OpenAIClient(cfg,sdk=SimpleNamespace(responses=SimpleNamespace(create=send)),root=tmp_path)
    client.attach(tmp_path);client.attempt=tmp_path;client.project_id='P'
    with pytest.raises(OllamaError,match=expected) as exc:
        client.request('POST','/api/chat',dict(messages=[dict(role='user',content='synthetic')],format={'type':'object','properties':{}}))
    assert 'DO_NOT_LOG' not in str(exc.value)
    assert all(b'DO_NOT_LOG' not in p.read_bytes() for p in tmp_path.rglob('*') if p.is_file())


def test_external_stop_offline_export_and_ordered_queue(tmp_path):
    from run_control import request_stop,export_only
    from autonomous_execution import store as s
    run=tmp_path/'outputs/runs/test';run.mkdir(parents=True)
    s.write(run/'run.json',{})
    assert request_stop(run)['status']=='STOP_REQUESTED'
    assert (run/'stop.request.json').exists()
    seen=[]
    engine=SimpleNamespace(export=lambda root,path:seen.append(path) or {'status':'PARTIAL'})
    assert export_only(tmp_path,run,engine)['status']=='PARTIAL' and seen==[run]
    db=s.connect(run)
    db.execute("INSERT INTO meta VALUES('project_order',?)",(json.dumps(['Z','A']),))
    for pid in ['A','Z']:db.execute('INSERT INTO jobs(pid,iid,status) VALUES(?,?,?)',(pid,'I','PENDING'))
    assert s.claim(db)['pid']=='Z'
    db.close()
