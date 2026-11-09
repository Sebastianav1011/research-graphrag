"""Deterministic selection from immutable SOURCE_INDICATOR_V1 publications."""
from collections import defaultdict
import hashlib
import json
import math

SEED = 'PRELIMINARY_LAYER4_20_V1'
METHOD = ('ROUND_ROBIN_PRIMARY_INDICATOR; candidate_order=hybrid_retrieval_score DESC,indicator_id ASC; '
          'group_order=indicator_id ASC; project_order=SHA256(seed+":"+project_id) ASC; seed='+SEED)
FIELDS = ('title','keywords','summary','methodology','objectives','expected_results')


def field_instructions(fields):
    extra = [f for f in fields if f not in FIELDS]
    if not extra:
        return ''
    return ('\nAdemás de los seis campos base, los siguientes campos textuales seleccionados '
            'son evidencia sustantiva autorizada, citable por su nombre exacto: ' + ', '.join(extra) +
            '. Conserva sus significados separados: resultado, resultados esperados y posibles '
            'resultados no son equivalentes. El nombre de una columna nunca demuestra un logro. '
            'Aplica las mismas reglas de citas, pertinencia y temporalidad a cada campo.\n')


def authorized_fields(fields):
    """Fixed core plus preprocessing-selected fields; no extra envelope metadata."""
    return set(FIELDS).issubset(fields) and all(f in FIELDS or
        (isinstance(f, str) and f.startswith('text__') and f[6:] and
         all(c.isalnum() or c == '_' for c in f[6:])) for f in fields)


def substantive_fields(fields):
    return set(FIELDS[2:]) | {f for f in fields if isinstance(f, str) and f.startswith('text__')}


def field_schema(schema, fields):
    """Bind existing citation schemas to this project's selected input fields."""
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == 'field' and isinstance(value, dict) and value.get('enum') == list(FIELDS):
                value['enum'] = list(fields)
            else:
                field_schema(value, fields)
    elif isinstance(schema, list):
        for value in schema:
            field_schema(value, fields)
    return schema



def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def candidate_key(row):
    score=row['hybrid_retrieval_score']
    if not isinstance(score,(int,float)) or not math.isfinite(score):
        raise ValueError('Nonfinite historical hybrid retrieval score')
    return -score,row['indicator_id']


def eligible_projects(candidates, contexts, documents, sections, *, run_id):
    docs={r['document_id']:r for r in documents if r['source_type']=='PROJECT'}
    if len(docs)!=len([r for r in documents if r['source_type']=='PROJECT']):raise ValueError('Duplicate document')
    secs={r['section_id']:r for r in sections if r['source_type']=='PROJECT'}
    ctx={r['context_package_id']:r for r in contexts}
    if len(ctx)!=len(contexts):raise ValueError('Duplicate context package')
    bydoc=defaultdict(dict)
    for s in secs.values():
        if s['field_name'] in FIELDS:
            if s['field_name'] in bydoc[s['document_id']]:raise ValueError('Duplicate project field')
            bydoc[s['document_id']][s['field_name']]=s
    groups=defaultdict(list)
    for row in candidates:
        if row['source_type']!='PROJECT' or row['context_status']!='ASSESSMENT_READY':continue
        doc=docs.get(row['document_id']);context=ctx.get(row['context_package_id'])
        if doc is None or context is None:raise ValueError('Eligible candidate has no Layer2 document/context')
        if any(context[k]!=row[k] for k in ('source_type','source_id','document_id','context_status','source_context_hash','layer3_run_id')):
            raise ValueError('Candidate/context mismatch')
        if row['layer3_run_id']!=run_id or doc['source_id']!=row['source_id']:raise ValueError('Source/run mismatch')
        refs=context['orientation_sections']+context['substantive_sections']
        if not context['substantive_sections']:raise ValueError('ASSESSMENT_READY lacks substantive context')
        for ref in refs:
            section=secs.get(ref['section_id'])
            if (section is None or section['document_id']!=doc['document_id']
                    or section['source_id']!=row['source_id'] or section['field_name']!=ref['field_name']
                    or section['text_hash_normalized']!=ref['text_hash']):
                raise ValueError('Context section cannot be reconstructed from Layer2')
        core={k:context[k] for k in ('source_type','source_id','document_id','title_section_id',
              'orientation_sections','substantive_sections','available_field_names','context_status')}
        if canonical_hash(core)!=context['source_context_hash']:raise ValueError('Context hash mismatch')
        if set(context['available_field_names'])!={s['field_name'] for s in refs}:raise ValueError('Context fields mismatch')
        fields=bydoc[doc['document_id']]
        if set(fields)!=set(FIELDS):raise ValueError('Incomplete six-field Layer2 project schema')
        groups[row['source_id']].append(row)
    result=[]
    for project_id,rows in sorted(groups.items()):
        if len({r['indicator_id'] for r in rows})!=len(rows):raise ValueError('Duplicate PROJECT+INDICATOR candidate')
        ranked=sorted(rows,key=candidate_key);doc=docs[ranked[0]['document_id']]
        if any(r['document_id']!=doc['document_id'] for r in rows):raise ValueError('Project maps to multiple documents')
        # Original authorized field text only. No provenance/PII tables enter provider inputs.
        fields={f:bydoc[doc['document_id']][f]['text_original'] for f in FIELDS}
        if any(v is not None and not isinstance(v,str) for v in fields.values()):raise ValueError('Unexpected source field type')
        result.append({'project_id':project_id,'document_id':doc['document_id'],'title':fields['title'],
                       'fields':fields,'candidates':ranked})
    return result


def select_projects(eligible, count=20, limit=2):
    if count!=20 or limit!=2:raise ValueError('This version requires exactly20 projects and max2 candidates')
    if len({r['project_id'] for r in eligible})!=len(eligible):raise ValueError('Duplicate eligible project')
    groups=defaultdict(list)
    for project in eligible:groups[project['candidates'][0]['indicator_id']].append(project)
    for group in groups.values():
        group.sort(key=lambda p:(hashlib.sha256((SEED+':'+p['project_id']).encode()).hexdigest(),p['project_id']))
    chosen=[];position=0
    while len(chosen)<count:
        added=0
        for indicator_id in sorted(groups):
            if position<len(groups[indicator_id]):
                chosen.append({**groups[indicator_id][position],
                    'candidates':groups[indicator_id][position]['candidates'][:limit],
                    'selection_order':len(chosen)+1,'selection_method':METHOD})
                added+=1
                if len(chosen)==count:break
        if not added:raise ValueError('Fewer than20 eligible projects')
        position+=1
    return chosen
