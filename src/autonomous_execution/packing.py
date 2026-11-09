"""GraphRAG-only packing against the actual phase schema and output reservation.

Original intervals, ranking, one intact chunk/sentence window per field and
omission audits match the existing packer. Only the per-phase prompt differs.
"""
import hashlib
from difflib import SequenceMatcher
from functools import lru_cache
from layer4_evaluation.indicators import context_budget as cb
from layer4_evaluation.indicators.selection import substantive_fields
from . import policy as p
from layer4_evaluation.indicators.performance import timed

VERSION='ADAPTIVE_GRAPH_CONTEXT_V1'


@lru_cache(maxsize=128)
def original_bounds(original,normalized,start,end):
    blocks=SequenceMatcher(None,original,normalized,autojunk=False).get_opcodes()
    def boundary(pos,is_start):
        for tag,a,b,c,d in blocks:
            if tag=='equal' and (c<=pos<d if is_start else c<pos<=d):return a+pos-c
            if tag=='replace' and pos==(c if is_start else d):return a if is_start else b
        raise ValueError('GraphRAG normalized boundary cannot map exactly to original')
    return boundary(start,True),boundary(end,False)


def original_chunk(project,sections,chunk,hit):
    """Project a verified normalized interval onto its authorized original field.

    Both representations belong to the sealed section. Diff boundaries only
    translate coordinates; they never search for or select another passage.
    A boundary inside a replacement is ambiguous and must be rejected.
    """
    pid=project['project_id'];field=chunk['field_name'];section=sections.get(chunk['section_id'])
    detail=(f'expected_project={pid}; found_project={chunk["source_id"]}; '
        f'chunk={chunk["chunk_id"]}; section={chunk["section_id"]}; '
        f'expected_field={field}; found_field={hit["field_name"]}')
    if (chunk['source_id']!=pid or hit['field_name']!=field or not section or
            section['source_id']!=pid or section['field_name']!=field or
            field not in project['fields'] or section['text_original']!=project['fields'][field]):
        raise ValueError('GraphRAG source identity/original field mismatch; '+detail)
    original=section['text_original'] or '';normalized=section.get('text_normalized',original)
    start,end=chunk['char_start'],chunk['char_end']
    if not 0<=start<end<=len(normalized) or normalized[start:end]!=chunk['text']:
        raise ValueError('GraphRAG interval mismatch; expected=text_normalized; '+detail)
    if original==normalized:return chunk
    try:left,right=original_bounds(original,normalized,start,end)
    except ValueError as exc:raise ValueError(str(exc)+'; '+detail) from None
    if not 0<=left<right<=len(original):raise ValueError('GraphRAG original interval invalid; '+detail)
    return chunk|dict(char_start=left,char_end=right,text=original[left:right],normalized_interval=dict(
        char_start=start,char_end=end,text_sha256=hashlib.sha256(chunk['text'].encode()).hexdigest(),
        offset_basis='text_normalized'))


@timed('recuperacion')
def pack(data,profile,rubric,settings,schema,*,criterion_ids=None,concise=False,preserve=False,integral=False,prompt_factory=None):
    project=data['project'];pid=project['project_id'];iid=profile['indicator_id']
    def estimate(request):return cb.estimate(request['prompt'],schema,settings,tokenizer=request.get('tokenizer_budget'))
    fields={f:'' for f in project['fields']}
    def request_for(values):
        request=cb.make_request(project,profile,rubric,values)
        if criterion_ids is not None:
            request['payload']['indicators'][0]['rubric']['criteria']=[c for c in
                request['payload']['indicators'][0]['rubric']['criteria'] if c['criterion_id'] in criterion_ids]
            request['payload']['requested_criterion_ids']=criterion_ids
        request['prompt']=p.NORMATIVE+p.REPAIR+(p.CONCISE if concise else '')+(p.SHARD if criterion_ids is not None else '')+'\nINPUT_JSON:\n'+cb.compact(request['payload'])
        request['packing_version']=VERSION
        if preserve:
            from .phase11 import catalog_prompt
            if integral:
                from .phase12 import catalog_prompt
            catalog_prompt(request,rubric,shard=criterion_ids is not None)
            request['packing_version']='NO_LOSS_RETRIEVED_INTERVALS_V1'
        if prompt_factory is not None:
            prompt_factory(request,rubric)
        return request
    request=request_for(fields)
    base=estimate(request)
    if not base['fits']:
        from .engine import JobError
        # A custom factory can include its evidence registry even with empty
        # field placeholders. That is the actual input, not static instructions.
        raise JobError('CONTEXT_TOO_LONG' if prompt_factory is not None else 'STATIC_CONTEXT_TOO_LONG', budget=base)
    candidates=[c for c in data['candidates'] if c['indicator_id']==iid]
    if len(candidates)>1:
        raise ValueError('GraphRAG candidate duplicado')
    chunks={c['chunk_id']:c for c in data['chunks']};sections={c['section_id']:c for c in data['sections']}
    hits=[]
    for candidate in candidates:
        if candidate['source_id']!=pid or candidate['source_type']!='PROJECT':
            raise ValueError('Contexto GraphRAG de otra fuente')
        for hit in candidate['discovery_chunks']:
            chunk=chunks.get(hit['chunk_id'])
            if not chunk or chunk['source_id']!=pid or chunk['field_name']!=hit['field_name']:
                raise ValueError('Referencia GraphRAG fuera del proyecto')
            chunk=original_chunk(project,sections,chunk,hit)
            hits.append((hit,chunk))
    hits.sort(key=lambda pair:(pair[1]['field_name'] not in substantive_fields(fields),pair[0].get('vector_rank') or 10**9,
        -float(pair[0].get('vector_score') or 0),pair[1]['chunk_id']))
    selected=[];omitted=[];seen=set()
    for hit,chunk in hits:
        field,text=chunk['field_name'],chunk['text']
        ref=dict(chunk_id=chunk['chunk_id'],section_id=chunk['section_id'],source_id=pid,field=field,
            char_start=chunk['char_start'],char_end=chunk['char_end'],text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            coordinate_system='original_unicode_codepoints_0_based_half_open',retrieval_origin=hit.get('retrieval_origin'),vector_rank=hit.get('vector_rank'))
        if 'normalized_interval' in chunk:ref['normalized_interval']=chunk['normalized_interval']
        if (field,text) in seen:
            omitted.append(ref|dict(reason='DUPLICATE_EXACT_FIELD_TEXT'));continue
        seen.add((field,text))
        if fields[field]:
            if preserve:
                # Cover all retrieved intervals using an original contiguous hull;
                # never concatenate disjoint text into a fabricated quote field.
                previous=next(r for r in selected if r['field']==field)
                start=min(previous['char_start'],chunk['char_start']);end=max(previous['char_end'],chunk['char_end'])
                text=project['fields'][field][start:end]
                ref=ref|dict(char_start=start,char_end=end,unit='ORIGINAL_RETRIEVED_INTERVAL_HULL',
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    included_chunk_ids=previous.get('included_chunk_ids',[previous['chunk_id']])+[chunk['chunk_id']])
                trial=request_for(fields|{field:text})
                if not estimate(trial)['fits']:
                    from .engine import JobError
                    raise JobError('EVIDENCE_COVERAGE_BUDGET')
                fields[field]=text;selected.remove(previous);selected.append(ref);continue
            omitted.append(ref|dict(reason='ONE_INTACT_CHUNK_PER_FIELD'));continue
        def fits(value):
            trial=request_for(fields|{field:value})
            return estimate(trial)['fits']
        if not fits(text):
            if preserve:
                from .engine import JobError
                raise JobError('EVIDENCE_COVERAGE_BUDGET')
            span=cb.sentence_span(text,fits)
            if span is None:
                omitted.append(ref|dict(reason='INPUT_BUDGET_EXCEEDED'));continue
            start,end=span
            omitted.append(ref|dict(reason='PARENT_CHUNK_SUBSPAN_SELECTED',
                excluded_intervals=[[chunk['char_start'],chunk['char_start']+start],[chunk['char_start']+end,chunk['char_end']]]))
            text=text[start:end]
            ref=ref|dict(unit='ORIGINAL_SENTENCE_SPAN',parent_char_start=chunk['char_start'],parent_char_end=chunk['char_end'],
                char_start=chunk['char_start']+start,char_end=chunk['char_start']+end,text_sha256=hashlib.sha256(text.encode()).hexdigest())
        fields[field]=text;selected.append(ref)
    if not any(fields[f].strip() for f in substantive_fields(fields)):
        from .engine import JobError
        raise JobError('NO_EVIDENCE_FITS' if hits else 'NO_RETRIEVED_EVIDENCE')
    request=request_for(fields)
    request['context_selection']=dict(status='READY',selected=selected,omitted=omitted,evidence_limited=bool(omitted))
    request['context_budget']=estimate(request)
    if preserve:
        from .phase11 import coverage
        request['coverage_receipt']=coverage(request)
    return request
