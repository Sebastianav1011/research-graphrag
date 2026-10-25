"""Preliminary diagnostics, unchanged confidence and verified four-sheet export."""
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import statistics
from jsonschema import Draft202012Validator
from layer4.indicators.confidence import calculate_raw_confidence
from layer4.indicators.assessment import validate_structured_assessment
from layer4.indicators.contracts import TERRITORY_COLUMNS,INDICATOR_COLUMNS
from layer4.indicators.export import export_workbook_spec
from .contracts import schemas


def indicator_row(project,profile,assessment):
    errors=validate_structured_assessment(project['fields'],profile,assessment)
    confidence=calculate_raw_confidence(project['fields'],profile,assessment)
    # A strict-schema error has authority even if confidence's compatibility
    # validator alone ignores an unexpected field.
    if errors:
        confidence.update(confidence_status='INVALID_ASSESSMENT',confidence_raw_score=None,
            **dict.fromkeys(('key_element_coverage','field_relevance_score','corroboration_score','support_strength_score')))
    row={'project_id':project['project_id'],**{k:profile[k] for k in ('indicator_id','indicator_name','indicator_category','indicator_dimension')},
        'decision':assessment['decision'],'support_strength':assessment['support_strength'],
        'supported_key_elements':assessment['supported_key_elements'],
        'evidence_source_fields':[e['field'] for e in assessment['evidence']],
        'evidence_texts':[e['text'] for e in assessment['evidence']],
        'evidence_explanation':assessment['explanation'],'assessment_engine':'CODEX_CLI',
        'assessment_engine_status':'PROVISIONAL',
        **{k:float(v) if isinstance(v,Decimal) else v for k,v in confidence.items() if k!='validation_errors'},
        'assessment_validation_status':'INVALID_ASSESSMENT' if errors else 'VALID','validation_errors':errors}
    Draft202012Validator(schemas()['project_indicator_preliminary']).validate(row)
    return row


def validate_rows(selected,profiles,assessments,rows,territories,metadata):
    ids={p['project_id'] for p in selected}
    if len(selected)!=20 or len(ids)!=20:raise ValueError('Exactly20 distinct projects required')
    expected={(p['project_id'],c['indicator_id']) for p in selected for c in p['candidates']}
    keys=[(r['project_id'],r['indicator_id']) for r in rows]
    if len(keys)!=len(set(keys)) or set(keys)!=expected or not 20<=len(rows)<=40:
        raise ValueError('Missing, extra or duplicate assessment')
    projects={p['project_id']:p for p in selected}
    returned={(a['project_id'],a['indicator_id']):a['assessment'] for a in assessments}
    if set(returned)!=expected or len(returned)!=len(assessments):raise ValueError('Raw assessment correspondence mismatch')
    for row in rows:
        key=row['project_id'],row['indicator_id']
        calculated=indicator_row(projects[key[0]],profiles[key[1]],returned[key])
        if row!=calculated:raise ValueError('Output changed after validation/confidence')
        if row['confidence_probability'] is not None or row['confidence_level'] is not None:raise ValueError('Not probability/level')
        if row['confidence_status']=='COMPUTED':
            if row['decision']!='SUPPORTED' or row['validation_errors']:raise ValueError('Invalid evidence produced a score')
            components=[row[k] for k in ('key_element_coverage','field_relevance_score','corroboration_score','support_strength_score')]
            if not all(0<=n<=1 for n in components) or not 0<=row['confidence_raw_score']<=100:raise ValueError('Score bounds')
        elif row['confidence_raw_score'] is not None:raise ValueError('Inapplicable assessment has score')
    if any(t['project_id'] not in ids for t in territories):raise ValueError('Unknown territory project')
    for t in territories:
        from layer4.indicators.contracts import load_schema
        Draft202012Validator(load_schema(Path(__file__).resolve().parents[3],'project_territory')).validate(t)
    if metadata['project_count']!=20 or metadata['assessment_engine']!='CODEX_CLI':raise ValueError('Wrong metadata')
    forbidden=('retrieval_score','vector_score','graph_score','hybrid_retrieval_score','source_rank')
    if any(any(k in row for k in forbidden) for row in rows):raise ValueError('Retrieval contaminated assessment output')
    return True


def spec(selected,rows,territories,metadata):
    def cell(v):return json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v
    friendly={'key_element_coverage':'K','field_relevance_score':'F','corroboration_score':'C',
              'support_strength_score':'S','evidence_texts':'evidence_text'}
    columns=[c for c in INDICATOR_COLUMNS if c not in ('assessment_engine','assessment_engine_status','confidence_probability','confidence_level')]
    columns+=['assessment_validation_status','validation_errors']
    return {'sheets':[
        {'name':'PROYECTOS','columns':['project_id','title'],
         'rows':[[p['project_id'],p['title']] for p in selected]},
        {'name':'INDICADORES','columns':[friendly.get(c,c) for c in columns],
         'rows':[[cell(r[c]) for c in columns] for r in rows]},
        {'name':'TERRITORIOS','columns':TERRITORY_COLUMNS,
         'rows':[[r[c] for c in TERRITORY_COLUMNS] for r in territories]},
        {'name':'METADATA','columns':['key','value'],
         'rows':[[k,'NO' if k=='confidence_is_probability' else cell(v)] for k,v in metadata.items()]}]}


def export_and_verify(selected,rows,territories,metadata,path):
    expected=spec(selected,rows,territories,metadata)
    export_workbook_spec(expected,path)
    return verify_workbook(path,expected)


def verify_workbook(path,expected):
    from openpyxl import load_workbook
    workbook=load_workbook(path,data_only=False)
    if workbook.sheetnames!=[s['name'] for s in expected['sheets']]:raise ValueError('Workbook sheets mismatch')
    counts={}
    for tab in expected['sheets']:
        sheet=workbook[tab['name']];actual=list(sheet.values)
        wanted=[tab['columns'],*tab['rows']]
        if len(actual)!=len(wanted):raise ValueError('Workbook row count mismatch: '+tab['name'])
        for values,source in zip(actual,wanted):
            for value,original in zip(values,source):
                if original=='' and value is None:continue
                if isinstance(original,float) and isinstance(value,(int,float)):
                    if abs(original-value)<1e-10:continue
                if value!=original:raise ValueError('Workbook value changed or truncated: '+tab['name'])
        if any(c.data_type in ('f','e') for row in sheet for c in row):raise ValueError('Unexpected formula/error cell')
        if not sheet.freeze_panes:raise ValueError('Missing freeze panes')
        if sheet.max_row>1 and not(sheet.auto_filter.ref or sheet.tables):raise ValueError('Missing autofilter')
        counts[tab['name']]=len(tab['rows'])
    workbook.close()
    return {'status':'PASS','sheet_rows':counts,'all_values_preserved':True,'formulas':0}


def distribution(values):
    if not values:return dict.fromkeys(('min','p25','median','mean','p75','max'))
    ordered=sorted(values)
    def quantile(p):
        index=(len(ordered)-1)*p;lo=int(index);hi=min(lo+1,len(ordered)-1)
        return ordered[lo]+(ordered[hi]-ordered[lo])*(index-lo)
    return {'min':min(values),'p25':quantile(.25),'median':statistics.median(values),
            'mean':statistics.mean(values),'p75':quantile(.75),'max':max(values)}


def summary(selected,rows,territories,ambiguous,calls):
    computed=[r for r in rows if r['confidence_status']=='COMPUTED']
    decisions=Counter(r['decision'] for r in rows);types=Counter(t['territory_type'] for t in territories)
    return {'projects':20,'assessments':{'requested':sum(len(p['candidates']) for p in selected),'returned':len(rows),
        'valid':sum(r['assessment_validation_status']=='VALID' for r in rows),
        'invalid':sum(r['assessment_validation_status']=='INVALID_ASSESSMENT' for r in rows)},
        'decisions':{d:decisions[d] for d in ('SUPPORTED','INSUFFICIENT_EVIDENCE','NOT_SUPPORTED')},
        'confidence_supported_computed':distribution([r['confidence_raw_score'] for r in computed]),
        'components':{short:{'mean':statistics.mean([r[key] for r in computed]) if computed else None,
                             'median':statistics.median([r[key] for r in computed]) if computed else None}
             for short,key in zip('KFCS',('key_element_coverage','field_relevance_score','corroboration_score','support_strength_score'))},
        'territory':{'projects_with_territory':len({t['project_id'] for t in territories}),
             'projects_without_territory':20-len({t['project_id'] for t in territories}),
             'projects_with_subnational':len({t['project_id'] for t in territories if t['territory_type']!='COUNTRY'}),
             'projects_with_country':len({t['project_id'] for t in territories if t['territory_type']=='COUNTRY'}),
             'municipality_relations':types['MUNICIPALITY'],'department_relations':types['DEPARTMENT'],
             'country_relations':types['COUNTRY'],'projects_with_ambiguous_mentions':len({a['project_id'] for a in ambiguous}),
             'ambiguous_mentions':len(ambiguous)},
        'codex':{'calls':len(calls),'retries':sum(c['retry']>0 for c in calls),
                 'failures':sum(not c['successful_transport'] for c in calls)},
        'confidence_is_probability':False,'confidence_version':'RAW_CONFIDENCE_V1'}
