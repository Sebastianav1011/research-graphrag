"""Typed territorial outputs, including valid empty publications."""

import pyarrow as pa
from pathlib import Path
from jsonschema import Draft202012Validator
from .. import load_schema

BRIDGE = pa.schema([(name, pa.string()) for name in
                   ('project_id', 'territory_type', 'dane_code')])
COMMON = [(name, pa.string()) for name in
          ('project_id', 'document_id', 'section_id', 'field_name', 'matched_text',
           'normalized_match', 'context_text')]
COMMON += [('start_char', pa.int64()), ('end_char', pa.int64())]
EVIDENCE = pa.schema(COMMON + [(name, pa.string()) for name in
                             ('territory_type', 'dane_code', 'territory_name',
                              'resolution_method', 'resolution_status')])
AMBIGUOUS = pa.schema(COMMON + [(name, pa.string()) for name in
                              ('territory_type_detected', 'dane_code', 'resolution_status')]
                     + [('candidate_count', pa.int64())]
                     + [(name, pa.list_(pa.string())) for name in
                        ('candidate_dane_codes', 'candidate_names',
                         'candidate_departments', 'candidate_territory_types')])
SCHEMAS = {'project_territories': BRIDGE,
           'project_territory_evidence': EVIDENCE,
           'project_territory_ambiguous': AMBIGUOUS}


def table(name, rows):
    return pa.Table.from_pylist(rows, schema=SCHEMAS[name])


ROOT=Path(__file__).resolve().parents[3]


def consumption_rows(relationships, dimension):
    catalog={(row['territory_type'],row['dane_code']):row for row in dimension}
    if len(catalog)!=len(dimension):raise ValueError('Duplicate territory dimension keys')
    result=[];seen=set()
    for row in relationships:
        if row.get('resolution_status','RESOLVED')!='RESOLVED':
            raise ValueError('AMBIGUOUS is technical audit, never a consumer territory')
        key=row['territory_type'],row['dane_code']
        if key not in catalog:raise ValueError('Territory absent from authoritative dimension')
        territory=catalog[key]
        if key[0]=='COUNTRY' and territory.get('territory_origin')!='USER_DEFINED_COUNTRY':
            raise ValueError('COUNTRY must declare its internal origin')
        output={'project_id':row['project_id'],'territory_type':key[0],'territory_code':key[1],
            'territory_name':territory['territory_name'],'department_code':territory['department_code'],
            'department_name':territory['department_name'],'code_system':'INTERNAL' if key[0]=='COUNTRY' else 'DANE'}
        Draft202012Validator(load_schema(ROOT,'project_territory')).validate(output)
        unique=row['project_id'],*key
        if unique in seen:raise ValueError('Duplicate project-territory relationship')
        seen.add(unique);result.append(output)
    specific={r['project_id'] for r in result if r['territory_type']!='COUNTRY'}
    if any(r['territory_type']=='COUNTRY' and r['project_id'] in specific for r in result):
        raise ValueError('COUNTRY cannot duplicate a resolved subnational territory')
    return sorted(result,key=lambda r:(r['project_id'],r['territory_type'],r['territory_code']))
