"""Prepared six-column consumer contract. Pure projection; no publication/I/O."""
from . import assessment_v3 as v3, global_discovery_v3_3 as discovery
from .final_projection import TERRITORY_COLUMNS, territories
from .review import evidence_locations

VERSION='LAYER4_CONSUMER_V3_3_V1'
COLUMNS=['siap_id','indicador_id','parrafo_evidencia','fuente_evidencia','ubicacion_evidencia','confianza']


def build_spec(projects, rows, profiles, rubrics, selections, data, *, require_complete=True):
    """Only validated SUPPORTED pairs selected by V3.3 enter the consumer sheet.

    Partial evidence remains internal because the six-column sheet cannot safely
    distinguish it from demonstrated support. No confidence threshold is used.
    Returns workbook specification and separate audit; never writes an Excel.
    """
    by_project={p['project_id']:p for p in projects}
    if len(by_project)!=len(projects) or set(selections)!=set(by_project):
        raise ValueError('Exact project/selection coverage required')
    selected=set()
    for pid,p in by_project.items():
        result=discovery.validate_selection(selections[pid],p,profiles)
        selected.update((pid,i) for i in result['prioritized_ids'])
    exported=[];audit=[];seen=set();valid=set()
    for row in rows:
        key=row['project_id'],row['indicator_id']
        if key in seen or key[0] not in by_project:raise ValueError('Unknown/duplicate project+indicator')
        seen.add(key)
        state=row.get('decision')
        entry=dict(project_id=key[0],indicator_id=key[1],decision=state,exported=False)
        audit.append(entry)
        if key not in selected:entry['reason']='NOT_PRIORITIZED_BY_CURRENT_V3_3';continue
        if row.get('assessment_validation_status')!='VALID' or row.get('validation_errors'):
            entry['reason']='INVALID_INTERNAL_ONLY';continue
        if row.get('assessment_version')!=v3.VERSION:raise ValueError('Assessment version incompatible')
        fields,texts,stages=(row[n] for n in ('evidence_source_fields','evidence_texts','evidence_stages'))
        if not len(fields)==len(texts)==len(stages):raise ValueError('Evidence alignment mismatch')
        assessment=dict(assessment_version=v3.VERSION,decision=state,support_strength=row['support_strength'],
            criterion_assessments=row['criterion_assessments'],
            evidence=[dict(field=f,text=t,stage=s) for f,t,s in zip(fields,texts,stages)],explanation=row['evidence_explanation'])
        project=by_project[key[0]]
        computed=v3.indicator_row(project,profiles[key[1]],assessment,rubrics[key[1]])
        if computed['assessment_validation_status']!='VALID':raise ValueError('Invalid citations/temporal support')
        if any(row.get(k)!=v for k,v in computed.items()):raise ValueError('Saved assessment/confidence differs from deterministic validation')
        valid.add(key)
        if state!='SUPPORTED':entry['reason']='PARTIAL_INTERNAL_ONLY' if state=='INSUFFICIENT_EVIDENCE' else 'NOT_SUPPORTED_INTERNAL_ONLY';continue
        locations=evidence_locations(project,assessment)
        if not locations or any(not e['match_valid'] or not e['section_id'] for e in locations):raise ValueError('Unverifiable evidence location')
        siap=project.get('siap_id')
        if not isinstance(siap,str) or not siap.strip():raise ValueError('Missing institutional SIAP ID')
        entry.update(exported=True,reason='VALID_SUPPORTED_SELECTED')
        exported.append(dict(siap_id=siap,indicador_id=key[1],
            parrafo_evidencia='\n\n'.join(f'[{i}] {e["text"]}' for i,e in enumerate(locations,1)),
            fuente_evidencia='\n'.join(f'[{i}] SIAP {siap}; {e["field"]}' for i,e in enumerate(locations,1)),
            ubicacion_evidencia='\n'.join(f'[{i}] section_id={e["section_id"]}; [{e["start"]},{e["end"]}); {e["coordinate_system"]}' for i,e in enumerate(locations,1)),
            confianza=row['confidence_raw_score']))
    if require_complete and selected-valid:raise ValueError('Missing/invalid assessment for prioritized pairs; publication not ready')
    territorial=territories(data,projects)
    spec=dict(sheets=[dict(name='RESULTADO_INDICADORES',columns=COLUMNS,rows=[[r[c] for c in COLUMNS] for r in exported]),
        dict(name='TERRITORIOS',columns=TERRITORY_COLUMNS,rows=[[r[c] for c in TERRITORY_COLUMNS] for r in territorial])])
    return spec,dict(contract_version=VERSION,records=audit,exported=len(exported),
        missing_assessments=sorted(selected-valid),confidence_is_probability=False,
        partial_evidence_policy='INTERNAL_ONLY',publication_performed=False)
