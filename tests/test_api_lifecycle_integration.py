"""SDK-mocked lifecycle. Requires the existing offline DANE fixture bundle.

No API, Ollama, embeddings or new institutional-project execution is permitted.
Only the synthetic environment fixture and immutable reference bytes are used.
"""
from types import SimpleNamespace
import shutil

import pytest

from autonomous_execution import lifecycle as l, store as s
from layer4_evaluation.indicators.ollama_provider import configuration
from layer4_evaluation.indicators.openai_provider import OpenAIClient, Ledger
from tests.test_autonomous_execution import environment, ClientFactory, authorize
from tests.test_context_budget import corpus
from tests.test_ollama_provider import sample


def prepare_api(e,monkeypatch,budget=15,stop=False):
    import model_access
    from run_control import request_stop
    monkeypatch.setattr(model_access,'api_key',lambda *_:'synthetic-only')
    # A model comparison always creates a separate run; never mutate a sealed one.
    from run_paths import find_run
    api_run=find_run(e.root,e.root/'outputs/runs','api-test','openai')
    shutil.copytree(e.run,api_run,ignore=shutil.ignore_patterns('autonomous','model.binding.json'))
    e.run=api_run;e.directory=l.folder(api_run)
    settings=configuration(dict(provider='openai',num_ctx=e.corpus.settings['num_ctx'],api=dict(budget_usd=budget)))
    s.write(e.run/'model.binding.json',dict(llm=settings,contract=None))
    state=s.read(e.run/'run.json');state['configuration']['llm']=settings;s.write(e.run/'run.json',state)
    e.prepared=l.prepare(e.root,e.run,e.policy,runtime=OpenAIClient(settings).inspect())
    fake=ClientFactory(e.sample)
    def factory(cfg):
        legacy=fake(cfg)
        def send(**request):
            result=legacy.request('POST','/api/chat',dict(messages=request['input'],format=request['text']['format']['schema']))
            if stop and len(fake.calls)==1:request_stop(e.run)
            native=dict(id='fake-'+str(len(fake.calls)),status='completed',model=cfg['model'],
                usage=dict(input_tokens=300,output_tokens=150,output_tokens_details=dict(reasoning_tokens=20)))
            return SimpleNamespace(id=native['id'],output_text=result['message']['content'],model_dump=lambda **_:native)
        return OpenAIClient(cfg,sdk=SimpleNamespace(responses=SimpleNamespace(create=send)),root=e.root)
    authorize(e)
    return fake,factory,settings


@pytest.mark.parametrize('stop',[False,True])
def test_api_lifecycle_preserves_valid_results_on_stop_export_and_resume(environment,monkeypatch,stop):
    e=environment;fake,factory,settings=prepare_api(e,monkeypatch,stop=stop)
    execute=lambda:l.execute(e.root,e.run,client_factory=factory,ram=lambda:100000,sleep=lambda _:None)
    result=execute()
    if stop:
        assert result['evaluated']==1 and 'export' in result
    else:assert result['status']=='COMPLETE'
    persisted={p:p.read_bytes() for p in (e.directory/'results').rglob('*.json')}
    assert execute()['status']=='COMPLETE' and len(fake.calls)==2
    assert all(p.read_bytes()==raw for p,raw in persisted.items())
    assert execute()['status']=='COMPLETE' and len(fake.calls)==2
    report=l.export(e.root,e.run,partial=True)
    assert report and len(fake.calls)==2
    summary=Ledger(e.run/'api-ledger.sqlite',settings['api']).summary()
    assert summary['calls']==2 and summary['reasoning_tokens']==40


def test_api_lifecycle_budget_exhaustion_exports_without_dispatch(environment,monkeypatch):
    e=environment;fake,factory,settings=prepare_api(e,monkeypatch,budget=.00000001)
    result=l.execute(e.root,e.run,client_factory=factory,ram=lambda:100000,sleep=lambda _:None)
    assert result['status']!='COMPLETE' and 'export' in result and not fake.calls
    assert Ledger(e.run/'api-ledger.sqlite',settings['api']).summary()['calls']==0
