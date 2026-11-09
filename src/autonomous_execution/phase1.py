"""Lossless citation ledger for decision synthesis; no semantic decisions in Python."""
from copy import deepcopy
import hashlib
from layer4_evaluation.indicators import context_budget as cb
from . import policy as p

VERSION='CITATION_LEDGER_SYNTHESIS_V1'
INSTRUCTIONS=('\nSINTESIS ESTRUCTURADA: source_spans contiene los textos originales enviados '
    'a los shards, sin fuentes nuevas. Cada evidencia referencia source_span y [start,end) '
    'en puntos de codigo Unicode base cero de su text; el pasaje citado se reconstruye exactamente. '
    'Los juicios conservan todos los criterios y fueron validados, incluidas sus temporalidades. '
    'Interpreta la definicion completa y las fuentes para decidir; no cambies los juicios. '
    'Devuelve solo indicator_id, decision, support_strength y explanation. Una explicacion breve '
    'y completa; no repitas las explicaciones individuales.\n')


def merge(evidence,judgments):
    """Deduplicate only exact (field,text,stage), remap references without loss."""
    unique=[];mapping={};seen={}
    for i,e in enumerate(evidence):
        key=(e['field'],e['text'],e['stage'])
        if key not in seen:seen[key]=len(unique);unique.append(deepcopy(e))
        mapping[i]=seen[key]
    items=[{**c,'evidence_indices':list(dict.fromkeys(mapping[i] for i in c['evidence_indices']))} for c in judgments]
    return unique,items


def synthesis(project,profile,rubric,requests,judgments,evidence):
    """Union every sent interval, retain all source text once and reference exact quotes.

    Explanation prose remains in the durable shard/bundle, never summarized or
    reassigned as source evidence. No source or criterion is discarded to fit.
    """
    intervals={}
    for request in requests:
        for ref in request['context_selection']['selected']:
            field=ref['field'];start=ref['char_start'];end=ref['char_end']
            original=project['fields'][field]
            sent=request['payload']['project']['fields'][field]
            if original[start:end]!=sent:
                raise ValueError('SYNTHESIS_SOURCE_INTERVAL_MISMATCH')
            intervals.setdefault(field,[]).append((start,end))
    spans=[]
    for field,ranges in sorted(intervals.items()):
        merged=[]
        for start,end in sorted(set(ranges)):
            if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
            else:merged.append((start,end))
        for start,end in merged:
            spans.append(dict(id=f'S{len(spans)}',field=field,original_start=start,original_end=end,
                text=project['fields'][field][start:end]))
    refs=[]
    for e in evidence:
        candidates=[span for span in spans if span['field']==e['field'] and e['text'] in span['text']]
        if not candidates:raise ValueError('SYNTHESIS_QUOTE_WITHOUT_SENT_SOURCE')
        span=candidates[0];start=span['text'].index(e['text'])
        refs.append(dict(field=e['field'],stage=e['stage'],source_span=span['id'],start=start,end=start+len(e['text'])))
    payload=cb.make_request(project,profile,rubric,{f:'' for f in project['fields']})['payload']
    # Empty placeholders convey no information; real source fields live in spans.
    payload['project']=dict(project_id=project['project_id'])
    payload.update(source_spans=spans,verified_evidence=refs,
        verified_criterion_assessments=[{k:c[k] for k in ('criterion_id','support','evidence_indices')} for c in judgments])
    prompt=p.NORMATIVE+p.REPAIR+INSTRUCTIONS+'\nINPUT_JSON:\n'+cb.compact(payload)
    trace=dict(version=VERSION,quote_references=refs,
        criterion_explanation_sha256={c['criterion_id']:hashlib.sha256(c['explanation'].encode()).hexdigest() for c in judgments},
        source_spans=[{k:v for k,v in span.items() if k!='text'}|dict(text_sha256=hashlib.sha256(span['text'].encode()).hexdigest()) for span in spans])
    return dict(project_id=project['project_id'],input_version=VERSION,payload=payload,prompt=prompt,
        synthesis_provenance=trace,context_selection=dict(status='READY',selected=[r for request in requests for r in request['context_selection']['selected']],
        omitted=[],evidence_limited=any(r['context_selection']['evidence_limited'] for r in requests)))


def feedback(issues):
    # Only safe identifiers/rules. Never feed raw institutional/model narratives.
    safe=[{k:i[k] for k in ('rule','path','criterion_id','criterion_ids','indicator_id','evidence_indices','evidence_count','temporal_requirement','observed_stages') if k in i} for i in issues]
    return '\nREPARACION DEL CONTRATO: corrige estas reglas sin inventar evidencia: '+cb.compact(safe)+'\n' if safe else ''
