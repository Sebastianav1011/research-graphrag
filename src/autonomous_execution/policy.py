"""Finite per-request bounds; no run-wide token, call or project quota."""
from copy import deepcopy
import ctypes
import os

from layer4_evaluation.indicators import assessment_v3 as v3
from layer4_evaluation.indicators.ollama_provider import configuration

VERSION = 'AUTONOMOUS_POLICY_V1'
PHASE1 = 'AUTONOMOUS_POLICY_V2'
PHASE11 = 'AUTONOMOUS_POLICY_V3'
PHASE12 = 'AUTONOMOUS_POLICY_V4'


def coherent(policy):
    return policy['version'] in (PHASE1,PHASE11,PHASE12)


def preserving(policy):
    return policy['version'] in (PHASE11,PHASE12)
CONCISE = ('\nCONCISION: evalua cada criterio independientemente de la decision global. '
           'Reconocer contexto no demuestra impacto. Explica cada juicio en una frase completa '
           'breve (objetivo 80-120 caracteres); conserva la relacion y temporalidad necesarias. '
           'Cita el pasaje literal minimo suficiente, sin cortar negaciones o atribucion.\n')
# Keep the historical template byte-for-byte: legacy checkpoints pin its hash.
# All autonomous phases and their authorization manifest use this adaptation.
_HISTORICAL_ROLES = 'Codex es el único intérprete; Python comprobará citas y calculará confianza.'
_LOCAL_ROLES = ('Qwen, mediante Ollama local, realiza la evaluación semántica; '
                'Python valida el contrato y las evidencias y calcula la confianza.')
if v3.INSTRUCTIONS.count(_HISTORICAL_ROLES) != 1:
    raise ValueError('Plantilla normativa historica incompatible: revisar responsabilidades')
NORMATIVE = v3.INSTRUCTIONS.replace(_HISTORICAL_ROLES, _LOCAL_ROLES, 1)

REPAIR = ('\nCONTROL: evidencia literal; evidence_indices base cero dentro de evidence. '
          'Con dos citas solo existen 0 y 1. NOT_SUPPORTED no admite criterios positivos. '
          'Responde JSON completo y conciso; nunca inventes evidencia.\n')
SHARD = ('\nSUBEVALUACION: devuelve solo los criterion_assessments solicitados y su evidence. '
         'No decidas el indicador aun. Conserva los IDs, roles y temporalidades originales.\n')
SYNTHESIS = ('\nSINTESIS: los juicios adjuntos fueron verificados estructuralmente y sus citas '
             'existen; no son fuentes nuevas. Decide desde la definicion completa y las fuentes. '
             'Devuelve solo decision, support_strength y explanation. No cambies los criterios.\n')


def validate(value):
    from layer2_processing.preprocessing.adapters import read
    from pathlib import Path
    default = read(Path(__file__).resolve().parents[2]/'config/autonomous.json')
    if not isinstance(value, dict) or set(value) != set(default) or value.get('version') not in (VERSION, PHASE1, PHASE11, PHASE12):
        raise ValueError('Politica autonoma desconocida o incompleta')
    p = deepcopy(value)
    bounds = dict(workers=(1,2), max_context=(2048,32768), context_margin_tokens=(512,4096),
        attempts_per_step=(1,3), metadata_attempts=(1,5), recovery_rounds=(0,2), criteria_per_shard=(1,6), criterion_explanation_characters=(80,1000),
        assessment_explanation_characters=(120,2000), min_free_ram_mb=(512,1048576),
        min_free_disk_mb=(64,1048576),
        cooldown_seconds=(0,60), timeout_seconds=(30,3600), consecutive_service_failures=(1,10),
        parquet_batch_rows=(1,1024))
    for key,(low,high) in bounds.items():
        if type(p[key]) is not int or not low <= p[key] <= high:
            raise ValueError('Limite de recursos invalido: '+key)
    if not isinstance(p['tiers'], list) or not 1 <= len(p['tiers']) <= 4:
        raise ValueError('Definir entre uno y cuatro presupuestos finitos')
    previous = (0,0)
    for tier in p['tiers']:
        if set(tier) != {'num_ctx','num_predict'} or any(type(x) is not int for x in tier.values()):
            raise ValueError('Presupuesto invalido')
        pair = tier['num_ctx'],tier['num_predict']
        if pair[0] <= previous[0] or pair[1] <= previous[1] or pair[0] > p['max_context']:
            raise ValueError('Presupuestos deben crecer dentro del techo aprobado')
        configuration(tier | dict(context_margin_tokens=p['context_margin_tokens'], keep_alive=p['keep_alive']))
        previous = pair
    if coherent(p):
        inputs=[t['num_ctx']-t['num_predict']-p['context_margin_tokens'] for t in p['tiers']]
        if any(b<=a for a,b in zip(inputs,inputs[1:])):
            raise ValueError('Cada nivel V2 debe ampliar el presupuesto efectivo de entrada')
    return p


def settings(base, policy, tier, *, decision_only=False):
    limits=policy['tiers'][tier]
    if coherent(policy) and decision_only:
        limits=limits|dict(num_predict=min(limits['num_predict'],512))
    return configuration(base | limits | dict(context_margin_tokens=policy['context_margin_tokens'],
        timeout_seconds=policy['timeout_seconds'], keep_alive=policy['keep_alive']))


def start_tier(policy, criteria_count):
    desired = (384 + criteria_count*128) if coherent(policy) else (512 + criteria_count*180)
    return next((i for i,t in enumerate(policy['tiers']) if t['num_predict'] >= desired), len(policy['tiers'])-1)


def schema(fields, policy, *, ids=None, decision_only=False, criterion_ids=None):
    result = deepcopy(v3.schemas(fields)['assessment_batch'])
    item = result['properties']['assessments']['items']
    result['properties']['assessments'].update(minItems=1, maxItems=1)
    item['properties']['explanation']['maxLength'] = policy['assessment_explanation_characters']
    criterion = item['properties']['criterion_assessments']['items']
    criterion['properties']['explanation']['maxLength'] = policy['criterion_explanation_characters']
    if decision_only:
        keep = ('indicator_id','decision','support_strength','explanation')
        item['properties'] = {k:v for k,v in item['properties'].items() if k in keep}
    elif ids is not None:
        keep = ('indicator_id','criterion_assessments','evidence')
        item['properties'] = {k:v for k,v in item['properties'].items() if k in keep}
        criteria = item['properties']['criterion_assessments']
        criteria.update(minItems=len(ids), maxItems=len(ids))
        criteria['items']['properties']['criterion_id']['enum'] = ids
    if coherent(policy) and criterion_ids is not None and not decision_only:
        criteria=item['properties']['criterion_assessments']
        criteria.update(minItems=len(criterion_ids),maxItems=len(criterion_ids))
        criteria['items']['properties']['criterion_id']['enum']=list(criterion_ids)
    item['required'] = list(item['properties'])
    return result


def free_ram_mb():
    if os.name == 'nt':
        class Memory(ctypes.Structure):
            _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong)] + [(k,ctypes.c_ulonglong) for k in
                ('total','available','total_page','available_page','total_virtual','available_virtual','extended')]
        mem = Memory(); mem.length = ctypes.sizeof(mem)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            return mem.available//(1024*1024)
        raise RuntimeError('No fue posible verificar RAM disponible')
    try:
        return os.sysconf('SC_AVPHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')//(1024*1024)
    except (ValueError, OSError):
        raise RuntimeError('No fue posible verificar RAM disponible') from None
