"""Export immutable evidence, independent labels, retry facts and test results.

This is a test report builder, never an evaluator or repair tool.
"""
import sys,xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from .harness import *

def main():
    OUT.mkdir(parents=True,exist_ok=True);profiles,rubrics=catalog()
    # Read authoritative workbooks, not model predictions, to pin the oracle source.
    from openpyxl import load_workbook
    catalog_sources=[]
    for name,sheet in [('catalogo_indicadores.xlsx','Catalogo_Indicadores'),('catalogo_indicadores_v2.xlsx','Indicadores_enriquecidos')]:
        path=ROOT/'data/layer1_sources/reference/indicadores'/name;w=load_workbook(path,read_only=True,data_only=True);values=iter(w[sheet].values);headers=next(values)
        entries=[dict(zip(headers,row)) for row in values if row[0]];w.close()
        assert len(entries)==48 and {e['id_indicador'] for e in entries}==set(profiles)
        mismatches=[e['id_indicador'] for e in entries if e['indicador']!=profiles[e['id_indicador']]['indicator_name']]
        catalog_sources.append(dict(path=str(path.relative_to(ROOT)),sha256=filehash(path),sheet=sheet,rows=entries,enunciado_mismatches=mismatches))
        assert not mismatches
    write(OUT/'catalogos_fuente.json',catalog_sources)
    coverage={(x['siap_id'],x['indicator_id']):x for x in read(RUN/'resultados/estado_indicadores.json')['indicators']}
    valid={(x['siap_id'],x['indicator_id']):x for x in read(RUN/'resultados/evaluaciones_validas.json')['assessments']}
    provisional=read(AUDIT/'juicios_revision.json');promoted={x['caso'] for x in read(AUDIT/'positivos_tras_correccion.json')}
    history=[];retries=[];replay=[];human=[];formula=[]
    from layer4_evaluation import live_execution as live
    from layer4_evaluation.indicators import assessment_v3 as v3
    from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError
    from decimal import Decimal,ROUND_HALF_UP
    for plan,p,iid,base,rec,dirs in original_attempts():
        pid=p['siap_id'];key=(pid,iid);cid=pid+':'+iid;request=plan['context_requests'][p['project_id']][iid];row=valid.get(key);groups=[]
        if row and row['decision']=='SUPPORTED':groups.append('SUPPORTED_44')
        if row and row['confidence_raw_score']==100:groups.append('CONFIDENCE_100_42')
        if cid in promoted:groups.append('RETRY_PROMOTION_15')
        if coverage[key]['status']=='BLOCKED_ERROR':groups.append('BLOCKED_100')
        if row and row['decision']=='INSUFFICIENT_EVIDENCE':groups.append('INSUFFICIENT_ADDITIONAL')
        original_responses=[];decision_receipts=[];attempt_acceptance=[];native_calls=[]
        for d in dirs:
            selection=read(d/'selection.json');native_request=read(d/'request.json');payload=json.loads(native_request['messages'][0]['content'].split('INPUT_JSON:\n',1)[1]);native_calls.append(native_request)
            try:resolved,receipt=live.materialize_output(plan,p,request,selection);accepted=True;issues=[]
            except AssessmentValidationError as e:accepted=False;issues=e.issues
            attempt_acceptance.append(accepted)
            replay.append(dict(test_id=cid+':'+d.name,scope='HISTORICAL_CONTRACT_REPLAY_NOT_GROUND_TRUTH',expected='ACCEPT' if (d/'response.json').exists() else 'REJECT',actual='ACCEPT' if accepted else 'REJECT',result='PASS' if accepted==(d/'response.json').exists() else 'FAIL',evidence=str(d.relative_to(ROOT)),details=json.dumps(issues,ensure_ascii=False)))
            if (d/'decision.json').exists():decision_receipts.extend(read(d/'decision.json'))
            original_responses.append(dict(path=str(d.relative_to(ROOT)),selection=selection,raw_response=(d/'response.raw.txt').read_text(encoding='utf8'),validation=read(d/'validation.json'),native_request=native_request,
                payload_sha256=digest(payload),fragment_sha256=digest(payload['project']),schema_sha256=digest(native_request['format']),instructions_sha256=digest(native_request['messages'][0]['content'].split('INPUT_JSON:\n',1)[0]),validated_in_memory=accepted))
        if any(x['original_decision']=='NOT_APPLICABLE' and x['derived_decision']=='INSUFFICIENT_EVIDENCE' for x in decision_receipts):groups.append('NOT_APPLICABLE_DERIVED_49')
        pair_retries=[]
        for index in range(1,len(original_responses)):
            before=original_responses[0];after=original_responses[index];b=before['selection']['assessments'][0];a=after['selection']['assessments'][0]
            evidence_before=json.loads(before['native_request']['messages'][0]['content'].split('INPUT_JSON:\n',1)[1])
            evidence_after=json.loads(after['native_request']['messages'][0]['content'].split('INPUT_JSON:\n',1)[1])
            finding=promotion_findings(b,a,evidence_before['project'],evidence_after['project'])
            rr=dict(project=pid,indicator=iid,first=dirs[0].name,later=dirs[index].name,groups='|'.join(groups),
                same_fragments=finding['same_evidence'],same_full_payload=digest(evidence_before)==digest(evidence_after),same_indicator_conditions=digest(evidence_before['indicators'])==digest(evidence_after['indicators']),
                same_schema=before['schema_sha256']==after['schema_sha256'],same_instructions=before['instructions_sha256']==after['instructions_sha256'],
                same_options=before['native_request']['options']==after['native_request']['options'],promoted_criteria='|'.join(finding['promoted_criteria']),requires_adjudication=finding['requires_adjudication'],
                original_decision=b['decision'],later_recommendation=a['decision'],originally_valid=before['validated_in_memory'],later_valid=after['validated_in_memory'])
            retries.append(rr);pair_retries.append(rr)
        snap=OUT/'historicos'/ (pid+'_'+iid+'.json')
        snapshot=dict(project=p,indicator_id=iid,original_plan=str((base.parents[2]/'plan.json').relative_to(ROOT)),request=request,assessment=row,coverage=coverage[key],
            record=rec,attempts=original_responses,decision_receipts=decision_receipts,retry_findings=pair_retries,provisional_audit=provisional.get(cid),human_ground_truth=None)
        write(snap,snapshot)
        h=dict(case_id='HIST_'+pid+'_'+iid,project_id=pid,indicator_id=iid,groups='|'.join(groups),original_state=coverage[key]['status'],decision=row['decision'] if row else '',confidence=row['confidence_raw_score'] if row else '',
            provisional_diagnosis=provisional.get(cid,['PENDING_HUMAN'])[0],human_validation='PENDING',snapshot=str(snap.relative_to(ROOT)),snapshot_sha256=filehash(snap),attempts=len(dirs),evidence_sha256=digest(request['payload']['project']),
            criterion_components=json.dumps(row['criterion_assessments'],ensure_ascii=False) if row else '',confidence_components=json.dumps(row['strength_rubric'],ensure_ascii=False) if row else '',source_registry='snapshot.project.field_provenance',error=rec.get('error') or '')
        history.append(h)
        human.append(dict(case_id=h['case_id'],data_type='REAL_HISTORICAL',indicator_id=iid,mode='PROSPECTIVE_V2',input_or_snapshot=h['snapshot'],expected_independent='',system_decision=h['decision'],provisional_audit=h['provisional_diagnosis'],human_status='PENDING',human_decision='',reviewer='',second_reviewer='',criterion_citations='',rationale='',adjudication_date='',definition_approved=''))
        if row:
            r=plan['rubrics'][iid];a=rec['wrapper']['assessments'][0];a={k:v for k,v in a.items() if k!='indicator_id'}
            levels={c['criterion_id']:Decimal(c['coverage'])/4 for c in a['criterion_assessments']};units=[levels[c['criterion_id']] for c in r['criteria'] if c['role']=='REQUIRED']
            for g in {c['alternative_group'] for c in r['criteria'] if c['role']=='ALTERNATIVE'}:units.append(max(levels[c['criterion_id']] for c in r['criteria'] if c.get('alternative_group')==g))
            k=sum(units)/len(units);s=sum(Decimal(a['strength_rubric'][d]) for d in v3.STRENGTH_DIMENSIONS)/16
            expected=(100*(Decimal('.55')*s+Decimal('.45')*k)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
            computed=v3.confidence(p['fields'],plan['profiles'][iid],a,r)['confidence_raw_score']
            formula.append(dict(case_id=cid,S=str(s),K=str(k),expected=float(expected),actual=computed,result='PASS' if computed==float(expected)==row['confidence_raw_score'] else 'FAIL'))
    assert len(history)==len({h['case_id'] for h in history})==240
    groupcounts=Counter(g for h in history for g in h['groups'].split('|'))
    assert all(groupcounts[k]==v for k,v in {'SUPPORTED_44':44,'CONFIDENCE_100_42':42,'RETRY_PROMOTION_15':15,'BLOCKED_100':100,'NOT_APPLICABLE_DERIVED_49':49}.items()),groupcounts
    csvwrite(OUT/'regresion_run_original.csv',sorted(history,key=lambda r:r['case_id']));csvwrite(OUT/'comparacion_reintentos.csv',retries);csvwrite(OUT/'verificacion_formula.csv',formula)
    cases=read(OUT/'corpus_congelado.json');assert digest(cases)==digest(corpus()),'El corpus congelado cambió: versionar antes de modificar etiquetas.'
    livefile=OUT/'inferencia_local/baseline_v1/results.json';local=read(livefile) if livefile.exists() else [];byid={r['case_id']:r for r in local}
    matrix=[]
    for c in cases:
        r=byid.get(c['case_id']);matrix.append(dict(case_id=c['case_id'],indicador=c['indicator_id'],escenario=c['scenario'],modo=c['mode'],tipo_dato=c['data_type'],entrada=c['text'],decision_esperada=c['expected'],estado_oraculo=c['oracle_status'],
            decision_obtenida=r['actual'] if r else '',resultado=r['result'] if r else 'NOT_EXECUTED',justificacion=c['rationale'],criterio_critico=c['critical_criterion'],par_minimo=c['pair_id'],definicion=c['reference_definition']))
        human.append(dict(case_id=c['case_id'],data_type='SYNTHETIC',indicator_id=c['indicator_id'],mode=c['mode'],input_or_snapshot=c['text'],expected_independent=c['expected'],system_decision=r['actual'] if r else '',provisional_audit=c['oracle_status'],human_status='PENDING',human_decision='',reviewer='',second_reviewer='',criterion_citations='',rationale='',adjudication_date='',definition_approved=''))
    csvwrite(OUT/'matriz_pruebas.csv',matrix)
    hp=OUT/'validacion_humana.csv'
    if hp.exists():
        with hp.open(encoding='utf-8-sig',newline='') as f:old={r['case_id']:r for r in csv.DictReader(f,delimiter=';')}
        for row in human:
            for k in ('human_status','human_decision','reviewer','second_reviewer','criterion_citations','rationale','adjudication_date','definition_approved'):
                if row['case_id'] in old:row[k]=old[row['case_id']][k]
    csvwrite(hp,human)
    tests=[];xml=OUT/'pytest_resultados.xml'
    if xml.exists():
        for t in ET.parse(xml).getroot().iter('testcase'):
            problem=t.find('failure');problem=t.find('error') if problem is None else problem
            tests.append(dict(test_id=t.attrib['name'],scope='PYTEST_ISOLATED',expected='ASSERTION_SATISFIED',actual='FAILED' if problem is not None else 'PASSED',result='FAIL' if problem is not None else 'PASS',evidence=str(xml.relative_to(ROOT)),details=(problem.attrib.get('message','') if problem is not None else '')))
    compat=OUT/'pytest_compatibilidad.xml'
    if compat.exists():
        for t in ET.parse(compat).getroot().iter('testcase'):
            problem=t.find('failure');problem=t.find('error') if problem is None else problem
            tests.append(dict(test_id=t.attrib['classname']+'::'+t.attrib['name'],scope='EXISTING_CONTRACT_TESTS',expected='ASSERTION_SATISFIED',actual='FAILED' if problem is not None else 'PASSED',result='FAIL' if problem is not None else 'PASS',evidence=str(compat.relative_to(ROOT)),details=(problem.attrib.get('message','') if problem is not None else '')))
    for r in local:tests.append(dict(test_id=r['case_id'],scope='NEW_LOCAL_INFERENCE',expected=r['expected'],actual=r['actual'],result=r['result'],evidence=r['path'],details=json.dumps(r['error'],ensure_ascii=False)))
    for r in formula:tests.append(dict(test_id=r['case_id']+':formula',scope='INDEPENDENT_ARITHMETIC',expected=r['expected'],actual=r['actual'],result=r['result'],evidence='verificacion_formula.csv',details='S='+r['S']+' K='+r['K']))
    tests.extend(replay)
    if (OUT/'preflight_local_bloqueado.json').exists() and not local:
        tests.append(dict(test_id='LOCAL_PREFLIGHT',scope='INFRASTRUCTURE_NOT_MODEL_EVALUATION',expected='SUFFICIENT_RAM',actual='BLOCKED_RESOURCE_PREFLIGHT',result='NOT_EXECUTED',evidence='preflight_local_bloqueado.json',details='0 new model calls; no synthetic predictions to score.'))
    if (OUT/'compatibilidad_ejecucion.json').exists():
        tests.append(dict(test_id='EXISTING_SUITE_INITIAL_ATTEMPT',scope='INTERRUPTED_TEST_COMMAND',expected='COMPLETE_XML',actual='INTERRUPTED_NO_COMPLETE_XML',result='INCOMPLETE',evidence='compatibilidad_ejecucion.json',details='Observed partial failures; no full pass/fail count claimed. Bounded rerun preserves first reproducible failure.'))
    csvwrite(OUT/'resultados_pruebas.csv',tests)
    summary=dict(corpus=len(cases),indicator_count=len({c['indicator_id'] for c in cases}),historical_pairs=len(history),groups=dict(groupcounts),attempts_replayed=len(replay),replay_failures=sum(r['result']=='FAIL' for r in replay),formula_count=len(formula),formula_failures=sum(r['result']=='FAIL' for r in formula),
        pytest_count=sum(t['scope']=='PYTEST_ISOLATED' for t in tests),pytest_passed=sum(t['scope']=='PYTEST_ISOLATED' and t['result']=='PASS' for t in tests),pytest_failed=sum(t['scope']=='PYTEST_ISOLATED' and t['result']=='FAIL' for t in tests),
        existing_tests=sum(t['scope']=='EXISTING_CONTRACT_TESTS' for t in tests),existing_passed=sum(t['scope']=='EXISTING_CONTRACT_TESTS' and t['result']=='PASS' for t in tests),existing_failed=sum(t['scope']=='EXISTING_CONTRACT_TESTS' and t['result']=='FAIL' for t in tests),
        local_pairs=len(local),local_calls=sum(len(r['calls']) for r in local),human_confirmed=sum(bool(r['human_status']=='CONFIRMED' and r['human_decision'] and r['reviewer'] and r['rationale'] and r['definition_approved']=='YES') for r in human),human_pending=sum(r['human_status']!='CONFIRMED' for r in human),
        retry_pairs_with_changes=sum(bool(r['promoted_criteria']) for r in retries),retry_comparisons=len(retries),all_retry_evidence_identical=all(r['same_fragments'] for r in retries),all_retry_indicator_conditions_identical=all(r['same_indicator_conditions'] for r in retries),
        retry_instruction_changes=sum(not r['same_instructions'] for r in retries),retry_schema_changes=sum(not r['same_schema'] for r in retries),retry_option_changes=sum(not r['same_options'] for r in retries),
        corpus_sha256=filehash(OUT/'corpus_congelado.json'))
    write(OUT/'resumen_validacion.json',summary);print(json.dumps(summary,ensure_ascii=True,indent=2))
if __name__=='__main__':main()
