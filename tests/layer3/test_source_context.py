"""SOURCE-level discovery, complete section references and orientation safeguards."""
import copy
import json
import pytest
from layer3_graphrag.source_context import SourceContextResolver, FIELD_ROLES
from layer3_graphrag.provenance import text_hash
from layer3_graphrag.embedding_pipeline import build_embeddings,save_bundle,reuse_bundle
from layer3_graphrag.indicator_retrieval import write_outputs
from layer3_graphrag.contracts import source_candidate_arrow_schema,source_context_arrow_schema


def add_section(snapshot,kind,field,text):
    original=next(r for r in snapshot.tables['source_sections'] if r['source_type']==kind)
    section=dict(original,section_id=original['document_id']+'-'+field,field_name=field,text_normalized=text,
        text_hash=text_hash(text),text_hash_normalized=text_hash(text),field_order=1)
    snapshot.tables['source_sections'].append(section)
    return section


def hit(snapshot,kind='PROJECT',score=.8):
    chunk=next(c for c in snapshot.tables['source_chunks'] if c['source_type']==kind)
    return chunk|{'vector_score':score,'vector_rank':1,'graph_score':0.,'graph_hops':None,'graph_path_json':'[]',
        'reference_chunk_ids':['c-reference'],'retrieval_origin':'VECTOR'}


@pytest.mark.parametrize('kind,fields',[('PROJECT',('summary','methodology','objectives','expected_results')),('ARTICLE',('abstract',))])
def test_title_hit_attaches_all_existing_substantive_fields(snapshot,layer3_config,kind,fields):
    for field in fields: add_section(snapshot,kind,field,'Full substantive text '+field)
    add_section(snapshot,kind,'keywords','forest culture')
    resolver=SourceContextResolver(snapshot)
    rows,contexts=resolver.group_candidates([hit(snapshot,kind)],'I1',layer3_config,'fingerprint','run')
    assert len(rows)==len(contexts)==1
    assert rows[0]['context_status']=='ASSESSMENT_READY'
    assert rows[0]['discovery_field_names']==['title']
    assert {s['field_name'] for s in contexts[0]['substantive_sections']}==set(fields)
    assert set(rows[0]['available_field_names'])==set(fields)|{'title','keywords'}
    assert all('text' not in s for s in contexts[0]['substantive_sections'])
    assert all('evidence' not in key and 'confidence' not in key and 'decision' not in key for key in rows[0])


def test_orientation_only_retained_without_negative_assessment(snapshot,layer3_config):
    add_section(snapshot,'PROJECT','keywords','culture')
    add_section(snapshot,'PROJECT','summary','  ')
    rows,contexts=SourceContextResolver(snapshot).group_candidates([hit(snapshot)],'I1',layer3_config,'f','run')
    assert rows[0]['context_status']=='DISCOVERY_ONLY'
    assert rows[0]['substantive_section_ids']==[]
    assert len(contexts[0]['orientation_sections'])==2
    assert 'decision' not in rows[0]


def test_grouping_not_chunk_volume_and_roundtrip(snapshot,layer3_config,tmp_path):
    row=hit(snapshot)
    chunk=copy.deepcopy(snapshot.tables['source_chunks'][0]); chunk['chunk_id']='another-project-chunk'; snapshot.tables['source_chunks'].append(chunk)
    other=dict(row,chunk_id=chunk['chunk_id'],vector_score=.7,vector_rank=2)
    resolver=SourceContextResolver(snapshot)
    candidates,contexts=resolver.group_candidates([other,row],'I1',layer3_config,'f','r')
    assert len(candidates)==1
    assert len(candidates[0]['discovery_chunk_ids'])==2
    assert candidates[0]['best_vector_score']==.8
    assert candidates[0]['hybrid_retrieval_score']==pytest.approx(.8*.9)
    reversed_rows,_=resolver.group_candidates([row,other],'I1',layer3_config,'f','other-run')
    assert {k:v for k,v in reversed_rows[0].items() if k!='layer3_run_id'}=={k:v for k,v in candidates[0].items() if k!='layer3_run_id'}
    write_outputs(tmp_path/'retrieval',candidates,contexts)
    assert not (tmp_path/'retrieval/indicator_candidates.parquet').exists()
    assert not (tmp_path/'retrieval/context_packages.parquet').exists()


def test_reference_never_source_context(snapshot,layer3_config):
    reference=snapshot.tables['reference_chunks'][0]
    with pytest.raises(ValueError,match='Non-SOURCE'):
        SourceContextResolver(snapshot).group_candidates([reference],'I1',layer3_config,'f','r')


def test_provenance_references_all_sections_without_text_duplication(snapshot,layer3_config):
    section=add_section(snapshot,'PROJECT','summary','Secret-to-duplicate-long-full-field')
    candidates,contexts=SourceContextResolver(snapshot).group_candidates([hit(snapshot)],'I1',layer3_config,'f','r')
    prov=json.loads(candidates[0]['provenance_json'])
    assert prov['layer2_manifest_hash']==snapshot.manifest_hash
    assert prov['layer1_run_id']==snapshot.manifest['layer1_run_id']
    assert section['section_id'] in [s['section_id'] for s in prov['sections']]
    assert section['text_normalized'] not in candidates[0]['provenance_json']


def test_compatible_embeddings_reused_without_provider_calls(snapshot,fake_provider,layer3_config,tmp_path):
    settings=layer3_config['embeddings']|{'model':fake_provider.model_name,'model_version':fake_provider.model_version,'dimensions':3,'batch_size':2}
    original=build_embeddings(snapshot,'SOURCE',fake_provider,settings,'before')
    save_bundle(original,tmp_path/'embeddings')
    fake_provider.document_calls.clear()
    reused=reuse_bundle(tmp_path/'embeddings',snapshot,'SOURCE',fake_provider,settings,'after')
    assert reused is not None and fake_provider.document_calls==[]
    assert reused.metadata['computed_unique_texts']==0
    assert [r['embedding_id'] for r in reused.records]==[r['embedding_id'] for r in original.records]
    assert reuse_bundle(tmp_path/'embeddings',snapshot,'SOURCE',fake_provider,settings|{'normalization_version':'changed'},'after') is None


def test_graph_expanded_source_reconstructs_unretrieved_substantive_section(snapshot,fake_provider,layer3_config):
    import numpy as np
    from layer3_graphrag.indicator_retrieval import IndicatorRetriever
    from layer3_graphrag.vector_index import NumpyVectorIndex
    from layer3_graphrag.graph_builder import build_graph
    # A deterministic synthetic provider gives ARTICLE partial query similarity;
    # PROJECT remains the sole top-1 vector seed, then factual graph expands ARTICLE.
    class PartialProvider(type(fake_provider)):
        def _embed(self,texts):
            return np.asarray([[.6,.8,0.] if 'sea' in t else [1.,0.,0.] for t in texts],dtype=np.float32)
    provider=PartialProvider()
    cfg=copy.deepcopy(layer3_config)
    cfg['embeddings'].update(model=provider.model_name,model_version=provider.model_version,dimensions=3,batch_size=2)
    cfg['retrieval'].update(enabled=True,vector_top_k_per_reference_chunk=1)
    add_section(snapshot,'ARTICLE','abstract','Full abstract was not a vector hit')
    bundle=build_embeddings(snapshot,'SOURCE',provider,cfg['embeddings'],'test')
    index=NumpyVectorIndex('SOURCE'); index.build(bundle)
    retriever=IndicatorRetriever(snapshot,index,provider,build_graph(snapshot),cfg,'test')
    candidates,contexts,expanded,metrics=retriever.retrieve_sources(['forest'],['c-reference'],'I1')
    article=next(r for r in candidates if r['source_type']=='ARTICLE')
    assert article['graph_hops']==2
    assert article['discovery_retrieval_origins']==['GRAPH_SEMANTIC_RECHECK']
    assert article['context_status']=='ASSESSMENT_READY'
    context=next(p for p in contexts if p['source_type']=='ARTICLE')
    assert context['substantive_sections'][0]['field_name']=='abstract'
    assert metrics['ambiguous_bridge_uses']==0


def test_many_keyword_discovery_chunks_do_not_inflate_score(snapshot,layer3_config):
    section=add_section(snapshot,'PROJECT','keywords','forest')
    original=hit(snapshot)
    rows=[original]
    for n in range(10):
        chunk=dict(snapshot.tables['source_chunks'][0],chunk_id=f'keyword-{n}',field_name='keywords',section_id=section['section_id'])
        snapshot.tables['source_chunks'].append(chunk)
        rows.append(dict(original,chunk_id=chunk['chunk_id'],field_name='keywords'))
    resolver=SourceContextResolver(snapshot)
    many,_=resolver.group_candidates(rows,'I1',layer3_config,'f','r')
    one,_=resolver.group_candidates([original],'I1',layer3_config,'f','r')
    assert many[0]['hybrid_retrieval_score']==one[0]['hybrid_retrieval_score']
    assert len(many)==1 and len(many[0]['discovery_chunk_ids'])==3


def test_multiple_documents_for_one_source_rejected(snapshot):
    snapshot.tables['source_documents'].append(dict(snapshot.tables['source_documents'][0],document_id='other-doc'))
    with pytest.raises(ValueError,match='multiple documents'):
        SourceContextResolver(snapshot)
