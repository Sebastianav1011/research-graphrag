"""Small offline regressions for the diagnosed scope/context defects."""
from copy import deepcopy
import numpy as np

from tests.test_context_budget import corpus
from tests.test_ollama_provider import sample
from layer4_evaluation.indicators.scoped_retrieval import rank_project_passages
from layer4_evaluation.indicators import context_budget as cb, evidence_references as refs
from layer4_evaluation.indicators.validation_diagnostics import semantic_issues


def test_each_project_receives_its_own_substantive_passages_despite_articles():
    projects=[dict(project_id=p,fields={'methodology':''}) for p in ('P1','P2')]
    chunks=[dict(chunk_id='A',source_id='ARTICLE',source_type='ARTICLE',field_name='methodology'),
        dict(chunk_id='T',source_id='P1',source_type='PROJECT',field_name='title'),
        dict(chunk_id='M1',source_id='P1',source_type='PROJECT',field_name='methodology'),
        dict(chunk_id='M2',source_id='P2',source_type='PROJECT',field_name='methodology')]
    rows=rank_project_passages(projects,{'I1':{},'I2':{}},chunks,[dict(chunk_id=c['chunk_id']) for c in chunks],
        np.asarray([[1.,0.],[1.,0.],[.6,.8],[0.,1.]]),
        {i:(['R'],np.asarray([[1.,0.]])) for i in ('I1','I2')})
    assert len(rows)==4
    assert all([h['chunk_id'] for h in c['discovery_chunks']]==(['M1'] if c['source_id']=='P1' else ['M2']) for c in rows)


def test_graph_paths_rank_external_context_without_leaking_external_evidence():
    from tests.test_context_budget import relational_fixture
    chunks=[dict(chunk_id='C'+p,source_id=p,source_type='PROJECT',field_name='methodology',text='Text '+p)
        for p in ('P1','UNSELECTED')]
    rows=rank_project_passages([dict(project_id='P1',fields={'methodology':''})],{'I1':{}},chunks,
        [dict(chunk_id=c['chunk_id']) for c in chunks],np.asarray([[.8,.6],[1.,0.]]),
        {'I1':(['QUERY'],np.asarray([[1.,0.]]))},{'P1':relational_fixture('P1')})
    assert len(rows)==1 and [h['chunk_id'] for h in rows[0]['discovery_chunks']]==['CP1']
    context=rows[0]['relational_context']
    assert context['support_paths']['UNSELECTED']==['E1','E2']
    assert len(context['relations'])==2 and context['relations'][0]['provenance']['source_row']==1


def test_orientation_only_is_not_reported_as_token_budget_failure(corpus):
    corpus.project['fields']['title']=corpus.chunks[0]['text']
    corpus.chunks[0]['field_name']='title';corpus.sections[0]['field_name']='title'
    for hit in corpus.hits:hit['discovery_chunks'][0]['field_name']='title'
    requests,_=cb.prepare_contexts([corpus.project],corpus.profiles,corpus.rubrics,corpus.settings,
        corpus.hits,corpus.chunks,corpus.sections,evidence_references=True)
    request=requests['TEST_PROJECT']['I00']
    assert request['context_budget']['fits']
    assert request['context_selection']['status']=='NO_SUBSTANTIVE_CONTEXT'


def test_two_chunks_in_same_field_preserve_independent_literal_fragments(corpus):
    old=corpus.chunks[0]['text']; new='A second documented action is performed.'
    corpus.project['fields']['methodology']=old+'\n\n'+new
    corpus.sections[0]['text_original']=corpus.project['fields']['methodology']
    corpus.chunks.append(corpus.chunks[0]|dict(chunk_id='SECOND',text=new,char_start=len(old)+2,char_end=len(old)+2+len(new)))
    for hit in corpus.hits:hit['discovery_chunks'].append(dict(chunk_id='SECOND',field_name='methodology',vector_rank=2))
    requests,_=cb.prepare_contexts([corpus.project],{'I00':corpus.profiles['I00']},corpus.rubrics,corpus.settings,
        [corpus.hits[0]],corpus.chunks,corpus.sections,evidence_references=True)
    r=requests['TEST_PROJECT']['I00']
    assert len(r['context_selection']['selected'])==2
    assert [f['text'] for f in r['payload']['project']['fragments']]==[old,new]
    assert len({f['fragment_id'] for f in r['payload']['project']['fragments']})==2


def test_empty_positive_strength_feedback_identifies_actual_field():
    issues=semantic_issues(['V3_POSITIVE_STRENGTH:REQUIRES_EVIDENCE'],{},'I')
    assert issues[0]['path']=='$.support_strength'
    assert 'no inventes' in issues[0]['correction_hint']
