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


CORRECTION_VERSION = 'LITERAL_GRAPH_EVIDENCE_V1'
CORRECTION = '''
CORRECTIVE_JSON_RULES:
evidence.text: copia LITERAL continua de project.fields[evidence.field] del INPUT_JSON,
solo del fragmento enviado; no reformules ni inventes.
evidence_indices: posiciones 0..len(evidence)-1 de TU array, nunca IDs de fragmentos.
NOT_SUPPORTED: todos NOT_DEMONSTRATED, strength=0. Apoyo parcial: INSUFFICIENT_EVIDENCE.
Respeta IDs y temporalidad de rubrica. Devuelve JSON completo corregido.
'''


# Targeted correction for reference transport. The previous protocol only named
# the failed rule, so the model re-judged every criterion blind and discarded
# valid partial evidence. V2 names the exact fields, shows the previous
# judgments (from the persisted selection.json) and asks to fix only them.
TARGETED_CORRECTION_VERSION = 'TARGETED_REFERENCE_CORRECTION_V2'
TARGETED_CORRECTION = '''REFERENCE_CORRECTION_V2:
Tu respuesta anterior fue rechazada SOLO por las inconsistencias de ERRORES; no es un juicio sobre la evidencia.
RESPUESTA_ANTERIOR resume tus juicios previos (referencias en formato fragment_id:stage).
Corrige unicamente los campos senalados y la decision o fuerza que dependan de ellos. Conserva los
demas criterios con su support, coverage, evidence_refs y razonamiento.
No subas coverage ni conviertas un criterio en CLEAR para cuadrar el JSON: si el respaldo que justificaste
es menor, baja support o coverage. Puedes reducir el soporte de un criterio senalado solo si su fragmento no
respalda lo afirmado, explicando por que. No elimines referencias validas para evitar el error.
evidence_refs usa objetos {fragment_id,stage}, nunca indices ni citas. Devuelve el JSON completo.
'''
TARGETED_RULES = {
    'SK_CRITERION:COVERAGE_SUPPORT_MISMATCH': 'support y coverage deben concordar: NOT_DEMONSTRATED=0; '
        'PARTIAL=1, 2 o 3; CLEAR=4. Si la cobertura justificada es menor que 4, usa PARTIAL con esa cobertura.',
    'SK_STRENGTH:ZERO_ANCHOR_MISMATCH': 'support_strength=0 si y solo si las cuatro dimensiones de strength_rubric '
        'son 0. Con criterios PARTIAL/CLEAR referenciados usa valores positivos; sin ninguno, todo en 0.',
    'SK_STRENGTH:POSITIVE_REQUIRES_EVIDENCE': 'Dimensiones de fuerza positivas exigen strength_rubric.evidence_refs '
        'tomadas de criterios PARTIAL/CLEAR; sin criterios positivos, las dimensiones deben ser 0.',
    'V3_POSITIVE_STRENGTH:REQUIRES_EVIDENCE': 'support_strength>0 exige algun criterio PARTIAL/CLEAR con evidence_refs; '
        'si ningun criterio tiene respaldo, support_strength=0.',
    'SK_STRENGTH:UNVERIFIABLE_CRITERION_REFERENCE': 'strength_rubric.evidence_refs solo repite referencias '
        'de criterios PARTIAL/CLEAR.',
    'V3_CRITERION:UNSUPPORTED_CANNOT_CLAIM_EVIDENCE': 'NOT_DEMONSTRATED exige evidence_refs=[]. Resuelve la '
        'contradiccion con tu juicio: si esas referencias no respaldan el criterio, conserva NOT_DEMONSTRATED y vacialas; '
        'si lo respaldan parcialmente, usa PARTIAL con coverage 1..3 y solo esas referencias. Nunca CLEAR ni referencias nuevas.',
    'TARGETED_CORRECTION:UNFLAGGED_CRITERION_CHANGED': 'Ese criterio no tenia error: restaura exactamente su '
        'support, coverage y evidence_refs de RESPUESTA_ANTERIOR.',
    'TARGETED_CORRECTION:FLAGGED_CRITERION_INCREASED': 'Al corregir no puedes aumentar support ni coverage '
        'respecto de RESPUESTA_ANTERIOR; si no concuerdan, baja el que exceda tu justificacion.',
}
TARGETED_DETAIL_KEYS = ('category', 'path', 'rule', 'criterion_id', 'criterion_ids', 'support', 'coverage',
    'allowed_coverage', 'previous_support', 'previous_coverage', 'support_strength', 'strength_total',
    'positive_criterion_ids', 'evidence_indices', 'evidence_count', 'temporal_requirement', 'observed_stages',
    'missing_fields')
SUPPORT_ORDER = {'NOT_DEMONSTRATED': 0, 'PARTIAL': 1, 'CLEAR': 2}


def correction_scope(baseline, issues):
    """Criterion IDs a targeted correction may lower; None leaves the attempt unrestricted.

    Restricted only when every criterion-level error names its criterion. Global
    errors (strength, decision) leave all criteria fixed: the first complete
    judgment stands and only the dependent decision/strength may change.
    """
    if not isinstance(baseline, dict) or not baseline.get('assessments'):
        return None
    criteria = baseline['assessments'][0].get('criterion_assessments', [])
    flagged = set()
    for issue in issues or []:
        rule = issue.get('rule', '')
        if issue.get('category') in ('INVALID_JSON', 'INTERNAL_VALIDATION_ERROR') or rule.startswith('V3_CRITERIA:'):
            return None
        ids = [issue['criterion_id']] if issue.get('criterion_id') else list(issue.get('criterion_ids') or [])
        match = re.match(r'\$\.criterion_assessments\[(\d+)\]', issue.get('path', ''))
        if match and int(match[1]) < len(criteria):
            ids.append(criteria[int(match[1])].get('criterion_id'))
        if not ids and rule.startswith(('V3_CRITERION:', 'SK_CRITERION:')):
            return None
        flagged.update(ids)
    return sorted(flagged)


def scope_issues(baseline, flagged, selection):
    """Deterministic correction contract checked against the persisted first judgment."""
    if flagged is None:
        return []
    previous = {c['criterion_id']: c for c in baseline['assessments'][0]['criterion_assessments']}
    refs = lambda c: sorted((r['fragment_id'], r['stage']) for r in c.get('evidence_refs', []))
    issues = []
    for index, item in enumerate(selection['assessments'][0]['criterion_assessments']):
        before = previous.get(item['criterion_id'])
        if before is None:
            continue
        detail = dict(category='INVALID_FIELD_VALUE', path=f'$.criterion_assessments[{index}]',
            criterion_id=item['criterion_id'], support=item['support'], coverage=item.get('coverage'),
            previous_support=before['support'], previous_coverage=before.get('coverage'))
        if item['criterion_id'] in flagged:
            # NOT_DEMONSTRATED with its own references is an internal contradiction
            # with two legitimate readings: keep ND (empty refs) or PARTIAL 1..3
            # restricted to those same references. Never CLEAR, never new refs.
            contradictory = before['support'] == 'NOT_DEMONSTRATED' and before.get('evidence_refs')
            bounded_partial = (contradictory and item['support'] == 'PARTIAL' and 1 <= (item.get('coverage') or 0) <= 3
                               and item.get('evidence_refs') and set(refs(item)) <= set(refs(before)))
            if not bounded_partial and (SUPPORT_ORDER[item['support']] > SUPPORT_ORDER[before['support']] or
                    (item.get('coverage') or 0) > (before.get('coverage') or 0)):
                issues.append(dict(detail, rule='TARGETED_CORRECTION:FLAGGED_CRITERION_INCREASED'))
        elif (item['support'], item.get('coverage'), refs(item)) != (before['support'], before.get('coverage'), refs(before)):
            issues.append(dict(detail, rule='TARGETED_CORRECTION:UNFLAGGED_CRITERION_CHANGED'))
    return issues


def previous_judgments(selection, flagged=(), explanations=True):
    """Compact, deterministic summary of the model's own previous reference selection."""
    if not isinstance(selection, dict) or not selection.get('assessments'):
        return None
    item = selection['assessments'][0]
    refs = lambda values: [f"{r.get('fragment_id')}:{r.get('stage')}" for r in values or []]
    criteria = []
    for c in item.get('criterion_assessments', []):
        entry = dict(criterion_id=c.get('criterion_id'), support=c.get('support'),
                     coverage=c.get('coverage'), evidence_refs=refs(c.get('evidence_refs')))
        if explanations and c.get('criterion_id') in flagged:
            entry['explanation'] = (c.get('explanation') or '')[:300]
        criteria.append(entry)
    strength = item.get('strength_rubric') or {}
    return dict(decision=item.get('decision'), support_strength=item.get('support_strength'),
        criteria=criteria, strength_rubric=dict({k: strength.get(k) for k in
            ('directness', 'specificity', 'clarity', 'temporal_alignment')}, evidence_refs=refs(strength.get('evidence_refs'))))


def targeted_scope(attempt_directories, attempt_issues):
    """(first persisted selection, flagged criteria, whether a global field was flagged)."""
    for directory, issues in zip(attempt_directories, attempt_issues):
        path = Path(directory) / 'selection.json'
        if path.exists():
            baseline = strict_json(path.read_text(encoding='utf-8'))
            return baseline, correction_scope(baseline, issues), has_global_issue(baseline, issues)
    return None, None, None


def targeted_baseline(attempt_directories, attempt_issues):
    """(first persisted selection, its correction scope) for one evaluation's attempts."""
    return targeted_scope(attempt_directories, attempt_issues)[:2]


# TARGETED_REFERENCE_CORRECTION_V3_CRITERION_MERGE. Same corrective prompt as V2,
# but the accepted assessment keeps every unflagged criterion of the first
# judgment and takes only the flagged criteria from the corrective answer. The
# global fields come from the first judgment when they were not flagged and the
# merge validates, otherwise from the corrective answer. Every value comes from
# one of the model's own outputs; origins are written to repair.json and the
# full assessment is revalidated with the unchanged rules.
MERGE_CORRECTION_VERSION = 'TARGETED_REFERENCE_CORRECTION_V3_CRITERION_MERGE'
TARGETED_VERSIONS = (TARGETED_CORRECTION_VERSION, MERGE_CORRECTION_VERSION)
GLOBAL_FIELDS = ('decision', 'support_strength', 'strength_rubric', 'explanation')


def has_global_issue(baseline, issues):
    criteria = baseline['assessments'][0].get('criterion_assessments', [])
    for issue in issues or []:
        match = re.match(r'\$\.criterion_assessments\[(\d+)\]', issue.get('path', ''))
        if not (issue.get('criterion_id') or issue.get('criterion_ids') or (match and int(match[1]) < len(criteria))):
            return True
    return False


def merge_candidates(baseline, flagged, has_global, selection):
    from copy import deepcopy
    first, answer = baseline['assessments'][0], selection['assessments'][0]
    corrected = {c['criterion_id']: c for c in answer['criterion_assessments']}
    criteria, origin = [], {}
    for item in first['criterion_assessments']:
        cid = item['criterion_id']
        criteria.append(deepcopy(corrected[cid] if cid in flagged else item))
        origin[cid] = 'correction' if cid in flagged else 'first_judgment'
    for source in (('correction',) if has_global else ('first_judgment', 'correction')):
        item = deepcopy(answer)
        origin_item = answer if source == 'correction' else first
        for key in GLOBAL_FIELDS:
            if key in origin_item:  # strength_rubric exists only in SK assessments
                item[key] = deepcopy(origin_item[key])
        item['criterion_assessments'] = deepcopy(criteria)
        yield (dict(selection, assessments=[item]),
               dict(criteria_origin=origin, global_fields_origin=source, flagged=sorted(flagged)))


def merged_attempt(baseline, flagged, has_global, selection, request, validator):
    """Accepted (wrapper, provenance) for a criterion merge; raises when nothing coherent exists."""
    from .evidence_references import materialize
    scoped = [i for i in scope_issues(baseline, flagged, selection)
              if i['rule'] != 'TARGETED_CORRECTION:UNFLAGGED_CRITERION_CHANGED']
    if scoped:
        raise AssessmentValidationError(scoped)
    last = None
    for candidate, provenance in merge_candidates(baseline, flagged, has_global, selection):
        try:
            wrapper = materialize(request, candidate)
            validator(wrapper)
            return wrapper, dict(version=MERGE_CORRECTION_VERSION, **provenance)
        except AssessmentValidationError as exc:
            last = exc
    raise last


def _targeted_prompt(prefix, marker, payload, issues, previous, schema, settings, budget):
    from .context_budget import rebudget
    details = []
    for issue in issues or []:
        detail = {k: issue[k] for k in TARGETED_DETAIL_KEYS if k in issue}
        if 'path' in detail:
            detail['path'] = detail['path'].replace('.evidence_indices', '.evidence_refs')
        details.append(detail)
    rules = {d['rule']: TARGETED_RULES[d['rule']] for d in details if d.get('rule') in TARGETED_RULES}
    flagged = {d['criterion_id'] for d in details if 'criterion_id' in d}
    ladder = [(len(details), True), (len(details), False)]
    ladder += [(count, False) for count in range(len(details) - 1, 0, -1)]
    ladder += [(len(details), None), (max(len(details), 1), None)]
    prompt = None
    for count, explain in ladder:
        summary = previous_judgments(previous, flagged, explain) if explain is not None else None
        prompt = (prefix + '\n' + TARGETED_CORRECTION + 'ERRORES: '
            + json.dumps(details[:count], ensure_ascii=False, separators=(',', ':'))
            + (f'\nOtros errores pendientes: {len(details)-count}' if count < len(details) else '')
            + ('\nREGLAS: ' + json.dumps(rules, ensure_ascii=False, separators=(',', ':')) if rules else '')
            + ('\nRESPUESTA_ANTERIOR: ' + json.dumps(summary, ensure_ascii=False, separators=(',', ':')) if summary else '')
            + '\n' + marker + payload)
        if rebudget(prompt, schema, settings, budget)['fits']:
            break
    return prompt


def corrective_request(request, schema, settings, issues=None, previous=None, version=None):
    """Keep the exact evidence payload; budget and fingerprint the actual prompt."""
    from .context_budget import rebudget
    revised = dict(request)
    prefix, marker, payload = request['prompt'].partition('INPUT_JSON:\n')
    if not marker:
        raise ValueError('Solicitud correctiva sin INPUT_JSON')
    prefix = prefix.split('\nCORRECTIVE_JSON_RULES:\n', 1)[0]
    from . import prospective_v2 as p2, assessment_v3 as v3
    if version==p2.CORRECTION:
        if request.get('assessment_version')!=p2.VERSION:
            raise ValueError('Correccion prospectiva V2 con contrato incompatible')
        # Always rebuild from immutable evidence, never append responses or
        # narratives. Full semantic rejudgment is allowed; every original gate
        # still applies. The previous invalid judgment is not an upper bound.
        details=[{k:i[k] for k in ('rule','path','criterion_id') if k in i} for i in issues or []]
        correction=('\nCorrige la respuesta completa. No ajustes juicios para obtener una decision prefijada. '
            'Reevalua criterios y aplicabilidad desde las mismas citas. IDs exactos, evidence_refs={fragment_id,stage}; '
            'NOT_DEMONSTRATED sin referencias; CLEAR=4, PARTIAL=1..3, NOT_DEMONSTRATED=0. '
            'Fuerza referencia solo criterios positivos. Todos los REQUIRED y una alternativa por grupo CLEAR para SUPPORTED. '
            'Usa el esquema cerrado; no escribas citas ni indices. Errores: '+json.dumps(details,ensure_ascii=False,separators=(',',':')))
        concise=p2.instructions_for(request.get('prompt_version',p2.PROMPT))+v3.SK_INSTRUCTIONS.replace(v3.SK_VERSION,p2.VERSION).replace(
            v3.SK_TEMPORAL_SCALE,v3.PROSPECTIVE_TEMPORAL_SCALE)+v3.SK_COHERENCE
        options=[prefix+correction+'\n'+marker+payload,concise+correction+'\n'+marker+payload]
        revised['prompt']=min(options,key=lambda p:rebudget(p,schema,settings,request.get('context_budget'))['estimated_input_tokens'])
        revised['context_budget']=rebudget(revised['prompt'],schema,settings,request.get('context_budget'))
        return revised
    from .evidence_references import active
    if active(request) and version in TARGETED_VERSIONS:
        prefix = prefix.split('\nREFERENCE_CORRECTION_V2:\n', 1)[0]
        revised['prompt'] = _targeted_prompt(prefix, marker, payload, issues, previous, schema, settings,
                                             request.get('context_budget'))
    elif active(request):
        # Versioned separately from legacy literal prompts: old call hashes can
        # still be reconstructed byte for byte.
        prefix = prefix.split('\nREFERENCE_CORRECTION:\n', 1)[0]
        details = [{k:i[k] for k in ('category','path','rule','criterion_id','criterion_ids',
            'evidence_indices','evidence_count','temporal_requirement','observed_stages','missing_fields','correction_hint') if k in i}
            for i in (issues or [])]
        for detail in details:
            if 'path' in detail:
                detail['path'] = detail['path'].replace('.evidence_indices', '.evidence_refs')
        for count in range(len(details), 0, -1) if details else [0]:
            revised['prompt'] = (prefix + '\nREFERENCE_CORRECTION:\nCorrige el JSON completo segun estas reglas fallidas. '
                'Conserva IDs del INPUT_JSON; evidence_refs usa fragment_id y stage, nunca indices ni citas.\nERRORES: '
                + json.dumps(details[:count], ensure_ascii=False, separators=(',', ':'))
                + (f'\nOtros errores pendientes: {len(details)-count}' if count<len(details) else '')
                + '\n' + marker + payload)
            if rebudget(revised['prompt'], schema, settings, request.get('context_budget'))['fits']:
                break
    else:
        feedback = ('\nERRORES: ' + '; '.join(sorted({i['category'] for i in issues}))
                    if issues else '')
        correction = CORRECTION
        from .assessment_v3 import SK_VERSION, SK_STATE_INSTRUCTIONS
        if request.get('assessment_version') == SK_VERSION:
            correction = correction.replace(
                'NOT_SUPPORTED: todos NOT_DEMONSTRATED, strength=0. Apoyo parcial: INSUFFICIENT_EVIDENCE.',
                SK_STATE_INSTRUCTIONS)
        revised['prompt'] = prefix + correction + feedback + '\n' + marker + payload
    revised['context_budget'] = rebudget(revised['prompt'], schema, settings, request.get('context_budget'))
    return revised


def context_guard(prompt, schema, settings, runtime=None, budget=None):
    if budget is not None:
        from .context_budget import rebudget
        actual = rebudget(prompt, schema, settings, budget)
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
                    model_metadata_sha256=metadata_hash(info))


def metadata_hash(info):
    # Ollama serialises the Modelfile PARAMETER map in nondeterministic order
    # (it varies across server restarts). Line order carries no meaning, so the
    # lines are sorted (also the PARAMETER block of the modelfile); any change in
    # names or values still alters the hash.
    info = dict(info)
    if isinstance(info.get('parameters'), str):
        info['parameters'] = '\n'.join(sorted(info['parameters'].splitlines()))
    if isinstance(info.get('modelfile'), str):
        lines = info['modelfile'].split('\n')
        index = [i for i, line in enumerate(lines) if line.startswith('PARAMETER ')]
        for i, line in zip(index, sorted(lines[i] for i in index)):
            lines[i] = line
        info['modelfile'] = '\n'.join(lines)
    return canonical_hash(info)


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
                 token_limit_retries=0, corrective_retries=0, correction_version=None, wrapper_resolver=None):
        options = dict(settings or {})
        if timeout is not None:
            options['timeout_seconds'] = timeout
        if model is not None:
            options['model'] = model
        self.settings = configuration(options)
        if type(token_limit_retries) is not int or not 0 <= token_limit_retries <= self.settings['token_limit_retries']:
            raise ValueError('Reintentos de salida fuera de la configuracion')
        self.token_limit_retries = token_limit_retries
        if type(corrective_retries) is not int or not 0 <= corrective_retries <= 2:
            raise ValueError('Maximo dos reintentos correctivos')
        self.corrective_retries = corrective_retries
        self.correction_version = correction_version
        if max_retries != 0 or max_indicators not in (1, 2, 3, 5) or not stop_on_uncertain:
            raise ValueError('Ollama requiere ejecucion secuencial sin reintentos automaticos')
        self.directory, self.schema = Path(run_directory), Path(schema_path)
        self.input_factory, self.client = input_factory, client or create_client(self.settings)
        self.runtime, self.max_indicators = runtime, max_indicators
        self.wrapper_validator = wrapper_validator or validate_wrapper
        self.wrapper_resolver = wrapper_resolver
        self.output_adapter = output_adapter
        self.execution_id = execution_id or uuid.uuid4().hex
        self.calls, self.raw_outputs, self.last_output = [], [], None

    @measured_project
    def evaluate(self, project, indicators):
        from . import prospective_v2 as p2
        # Retries are explicitly enabled by the live run plan. Other callers keep
        # their existing outer retry policy and do not multiply inference calls.
        retries = max(self.token_limit_retries, self.corrective_retries)
        output = self.settings['num_predict']
        request = self.input_factory(project, indicators)
        first, self.scope = len(self.calls), None
        for attempt in range(retries + 1):
            try:
                return self._evaluate_once(project, indicators, attempt=attempt, output=output, request=request)
            except OllamaError as exc:
                if attempt == retries:
                    raise
                if exc.code == 'INVALID_ASSESSMENT' and attempt < self.corrective_retries:
                    if any(i.get('category') == 'INTERNAL_VALIDATION_ERROR' for i in self.calls[-1]['validation_issues']):
                        raise
                    previous = None
                    if self.correction_version in TARGETED_VERSIONS:
                        # The first complete judgment of this evaluation is the
                        # baseline for every corrective attempt (also on replay).
                        previous, flagged, broad = targeted_scope(
                            [self.directory.parent / c['working_directory'] for c in self.calls[first:]],
                            [c['validation_issues'] for c in self.calls[first:]])
                        self.scope = (previous, flagged, broad) if previous is not None and flagged is not None else None
                    revised = corrective_request(self.input_factory(project, indicators),
                        strict_json(self.schema.read_text(encoding='utf-8')), self.settings,
                        self.calls[-1]['validation_issues'], previous, self.correction_version)
                    if self.correction_version==p2.CORRECTION and not revised['context_budget']['fits']:
                        # Keep the actual failed validation, not a fictitious new
                        # inference or semantic rejection. Nothing is dispatched.
                        raise
                    revised_output = output
                    if revised.get('evidence_protocol') and revised['context_budget']['fits']:
                        # A previous token-limit retry may have raised the output
                        # allowance. Keep room for the specific corrective input.
                        revised_output = min(output, self.settings['num_ctx'] - self.settings['context_margin_tokens']
                            - revised['context_budget']['estimated_input_tokens'])
                    if (self.settings['provider'] == 'ollama' and
                            revised['prompt'] == request['prompt'] and revised_output == output):
                        # The same failed correction with the same allowance is
                        # not another recovery strategy. Keep its original error.
                        raise
                    request, output = revised, revised_output
                    continue
                if exc.code != 'TOKEN_LIMIT' or attempt >= self.token_limit_retries:
                    raise
                budget = self.calls[-1].get('context_budget')
                input_tokens = (budget['estimated_input_tokens'] if budget else
                    len(self.input_factory(project, indicators)['prompt'].encode('utf-8')))
                observed = self.calls[-1]['usage_observations'][0].get('input_tokens')
                if type(observed) is int:
                    input_tokens = max(input_tokens, observed)
                available = self.settings['num_ctx'] - self.settings['context_margin_tokens'] - input_tokens
                ceiling = min(max(output, self.settings['max_predict']), available)
                if ceiling <= output:
                    # No additional output room: do not repeat a deterministically
                    # truncated request at the same cap (including on the last tier).
                    raise
                output = min(output * 2, ceiling)

    def _evaluate_once(self, project, indicators, *, attempt=0, output=None, request=None):
        self.last_output = None
        if not 1 <= len(indicators) <= self.max_indicators or not re.fullmatch(r'[A-Za-z0-9_-]+', project['project_id']):
            raise ValueError('Identificador de proyecto o lote invalido')
        request = request or self.input_factory(project, indicators)
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
            from .context_budget import rebudget
            budget = rebudget(prompt, schema, generation, budget)
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
            from .evidence_references import active, materialize
            from . import prospective_v2 as p2
            scoped, scope = [], getattr(self, 'scope', None)
            ids = [i['indicator_id'] for i in indicators]
            if active(request):
                save('selection.json', parsed)
            if active(request) and scope and self.correction_version == MERGE_CORRECTION_VERSION:
                parsed, provenance = merged_attempt(*scope, parsed, request,
                    lambda wrapper: self.wrapper_validator(wrapper, project['project_id'], ids))
                save('repair.json', provenance)
            else:
                if active(request) and scope:
                    scoped = scope_issues(scope[0], scope[1], parsed)
                try:
                    if active(request):
                        parsed = materialize(request, parsed)
                    if request.get('decision_policy') == p2.DECISION_POLICY:
                        if self.wrapper_resolver is None:
                            raise ValueError('La politica determinista requiere su resolver validado')
                        parsed, decision_receipt = self.wrapper_resolver(parsed)
                        save('decision.json', decision_receipt)
                    self.wrapper_validator(parsed, project['project_id'], ids)
                except AssessmentValidationError as exc:
                    raise AssessmentValidationError(exc.issues + scoped) if scoped else exc
                if scoped:
                    raise AssessmentValidationError(scoped)
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
