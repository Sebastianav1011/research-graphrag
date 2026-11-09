"""Local HTTP transport for the existing assessment-provider interface.

Uses Ollama's documented /api/chat JSON Schema API, without proxies, redirects,
cloud models, downloads, tools, streaming or automatic inference retries.
"""
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
from pathlib import Path
import re
import socket
from urllib.parse import urlsplit
import uuid

from jsonschema import Draft202012Validator, ValidationError

from .contracts import validate_wrapper
from .performance import Measurement, span, record_call, measured_project
from .selection import canonical_hash
from .validation_diagnostics import AssessmentValidationError


DEFAULTS = dict(provider='ollama', model='qwen3.5:4b-q4_K_M',
                endpoint='http://127.0.0.1:11434', temperature=0, num_ctx=8192,
                num_predict=4096, token_limit_retries=2, max_predict=6144,
                timeout_seconds=600, keep_alive='5m', seed=0,
                context_margin_tokens=512, expected_quantization='Q4_K_M')


class OllamaError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(code + ': ' + message)


def configuration(value=None):
    if isinstance(value, dict) and value.get('provider') == 'openai':
        from .openai_provider import defaults
        api = defaults() | value.get('api', {})
        if set(api) - (set(defaults()) | {'budget_usd'}):raise ValueError('Parametro API desconocido')
        if value.get('model', 'gpt-6.1-terra') != 'gpt-6.1-terra':raise ValueError('Modelo API incompatible')
        if api['reasoning_effort'] not in ('low','medium','high'):raise ValueError('Razonamiento invalido')
        for key in ('max_concurrency','max_rate_retries','retry_seconds'):
            if type(api[key]) is not int or api[key] < (1 if key=='max_concurrency' else 0) or api[key]>30:raise ValueError('Limite API invalido')
        for key in ('input_usd_per_million','output_usd_per_million','safety_factor','budget_usd'):
            if key in api and (type(api[key]) not in (int,float) or not math.isfinite(api[key]) or api[key]<=0):raise ValueError('Costo/presupuesto API invalido')
        if api['safety_factor']<1:raise ValueError('Margen API debe ser >= 1')
        # Reuse the established GraphRAG context/output limits, without local model controls.
        allowed=set(DEFAULTS)|{'api'}
        if set(value)-allowed:raise ValueError('Parametro LLM desconocido')
        local={k:v for k,v in value.items() if k not in ('provider','model','api')}
        result=configuration(local)
        return result | dict(provider='openai',model='gpt-6.1-terra',api=api,expected_quantization=None)
    if value is not None and not isinstance(value, dict):
        raise ValueError('llm debe ser un objeto de configuracion')
    if set(value or {}) - set(DEFAULTS):
        raise ValueError('Parametros llm desconocidos: ' + ', '.join(sorted(set(value) - set(DEFAULTS))))
    result = DEFAULTS | (value or {})
    if result['provider'] != 'ollama':
        raise ValueError('Solo Ollama local esta habilitado para nuevas inferencias')
    url = urlsplit(result['endpoint'])
    if (url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1', '::1')
            or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment):
        raise ValueError('Endpoint Ollama debe ser HTTP en localhost, sin credenciales, rutas ni redirecciones')
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError('Puerto Ollama invalido')
    if not isinstance(result['model'], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]+', result['model']) or 'cloud' in result['model'].lower():
        raise ValueError('Configurar un nombre de modelo local, sin rutas o sufijos cloud')
    for key in ('num_ctx', 'num_predict', 'timeout_seconds', 'context_margin_tokens'):
        if type(result[key]) is not int or result[key] <= 0:
            raise ValueError('llm.' + key + ' debe ser un entero positivo')
    if result['num_predict'] + result['context_margin_tokens'] >= result['num_ctx']:
        raise ValueError('Contexto insuficiente para generacion y margen de plantilla')
    if type(result['token_limit_retries']) is not int or not 0 <= result['token_limit_retries'] <= 2:
        raise ValueError('Se permiten como maximo dos reintentos por limite de tokens')
    if type(result['max_predict']) is not int or result['max_predict'] <= 0:
        raise ValueError('max_predict debe ser un entero positivo')
    if type(result['seed']) is not int:
        raise ValueError('llm.seed debe ser entero')
    temp = result['temperature']
    if type(temp) not in (int, float) or not math.isfinite(temp) or not 0 <= temp <= 2:
        raise ValueError('Temperatura Ollama invalida')
    if not isinstance(result['keep_alive'], str) or not re.fullmatch(r'\d+(?:s|m|h)?', result['keep_alive']):
        raise ValueError('keep_alive debe ser una duracion local, por ejemplo 5m o 0')
    if result['expected_quantization'] is not None and not isinstance(result['expected_quantization'], str):
        raise ValueError('Cuantizacion esperada invalida')
    return result


def strict_json(text):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError('Clave JSON duplicada')
            obj[key] = value
        return obj
    def constant(value):
        raise ValueError('Constante JSON no admitida')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def context_guard(prompt, schema, settings, runtime=None, budget=None):
    if budget is not None:
        from .context_budget import estimate
        actual = estimate(prompt, schema, settings,tokenizer=budget.get('tokenizer'))
        if budget.get('tokenizer') and runtime:
            descriptor=budget['tokenizer']
            if any(descriptor[k]!=runtime[k] for k in ('model_metadata_sha256',)) or descriptor['model_digest']!=runtime['digest']:
                raise OllamaError('RUNTIME_DRIFT','Tokenizer y plantilla no corresponden al modelo calibrado')
        if actual != budget:
            raise OllamaError('CONTEXT_BUDGET_MISMATCH', 'Prompt, esquema o configuracion difieren de la revision presupuestada')
        template_allowance = math.ceil((runtime or {}).get('template_bytes', 0) / 3) + 256
        if not actual['fits'] or template_allowance > settings['context_margin_tokens']:
            raise OllamaError('CONTEXT_TOO_LONG',
                f'Estimacion aproximada de entrada: {actual["estimated_input_tokens"]}; presupuesto {actual["input_budget"]}. '
                'Sin envio ni truncamiento. Revisar seleccion/configuracion y autorizar otra revision.')
        return actual['estimated_input_tokens'] + settings['num_predict'] + settings['context_margin_tokens']
    # Conservative bound for Qwen's byte-level tokenizer and template overhead.
    # The schema constrains decoding and is not appended to the immutable prompt.
    # This is deliberately NOT an exact token count. A
    # rejected request is never shortened or sent with a larger context implicitly.
    upper = len(prompt.encode('utf-8'))
    margin = max(settings['context_margin_tokens'], (runtime or {}).get('template_bytes', 0) + 256)
    upper += margin + settings['num_predict']
    if upper > settings['num_ctx']:
        raise OllamaError('CONTEXT_TOO_LONG',
            f'Estimacion conservadora (no tokenizacion exacta): {upper} tokens frente a num_ctx={settings["num_ctx"]}. '
            'No se envio ni trunco texto. Revisar contexto y memoria; una configuracion distinta requiere otra revision autorizada.')
    return upper


def server_error(status, message):
    lowered = message.lower()
    if any(word in lowered for word in ('out of memory', 'not enough memory', 'unable to allocate', 'cuda error')):
        return OllamaError('OUT_OF_MEMORY', 'Ollama no dispone de memoria. Liberar VRAM/RAM y revisar num_ctx; no se reintenta automaticamente.')
    if any(word in lowered for word in ('context length', 'context window', 'too long', 'input length')):
        return OllamaError('CONTEXT_TOO_LONG', 'Ollama rechazo la longitud de entrada; no se trunca el documento.')
    if status == 404:
        return OllamaError('MODEL_NOT_INSTALLED', 'Modelo o API no disponible. Comprobar ollama list y actualizar Ollama; descargar el modelo manualmente.')
    return OllamaError('SERVER_ERROR', f'Ollama devolvio HTTP {status}. Revisar el servidor local; no hay fallback ni reintento automatico.')


class OllamaClient:
    """Minimal documented HTTP client; constructor never contacts the server."""
    def __init__(self, settings=None):
        self.settings = configuration(settings)
        self.url = urlsplit(self.settings['endpoint'])

    def request(self, method, path, payload=None):
        if (method, path) not in {('GET', '/api/version'), ('GET', '/api/tags'), ('POST', '/api/show'), ('POST', '/api/chat')}:
            raise ValueError('Operacion Ollama no autorizada')
        # http.client does not consult HTTP_PROXY or follow redirects. Resolve the
        # literal localhost alias ourselves, avoiding a configurable remote host.
        host = '127.0.0.1' if self.url.hostname == 'localhost' else self.url.hostname
        connection = http.client.HTTPConnection(host, self.url.port or 11434, timeout=self.settings['timeout_seconds'])
        try:
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
            connection.request(method, path, body=body, headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            data = response.read(32 * 1024 * 1024 + 1)
            if len(data) > 32 * 1024 * 1024:
                raise OllamaError('INVALID_RESPONSE', 'Respuesta Ollama excede el limite local permitido')
            try:
                value = strict_json(data.decode('utf-8'))
            except (ValueError, UnicodeError):
                raise OllamaError('INVALID_RESPONSE', 'El servidor no devolvio JSON valido') from None
            if response.status != 200:
                raise server_error(response.status, str(value.get('error', '')) if isinstance(value, dict) else '')
            if not isinstance(value, dict) or value.get('error'):
                raise server_error(response.status, str(value.get('error', '')) if isinstance(value, dict) else '')
            return value
        except (TimeoutError, socket.timeout):
            raise OllamaError('TIMEOUT', 'Ollama excedio el timeout. Conservar el checkpoint; no repetir una llamada de resultado incierto.') from None
        except (OSError, http.client.HTTPException):
            raise OllamaError('SERVER_UNAVAILABLE', 'Ollama local no disponible. Iniciar Ollama (ollama serve) y comprobar el endpoint configurado.') from None
        finally:
            connection.close()

    def inspect(self):
        version = self.request('GET', '/api/version').get('version')
        tags = self.request('GET', '/api/tags').get('models', [])
        model = next((item for item in tags if item.get('name') == self.settings['model'] or item.get('model') == self.settings['model']), None)
        if not model:
            raise OllamaError('MODEL_NOT_INSTALLED', 'Modelo exacto ausente. Ejecutar manualmente ollama pull ' + self.settings['model'])
        info = self.request('POST', '/api/show', {'model': self.settings['model']})
        if any(obj.get(key) for obj in (model, info) for key in ('remote_host', 'remote_model')):
            raise OllamaError('REMOTE_MODEL_BLOCKED', 'El modelo referencia un proveedor cloud; solo se permiten pesos locales')
        details = info.get('details', model.get('details', {}))
        if not model.get('digest') or not version or details.get('format') != 'gguf':
            raise OllamaError('INVALID_MODEL_METADATA', 'Se requieren version Ollama, digest y pesos GGUF locales verificables')
        expected = self.settings['expected_quantization']
        if expected and details.get('quantization_level') != expected:
            raise OllamaError('MODEL_MISMATCH', 'La cuantizacion instalada no coincide con la configurada')
        model_info = info.get('model_info', {})
        maximum = model_info.get(str(model_info.get('general.architecture', '')) + '.context_length')
        if type(maximum) is int and self.settings['num_ctx'] > maximum:
            raise OllamaError('CONTEXT_TOO_LONG', 'num_ctx supera el contexto declarado por el modelo instalado')
        controls = info.get('thinking', {}).get('values', [])
        # Older servers advertise the boolean thinking capability without values.
        no_thinking = any(value is False for value in controls) or (not controls and 'thinking' in info.get('capabilities', []))
        return dict(provider='ollama', model=self.settings['model'], digest=model['digest'], server_version=version,
                    configuration=self.settings, configuration_sha256=canonical_hash(self.settings),
                    quantization=details.get('quantization_level'), capabilities=info.get('capabilities', []),
                    think=False if no_thinking else None,
                    template_bytes=len((info.get('template', '') + info.get('system', '')).encode('utf-8')),
                    model_metadata_sha256=canonical_hash(info))


def create_client(settings):
    if settings.get('provider') == 'openai':
        from .openai_provider import OpenAIClient
        return OpenAIClient(settings)
    return OllamaClient(settings)


class OllamaAssessmentProvider:
    """Drop-in evaluate(project, indicators), calls/raw_outputs/last_output contract."""
    def __init__(self, run_directory, schema_path, input_factory, *, settings=None, client=None,
                 runtime=None, timeout=None, model=None, max_retries=0, max_indicators=3,
                 wrapper_validator=None, execution_id=None, stop_on_uncertain=True, output_adapter=None,
                 token_limit_retries=0):
        options = dict(settings or {})
        if timeout is not None:
            options['timeout_seconds'] = timeout
        if model is not None:
            options['model'] = model
        self.settings = configuration(options)
        if type(token_limit_retries) is not int or not 0 <= token_limit_retries <= self.settings['token_limit_retries']:
            raise ValueError('Reintentos de salida fuera de la configuracion')
        self.token_limit_retries = token_limit_retries
        if max_retries != 0 or max_indicators not in (1, 2, 3, 5) or not stop_on_uncertain:
            raise ValueError('Ollama requiere ejecucion secuencial sin reintentos automaticos')
        self.directory, self.schema = Path(run_directory), Path(schema_path)
        self.input_factory, self.client = input_factory, client or create_client(self.settings)
        self.runtime, self.max_indicators = runtime, max_indicators
        self.wrapper_validator = wrapper_validator or validate_wrapper
        self.output_adapter = output_adapter
        self.execution_id = execution_id or uuid.uuid4().hex
        self.calls, self.raw_outputs, self.last_output = [], [], None

    @measured_project
    def evaluate(self, project, indicators):
        # Retries are explicitly enabled by the live run plan. Other callers keep
        # their existing outer retry policy and do not multiply inference calls.
        retries = self.token_limit_retries
        output = self.settings['num_predict']
        for attempt in range(retries + 1):
            try:
                return self._evaluate_once(project, indicators, attempt=attempt, output=output)
            except OllamaError as exc:
                if exc.code != 'TOKEN_LIMIT' or attempt == retries:
                    raise
                budget = self.calls[-1].get('context_budget')
                input_tokens = (budget['estimated_input_tokens'] if budget else
                    len(self.input_factory(project, indicators)['prompt'].encode('utf-8')))
                observed = self.calls[-1]['usage_observations'][0].get('input_tokens')
                if type(observed) is int:
                    input_tokens = max(input_tokens, observed)
                available = self.settings['num_ctx'] - self.settings['context_margin_tokens'] - input_tokens
                ceiling = min(max(output, self.settings['max_predict']), available)
                if ceiling > output:
                    output = min(output * 2, ceiling)

    def _evaluate_once(self, project, indicators, *, attempt=0, output=None):
        self.last_output = None
        if not 1 <= len(indicators) <= self.max_indicators or not re.fullmatch(r'[A-Za-z0-9_-]+', project['project_id']):
            raise ValueError('Identificador de proyecto o lote invalido')
        request = self.input_factory(project, indicators)
        prompt = request['prompt']
        schema = strict_json(self.schema.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        if hasattr(self.client, 'attach'):
            self.client.attach(self.directory)
            self.client.project_id = project['project_id']
        runtime = self.runtime or self.client.inspect()
        if runtime['configuration'] != self.settings:
            raise OllamaError('RUNTIME_DRIFT', 'Modelo, digest, servidor o configuracion distintos del checkpoint; no se reutiliza otra version')
        generation = self.settings | dict(num_predict=output or self.settings['num_predict'])
        budget = request.get('context_budget')
        if budget and generation != self.settings:
            from .context_budget import estimate
            budget = estimate(prompt, schema, generation, tokenizer=budget.get('tokenizer'))
        context_guard(prompt, schema, generation, runtime, budget)
        payload = dict(model=self.settings['model'], messages=[dict(role='user', content=prompt)], format=schema,
                       stream=False, truncate=False, shift=False, keep_alive=self.settings['keep_alive'],
                       options={key: generation[key] for key in ('temperature', 'num_ctx', 'num_predict', 'seed')})
        if runtime['think'] is not None:
            payload['think'] = runtime['think']
        cwd = self.directory / project['project_id'] / ('attempt_' + str(attempt + 1))
        cwd.mkdir(parents=True, exist_ok=False)
        if hasattr(self.client, 'attach'):self.client.attempt = cwd
        (cwd / 'prompt.txt').write_text(prompt, encoding='utf-8')
        def save(name, value):
            (cwd / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        save('request.json', payload)
        started = datetime.now(timezone.utc).isoformat()
        error, native, raw, issues, validation_stage = None, {}, '', [], 'transport'
        measurement = Measurement()
        try:
            with span('inferencia'), measurement:
                native = self.client.request('POST', '/api/chat', payload)
            save('native_response.json', native)
            raw = native.get('message', {}).get('content', '')
            (cwd / 'response.raw.txt').write_text(raw if isinstance(raw, str) else '', encoding='utf-8')
            if native.get('done_reason') == 'length' or (type(native.get('eval_count')) is int and native['eval_count'] >= generation['num_predict']):
                raise OllamaError('TOKEN_LIMIT', 'Limite de salida alcanzado; respuesta incompleta no aceptada')
            if native.get('done') is not True or native.get('done_reason') != 'stop':
                raise OllamaError('INCOMPLETE_RESPONSE', 'Generacion incompleta o limite de tokens alcanzado; no es NOT_SUPPORTED')
            if native.get('model') != self.settings['model'] or native.get('message', {}).get('tool_calls'):
                raise OllamaError('INVALID_RESPONSE', 'Modelo de respuesta distinto o solicitud de herramientas no permitida')
            for key in ('prompt_eval_count', 'eval_count'):
                if type(native.get(key)) is not int or native[key] < 0:
                    raise OllamaError('MISSING_METRICS', 'Faltan conteos reales de tokens de Ollama')
            if native['prompt_eval_count'] + native['eval_count'] >= self.settings['num_ctx']:
                raise OllamaError('CONTEXT_EXHAUSTED', 'Se alcanzo la ventana de contexto; no se acepta una posible entrada truncada')
            if budget and native['prompt_eval_count'] > budget['input_budget']:
                raise OllamaError('CONTEXT_EXHAUSTED', 'El conteo real de entrada supera el presupuesto estimado revisado; respuesta no aceptada. Requiere revisar contexto/configuracion, nunca asignar NOT_SUPPORTED')
            if self.client.inspect() != runtime:
                raise OllamaError('RUNTIME_DRIFT', 'El modelo o servidor cambio durante la llamada')
            validation_stage = 'json'
            parsed = strict_json(raw)
            validation_stage = 'schema'
            Draft202012Validator(schema).validate(parsed)
            validation_stage = 'semantic'
            self.wrapper_validator(parsed, project['project_id'], [i['indicator_id'] for i in indicators])
            save('response.json', parsed)
            self.last_output = parsed
        except OllamaError as exc:
            error = exc
        except AssessmentValidationError as exc:
            issues = exc.issues
            error = OllamaError('INVALID_ASSESSMENT', str(exc))
        except ValidationError as exc:
            issues = [dict(category='INVALID_FIELD_VALUE', path='$' + ''.join(
                f'[{p}]' if isinstance(p, int) else '.' + p for p in exc.absolute_path), rule=str(exc.validator))]
            if exc.validator == 'required' and isinstance(exc.instance, dict):
                missing = [key for key in exc.validator_value if key not in exc.instance]
                issues[0]['missing_fields'] = missing
                if len(missing) == 1:
                    issues[0]['path'] += '.' + missing[0]
            error = OllamaError('INVALID_ASSESSMENT', 'Campo o valor invalido: ' + issues[0]['path'] + '; regla=' + str(exc.validator))
        except (ValueError, TypeError):
            category = 'INVALID_JSON' if validation_stage == 'json' else 'INTERNAL_VALIDATION_ERROR'
            issues = [dict(category=category, path='$', rule=validation_stage)]
            error = OllamaError('INVALID_ASSESSMENT', category + '; etapa=' + validation_stage)
        except KeyboardInterrupt:
            error = OllamaError('INTERRUPTED', 'Llamada interrumpida: conservar claim y verificar antes de continuar')
            raise
        except Exception:
            issues = [dict(category='INTERNAL_VALIDATION_ERROR', path='$', rule=validation_stage)]
            error = OllamaError('INFERENCE_ERROR', 'Fallo tecnico de inferencia; consultar los artefactos privados, sin reintento automatico')
        finally:
            # Never print the prompt, response, reasoning or server error text.
            save('validation.json', dict(stage=validation_stage, issues=issues))
            (cwd / 'events.jsonl').write_text(json.dumps(dict(provider=self.settings['provider'], done=native.get('done'), error=error.code if error else None, validation_issues=issues)) + '\n', encoding='utf-8')
            (cwd / 'stderr.txt').write_text(str(error) if error else '', encoding='utf-8')
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            call = dict(project_id=project['project_id'], call_number=len(self.calls)+1, retry=attempt,
                generation_options=payload['options'],
                execution_id=self.execution_id, provider=self.settings['provider'], runtime=runtime,
                requested_model=self.settings['model'], timestamp=started, finished_at=datetime.now(timezone.utc).isoformat(),
                successful_transport=error is None, technical_error=str(error) if error else None,
                exit_status=0 if error is None else error.code, performance=getattr(measurement, 'result', {}),
                timeout_seconds=self.settings['timeout_seconds'], prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                schema_sha256=digest(self.schema), response_sha256=digest(cwd/'response.json') if (cwd/'response.json').exists() else None,
                events_sha256=digest(cwd/'events.jsonl'), stderr_sha256=digest(cwd/'stderr.txt'),
                working_directory=cwd.relative_to(self.directory.parent).as_posix(),
                usage_observations=[dict(input_tokens=native.get('prompt_eval_count'), output_tokens=native.get('eval_count'))],
                usage_source='OLLAMA_HTTP_PROMPT_EVAL_COUNT_AND_EVAL_COUNT',
                ollama_durations_ns={key:native.get(key) if type(native.get(key)) is int and native[key]>=0 else None
                    for key in ('total_duration','load_duration','prompt_eval_duration','eval_duration')},
                model_observations=[dict(model=self.settings['model'], digest=runtime['digest'], provider=self.settings['provider'])])
            if self.settings['provider'] == 'openai':
                call.update(usage_source='OPENAI_RESPONSES_USAGE',api_usage=native.get('api_usage'),
                    api_response_id=native.get('api_response_id'),api_request_id=native.get('api_request_id'),
                    api_returned_model=native.get('api_returned_model'),rate_limit_retries=native.get('rate_limit_retries'),
                    estimated_cost_usd=native.get('estimated_cost_usd'),remote_response_seconds=native.get('remote_response_seconds'),
                    remote_hardware='NOT_AVAILABLE',local_hardware_scope='LOCAL_PIPELINE_ONLY')
            if budget:
                call['context_budget'] = budget
            call['validation_issues'] = issues
            save('call.json', call)
            record_call(call, cwd/'call.json')
            self.calls.append(call)
            self.raw_outputs.append(dict(raw_output=raw, technical_error=str(error) if error else None))
        if error:
            raise error
        output = self.output_adapter(self.last_output) if self.output_adapter else self.last_output
        by_id = {item['indicator_id']:item for item in output['assessments']}
        return [dict(indicator_id=indicator['indicator_id'],
            assessment={k:v for k,v in by_id[indicator['indicator_id']].items() if k!='indicator_id'}) for indicator in indicators]
