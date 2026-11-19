"""Focused thesis-format checks; synthetic rows and no inference."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator
from layer4_evaluation import thesis_output as output

ROOT=Path(__file__).resolve().parents[1]


def case():
    project=dict(siap_id='00012',field_provenance={'methodology':{'raw_sources':[dict(
        record_source='original.csv',source_row=7,field_mapping={'methodology':'metodologia_original'})]}})
    row=dict(indicator_id='I1',assessment_validation_status='VALID',decision='SUPPORTED',
        confidence_status='COMPUTED',confidence_raw_score=87.5,evidence_explanation='El mecanismo documentado cumple el criterio.')
    locations=[dict(field='methodology',text='El mecanismo funciona.',match_valid=True,section_id='SEC',
        start=10,end=32,coordinate_system='original_unicode_codepoints_0_based_half_open')]
    return project,row,locations


def test_exact_schema_original_column_and_explanation_with_literal_support():
    p,r,e=case();record=output.positive_record(p,r,e)
    assert list(record)==output.COLUMNS and record['fuente_evidencia']=='metodologia_original'
    assert record['confianza']==87.5 and record['territorio_region'] is None
    assert r['evidence_explanation'] in record['parrafo_evidencia'] and e[0]['text'] in record['parrafo_evidencia']
    assert all(x in record['ubicacion_evidencia'] for x in ('original.csv','fila=7','metodologia_original','[10,32)'))
    schema=json.loads((ROOT/'schemas/thesis_output.v1.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator(schema).validate({'Proyectos':[record],'Artículos':[]})


@pytest.mark.parametrize('decision',['NOT_SUPPORTED','INSUFFICIENT_EVIDENCE'])
def test_nonpositive_assessments_never_become_consumer_rows(decision):
    p,r,e=case();r['decision']=decision
    with pytest.raises(ValueError,match='SUPPORTED VALID'):output.positive_record(p,r,e)


def test_duplicate_source_indicator_and_technical_source_are_rejected():
    p,r,e=case();record=output.positive_record(p,r,e)
    with pytest.raises(ValueError,match='duplicado'):output.verify_records([record,deepcopy(record)])
    p['field_provenance']['methodology']['raw_sources'][0]['field_mapping']['methodology']='GraphRAG'
    with pytest.raises(ValueError,match='columna original'):output.positive_record(p,r,e)


def test_autonomous_renderer_uses_same_template_and_leaves_articles_empty(tmp_path):
    import openpyxl
    from autonomous_execution.final_output import render
    p,r,e=case();record=output.positive_record(p,r,e);target=tmp_path/'final.xlsx'
    render(ROOT,[record],target,contract=output.ALL_CONTRACT)
    book=openpyxl.load_workbook(target,read_only=True,data_only=True)
    try:
        assert book.sheetnames==output.SHEETS
        assert list(book['Proyectos'].values)==[tuple(output.COLUMNS),tuple(record[c] for c in output.COLUMNS)]
        assert list(book['Artículos'].values)==[tuple(output.COLUMNS)]
    finally:book.close()


def test_valid_output_keeps_seven_numeric_columns_and_technical_states_only_in_audit(tmp_path):
    import openpyxl,csv
    from layer4_evaluation.indicator_csv import write_results
    p,row,e=case();records=[]
    for n,score in enumerate((0,23.5,37.81,86.25)):
        r=dict(row,indicator_id='I'+str(n),decision='INSUFFICIENT_EVIDENCE' if n<3 else 'SUPPORTED',confidence_raw_score=score)
        records.append(output.indicator_record(p,r['indicator_id'],row=r,locations=e))
    records.extend(output.indicator_record(p,state,status=state) for state in ('NO_EVIDENCE_FITS','BLOCKED_ERROR'))
    original=deepcopy(records)
    target=tmp_path/'valid.xlsx';output.render(ROOT,target,records)
    book=openpyxl.load_workbook(target,read_only=True,data_only=True)
    try:
        rows=list(book['Proyectos'].values)
        assert rows[0]==tuple(output.GENERAL_COLUMNS) and len(rows)==5 and len(rows[0])==7
        assert [r[-1] for r in rows[1:]]==[0,23.5,37.81,86.25]
        assert all(book['Proyectos'].cell(i,7).data_type=='n' for i in range(2,6))
        assert book['Artículos'].max_row==1
    finally:book.close()
    assert records==original
    result=write_results(tmp_path,output.GENERAL_COLUMNS,records[:4],{('00012','I0'):['05']})
    with (tmp_path/'resultados/indicadores.csv').open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream,delimiter=';');values=list(reader)
        assert reader.fieldnames==output.GENERAL_COLUMNS and len(values)==4
        assert values[0]['confianza']=='0'
    with (tmp_path/'resultados/indicadores_territorios.csv').open(encoding='utf-8-sig',newline='') as stream:
        rows=list(csv.DictReader(stream,delimiter=';'))
        assert rows[0]['departamento']=='Antioquia' and rows[0]['municipio']==''
        assert rows[0]['codigo_dane']=='05' and rows[0]['codigo_municipio_dane']=='' and len(rows)==4


@pytest.mark.parametrize('decision',['SUPPORTED','INSUFFICIENT_EVIDENCE','NOT_SUPPORTED'])
@pytest.mark.parametrize('score',[0,23.50,37.81,86.25,100])
def test_all_contract_preserves_scores_decisions_and_evidence(tmp_path,decision,score):
    import openpyxl
    p,r,e=case();r.update(decision=decision,confidence_raw_score=score)
    record=output.indicator_record(p,'I1',row=r,locations=e)
    assert record['estado_cumplimiento']==decision and record['confianza']==score
    assert e[0]['text'] in record['parrafo_evidencia']
    schema=json.loads((ROOT/'schemas/thesis_all_indicators.v1.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator(schema).validate({'Proyectos':[record],'Artículos':[]})
    target=tmp_path/'result.xlsx';output.render(ROOT,target,[record])
    book=openpyxl.load_workbook(target,read_only=True,data_only=True)
    try:
        assert book['Proyectos']['A2'].value=='00012' and book['Proyectos']['A2'].data_type=='s'
        assert book['Proyectos']['H2'].value==score and book['Proyectos']['H2'].data_type=='n'
    finally:book.close()
    repeated=tmp_path/'repeated.xlsx';output.render(ROOT,repeated,[record])
    assert target.read_bytes()==repeated.read_bytes()
    if decision!='SUPPORTED':
        with pytest.raises(ValueError,match='histórico'):output.verify_records([record],output.POSITIVE_CONTRACT)


@pytest.mark.parametrize('state',['BLOCKED_ERROR','REVIEW_REQUIRED','PENDING','NO_EVIDENCE_FITS'])
def test_technical_states_have_null_confidence_and_no_fabricated_evidence(tmp_path,state):
    import openpyxl
    p,r,_=case();r.update(decision='INSUFFICIENT_EVIDENCE',confidence_raw_score=0)
    valid=output.indicator_record(p,'I1',row=r)
    blocked=output.indicator_record(p,'I2',status=state)
    assert valid['fuente_evidencia'] is None and valid['ubicacion_evidencia'] is None
    assert blocked['estado_cumplimiento']==state and all(blocked[k] is None for k in output.COLUMNS[3:])
    target=tmp_path/'result.xlsx';output.render(ROOT,target,[valid,blocked])
    book=openpyxl.load_workbook(target,read_only=True,data_only=True)
    try:
        assert book.sheetnames==output.SHEETS
        assert book['Proyectos']['H2'].value==0 and book['Proyectos']['H3'].value is None
        assert book['Artículos'].max_row==1
    finally:book.close()
    with pytest.raises(ValueError,match='duplicado'):output.verify_records([valid,valid])


def test_offline_recovery_reuses_writers_preserves_originals_and_refuses_overwrite(tmp_path,monkeypatch):
    import shutil
    from scripts import pipeline_coordinator
    p,r,e=case();record=output.indicator_record(p,'I1',row=r,locations=e)
    run=tmp_path/'outputs/runs/local/synthetic';directory=run/'resultados';directory.mkdir(parents=True)
    original=directory/'resultado_indicadores.xlsx';original.write_bytes(b'historical bytes')
    template=tmp_path/output.TEMPLATE;template.parent.mkdir(parents=True);shutil.copyfile(ROOT/output.TEMPLATE,template)
    monkeypatch.setattr(output,'persisted_records',lambda *args,**kwargs:([record],dict(status='PARTIAL',inference_calls=0,scoring_calls=0)))
    monkeypatch.setattr(pipeline_coordinator,'engine',lambda *args:pytest.fail('Offline must not load execution engine'))
    result=pipeline_coordinator.export(tmp_path,run,offline=True)
    assert result['rows']==1 and result['original_files_unchanged'] and result['status']=='PARTIAL'
    assert original.read_bytes()==b'historical bytes'
    receipt=json.loads((directory/'exportacion_completa.receipt.json').read_text(encoding='utf-8'))
    assert 'resultados/resultado_indicadores.xlsx' in receipt['original_files_sha256']
    with pytest.raises(FileExistsError):pipeline_coordinator.export(tmp_path,run,offline=True)


def test_real_persisted_run_is_unambiguous_without_scoring(monkeypatch):
    run=ROOT/'outputs/runs/local/run_20261113_202428_295589'
    if not run.exists():pytest.skip('Historical run not installed')
    from layer4_evaluation import live_execution as live
    monkeypatch.setattr(live,'indicator_row',lambda *a,**kw:pytest.fail('No scoring permitted'))
    monkeypatch.setattr(live,'verify_run',lambda *a,**kw:pytest.fail('Only persisted receipts permitted'))
    records,audit=output.persisted_records(ROOT,run)
    assert len(records)==240 and audit['valid_assessments']==230 and audit['catalog_indicators']==48
    assert sum(r['confianza'] is None for r in records)==10
    assert sum(r['confianza']==0 for r in records)==229
    assert next(r for r in records if r['confianza'])['confianza']==20.63


@pytest.mark.parametrize('corruption',['none','duplicate','missing','changed_score','changed_catalog','missing_block_receipt'])
def test_persisted_loader_stops_on_ambiguous_or_changed_records(tmp_path,corruption):
    import hashlib
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    def write(p,data):
        p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data),encoding='utf-8')
    run=tmp_path/'outputs/runs/local/synthetic';batch=run/'workspace/outputs/layer4/batch_one'
    p,row,_=case();p['project_id']='P';p['fields']={}
    row.update(project_id='P',decision='INSUFFICIENT_EVIDENCE',confidence_raw_score=0,
        evidence_source_fields=[],evidence_texts=[],evidence_stages=[])
    plan=dict(projects=[p],profiles={'I1':{},'I2':{}})
    write(batch/'plan.json',plan)
    write(batch/'manifest.json',dict(plan_sha256=sha(batch/'plan.json'),files={}))
    write(batch/'authorization.json',dict(authorized=True,run_plan_sha256=sha(batch/'plan.json')))
    for iid,status in [('I1','PASS'),('I2','BLOCKED_ERROR')]:
        call=batch/'calls/P'/iid
        write(call/'plan.json',dict(run_plan_sha256=sha(batch/'plan.json'),project_id='P',indicator_ids=[iid],phase='assessment'))
        write(call/'records/assessment/P.json',dict(artifact_hashes={}))
        if iid=='I1':write(call/'assessment.rows.json',dict(record_sha256=sha(call/'records/assessment/P.json'),rows=[row]))
        if not (corruption=='missing_block_receipt' and iid=='I2'):
            write(call/'verification.json',dict(status=status,indicator_ids=[iid]))
    items=[dict(siap_id=p['siap_id'],indicator_id=iid,status=status,decision=decision) for iid,status,decision in
        [('I1','VALID','INSUFFICIENT_EVIDENCE'),('I2','BLOCKED_ERROR',None)]]
    if corruption=='duplicate':items.append(deepcopy(items[0]))
    if corruption=='missing':items.pop()
    if corruption=='changed_score':row['confidence_raw_score']=99
    if corruption=='changed_catalog':write(batch/'plan.json',dict(plan,profiles={'I3':{}}))
    write(run/'estado/execution.json',dict(project_ids=[p['siap_id']]))
    write(run/'resultados/evaluaciones_validas.json',dict(status='PARTIAL',assessments=[dict(row,siap_id=p['siap_id'])]))
    write(run/'resultados/estado_indicadores.json',dict(status='PARTIAL',indicators=items))
    if corruption!='none':
        with pytest.raises(ValueError):output.persisted_records(tmp_path,run)
    else:
        records,audit=output.persisted_records(tmp_path,run)
        assert len(records)==2 and audit['valid_assessments']==1
        assert records[0]['confianza']==0 and records[1]['confianza'] is None
