"""Read-only PROJECT+INDICATOR retrieval from the published index/query cache.

Global discovery ranks documents competitively, including ARTICLEs. Exhaustive
project evaluation must instead rank the selected project's own substantive
passages. Missing cached queries are errors; this module never embeds or infers.
Scores order evidence only and never enter assessment or confidence.
"""
from collections import defaultdict
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from layer3_graphrag.embeddings import EmbeddingCache
from layer3_graphrag.manifest import validate_publication
from layer3_graphrag.provenance import digest
from layer3_graphrag.vector_index import NumpyVectorIndex
from .mapped_index import open_mapped
from .selection import substantive_fields

VERSION = 'OWN_PROJECT_CACHED_RETRIEVAL_V1'
# Access/compute policy only; hits, IDs and VERSION-derived candidate IDs are unchanged.
INDEX_ACCESS = 'MEMMAP_SELECTED_ROWS_FLOAT64_V1'


def project_relations(workspace,projects):
    """Read verified global graph facts with the existing bounded retriever; no model."""
    from layer3_graphrag.configuration import load_config
    from layer3_graphrag.validate_inputs import validate_inputs
    from layer3_graphrag.graph import LocalGraphStore
    from layer3_graphrag.graph_retriever import GraphRetriever
    workspace=Path(workspace)
    config,_=load_config(workspace)
    snapshot=validate_inputs(workspace,config)
    publication=workspace/'outputs/layer3/publication'
    manifest=validate_publication(publication,snapshot.manifest_hash)
    graph=LocalGraphStore.load(publication/'graph')
    if (set(graph.nodes)!={n['entity_id'] for n in snapshot.tables['entities']} or
            set(graph.relations)!={r['relation_id'] for r in snapshot.tables['relations']} or
            any(graph.relations[r['relation_id']]!=r for r in snapshot.tables['relations']) or
            any(any(graph.nodes[n['entity_id']][k]!=n[k] for k in ('entity_type','canonical_id','label'))
                for n in snapshot.tables['entities'])):
        raise ValueError('Grafo distinto del conocimiento aprobado')
    retriever=GraphRetriever(graph,snapshot,config['graph'])
    fingerprint=__import__('hashlib').sha256((publication/'_manifest.json').read_bytes()).hexdigest()
    return {p['project_id']:retriever.project_context(p['project_id'])|dict(
        graph_manifest_sha256=fingerprint,knowledge_manifest_sha256=snapshot.manifest_hash,
        layer3_run_id=manifest['layer3_run_id']) for p in projects}


def rank_project_passages(projects, profiles, chunks, records, vectors, queries,relational_contexts=None):
    return _rank_selected(projects, profiles, chunks, records, vectors, queries, relational_contexts)[0]


def _rank_selected(projects, profiles, chunks, records, vectors, queries,relational_contexts=None):
    """No global top-k, cross-project evidence, source-type competition or quota.

    SELECTED_ROWS_SCORING_V1: only the rows that can affect the result are scored:
    each source's own authorized passages and, for relational context, the chunks
    of documents reachable through its verified support paths. Selection, ordering,
    tie-breaks, reference IDs and relational ranking are unchanged; scores use the
    same float64 arithmetic on the same stored vectors (memmap or in-memory).
    """
    chunk_by_id={c['chunk_id']:c for c in chunks}
    if len(chunk_by_id)!=len(chunks): raise ValueError('Duplicate source chunk')
    positions=defaultdict(list)
    allowed={p['project_id']:substantive_fields(p['fields']) for p in projects}
    # Each source ranks only its own passages; ARTICLE sources keep their type.
    kinds={p['project_id']:p.get('source_type','PROJECT') for p in projects}
    by_source=defaultdict(list)
    for pos,record in enumerate(records):
        c=chunk_by_id[record['chunk_id']]
        if c['source_id'] in allowed and c['source_type']==kinds[c['source_id']] and c['field_name'] in allowed[c['source_id']]:
            positions[c['source_id']].append(pos)
        if relational_contexts is not None:
            by_source[(c.get('source_type'),c['source_id'])].append(pos)
    needed=set()
    for p in projects:
        needed.update(positions[p['project_id']])
        if relational_contexts is not None:
            package=relational_contexts[p['project_id']]
            nodes={n['entity_id']:n for n in package['entities']}
            for eid,path in package['support_paths'].items():
                if path:needed.update(by_source.get((nodes[eid]['entity_type'],nodes[eid]['canonical_id']),[]))
    rows=sorted(needed)
    column={pos:n for n,pos in enumerate(rows)}
    selected=np.asarray(vectors[rows],dtype=np.float64).reshape(len(rows),vectors.shape[1])
    result=[]
    for iid in sorted(profiles):
        reference_ids,q=queries[iid]
        q=np.asarray(q,dtype=np.float64)
        if q.ndim!=2 or q.shape[1]!=vectors.shape[1] or not np.isfinite(q).all():
            raise ValueError('Invalid cached query matrix')
        norms=np.linalg.norm(q,axis=1)
        if np.any(norms<=0): raise ValueError('Zero query vector')
        scores=np.clip((q/norms[:,None]) @ selected.T,-1.,1.)
        best=scores.max(axis=0) if len(rows) else np.empty(0)
        for p in projects:
            pid=p['project_id']
            order=sorted(positions[pid],key=lambda pos:(-float(best[column[pos]]),records[pos]['chunk_id']))
            if not order: continue  # An actual missing authorized source stays blocked.
            hits=[]
            for rank,pos in enumerate(order,1):
                c=chunk_by_id[records[pos]['chunk_id']];col=column[pos]
                hits.append(dict(chunk_id=c['chunk_id'],field_name=c['field_name'],vector_score=float(best[col]),
                    vector_rank=rank,retrieval_origin=VERSION,
                    reference_chunk_ids=[rid for n,rid in enumerate(reference_ids) if scores[n,col]==best[col]]))
            candidate=dict(candidate_id='SCOPED_SOURCE_INDICATOR_'+digest([VERSION,pid,iid,hits]),
                context_package_id='SCOPED_PROJECT_CONTEXT_'+digest([pid,[h['chunk_id'] for h in hits]]),
                source_id=pid,source_type=kinds[pid],indicator_id=iid,discovery_chunks=hits)
            if relational_contexts is not None:
                package=relational_contexts[pid]
                nodes={n['entity_id']:n for n in package['entities']}
                # Rank only documents reachable through verified graph paths with
                # the same BGE query. Their text never becomes project evidence.
                ranked=[]
                own_text=' '.join(chunk_by_id[h['chunk_id']]['text'] for h in hits[:3]).casefold()
                for eid,path in package['support_paths'].items():
                    if not path:continue
                    node=nodes[eid];linked=by_source.get((node['entity_type'],node['canonical_id']),[])
                    score=max((float(best[column[pos]]) for pos in linked),default=0.)
                    if score>0 or (node.get('label') and node['label'].casefold() in own_text):
                        ranked.append((-score,eid,path))
                paths={eid:path for _,eid,path in sorted(ranked)[:3]}
                ids={rid for path in paths.values() for rid in path}
                relations=[r for r in package['relations'] if r['relation_id'] in ids]
                entities={package['seed_entity_id']}|{r[k] for r in relations for k in ('source_entity_id','target_entity_id')}
                candidate['relational_context']=package|dict(support_paths=paths,relations=relations,
                    entities=[nodes[eid] for eid in sorted(entities)])
            result.append(candidate)
    return result, len(rows)


CHUNK_IDENTITY_COLUMNS = ['chunk_id', 'source_id', 'source_type', 'field_name']


def load_chunks(workspace, source_ids):
    """Source chunks for scoped retrieval with bounded memory.

    Complete rows (text, offsets, sections) only for the evaluated sources, whose
    passages are the only possible evidence; identity columns for every other chunk,
    which ranking needs to keep sources apart and to locate relational documents.
    """
    path = Path(workspace) / 'outputs/layer2/knowledge/source_chunks.parquet'
    ids = set(source_ids)
    parquet = pq.ParquetFile(path)
    identity = parquet.read(columns=CHUNK_IDENTITY_COLUMNS).to_pylist()
    rows = [n for n, c in enumerate(identity) if c['source_id'] in ids]
    # One column at a time: only the selected rows are materialized (bounded peak).
    columns = {}
    for name in parquet.schema_arrow.names:
        columns[name] = parquet.read(columns=[name]).column(name).take(rows).to_pylist() if rows else []
    own = [dict(zip(columns, values)) for values in zip(*columns.values())]
    selected = set(rows)
    return own + [c for n, c in enumerate(identity) if n not in selected]


def from_published_cache(workspace, projects, profiles, chunks,relational_contexts=None):
    workspace=Path(workspace);publication=workspace/'outputs/layer3/publication'
    knowledge=workspace/'outputs/layer2/knowledge'
    knowledge_hash=__import__('hashlib').sha256((knowledge/'_manifest.json').read_bytes()).hexdigest()
    manifest=validate_publication(publication,knowledge_hash)
    fingerprint=manifest['embedding_config_hash']
    # Same published file and checks; only the rows scored below are read (memmap).
    index=open_mapped(publication/'indexes/source',{'config_hash':fingerprint})
    references=defaultdict(list)
    for ref in pq.read_table(knowledge/'reference_chunks.parquet').to_pylist():
        references[ref['source_id']].append(ref)
    cache=EmbeddingCache(workspace/'outputs/layer3/query_cache');queries={}
    for iid in profiles:
        refs=sorted(references[iid],key=lambda r:r['chunk_id'])
        if not refs: raise ValueError('Missing reference query: '+iid)
        vectors=[]
        for ref in refs:
            key=digest(dict(text=ref['text'],encoding='query',fingerprint=fingerprint))
            vector=cache.get(key,index.metadata['dimensions'])
            if vector is None: raise ValueError('MISSING_CACHED_QUERY: '+iid+'; no automatic embedding allowed')
            vectors.append(vector)
        queries[iid]=([r['chunk_id'] for r in refs],np.asarray(vectors))
    candidates,scored=_rank_selected(projects,profiles,chunks,index.records,index.vectors,queries,relational_contexts)
    return candidates,dict(version=VERSION,query_source='VERIFIED_PUBLISHED_QUERY_CACHE',
        graph_manifest_sha256=__import__('hashlib').sha256((publication/'_manifest.json').read_bytes()).hexdigest(),
        project_count=len(projects),indicator_count=len(profiles),candidate_count=len(candidates),
        cross_source_evidence=False,global_rank_cutoff=False,model_calls=0,embeddings_generated=0,
        index_access=INDEX_ACCESS,index_rows=len(index.records),scored_positions=scored)
