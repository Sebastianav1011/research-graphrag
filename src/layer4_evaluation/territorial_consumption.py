"""Read-only territorial consumption contract, distinct from historical closure.

Only six named PNG previews are optional. Original manifests/acceptance and every
nonvisual output remain fingerprinted; source provenance and keys are rechecked.
This module never extracts territories, renders, writes a workbook or infers.
"""
import csv
import json
from pathlib import Path

import pyarrow.parquet as pq

from layer2_processing.preprocessing.dane_reference import load_reference
from .territories.contracts import SCHEMAS, consumption_rows
from .territories.inputs import load_projects, check_unchanged, sha256
from .territories.pipeline import OUTPUT_NAMES, logical_hash, validate_result, _verify_workbook
from .paths import verify_expected, resolve

VERSION='LAYER4_TERRITORIAL_CONSUMPTION_V1'
CONTRACT_PATH='outputs/layer4/auditoria/territorial_consumption_contract.json'
REQUIRED=(
    'idempotence.json','project_national_mentions.parquet','project_territories.parquet',
    'project_territories_powerbi.csv','project_territory_ambiguous.parquet',
    'project_territory_evidence.parquet','quality.json','revision_territorios.xlsx',
    'revision_territorios.xlsx.inspect.ndjson','territory_summary.json',
)
OPTIONAL_PNGS=(
    'qa/AMBIGUOS.png','qa/AMBIGUOS_detail.png','qa/CATALOGO_DANE.png',
    'qa/METADATA.png','qa/RESUELTOS.png','qa/RESUELTOS_detail.png',
)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def require(condition,message):
    if not condition:raise ValueError(message)


def partition_outputs(manifest):
    """Explicit whitelist: never exempt an arbitrary path or future output."""
    require(set(manifest['outputs'])==set(REQUIRED)|set(OPTIONAL_PNGS),'Territorial output contract differs')
    return REQUIRED,OPTIONAL_PNGS


def historical_files(directory,manifest):
    """Informative full-file check; cannot claim historical PASS with missing PNG."""
    issues=[]
    for name,item in manifest['outputs'].items():
        path=directory/name
        try:
            if not path.is_file():issues.append(dict(path=name,status='MISSING'))
            elif sha256(path)!=item['sha256']:issues.append(dict(path=name,status='HASH_MISMATCH'))
        except OSError:issues.append(dict(path=name,status='UNREADABLE'))
    return dict(status='NOT_PASS' if issues else 'FILES_MATCH',issues=issues,
                scope='All 16 original output files; not a replacement for historical acceptance verifier')


def verify_consumption(root,selected=None,consumer_data=None):
    root=Path(root).resolve();directory=root/'outputs/layer4/territorios/publicacion'
    contract=read(root/CONTRACT_PATH)
    require(contract['version']==VERSION and contract['required_files']==list(REQUIRED) and
        contract['optional_visual_files']==list(OPTIONAL_PNGS),'Consumption policy differs')
    # Exact archived validator bytes and separately bound current relocation;
    # the frozen acceptance/contract is never rewritten.
    if sha256(Path(__file__)) != contract['validator_sha256']:
        verify_expected(root, 'src/layer4/territorial_consumption.py', contract['validator_sha256'])
    manifest_path=directory/'territory_manifest.json'
    acceptance_path=root/'outputs/layer4/territorios/aceptacion/final_acceptance.json'
    require(sha256(manifest_path)==contract['historical_manifest_sha256'],'Accepted territorial manifest changed')
    require(sha256(acceptance_path)==contract['historical_acceptance_sha256'],'Historical acceptance changed')
    manifest=read(manifest_path);acceptance=read(acceptance_path)
    require(manifest['status']=='SUCCESS' and manifest['architecture']=='PROJECT_TERRITORY_V1' and
        acceptance['status']=='LAYER4_TERRITORY_V1_READY' and
        acceptance['build_id']==manifest['build_id'] and acceptance['reference_id']==manifest['reference_id'] and
        acceptance['summary']==manifest['summary'],'Publication differs from accepted build')
    partition_outputs(manifest)
    for name in REQUIRED:
        path=directory/name;expected=manifest['outputs'][name]
        require(path.is_file(),'Missing mandatory territorial file: '+name)
        require(path.stat().st_size==expected['bytes'] and sha256(path)==expected['sha256'],
                'Mandatory territorial checksum differs: '+name)
    documents,sections,upstream=load_projects(root)
    require(upstream==manifest['layer2'],'Territorial Layer 2 source snapshot differs')
    dimension,reference=load_reference(root/'outputs/layer2/reference')
    require(reference==manifest['reference_manifest'] and reference['reference_id']==manifest['reference_id'],
            'Accepted reference snapshot differs')
    require(sha256(resolve(root,reference['source_file']))==reference['source_sha256'],'DANE source workbook differs')
    result={}
    for key,name in OUTPUT_NAMES.items():
        table=pq.read_table(directory/(name+'.parquet'))
        require(table.schema.equals(SCHEMAS[name]),'Territorial schema differs: '+name)
        result[key]=table.to_pylist()
    result['national_mentions']=pq.read_table(directory/'project_national_mentions.parquet').to_pylist()
    result['summary']=read(directory/'territory_summary.json')
    require(result['summary']==manifest['summary'],'Territorial summary differs')
    quality=validate_result(documents,sections,dimension,result)
    require({k:logical_hash(v) for k,v in result.items()}==manifest['payload_hashes'],'Accepted logical payload hashes differ')
    # Reuse the existing type/code-system, duplicate and COUNTRY coexistence rules.
    resolved=consumption_rows(result['relationships'],dimension)
    with (directory/'project_territories_powerbi.csv').open(encoding='utf-8-sig',newline='') as stream:
        require(list(csv.DictReader(stream))==result['relationships'],'Power BI bridge differs from accepted resolved data')
    idempotence=read(directory/'idempotence.json')
    require(idempotence['status']=='PASS' and idempotence['same_inputs_and_code'],'Historical idempotence is not accepted')
    require(read(directory/'quality.json')['status']=='PASS','Accepted territorial quality is not PASS')
    # This substantive workbook check reads cells; it never reads PNG previews.
    _verify_workbook(directory/'revision_territorios.xlsx',result,len(dimension))
    if consumer_data is not None:
        require(consumer_data['dimension']==dimension and consumer_data['relationships']==result['relationships'],
                'Supplied consumer bundle differs from accepted territories')
    selected_rows=None
    if selected is not None:
        from .indicators.final_projection import territories
        projects={d['source_id'] for d in documents}
        require(len({p['project_id'] for p in selected})==len(selected) and
            len({p['siap_id'] for p in selected})==len(selected) and
            all(p['project_id'] in projects and isinstance(p['siap_id'],str) and p['siap_id'] for p in selected),
            'Selected project/SIAP identities differ')
        selected_rows=len(territories(dict(dimension=dimension,relationships=result['relationships']),selected))
    check_unchanged(root,upstream)
    require(sha256(manifest_path)==contract['historical_manifest_sha256'],'Manifest changed during consumption check')
    return dict(status='PASS',contract=VERSION,scope='Substantive accepted territorial data for V3.3 consumption',
        accepted_build_id=manifest['build_id'],mandatory_files_verified=len(REQUIRED),optional_visual_files=len(OPTIONAL_PNGS),
        historical_full_verification=historical_files(directory,manifest),quality=quality,
        resolved_relationships=len(resolved),selected_projects=len(selected) if selected is not None else None,
        selected_territory_rows=selected_rows,original_hashes_preserved=True,territorial_data_modified=False,
        extraction_performed=False,inference_calls=0)
