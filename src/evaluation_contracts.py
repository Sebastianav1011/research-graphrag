"""Immutable, portable project contracts over the native stratified sampler."""
import json
from pathlib import Path
import re

from layer2_processing.preprocessing.project_selection import select, sample_projects, digest, VERSION
from layer2_processing.preprocessing.adapters import sha

ELIGIBILITY='AUTHORIZED_SUBSTANTIVE_TEXT_V1'


def evaluable_features(root,raw,config,features):
    """Read the native adapter's text authorization; never build knowledge or infer."""
    from layer2_processing.preprocessing.adapters import (discover_sources,source_registry,
        file_configuration,select_text_columns,clean,PROJECT_FIELDS,PROJECT_EXTRA)
    from layer2_processing.preprocessing.knowledge_fields import analyze_columns
    from layer2_processing.preprocessing.normalize import identifier
    discovered=discover_sources(root,config,raw)
    if discovered['status']!='READY_FOR_VALIDATION':raise ValueError('Fuentes invalidas para determinar elegibilidad')
    known=source_registry(root,config);eligible=set()
    for item in discovered['files']:
        if item['domain']!='proyectos':continue
        override=file_configuration(config,item['file'])
        rows=[(r['row'],r['original_values']) for r in item['records']]
        policy=config.get('text_columns',{})|override.get('text_columns',{})
        mapping,extra,_,_=analyze_columns(item['headers'],rows,item['mapping'],
            known.get('knowledge_detection',{}),policy,select_text_columns)
        if item.get('project_contract'):extra=PROJECT_EXTRA.copy()
        for _,original in rows:
            available=any(clean(original.get(c)) for f in PROJECT_FIELDS if f not in ('title','keywords')
                for c in mapping.get(f,[])) or any(clean(original.get(c)) for c in extra.values())
            if available:
                eligible.update(str(original[c]) if item.get('project_contract') else identifier(original.get(c))
                    for c in mapping.get('source_project_id',[]))
    return {pid:values for pid,values in features.items() if pid in eligible}


def inventory(root,coordinator,config_path='config/pipeline_manual.json'):
    config,raw,_=coordinator.selected_configuration(root,config_path,source='base')
    population=select(Path(root),raw,config,all_projects=True)
    return population | dict(
        selection_configuration_sha256=digest({k:v for k,v in config.items() if k not in ('llm','runs_base','raw_base')}),
        evaluable_project_features=evaluable_features(Path(root),raw,config,population['project_features']))


def selection_population(population,require_evaluable=False):
    if not require_evaluable:return population['project_features'],None
    features=population.get('evaluable_project_features')
    if features is None:raise ValueError('Falta inventario de texto sustantivo autorizado')
    return features,dict(rule=ELIGIBILITY,population_count=len(features),
        population_sha256=digest(features),excluded_count=len(population['project_features'])-len(features))


def catalog_hash(root):
    # Bind the normative definitions/rubrics as well as the institutional source.
    from autonomous_execution.preparation_integrity import catalog
    data,_=catalog(Path(root))
    return digest(dict(profiles=data['profiles'],rubrics=data['rubrics'],rules=data['rules']))


def create(root,name,count,seed,population,catalog,*,require_evaluable=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',name):raise ValueError('Nombre: letras ASCII, numeros, guion o guion bajo')
    if type(seed) is not int:raise ValueError('Semilla entera requerida')
    features,eligibility=selection_population(population,require_evaluable)
    ids=sample_projects(features,count,seed)
    folder=Path(root)/'data/contratos';folder.mkdir(parents=True,exist_ok=True)
    versions=[int(p.stem.rsplit('.v',1)[1]) for p in folder.glob(name+'.v*.json') if p.stem.rsplit('.v',1)[1].isdigit()]
    version=max(versions,default=0)+1
    value=dict(contract_id=name,version=version,schema_version='EVALUATION_CONTRACT_V1',project_ids=ids,
        selected_count=len(ids),seed=seed,selection_method=VERSION,sources=population['sources'],
        population_sha256=population['population_sha256'],catalog_sha256=catalog,
        selection_configuration_sha256=population.get('selection_configuration_sha256'))
    if eligibility:value['eligibility']=eligibility
    value['sha256']=digest(value)
    path=folder/f'{name}.v{version}.json'
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
    return path


def load(path):
    value=json.loads(Path(path).read_text(encoding='utf-8'))
    unsigned={k:v for k,v in value.items() if k!='sha256'}
    ids=value['project_ids']
    if (value.get('schema_version')!='EVALUATION_CONTRACT_V1' or digest(unsigned)!=value.get('sha256') or
            not ids or len(set(ids))!=len(ids) or len(ids)!=value['selected_count'] or
            any(not isinstance(pid,str) or not pid for pid in ids)):
        raise ValueError('Contrato corrupto o modificado; crear otra version')
    return value


def resolve(value,population,catalog,additional=0):
    if (value['sources']!=population['sources'] or value['population_sha256']!=population['population_sha256'] or
            value['catalog_sha256']!=catalog or value.get('selection_configuration_sha256')!=population.get('selection_configuration_sha256')):
        raise ValueError('Fuentes, mapeos, poblacion o catalogo incompatibles con el contrato')
    if type(additional) is not int or additional<0:raise ValueError('Limite adicional entero >= 0 requerido')
    features,eligibility=selection_population(population,'eligibility' in value)
    if value.get('eligibility')!=eligibility:raise ValueError('Poblacion evaluable o regla de elegibilidad incompatible')
    mandatory=value['project_ids']
    if set(mandatory)-features.keys():raise ValueError('IDs obligatorios ausentes o sin texto autorizado')
    if eligibility and mandatory!=sample_projects(features,len(mandatory),value['seed']):
        raise ValueError('Muestra evaluable incompatible con la semilla del contrato')
    remaining={k:v for k,v in features.items() if k not in mandatory}
    extra=sample_projects(remaining,additional,value['seed']) if additional else []
    result=dict(contract_id=value['contract_id'],version=value['version'],sha256=value['sha256'],
        catalog_sha256=value['catalog_sha256'],sources=value['sources'],mandatory_project_ids=mandatory,
        additional_project_ids=extra,project_ids=mandatory+extra,additional_limit=additional)
    if eligibility:result.update(eligibility=eligibility,seed=value['seed'])
    return result


def menu(root,coordinator,config_path='config/pipeline_manual.json',*,defer_validation=False):
    while True:
        print('\nContratos de evaluacion\n1. Crear contrato\n2. Utilizar contrato existente\n0. Volver')
        answer=input('Opcion: ').strip()
        if answer=='0':return None
        if answer=='1':
            name=input('Nombre del contrato: ').strip()
            count=int(input('Cantidad de proyectos obligatorios: '))
            seed=int(input('Semilla de seleccion (42): ').strip() or '42')
            choice=input('Exigir texto sustantivo autorizado [S/N] (S): ').strip().upper() or 'S'
            if choice not in ('S','N'):raise ValueError('Responder S o N')
            if count<=0:raise ValueError('Cantidad positiva requerida')
            if defer_validation:
                return dict(limit=None,all_projects=False,seed=seed,project_count=count,
                    contract_label=name+' (nuevo)',
                    create_contract=dict(name=name,count=count,seed=seed,require_evaluable=choice=='S'))
            path=create(root,name,count,seed,inventory(root,coordinator,config_path),catalog_hash(root),require_evaluable=choice=='S')
            print('Contrato guardado: '+str(path)+'; no se iniciaron inferencias.')
        elif answer=='2':
            paths=sorted((Path(root)/'data/contratos').glob('*.json'))
            if not paths:print('No hay contratos.');continue
            for i,path in enumerate(paths,1):print(f'{i}. {path.name}')
            number=int(input('Contrato (0: volver): '))
            if number==0:continue
            if not 1<=number<=len(paths):raise ValueError('Contrato invalido')
            value=load(paths[number-1])
            answer=input('¿Desea procesar proyectos adicionales? (S/N): ').strip().upper()
            if answer not in ('S','N'):raise ValueError('Responder S o N')
            additional=int(input('Limite explicito de proyectos adicionales: ')) if answer=='S' else 0
            if answer=='S' and additional<=0:raise ValueError('Limite positivo requerido')
            if defer_validation:
                return dict(limit=None,all_projects=False,seed=value['seed'],
                    contract_path=paths[number-1].relative_to(root).as_posix(),additional_count=additional,
                    project_count=value['selected_count']+additional,contract_label=paths[number-1].name)
            result=resolve(value,inventory(root,coordinator,config_path),catalog_hash(root),additional)
            print(f"Seleccion: {len(value['project_ids'])} obligatorios + {additional} adicionales. La ejecucion requiere su autorizacion posterior.")
            return dict(limit=None,all_projects=False,seed=value['seed'],project_ids=result['project_ids'],contract_metadata=result)
