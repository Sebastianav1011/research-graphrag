"""Prepare metadata and validate frozen inputs; no project loading or engine execution."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import yaml
import pyarrow.parquet as pq
from jsonschema import Draft202012Validator,FormatChecker
from layer1_data.dane_reference import load_reference
from layer4.indicators.profiles import load_profiles
from layer4.indicators.confidence import load_confidence_config
from .contracts import load_schema,check_contracts


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(root):
    root=Path(root).resolve()
    config=yaml.safe_load((root/'config/layer4_preliminary.yaml').read_text(encoding='utf-8'))
    if (config['version']!='LAYER4_PRELIMINARY_PREPARATION_V1'
            or config['execution']!={'assessment_enabled':False,'sample_selection_enabled':False,'workbook_generation_enabled':False}
            or config['planned_project_count']!=20 or config['candidate_limit_per_project']!=2
            or config['country_internal_code']!='000' or config['country_internal_code_system']!='INTERNAL'
            or config['assessment_engine']!='UNCONFIGURED' or config['assessment_engine_status']!='NOT_EXECUTED'
            or config['confidence_version']!='RAW_CONFIDENCE_V1'):
        raise ValueError('Preparation config must not enable selection, providers or real workbook generation')
    check_contracts(root)
    profiles,profile_manifest=load_profiles(root)
    confidence=load_confidence_config(root/'config/layer4_confidence.yaml')
    if {k:str(v) for k,v in confidence['weights'].items()}!={
        'key_element_coverage':'0.35','field_relevance':'0.30','corroboration':'0.20','support_strength':'0.15'}:
        raise ValueError('Official RAW_CONFIDENCE_V1 weights changed')
    layer3_path=root/config['layer3_manifest']
    layer3_hash=digest(layer3_path)
    layer3=json.loads(layer3_path.read_text(encoding='utf-8'))
    if layer3.get('status')!='SUCCESS' or layer3.get('candidate_architecture')!='SOURCE_INDICATOR_V1':
        raise ValueError('Expected the frozen historical SOURCE_INDICATOR_V1 publication')
    candidate_path=root/'data/graphrag/retrieval/source_indicator_candidates.parquet'
    candidate_key=[k for k in layer3['output_hashes'] if str(k).replace('\\','/').endswith('retrieval/source_indicator_candidates.parquet')]
    if len(candidate_key)!=1 or digest(candidate_path)!=layer3['output_hashes'][candidate_key[0]]:
        raise ValueError('Historical candidate checksum mismatch')
    # Read indicator IDs only: do not load, rank or choose any PROJECT IDs.
    historical_ids=set(pq.read_table(candidate_path,columns=['indicator_id'])['indicator_id'].to_pylist())
    profile_ids={p['indicator_id'] for p in profiles}
    if historical_ids-profile_ids:raise ValueError('Historical indicator IDs missing from assessment v2')
    _,dane=load_reference(root/'data/reference/processed')
    territory_path=root/config['territory_manifest']
    territory=json.loads(territory_path.read_text(encoding='utf-8'))
    if (territory.get('status')!='SUCCESS' or territory['architecture']!=config['territory_version']
            or territory['reference_id']!=dane['reference_id']):
        raise ValueError('Frozen territorial publication/reference mismatch')
    for name,item in territory['outputs'].items():
        if digest(territory_path.parent/name)!=item['sha256']:raise ValueError('Territorial publication hash mismatch')
    metadata={'output_status':'PREPARED_NOT_EXECUTED','project_count':0,
        'planned_project_count':20,'candidate_limit_per_project':2,'layer3_run':layer3['layer3_run_id'],
        'retrieval_indicator_version':config['retrieval_indicator_version'],
        'assessment_indicator_version':config['assessment_indicator_version'],
        'assessment_indicator_sha256':profile_manifest['source_hash'],
        'assessment_engine':'UNCONFIGURED','assessment_engine_status':'NOT_EXECUTED',
        'confidence_version':'RAW_CONFIDENCE_V1','confidence_is_probability':False,
        'territory_version':territory['architecture'],'dane_reference_sha256':dane['source_sha256'],
        'country_internal_code':'000','country_internal_code_system':'INTERNAL',
        'generated_at':datetime.now(timezone.utc).isoformat()}
    Draft202012Validator(load_schema(root,'metadata'),format_checker=FormatChecker()).validate(metadata)
    if digest(layer3_path)!=layer3_hash:raise ValueError('Layer 3 manifest changed during preparation')
    report={'preparation_status':'PREPARED_NOT_EXECUTED','metadata':metadata,
        'profile_reference_id':profile_manifest['reference_id'],'profile_metrics':profile_manifest['metrics'],
        'layer3_manifest_sha256':layer3_hash,'historical_indicator_count':len(historical_ids),
        'historical_indicator_ids_covered':True,'territory_summary':territory['summary'],
        'provider_implementations':[],'selected_project_ids':[], 'assessment_rows_created':0,
        'real_workbooks_created':0,'retrieval_executed':False,'embeddings_recalculated':False,
        'llm_executed':False,'external_api_used':False}
    out=root/'outputs/layer4/auditoria/historicos/preparacion_inicial';out.mkdir(parents=True,exist_ok=True)
    for name,value in [('prepared_metadata.json',metadata),('prepared_inputs.json',report)]:
        (out/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return report
