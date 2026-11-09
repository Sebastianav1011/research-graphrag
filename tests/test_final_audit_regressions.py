"""Publication audit regressions: synthetic payloads and an injected SDK only."""
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace

import pytest

from autonomous_execution import store
from layer4_evaluation.indicators.openai_provider import OpenAIClient, Ledger
from layer4_evaluation.indicators.ollama_provider import OllamaError, configuration


def test_concurrent_checkpoint_writers_leave_complete_json(tmp_path):
    path=tmp_path/'checkpoint.json'
    def save(number):
        for _ in range(8):store.write(path,dict(writer=number,values=list(range(100))))
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(save,range(4)))
    assert store.read(path)['values']==list(range(100))
    assert not list(tmp_path.glob('*.pending'))


class RateLimit(Exception):
    status_code=429
    code='rate_limit_exceeded'


def fake_client(tmp_path,send,**api):
    settings=configuration(dict(provider='openai',api=dict(budget_usd=15,retry_seconds=0,**api)))
    client=OpenAIClient(settings,sdk=SimpleNamespace(responses=SimpleNamespace(create=send)),root=tmp_path)
    client.attach(tmp_path);client.attempt=tmp_path;client.project_id='synthetic-project'
    return client


PAYLOAD=dict(messages=[dict(role='user',content='synthetic')],format=dict(type='object',properties={}))


def test_rate_retry_counts_dispatches_and_charges_usage_once(tmp_path,monkeypatch):
    import model_access
    monkeypatch.setattr(model_access,'api_key',lambda *_:pytest.fail('Injected SDK must not read credentials'))
    calls=[]
    def send(**request):
        calls.append(request)
        if len(calls)==1:raise RateLimit('never persisted')
        native=dict(id='fake',status='completed',usage=dict(input_tokens=10,output_tokens=20))
        return SimpleNamespace(id='fake',output_text='{}',model_dump=lambda **_:native)
    client=fake_client(tmp_path,send)
    result=client.request('POST','/api/chat',PAYLOAD)
    summary=Ledger(tmp_path/'api-ledger.sqlite',client.settings['api']).summary()
    assert len(calls)==summary['calls']==2 and summary['requests']==1
    assert summary['estimated_cost_usd']==pytest.approx(.00011)
    assert summary['reasoning_tokens'] is None and summary['cached_tokens'] is None
    assert summary['token_details_reported_requests']['reasoning_tokens']==0
    assert result['rate_limit_retries']==1 and result['remote_response_seconds']>=0


def test_stop_after_known_rate_rejection_prevents_retry(tmp_path):
    calls=[]
    def send(**_):
        calls.append(1);store.write(tmp_path/'stop.request.json',{})
        raise RateLimit('never persisted')
    client=fake_client(tmp_path,send)
    with pytest.raises(OllamaError,match='STOP_REQUESTED'):client.request('POST','/api/chat',PAYLOAD)
    summary=Ledger(tmp_path/'api-ledger.sqlite',client.settings['api']).summary()
    assert summary['calls']==len(calls)==1
    assert summary['reserved_uncertain_usd']==summary['estimated_cost_usd']==0


def test_exhausted_budget_prevents_any_dispatch(tmp_path):
    client=fake_client(tmp_path,lambda **_:pytest.fail('Budget must block dispatch'))
    client.settings['api']['budget_usd']=.00000001
    with pytest.raises(OllamaError,match='API_BUDGET'):client.request('POST','/api/chat',PAYLOAD)
    assert not (tmp_path/'api.dispatch.json').exists()
    assert Ledger(tmp_path/'api-ledger.sqlite',client.settings['api']).summary()['calls']==0


def test_ledger_migrates_existing_schema_without_losing_reservations(tmp_path):
    import sqlite3
    path=tmp_path/'ledger.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE requests(id TEXT PRIMARY KEY,project TEXT,state TEXT,reserved REAL,cost REAL,usage TEXT,response_id TEXT)')
        db.execute("INSERT INTO requests VALUES('old','P','UNCERTAIN',1,NULL,NULL,NULL)")
    cfg=configuration(dict(provider='openai',api=dict(budget_usd=15)))
    summary=Ledger(path,cfg['api']).summary()
    assert summary['reserved_uncertain_usd']==1 and summary['requests']==1
