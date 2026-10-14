"""Stable publication verification, idempotence and regression operations."""
import json
import os
from pathlib import Path
import subprocess
import sys
import numpy as np
import pyarrow.parquet as pq

from .configuration import load_config
from .embedding_pipeline import load_bundle
from .graph_store import LocalGraphStore
from .manifest import validate_publication
from .provenance import file_hash,serialize
from .source_quality import validate_retrieval
from .validate_inputs import validate_inputs,assert_unchanged


def verify(root,config_path='config/layer3.yaml'):
    root=Path(root); config,_=load_config(root,config_path); snapshot=validate_inputs(root,config)
    directory=root/config['outputs']['publication']; manifest=validate_publication(directory,snapshot.manifest_hash)
    if manifest.get('candidate_architecture')!='SOURCE_INDICATOR_V1': raise ValueError('Published candidate architecture is not SOURCE_INDICATOR_V1')
    if any((directory/'retrieval'/name).exists() for name in ('indicator_candidates.parquet','context_packages.parquet')): raise ValueError('Obsolete active retrieval outputs')
    candidates=pq.read_table(directory/'retrieval/source_indicator_candidates.parquet').to_pylist()
    packages=pq.read_table(directory/'retrieval/source_context_packages.parquet').to_pylist()
    graph=LocalGraphStore.load(directory/'graph')
    result,issues,anomalies,privacy=validate_retrieval(snapshot,graph,candidates,packages,config)
    embedding_checks={}
    for space in ('SOURCE','REFERENCE'):
        bundle=load_bundle(directory/'embeddings'/space.lower())
        embedding_checks[space]={'count':len(bundle.records),'dimensions':bundle.vectors.shape[1],
            'reused':bundle.metadata.get('reuse_origin')=='VERIFIED_PUBLICATION','computed':bundle.metadata['computed_unique_texts']}
        if len(bundle.records)!=len(snapshot.tables[space.lower()+'_chunks']): raise ValueError('Incomplete published embeddings')
        del bundle
    assert_unchanged(snapshot)
    report={'status':result['status'],'layer3_run_id':manifest['layer3_run_id'],'layer3_manifest_hash':file_hash(directory/'_manifest.json'),
        'retrieval':result,'embedding_checks':embedding_checks,'issues':issues,'anomalies':anomalies,'privacy':privacy,
        'indicator_profiles_status':'PENDING_GROUP_REVIEW'}
    reports=root/config['outputs']['reports']; reports.mkdir(parents=True,exist_ok=True)
    (reports/'source_publication_verification.json').write_text(serialize(report),encoding='utf-8')
    if result['status']!='PASS': raise ValueError('Source publication verification failed')
    return report


def compare(root,config_path='config/layer3.yaml'):
    root=Path(root); config,_=load_config(root,config_path); directory=root/config['outputs']['publication']
    latest=validate_publication(directory); previous=root/config['outputs']['base']/'runs'/latest['layer3_run_id']/'previous_graphrag'
    before=validate_publication(previous,latest['layer2_manifest_hash'])
    if before['layer3_config_hash']!=latest['layer3_config_hash'] or before['embedding_config_hash']!=latest['embedding_config_hash']: raise ValueError('Two builds must use the same config/model/snapshot')
    checks={}; operational={'layer3_run_id'}
    for name in ('source_indicator_candidates','source_context_packages'):
        a=pq.read_table(previous/'retrieval'/f'{name}.parquet').to_pylist(); b=pq.read_table(directory/'retrieval'/f'{name}.parquet').to_pylist()
        checks[name]=[{k:v for k,v in r.items() if k not in operational} for r in a]==[{k:v for k,v in r.items() if k not in operational} for r in b]
    checks.update(candidate_ids=checks['source_indicator_candidates'],candidate_rankings=checks['source_indicator_candidates'],
        discovery_chunk_mappings=checks['source_indicator_candidates'],source_contexts=checks['source_context_packages'],
        graph_nodes=file_hash(previous/'graph/graph.json')==file_hash(directory/'graph/graph.json'),
        graph_edges=file_hash(previous/'graph/graph.json')==file_hash(directory/'graph/graph.json'))
    for space in ('source','reference'):
        a=np.load(previous/'embeddings'/space/'vectors.npy',mmap_mode='r'); b=np.load(directory/'embeddings'/space/'vectors.npy',mmap_mode='r')
        checks[space+'_numerical_embeddings']=a.shape==b.shape and all(np.allclose(a[n:n+512],b[n:n+512],atol=1e-6,rtol=0) for n in range(0,len(a),512))
        ma=json.loads((previous/'embeddings'/space/'records.json').read_text()); mb=json.loads((directory/'embeddings'/space/'records.json').read_text())
        checks[space+'_embedding_mappings']=[{k:v for k,v in r.items() if k not in operational} for r in ma]==[{k:v for k,v in r.items() if k not in operational} for r in mb]
        del a,b,ma,mb
    stable=('pipeline_version','layer2_manifest_hash','embedding_config_hash','embedding_model','code_hashes','candidate_architecture','candidate_unit','discovery_unit','source_context_storage','indicator_profiles_status','retrieval_parameters','graph_parameters','hybrid_weights','indicator_count','candidate_count','context_package_count','input_hashes')
    checks['manifest_payloads']=all(before.get(k)==latest.get(k) for k in stable)
    report={'status':'PASS' if all(checks.values()) else 'FAIL','builds':[before['layer3_run_id'],latest['layer3_run_id']],'atol':1e-6,'rtol':0,'checks':checks,
        'operational_fields_excluded':['run_id','timestamps','latencies','physical metadata hashes that include run_id']}
    (root/config['outputs']['reports']/'idempotence.json').write_text(serialize(report),encoding='utf-8')
    if report['status']!='PASS': raise ValueError('Source-level idempotence failed')
    return report


def regressions(root,real=False):
    root=Path(root); reports=root/'outputs/layer3/reports'; reports.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    if real: env.update(LAYER2_REAL_INTEGRATION='1',LAYER2_VERIFY_PUBLICATION='1',LAYER3_RUN_REAL_INTEGRATION='1')
    for layer in ('layer1','layer2','layer3'):
        args=[sys.executable,'-B','-m','pytest','tests/'+layer,'-q','-p','no:cacheprovider','--basetemp=outputs/layer3/'+layer+'-refactor-tests','--junitxml=outputs/layer3/reports/'+layer+'_source_regression.xml']
        if not real and layer!='layer1': args+=['--ignore=tests/'+layer+('/test_integration_real.py' if layer=='layer2' else '/test_integration_pending.py')]
        subprocess.run(args,cwd=root,env=env,check=True)
    return {'status':'PASS','real_integration':real}


def approve(root,manifest_sha256,config_path='config/layer3.yaml'):
    import yaml
    from .configuration import inside
    root=Path(root); config,_=load_config(root,config_path)
    if not manifest_sha256 or file_hash(root/'data/knowledge/_manifest.json')!=manifest_sha256:
        raise ValueError('Explicit current Layer 2 manifest SHA-256 required')
    config['readiness']={'layer2_status':'FINAL_PROJECT_LAYER_2_READY','approved_layer2_manifest_sha256':manifest_sha256}
    snapshot=validate_inputs(root,config)
    assert_unchanged(snapshot)
    inside(root,config_path,('config',)).write_text(yaml.safe_dump(config,sort_keys=False),encoding='utf-8')
    return {'status':'APPROVED_VALIDATED_LAYER_2_SNAPSHOT','layer2_run_id':snapshot.manifest['layer2_run_id'],'layer2_manifest_hash':manifest_sha256}
