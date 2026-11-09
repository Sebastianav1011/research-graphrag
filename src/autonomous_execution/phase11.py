"""Catalog-faithful, evidence-preserving, scoped semantic repair. No decisions in Python."""
from copy import deepcopy
import re
from jsonschema import Draft202012Validator
from layer4_evaluation.indicators import assessment_v3 as v3, context_budget as cb
from layer4_evaluation.indicators.selection import canonical_hash
from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError
from . import policy as p

VERSION='EVIDENCE_PRESERVING_SCOPED_REPAIR_V1'
FIDELITY=('\nCATALOGO: juzga cada criterio independientemente. CONTEXT_ONLY pide identificar '
    'el contexto; no exige participacion actual ni impacto. Una propuesta no prueba ejecucion. '
    'Clasifica la etapa del hecho citado, no la del campo ni la del proyecto entero; separa '
    'clausulas mixtas. No agregues requisitos de materialidad fisica, ventas, causalidad '
    'experimental o detalle administrativo ausentes en definicion/rubrica/evidencia favorable. '
    'Conserva las vias alternativas. No presupongas positivo ni negativo.\n')
REPAIR=('\nREPARACION LOCAL: devuelve project_id y assessments con indicator_id y changes; '
    'changes es un objeto ruta:valor; reason es una razon breve comun. '
    'No regeneres el assessment completo. Usa solo rutas permitidas. El estado previo no '
    'es evidencia: las fuentes originales siguen presentes. Corrige exactamente las reglas '
    'senaladas; conserva los demas juicios y citas. Razones breves. No rebajes soporte positivo '
    'con cita literal para hacer pasar el contrato: si exige reconsideracion semantica, quedara '
    'pendiente de revision. No inventes requisitos. NOT_SUPPORTED no admite ningun criterio '
    'positivo; no borres un PARTIAL para obtener esa decision. Qwen decide, Python valida.\n')


def compact_catalog(request,rubric):
    """Remove only a byte-equivalent duplicate, never an institutional definition."""
    indicator=request['payload']['indicators'][0]
    duplicate=indicator.get('key_elements')==[c['criterion'] for c in rubric['criteria']]
    if duplicate:indicator.pop('key_elements')
    requirements={c['temporal_requirement'] for c in indicator['rubric']['criteria']}
    request['payload']['temporal_compatibility']={k:sorted(v3.TEMPORAL[k]) for k in sorted(requirements)}
    request['catalog_compaction']=dict(removed=['key_elements'] if duplicate else [],
        reason='EXACT_DUPLICATE_OF_RUBRIC' if duplicate else 'NONE',definition_preserved=True)


def catalog_prompt(request,rubric,*,shard=False):
    compact_catalog(request,rubric)
    request['prompt']=p.NORMATIVE+p.REPAIR+p.CONCISE+FIDELITY+(p.SHARD if shard else '')+'\nINPUT_JSON:\n'+cb.compact(request['payload'])
    return request


def coverage(request):
    # Semantic relevance is not guessed from keywords. Every retrieved interval
    # must survive; only exact duplicates may be omitted.
    if any(x['reason']!='DUPLICATE_EXACT_FIELD_TEXT' for x in request['context_selection']['omitted']):
        raise ValueError('EVIDENCE_COVERAGE_INCOMPLETE')
    return dict(version=VERSION,retained=request['context_selection']['selected'],removed=[],
        all_retrieved_intervals_preserved=True,source_hash=canonical_hash(request['payload']['project'].get('fields',{})))


def _item(wrapper):return wrapper['assessments'][0]
def _get(item,path):
    value=item
    for key,index in re.findall(r'([a-z_]+)|\[(\d+)\]',path.removeprefix('$.')):
        value=value[key] if key else value[int(index)]
    return value
def _set(item,path,value):
    if path=='$.evidence[+]':item['evidence'].append(deepcopy(value));return
    tokens=[key if key else int(index) for key,index in re.findall(r'([a-z_]+)|\[(\d+)\]',path.removeprefix('$.'))]
    parent=item
    for token in tokens[:-1]:parent=parent[token]
    parent[tokens[-1]]=deepcopy(value)


def patch_request(request,schema,prior,issues,project):
    """Build a finite path/type allowlist, keeping original sources and response."""
    if not Draft202012Validator(schema).is_valid(prior):return None
    item=_item(prior);props=schema['properties']['assessments']['items']['properties'];allowed={}
    if prior['project_id']!=project['project_id'] or item['indicator_id']!=request['payload']['indicators'][0]['indicator_id']:return None
    def add(path,kind):allowed[path]=deepcopy(kind)
    def globals_():
        for key in ('decision','support_strength','explanation'):
            if key in props:add('$.'+key,props[key])
    def criterion(index):
        spec=props['criterion_assessments']['items']['properties']
        for key in ('support','evidence_indices','explanation'):add(f'$.criterion_assessments[{index}].{key}',spec[key])
    for issue in issues:
        rule=issue['rule'];path=issue['path']
        if 'NOT_SUPPORTED' in rule or 'INCONSISTENT_DECISION' in rule:globals_();continue
        if 'EXACT_FROZEN_RUBRIC' in rule:return None
        affected=[]
        for i,c in enumerate(item.get('criterion_assessments',[])):
            if issue.get('criterion_id')==c['criterion_id']:affected.append(i)
            elif 'POSITIVE_SUPPORT_REQUIRES_QUOTE' in rule and c['support']!='NOT_DEMONSTRATED' and not c['evidence_indices']:affected.append(i)
            elif 'EVIDENCE_INDEX_OUT_OF_RANGE' in rule and any(j>=len(item['evidence']) for j in c['evidence_indices']):affected.append(i)
        quote=re.match(r'\$\.evidence\[(\d+)\]',path)
        if quote:
            q=int(quote[1]);affected += [i for i,c in enumerate(item.get('criterion_assessments',[])) if q in c['evidence_indices']]
            if q<len(item.get('evidence',[])):
                for key,kind in props['evidence']['items']['properties'].items():add(f'$.evidence[{q}].{key}',kind)
        for i in sorted(set(affected)):
            criterion(i)
            for j in item['criterion_assessments'][i]['evidence_indices']:
                if 0<=j<len(item['evidence']):add(f'$.evidence[{j}].stage',props['evidence']['items']['properties']['stage'])
            if 'POSITIVE_SUPPORT_REQUIRES_QUOTE' in rule:add('$.evidence[+]',props['evidence']['items'])
        globals_()
    if not allowed:return None
    compact=deepcopy(item);compact.pop('explanation',None)
    for c in compact.get('criterion_assessments',[]):c.pop('explanation',None)
    request=deepcopy(request)
    request['payload']['repair_state']=compact
    safe=[{k:v for k,v in issue.items() if k in ('rule','path','criterion_id','criterion_ids','evidence_indices','temporal_requirement','observed_stages')} for issue in issues]
    request['payload']['repair_issues']=safe
    request['payload']['allowed_repair_paths']=list(allowed)
    # Retain source/catalog instructions, replace only the serialization section.
    prefix=request['prompt'].split('\nINPUT_JSON:\n',1)[0]
    request['prompt']=prefix+REPAIR+'\nINPUT_JSON:\n'+cb.compact(request['payload'])
    patch_item=dict(type='object',properties=dict(indicator_id=dict(const=item['indicator_id']),
        changes=dict(type='object',properties=allowed,minProperties=1,additionalProperties=False),
        reason=dict(type='string',minLength=1,maxLength=160)),
        required=['indicator_id','changes','reason'],additionalProperties=False)
    patch_schema=dict(type='object',properties=dict(project_id=dict(const=prior['project_id']),
        assessments=dict(type='array',minItems=1,maxItems=1,items=patch_item)),
        required=['project_id','assessments'],additionalProperties=False)
    request['repair_contract']=dict(version=VERSION,prior=deepcopy(prior),original_schema=deepcopy(schema),
        allowed_paths=list(allowed),source_hash=canonical_hash(request['payload']['project'].get('fields',request['payload'].get('source_spans'))),
        prior_sha256=canonical_hash(prior),information_removed=['prior_explanation_prose_from_prompt_only'],
        sources_removed=[],criterion_ids_preserved=[c['criterion_id'] for c in item.get('criterion_assessments',[])])
    return request,patch_schema


def changes(patch):
    item=_item(patch)
    if isinstance(item['changes'],dict):
        return [dict(path=key,value=value,reason=item['reason']) for key,value in item['changes'].items()]
    # Diagnostic callers may use explicit change records; transport V3 uses the
    # smaller typed sparse object. Both pass the same path and regression gates.
    return item['changes']


def apply_patch(request,patch):
    contract=request['repair_contract'];original=contract['prior'];value=deepcopy(original);item=_item(value)
    paths=[c['path'] for c in changes(patch)]
    if len(paths)!=len(set(paths)) or any(path not in contract['allowed_paths'] for path in paths):
        raise AssessmentValidationError([dict(category='INVALID_FIELD_VALUE',rule='REPAIR_PATCH_OUTSIDE_SCOPE',path='$.changes')])
    for change in changes(patch):_set(item,change['path'],change['value'])
    Draft202012Validator(contract['original_schema']).validate(value)
    prior=_item(original);sources=request['payload']['project'].get('fields',{})
    for old,new in zip(prior.get('criterion_assessments',[]),item.get('criterion_assessments',[])):
        literal=any(0<=j<len(prior.get('evidence',[])) and prior['evidence'][j]['text'] in
            (sources.get(prior['evidence'][j]['field']) or '') for j in old['evidence_indices'])
        if old['support']!='NOT_DEMONSTRATED' and new['support']=='NOT_DEMONSTRATED' and literal:
            raise AssessmentValidationError([dict(category='SEMANTIC_REVIEW_REQUIRED',rule='GROUNDED_SUPPORT_REGRESSION',
                path='$.criterion_assessments',criterion_id=old['criterion_id'])])
    return value


def repair_receipt(request,patch,result):
    before=_item(request['repair_contract']['prior']);after=_item(result)
    return dict(version=VERSION,changes=[dict(path=c['path'],reason=c['reason']) for c in changes(patch)],
        prior_sha256=canonical_hash(request['repair_contract']['prior']),result_sha256=canonical_hash(result),
        sources_removed=[],source_hash=request['repair_contract']['source_hash'],
        unchanged_criterion_ids=[a['criterion_id'] for a,b in zip(before.get('criterion_assessments',[]),after.get('criterion_assessments',[])) if a==b])
