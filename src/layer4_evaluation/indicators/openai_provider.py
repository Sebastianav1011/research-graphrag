"""Responses SDK transport at the existing provider seam; no network at import/inspect.

The normalized envelope is internal compatibility data, never a second evaluator.
Original Responses payload/usage/IDs are retained in native_response.json.
"""
from run_paths import file_path as run_file
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .selection import canonical_hash

ROOT=Path(__file__).resolve().parents[3]


def defaults(root=ROOT):
    return json.loads((Path(root)/'config/openai.json').read_text(encoding='utf-8'))


def cost(usage,settings):
    # output_tokens already includes reasoning; cached input charged conservatively
    # at standard input rate. Never add reasoning a second time.
    return (usage['input_tokens']*settings['input_usd_per_million']+
            usage['output_tokens']*settings['output_usd_per_million'])/1_000_000


class Ledger:
    def __init__(self,path,settings):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.settings=settings
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,project TEXT,state TEXT,reserved REAL,cost REAL,usage TEXT,response_id TEXT)')
            if 'attempts' not in {row[1] for row in db.execute('PRAGMA table_info(requests)')}:
                db.execute('ALTER TABLE requests ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0')

    def connect(self):
        db=sqlite3.connect(self.path,timeout=30);db.execute('PRAGMA synchronous=FULL');return db

    def reserve(self,key,project,amount):
        from .ollama_provider import OllamaError
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM requests WHERE id=?',(key,)).fetchone():raise OllamaError('UNCERTAIN_OUTCOME','Solicitud ya registrada; recuperar artefactos sin repetir')
            used=db.execute('SELECT COALESCE(SUM(COALESCE(cost,reserved)),0) FROM requests').fetchone()[0]
            active=db.execute("SELECT COUNT(*) FROM requests WHERE state='IN_FLIGHT'").fetchone()[0]
            if active>=self.settings['max_concurrency']:raise OllamaError('API_CONCURRENCY','Limite de solicitudes en curso')
            if used+amount>self.settings['budget_usd']:raise OllamaError('API_BUDGET','Reserva preventiva excede presupuesto; exportar parcial')
            db.execute('INSERT INTO requests(id,project,state,reserved) VALUES(?,?,?,?)',(key,project,'IN_FLIGHT',amount))

    def dispatched(self,key):
        with self.connect() as db:
            db.execute('UPDATE requests SET attempts=attempts+1 WHERE id=?',(key,))

    def finish(self,key,usage=None,response_id=None,known_rejection=False):
        with self.connect() as db:
            db.execute('UPDATE requests SET state=?,cost=?,usage=?,response_id=? WHERE id=?',
                ('REJECTED' if known_rejection else 'COMPLETED' if usage else 'UNCERTAIN',
                 0 if known_rejection else cost(usage,self.settings) if usage else None,
                 json.dumps(usage) if usage else None,response_id,key))

    def summary(self):
        with self.connect() as db:
            rows=db.execute('SELECT project,state,reserved,cost,usage,response_id,attempts FROM requests').fetchall()
        result=dict(provider='openai',model='gpt-6.1-terra',calls=sum(row[-1] for row in rows),requests=len(rows),input_tokens=0,output_tokens=0,
            reasoning_tokens=0,cached_tokens=0,estimated_cost_usd=0.,reserved_uncertain_usd=0.,projects={},
            token_details_reported_requests=dict(reasoning_tokens=0,cached_tokens=0),
            budget_usd=self.settings['budget_usd'],pricing=self.settings,remote_hardware='NOT_AVAILABLE')
        for project,state,reserved,spent,raw,_,attempts in rows:
            if spent is None:result['reserved_uncertain_usd']+=reserved
            else:
                result['estimated_cost_usd']+=spent
                result['projects'][project]=result['projects'].get(project,0)+spent
            for name,value in (json.loads(raw) if raw else {}).items():
                if name in ('input_tokens','output_tokens','reasoning_tokens','cached_tokens'):result[name]+=value or 0
                if name in result['token_details_reported_requests'] and type(value) is int:
                    result['token_details_reported_requests'][name]+=1
        for name,reported in result['token_details_reported_requests'].items():
            if rows and not reported:result[name]=None
        result['available_usd']=max(0,result['budget_usd']-result['estimated_cost_usd']-result['reserved_uncertain_usd'])
        return result


class OpenAIClient:
    def __init__(self,settings,sdk=None,root=ROOT):
        self.settings=settings;self.sdk=sdk;self.root=Path(root);self.directory=None

    def attach(self,directory):
        directory=Path(directory)
        self.directory=next((p for p in [directory,*directory.parents] if (run_file(p, 'model.binding.json')).exists()),directory)

    def inspect(self):
        from importlib.metadata import version,PackageNotFoundError
        try:sdk_version=version('openai')
        except PackageNotFoundError:sdk_version='NOT_INSTALLED'
        return dict(provider='openai',model=self.settings['model'],configuration=self.settings,
            configuration_sha256=canonical_hash(self.settings),digest='API_MODEL_ALIAS',server_version='Responses',
            sdk_version=sdk_version,quantization=None,think=None,template_bytes=0,model_metadata_sha256=canonical_hash({'model':self.settings['model']}))

    def request(self,method,path,payload=None):
        from .ollama_provider import OllamaError
        from model_access import api_key
        from autonomous_execution.store import write
        if self.directory is None:raise OllamaError('API_CONFIGURATION','Falta directorio de auditoria')
        key=api_key(self.root) if self.sdk is None else None
        if not key and self.sdk is None:raise OllamaError('API_KEY_MISSING','Configure credenciales antes de ejecutar')
        if self.sdk is None:
            try:
                from openai import OpenAI
                import logging
                # SDK debug logging can include request headers. Never expose credentials,
                # even if OPENAI_LOG or application-wide DEBUG has been configured.
                for name in ('openai','openai._base_client','httpx','httpcore'):
                    logging.getLogger(name).disabled=True
                self.sdk=OpenAI(api_key=key,base_url='https://api.openai.com/v1',
                    timeout=self.settings['timeout_seconds'],max_retries=0)
            except Exception:raise OllamaError('API_CONFIGURATION','Ejecute uv sync --locked y revise la configuracion local del SDK') from None
        api=self.settings['api'];ledger=Ledger(self.directory/'api-ledger.sqlite',api)
        # Use UTF-8 bytes as a conservative bound and reserve reasoning within max_output_tokens.
        input_bound=len(json.dumps(payload['messages'],ensure_ascii=False).encode())+len(json.dumps(payload['format']).encode())+2048
        amount=cost(dict(input_tokens=input_bound,output_tokens=self.settings['num_predict']),api)*api['safety_factor']
        schema=strict_schema(payload['format'])
        request=dict(model=self.settings['model'],input=payload['messages'],store=False,
            reasoning=dict(effort=api['reasoning_effort']),max_output_tokens=self.settings['num_predict'],
            text=dict(format=dict(type='json_schema',name='indicator_assessment',strict=True,schema=schema)))
        write(self.attempt/'responses.request.json',request)
        request_id=uuid.uuid4().hex
        ledger.reserve(request_id,self.project_id,amount)
        response=None;usage=None;rejected=False;remote_seconds=0.
        try:
            for attempt in range(api['max_rate_retries']+1):
                if (run_file(self.directory, 'stop.request.json')).exists():
                    rejected=True
                    raise OllamaError('STOP_REQUESTED','Detencion solicitada antes del envio')
                write(self.attempt/'api.dispatch.json',dict(id=request_id,attempt=attempt,state='IN_FLIGHT'))
                ledger.dispatched(request_id)
                started=time.perf_counter()
                try:
                    response=self.sdk.responses.create(**request)
                    remote_seconds+=time.perf_counter()-started
                    break
                except Exception as exc:
                    remote_seconds+=time.perf_counter()-started
                    status=getattr(exc,'status_code',None)
                    code=getattr(exc,'code',None)
                    if status==429 and code not in ('insufficient_quota','billing_hard_limit_reached') and attempt<api['max_rate_retries']:
                        time.sleep(min(30,api['retry_seconds']*2**attempt));continue
                    rejected=status in (400,401,403,404,429)
                    category=('API_AUTHENTICATION' if status==401 else 'API_PERMISSIONS' if status in (403,404) else
                        'API_BALANCE' if code in ('insufficient_quota','billing_hard_limit_reached') else
                        'API_RATE_LIMIT' if status==429 else 'API_SERVER_UNCERTAIN' if status and status>=500 else
                        'API_BAD_REQUEST' if status==400 else 'API_OUTCOME_UNCERTAIN')
                    raise OllamaError(category,'Solicitud API detenida; consultar recibo privado. No se conserva texto de excepciones del SDK') from None
            native=response.model_dump(mode='json')
            u=native.get('usage') or {}
            if all(type(u.get(k)) is int and u[k]>=0 for k in ('input_tokens','output_tokens')):
                usage=dict(input_tokens=u['input_tokens'],output_tokens=u['output_tokens'],
                    reasoning_tokens=(u.get('output_tokens_details') or {}).get('reasoning_tokens'),
                    cached_tokens=(u.get('input_tokens_details') or {}).get('cached_tokens'))
            write(self.attempt/'responses.response.json',native)
            if usage is None:raise OllamaError('API_OUTCOME_UNCERTAIN','Respuesta sin contadores verificables')
            text=response.output_text
            complete=native.get('status')=='completed'
            return dict(model=self.settings['model'],done=complete,done_reason='stop' if complete else 'incomplete',
                message=dict(content=text),prompt_eval_count=usage['input_tokens'],eval_count=usage['output_tokens'],
                api_usage=usage,api_response_id=native.get('id'),api_request_id=getattr(response,'_request_id',None),
                api_returned_model=native.get('model'),rate_limit_retries=attempt,
                estimated_cost_usd=cost(usage,api),remote_response_seconds=remote_seconds)
        except OllamaError:raise
        except Exception:raise OllamaError('API_OUTCOME_UNCERTAIN','Fallo de procesamiento API; conservar reserva y recibos') from None
        finally:
            ledger.finish(request_id,usage,getattr(response,'id',None),rejected)
            write(self.directory/'resultados/performance/openai_usage.json',ledger.summary())


def strict_schema(schema):
    """Make objects strict for Responses; the original schema is validated unchanged afterwards."""
    import copy
    result=copy.deepcopy(schema)
    def visit(value):
        if isinstance(value,dict):
            if value.get('type')=='object':
                value['additionalProperties']=False
                value['required']=list(value.get('properties',{}))
            for item in value.values():visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(result);return result
