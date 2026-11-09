"""Single authority for technical Layer 4 assessment/export JSON Schemas."""

from .. import load_schema
from copy import deepcopy
import json
from pathlib import Path
from jsonschema import Draft202012Validator

FIELDS = ['title', 'keywords', 'summary', 'methodology', 'objectives', 'expected_results']
INDICATOR_COLUMNS = ['project_id', 'indicator_id', 'indicator_name', 'indicator_category', 'indicator_dimension',
    'decision', 'support_strength', 'supported_key_elements', 'evidence_source_fields', 'evidence_texts',
    'evidence_explanation', 'key_element_coverage', 'field_relevance_score', 'corroboration_score',
    'support_strength_score', 'confidence_raw_score', 'confidence_status', 'confidence_version',
    'assessment_engine', 'assessment_engine_status', 'confidence_probability', 'confidence_level']
TERRITORY_COLUMNS = ['project_id', 'territory_type', 'territory_code', 'territory_name',
                     'department_code', 'department_name', 'code_system']
PROJECT_COLUMNS = ['project_id', *FIELDS]
METADATA_KEYS = ['output_status', 'project_count', 'candidate_limit_per_project', 'layer3_run',
    'retrieval_indicator_version', 'assessment_indicator_version', 'assessment_indicator_sha256',
    'assessment_engine', 'assessment_engine_status', 'confidence_version', 'confidence_is_probability',
    'territory_version', 'dane_reference_sha256', 'country_internal_code', 'country_internal_code_system', 'generated_at']


def _object(title, properties, required=None):
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'title': title, 'type': 'object',
            'properties': properties, 'required': list(properties) if required is None else required,
            'additionalProperties': False}


def definitions(root):
    root = Path(root)
    assessment = json.loads((root/'schemas/layer4_confidence/assessment.schema.json').read_text(encoding='utf-8'))
    assessment['title'] = 'PROJECT_INDICATOR_ASSESSMENT_V1 provider response; no confidence'
    assessment['additionalProperties'] = False
    assessment['properties']['evidence']['items']['additionalProperties'] = False
    assessment['allOf'][0]['then']['properties']['evidence'] = {'minItems': 1}
    string = {'type': 'string', 'minLength': 1}
    optional_text = {'type': ['string', 'null']}
    array = {'type': 'array', 'items': string}
    profile_props = {name: deepcopy(optional_text) for name in (
        'indicator_id', 'indicator_name', 'indicator_category', 'indicator_dimension', 'descripcion_ampliada',
        'key_elements_original', 'key_elements_status', 'key_elements_parse_method', 'favorable_evidence',
        'insufficient_evidence', 'related_terms', 'relational_context', 'fuentes_relevantes_original',
        'preferred_fields_mapping_status', 'source_catalog', 'source_sheet', 'source_hash', 'source_record_json', 'profile_version')}
    for name in ('indicator_id', 'indicator_name', 'indicator_category', 'source_catalog', 'source_sheet', 'source_record_json'):
        profile_props[name] = string
    profile_props.update(key_elements=array, preferred_evidence_fields={'type':'array','items':{'enum':FIELDS},'uniqueItems':True},
        source_row={'type':'integer','minimum':2},source_hash={'type':'string','pattern':'^[0-9a-f]{64}$'},
        profile_version={'const':'INDICATOR_ASSESSMENT_PROFILES_V2'},
        key_elements_status={'enum':['AVAILABLE','MISSING']},
        preferred_fields_mapping_status={'enum':['MAPPED','PARTIALLY_MAPPED','UNMAPPED','EMPTY']})
    profile = _object('INDICATOR_ASSESSMENT_PROFILE_V2',profile_props)
    profile['allOf'] = [
        {'if':{'properties':{'key_elements_status':{'const':'AVAILABLE'}}},
         'then':{'properties':{'key_elements':{'minItems':1}}},'else':{'properties':{'key_elements':{'maxItems':0}}}},
        {'if':{'properties':{'preferred_fields_mapping_status':{'const':'MAPPED'}}},
         'then':{'properties':{'preferred_evidence_fields':{'minItems':1}}},
         'else':{'properties':{'preferred_evidence_fields':{'maxItems':0}}}}]
    confidence = json.loads((root/'schemas/layer4_confidence/confidence_result.schema.json').read_text(encoding='utf-8'))
    properties = {name: deepcopy(string) for name in ('project_id','indicator_id','indicator_name','indicator_category',
                                                     'evidence_explanation','assessment_engine','assessment_engine_status')}
    properties.update(indicator_dimension=optional_text, decision=assessment['properties']['decision'],
        support_strength=assessment['properties']['support_strength'], supported_key_elements=array,
        evidence_source_fields={'type':'array','items':{'enum':FIELDS}}, evidence_texts=array)
    properties.update({k:deepcopy(v) for k,v in confidence['properties'].items() if k!='validation_errors'})
    indicator = _object('PROJECT_INDICATOR_V1',properties)
    indicator['allOf'] = deepcopy(assessment['allOf'])
    # Evidence quote existence and array alignment are Python hard gates.
    for branch in indicator['allOf']:
        branch['then']['properties'].pop('evidence',None)
    for branch in deepcopy(confidence['allOf']):
        for alternative in ('then','else'):
            branch.get(alternative,{}).get('properties',{}).pop('validation_errors',None)
        indicator['allOf'].append(branch)
    indicator['allOf'].append({'if':{'properties':{'decision':{'enum':['NOT_SUPPORTED','INSUFFICIENT_EVIDENCE']}}},
        'then':{'properties':{'confidence_status':{'enum':['NOT_APPLICABLE','INVALID_ASSESSMENT']},'confidence_raw_score':{'type':'null'}}}})
    indicator['allOf'].append({'if':{'properties':{'confidence_status':{'const':'COMPUTED'}}},
        'then':{'properties':{'decision':{'const':'SUPPORTED'},'supported_key_elements':{'minItems':1},
                              'evidence_texts':{'minItems':1}}}})
    indicator['allOf'].append({'if':{'properties':{'decision':{'const':'SUPPORTED'}}},
        'then':{'properties':{'confidence_status':{'enum':['COMPUTED','NOT_COMPUTABLE','INVALID_ASSESSMENT']}}}})
    territory = _object('PROJECT_TERRITORY_CONSUMPTION_V1', {
        'project_id':string,'territory_type':{'enum':['COUNTRY','DEPARTMENT','MUNICIPALITY']},
        'territory_code':string,'territory_name':string,'department_code':optional_text,
        'department_name':optional_text,'code_system':{'enum':['DANE','INTERNAL']}})
    territory['allOf'] = [
        {'if':{'properties':{'territory_type':{'const':'COUNTRY'}}},
         'then':{'properties':{'territory_code':{'const':'000'},'territory_name':{'const':'Colombia'},
             'code_system':{'const':'INTERNAL'},'department_code':{'type':'null'},'department_name':{'type':'null'}}},
         'else':{'properties':{'code_system':{'const':'DANE'},'department_code':{'type':'string','pattern':'^[0-9]{2}$'},'department_name':string}}},
        {'if':{'properties':{'territory_type':{'const':'DEPARTMENT'}}},'then':{'properties':{'territory_code':{'pattern':'^[0-9]{2}$'}}}},
        {'if':{'properties':{'territory_type':{'const':'MUNICIPALITY'}}},'then':{'properties':{'territory_code':{'pattern':'^[0-9]{5}$'}}}}]
    metadata_props={key:deepcopy(string) for key in METADATA_KEYS}
    metadata_props.update(project_count={'type':'integer','minimum':0},candidate_limit_per_project={'const':2},
        output_status={'enum':['PREPARED_NOT_EXECUTED','SYNTHETIC_TEST','PRELIMINARY','FINAL']},
        confidence_version={'const':'RAW_CONFIDENCE_V1'}, confidence_is_probability={'const':False},
        country_internal_code={'const':'000'},country_internal_code_system={'const':'INTERNAL'},
        assessment_indicator_sha256={'type':'string','pattern':'^[0-9a-f]{64}$'},
        dane_reference_sha256={'type':'string','pattern':'^[0-9a-f]{64}$'},generated_at={'type':'string','format':'date-time'},
        planned_project_count={'type':'integer','minimum':0},territory_ambiguous_mentions={'type':'integer','minimum':0},
        territory_ambiguous_projects={'type':'integer','minimum':0})
    metadata=_object('LAYER4_EXPORT_METADATA_V1',metadata_props,METADATA_KEYS)
    project=_object('PROJECT_EXPORT_V1',{'project_id':string,**{f:optional_text for f in FIELDS}})
    project['properties']['keywords']={'oneOf':[optional_text,{'type':'array','items':{'type':'string'}}]}
    package=_object('LAYER4_WORKBOOK_DATA_V1',{'projects':{'type':'array','items':project},
        'indicators':{'type':'array','items':indicator},'territories':{'type':'array','items':territory},'metadata':metadata})
    return {'assessment':assessment,'indicator_profile':profile,'project_indicator':indicator,
            'project_territory':territory,'metadata':metadata,'workbook_data':package}




def check_contracts(root, write=False):
    directory=Path(root)/'schemas/layer4_assessment'
    if write:directory.mkdir(parents=True,exist_ok=True)
    for name,schema in definitions(root).items():
        Draft202012Validator.check_schema(schema)
        target=directory/(name+'.schema.json')
        if write:target.write_text(json.dumps(schema,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        elif json.loads(target.read_text(encoding='utf-8'))!=schema:
            raise ValueError('Layer 4 schema drift: '+name)
    return len(definitions(root))


ROOT=Path(__file__).resolve().parents[3]


def schemas(root=ROOT):
    base=definitions(root)
    assessment=deepcopy(base['assessment'])
    # Native structured output handles shape only. Semantic strength/evidence gates
    # run once after return and must NEVER trigger a provider retry.
    transport={k:v for k,v in assessment.items() if k in ('type','properties','required','additionalProperties')}
    transport['properties']={'indicator_id':{'type':'string'},**transport['properties']}
    transport['properties']['decision']['type']='string'
    transport['properties']['evidence']['items']['properties']['field']['type']='string'
    transport['required']=['indicator_id',*transport['required']]
    wrapper={'type':'object','additionalProperties':False,'properties':{
        'project_id':{'type':'string'},'assessments':{'type':'array','items':transport}},
        'required':['project_id','assessments']}
    row=deepcopy(base['project_indicator'])
    row['title']='PRELIMINARY_PROJECT_INDICATOR_V1 including invalid assessment diagnostics'
    row['properties']['assessment_validation_status']={'enum':['VALID','INVALID_ASSESSMENT']}
    row['properties']['validation_errors']={'type':'array','items':{'type':'string'}}
    row['required']+=['assessment_validation_status','validation_errors']
    # Invalid provider semantics stay visible, never silently repaired. The frozen
    # base schema still applies to valid rows, and rejects invalid final exports.
    row.pop('allOf',None)
    row['allOf']=[{'if':{'properties':{'assessment_validation_status':{'const':'INVALID_ASSESSMENT'}}},
        'then':{'properties':{'confidence_status':{'const':'INVALID_ASSESSMENT'},
                            'confidence_raw_score':{'type':'null'},'validation_errors':{'minItems':1}}},
        'else':{'properties':{'validation_errors':{'maxItems':0}},
                'allOf':deepcopy(base['project_indicator'].get('allOf',[]))}}]
    return {'assessment_batch':wrapper,'project_indicator_preliminary':row}


def validate_wrapper(output, project_id, indicator_ids):
    Draft202012Validator(schemas()['assessment_batch']).validate(output)
    if output['project_id']!=project_id:raise ValueError('Wrapper project ID mismatch')
    returned=[r['indicator_id'] for r in output['assessments']]
    if len(returned)!=len(set(returned)) or set(returned)!=set(indicator_ids):
        raise ValueError('Wrapper indicator IDs missing, extra or duplicate')
    return output


def write_or_check(root=ROOT,check=False):
    out=Path(root)/'schemas/layer4_preliminary'
    if not check:out.mkdir(parents=True,exist_ok=True)
    for name,schema in schemas(root).items():
        Draft202012Validator.check_schema(schema)
        target=out/(name+'.schema.json');text=json.dumps(schema,ensure_ascii=False,indent=2)+'\n'
        if check:
            if not target.exists() or target.read_text(encoding='utf-8')!=text:raise ValueError('Stale schema: '+name)
        else:target.write_text(text,encoding='utf-8')
