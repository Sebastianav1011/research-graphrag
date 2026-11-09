"""Behavioral tests for factual expansion with measured semantic support."""
import copy
import json
import pytest
from layer3_graphrag.embeddings import build_embeddings
from layer3_graphrag.graph import build_graph
from layer3_graphrag.indicator_retrieval import IndicatorRetriever, diverse
from layer3_graphrag.vector_index import NumpyVectorIndex
from layer3_graphrag.quality import validate_retrieval


def service(snapshot, fake_provider, layer3_config):
    cfg = copy.deepcopy(layer3_config)
    cfg['embeddings'].update(model=fake_provider.model_name, model_version=fake_provider.model_version,
        dimensions=fake_provider.dimensions, batch_size=fake_provider.batch_size)
    cfg['retrieval'].update(enabled=True, vector_top_k_per_reference_chunk=1)
    bundle = build_embeddings(snapshot, 'SOURCE', fake_provider, cfg['embeddings'], 'unit')
    index = NumpyVectorIndex('SOURCE')
    index.build(bundle)
    graph = build_graph(snapshot)
    return IndicatorRetriever(snapshot, index, fake_provider, graph, cfg, 'unit'), cfg


def test_graph_cannot_promote_zero_semantic_support(snapshot, fake_provider, layer3_config):
    retriever, cfg = service(snapshot, fake_provider, layer3_config)
    rows, expanded, metrics = retriever.score_rows(['forest'], ['c-reference'])
    assert {r['source_id'] for r in rows} == {'P1'}
    assert any(r['canonical_id'] == 'A1' for r in expanded['entities'])
    assert metrics['ambiguous_bridge_uses'] == 0
    assert rows[0]['hybrid_score'] == pytest.approx(.8)


def test_reference_batch_preserves_source_and_provenance(snapshot, fake_provider, layer3_config):
    retriever, cfg = service(snapshot, fake_provider, layer3_config)
    candidates, packages, comparison, metrics = retriever.process()
    assert len(packages) == 1
    assert all('c-reference' not in r['discovery_chunk_ids'] for r in candidates)
    assert candidates[0]['reference_chunk_ids'] == ['c-reference']
    result, issues, anomalies, privacy = validate_retrieval(snapshot, retriever.graph, candidates, packages, cfg)
    assert result['status'] == 'PASS' and not issues and not anomalies and not privacy
    assert comparison[0]['graph_candidates'] == 0


def test_ambiguous_bridge_is_blocked_and_invalid_path_rejected(snapshot, fake_provider, layer3_config):
    snapshot.tables['entities'][2]['metadata_json'] = json.dumps({'identity_status': 'ambiguous'})
    retriever, cfg = service(snapshot, fake_provider, layer3_config)
    _, expanded, _ = retriever.score_rows(['forest'], ['c-reference'])
    assert not any(r['canonical_id'] == 'A1' for r in expanded['entities'])
    with pytest.raises(ValueError, match='bridge'):
        retriever.check_path('ARTICLE:A1', ['rel-PROJECT:P1', 'rel-ARTICLE:A1'], ['PROJECT:P1'])


def test_diversity_retains_best_chunks_and_deterministic_ties():
    rows = [{'chunk_id': str(n), 'source_type': 'PROJECT', 'source_id': 'p' if n < 5 else 'q', 'score': 1-n*.01} for n in range(8)]
    chosen = diverse(rows, 'score', 6, 3)
    assert [r['chunk_id'] for r in chosen] == ['0','1','2','5','6','7']


def test_zero_candidates_is_not_missing_catalogue_coverage(snapshot, fake_provider, layer3_config):
    retriever, cfg = service(snapshot, fake_provider, layer3_config)
    ids=[row['source_id'] for row in snapshot.tables['reference_documents']]
    result, issues, anomalies, privacy=validate_retrieval(snapshot,retriever.graph,[],[],cfg,
        considered_indicators=ids)
    assert result['status']=='PASS' and not issues and not anomalies and not privacy
    # A missing or duplicate query still fails, independently of candidate count.
    for ledger in ([],ids+ids):
        result,_,anomalies,_=validate_retrieval(snapshot,retriever.graph,[],[],cfg,
            considered_indicators=ledger)
        assert result['status']=='FAIL'
        assert any(row['reason']=='Indicator query coverage mismatch' for row in anomalies)
    assert validate_retrieval(snapshot,retriever.graph,[],[],cfg)[0]['status']=='FAIL'


@pytest.mark.parametrize('criterion,selected',[('forest restoration',True),('sea conservation',False)])
@pytest.mark.parametrize('original',['forest restoration','  forest  restoration\r\n','forest\u200b restoration'])
def test_provisional_admission_needs_substantive_criterion_evidence_without_edges(snapshot,fake_provider,layer3_config,criterion,selected,original):
    from autonomous_execution.discovery import select,admission_settings
    snapshot.tables['relations']=[]
    for table in ('source_sections','source_chunks'):
        for row in snapshot.tables[table]:row['field_name']='summary' if row['source_type']=='PROJECT' else 'abstract'
    snapshot.tables['source_sections'][0]['text_original']=original
    retriever,cfg=service(snapshot,fake_provider,layer3_config)
    profiles={'I1':dict(indicator_id='I1',indicator_name='indicator forest')}
    rubrics={'I1':dict(criteria=[dict(criterion_id='C01',criterion=criterion)])}
    audit,candidates,_=select(retriever,profiles,rubrics,['P1'],admission_settings(cfg))
    assert audit['project_indicators']=={'P1':['I1'] if selected else []}
    assert len(audit['comparisons'])==1 and audit['graph_relations']==0
    assert audit['comparisons'][0]['selected']==selected
    assert not audit['comparisons'][0]['graph_contribution']
    assert bool(candidates)==selected
    assert audit['confidence_used'] is False and audit['selection_is_compliance'] is False
    assert retriever.settings['vector_top_k_per_reference_chunk']==1


@pytest.mark.parametrize('corruption',['text','offset','source','field'])
def test_discovery_still_rejects_unverifiable_chunks(snapshot,fake_provider,layer3_config,corruption):
    from autonomous_execution.discovery import select,admission_settings
    for table in ('source_sections','source_chunks'):
        snapshot.tables[table][0]['field_name']='summary'
    retriever,cfg=service(snapshot,fake_provider,layer3_config)
    section=snapshot.tables['source_sections'][0]
    section[dict(text='text_normalized',offset='text_normalized',source='source_id',field='field_name')[corruption]]={
        'text':'corrupt passage longer than the original', 'offset':'short', 'source':'FOREIGN', 'field':'other'}[corruption]
    with pytest.raises(ValueError,match='text_normalized: c-project'):
        select(retriever,{}, {},['P1'],admission_settings(cfg))


@pytest.mark.parametrize('failure',[{'error_type':'ValueError','error_message':'Invalid chunk offsets'},None])
def test_discovery_preparation_reports_current_worker_failure(tmp_path,monkeypatch,failure):
    from types import SimpleNamespace
    from autonomous_execution.discovery import prepare
    run=tmp_path/'outputs/runs/failed';run.mkdir(parents=True)
    log=run/'discovery.stderr.log'
    previous=json.dumps(dict(error_type='OldError',error_message='Stale failure'))+'\n'
    log.write_text(previous,encoding='utf-8')
    def worker(*args,**kwargs):
        if failure:kwargs['stderr'].write((json.dumps(failure)+'\n').encode('utf-8'))
        return SimpleNamespace(returncode=2)
    monkeypatch.setattr('autonomous_execution.discovery.subprocess.run',worker)
    with pytest.raises(ValueError) as caught:prepare(tmp_path,run)
    message=str(caught.value)
    assert 'DISCOVERY_PREPARATION_FAILED' in message and str(log) in message
    assert ('ValueError: Invalid chunk offsets' if failure else 'exit_code=2') in message
    assert 'Stale failure' not in message and log.read_text(encoding='utf-8').startswith(previous)


def test_title_only_never_admits_and_all_indicators_are_logged(snapshot,fake_provider,layer3_config):
    from autonomous_execution.discovery import select,admission_settings
    retriever,cfg=service(snapshot,fake_provider,layer3_config)
    profile=dict(indicator_name='forest')
    # No quota: both descriptors match the title, neither has substantive proof.
    profiles={'I1':profile,'I2':profile}
    snapshot.tables['reference_chunks'].append(dict(snapshot.tables['reference_chunks'][0],source_id='I2',chunk_id='ref2'))
    rubrics={iid:dict(criteria=[dict(criterion_id='C01',criterion='forest')]) for iid in profiles}
    audit,candidates,_=select(retriever,profiles,rubrics,['P1'],admission_settings(cfg))
    assert audit['project_indicators']=={'P1':[]} and not candidates
    assert len(audit['comparisons'])==2
    assert {row['reason'] for row in audit['comparisons']}=={'NO_AUTHORIZED_SUBSTANTIVE_PASSAGE'}


def test_project_selection_is_independent_and_has_no_candidate_quota(snapshot,fake_provider,layer3_config):
    from autonomous_execution.discovery import select,admission_settings
    snapshot.tables['relations']=[]
    for name in ('source_documents','source_sections','source_chunks'):
        for row in snapshot.tables[name]:
            if row['source_type']=='ARTICLE':row.update(source_type='PROJECT',source_id='P2')
            if 'field_name' in row:row['field_name']='summary'
    for row in snapshot.tables['entities']:
        if row['entity_type']=='ARTICLE':row.update(entity_type='PROJECT',entity_id='PROJECT:P2',canonical_id='P2')
    reference=snapshot.tables['reference_chunks'][0]
    snapshot.tables['reference_chunks'].append(dict(reference,source_id='I2',chunk_id='ref2',text='indicator sea'))
    retriever,cfg=service(snapshot,fake_provider,layer3_config)
    profiles={iid:dict(indicator_name=topic) for iid,topic in [('I1','forest'),('I2','sea')]}
    rubrics={iid:dict(criteria=[dict(criterion_id='C01',criterion=p['indicator_name'])]) for iid,p in profiles.items()}
    audit,candidates,_=select(retriever,profiles,rubrics,['P1','P2'],admission_settings(cfg))
    assert audit['project_indicators']=={'P1':['I1'],'P2':['I2']}
    assert len(audit['comparisons'])==4 and len(candidates)==2
    alone,_,_=select(retriever,profiles,rubrics,['P1'],admission_settings(cfg))
    assert alone['project_indicators']['P1']==audit['project_indicators']['P1']


def test_queries_batch_and_reuse_verified_cache(snapshot,fake_provider,layer3_config):
    retriever,cfg=service(snapshot,fake_provider,layer3_config)
    first=retriever.query_vectors(['forest','sea','forest'])
    assert fake_provider.query_calls==[['forest','sea']]
    second=retriever.query_vectors(['forest','sea','forest'])
    assert (first==second).all() and len(fake_provider.query_calls)==1
