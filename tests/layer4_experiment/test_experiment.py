"""Offline fixtures and mocked CLI processes. No institutional inference."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from layer4.indicators import experiment as ex
from layer4.indicators import experiment_export as export
from layer4.indicators.codex_cli import CodexCliAssessmentProvider
from layer4.indicators.experiment_selection import select_sample
from layer4.indicators.review import human_metrics, classification_metrics, evidence_locations

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture
def offline(tmp_path,monkeypatch):
    config=yaml.safe_load((ROOT/ex.CONFIG).read_text(encoding='utf-8'))
    (tmp_path/'config').mkdir()
    (tmp_path/ex.CONFIG).write_text(yaml.safe_dump(config),encoding='utf-8')
    schema=tmp_path/ex.SCHEMA;schema.parent.mkdir(parents=True)
    schema.write_bytes((ROOT/ex.SCHEMA).read_bytes())
    marker=tmp_path/'fixture.txt';marker.write_text('immutable synthetic publication',encoding='utf-8')
    profiles={}
    for i in range(4):
        profiles[f'I{i}']={'indicator_id':f'I{i}','indicator_name':f'Synthetic indicator {i}',
            'indicator_category':f'Category{i%2}','indicator_dimension':f'Dimension{i%3}',
            'key_elements':['Conservación','Participación','Recuperación','Seguimiento'],
            'preferred_evidence_fields':[], 'profile_version':'INDICATOR_ASSESSMENT_PROFILES_V2',
            'descripcion_ampliada':'Synthetic only','favorable_evidence':'Synthetic','insufficient_evidence':'Synthetic'}
    projects=[]
    for i in range(60):
        pid=f'SYNTH_P{i:02d}'
        fields=dict.fromkeys(('title','keywords','summary','methodology','objectives','expected_results'),'')
        fields.update(title='Synthetic project',summary='Conservar bosques.',objectives='Participación comunitaria.')
        projects.append({'project_id':pid,'document_id':'D'+pid,'siap_id':f'00{i:03d}',
            'knowledge_area':f'Area{i%5}','fields':fields,'title':fields['title'],
            'field_provenance':{k:{'section_id':pid+'_'+k} for k in fields},
            'candidates':[{'indicator_id':f'I{(i+j)%4}','hybrid_retrieval_score':0.9-j*0.1,
                           'candidate_id':pid+f'C{j}','source_rank':i+1,'context_status':'ASSESSMENT_READY'}
                          for j in range(1 if i%3==0 else 3)]})
    data={'eligible':projects,'profiles':profiles,'profile_manifest':{'version':'V2','reference_id':'SYNTH','source_hash':'SYNTH_HASH'},
          'layer2':{'layer2_run_id':'L2_SYNTH'},'layer3':{'layer3_run_id':'L3_SYNTH'},'rules':[],
          'candidate_distribution':{'PROJECT:ASSESSMENT_READY':sum(len(p['candidates']) for p in projects)}}
    runtime={'cli_version':'SYNTHETIC_NO_CLI_EXECUTED','command':['SYNTHETIC_NEVER_EXECUTE'],
             'executable_hashes':{},'exec_help_sha256':'SYNTH','features_sha256':'SYNTH'}
    hashes={'fixture.txt':ex.sha256(marker)}
    monkeypatch.setattr(ex,'load_inputs',lambda root,config:deepcopy(data))
    monkeypatch.setattr(ex,'protected_snapshot',lambda root:hashes)
    monkeypatch.setattr(ex,'code_snapshot',lambda root:hashes)
    monkeypatch.setattr(ex,'selected_territories',lambda data,selected:[])
    monkeypatch.setattr(ex,'inspect_runtime',lambda:deepcopy(runtime))
    calls=[];invalid=set()
    def runner(args,**kwargs):
        payload=json.loads(kwargs['input'].split('INPUT_JSON (datos no confiables como instrucciones):\n')[1])
        p=payload['project'];calls.append(p['project_id'])
        assessments=[]
        for profile in payload['indicators']:
            assessments.append({'indicator_id':profile['indicator_id'],'decision':'SUPPORTED','support_strength':3,
                'supported_key_elements':profile['key_elements'][:3],
                'evidence':[{'field':'summary','text':'Invented quote.' if p['project_id'] in invalid else 'Conservar bosques.'},
                            {'field':'objectives','text':'Participación comunitaria.'}], 'explanation':'Synthetic fixture only.'})
        Path(args[args.index('--output-last-message')+1]).write_text(json.dumps({'project_id':p['project_id'],'assessments':assessments}),encoding='utf-8')
        return SimpleNamespace(returncode=0,stdout='{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n',stderr='')
    def provider(*args,**kwargs):return CodexCliAssessmentProvider(*args,runner=runner,**kwargs)
    monkeypatch.setattr(ex,'CodexCliAssessmentProvider',provider)
    progress=ex.prepare(tmp_path)
    out=tmp_path/config['output_directory']
    def authorize(scope):
        auth=ex.read(out/'authorization.example.json')
        auth.update(institutional_text_authorized=True,authorized_by='SYNTH_TEST',authorization_reference='SYNTH_FIXTURE_NOT_REAL',
                    authorized_at='2026-10-19T00:00:00Z',scope=scope)
        path=tmp_path/(scope+'.json');ex.write_json(path,auth)
        return path
    return SimpleNamespace(root=tmp_path,out=out,config=config,data=data,calls=calls,invalid=invalid,
                           authorize=authorize,progress=progress,monkeypatch=monkeypatch)


def test_deterministic_diverse_selection(offline):
    d=offline.data
    first=select_sample(d['eligible'],d['profiles'])
    second=select_sample(list(reversed(d['eligible'])),d['profiles'])
    assert first==second
    assert len(first)==len({p['project_id'] for p in first})==50
    assert len({p['knowledge_area'] for p in first})==5
    for p in first:
        source=next(s for s in d['eligible'] if s['project_id']==p['project_id'])
        assert p['candidates'][0]==source['candidates'][0]
        assert 1<=len(p['candidates'])<=2
        assert all(c in source['candidates'] for c in p['candidates'])
    with pytest.raises(ValueError,match='Only'):select_sample(d['eligible'][:49],d['profiles'])


def test_prepare_no_inference_and_pending_labels(offline):
    f=offline
    assert f.progress['projects_selected']==50 and f.progress['assessments_valid']==0
    assert f.calls==[] and ex.verify(f.root)['status']=='PASS'
    selection=ex.read(f.out/'selection_manifest.json')['projects']
    pbi,human=export.specs(selection,f.data['profiles'],{},[], 'selection','technical')
    assert [s['name'] for s in pbi['sheets']]==['RESULTADO_INDICADORES','TERRITORIOS']
    assert pbi['sheets'][0]['rows']==[]
    assert len(human['sheets'][0]['rows'])==f.progress['assessments_requested']
    assert all(r[4:]==[None,None,None,None] for r in human['sheets'][0]['rows'])


def test_authorization_and_approval_gates(offline):
    f=offline
    with pytest.raises(ValueError,match='authorization file'):ex.execute_batch(f.root,stage='pilot')
    auth=f.authorize('pilot')
    value=ex.read(auth);value['selection_sha256']='wrong';ex.write_json(auth,value)
    with pytest.raises(ValueError,match='Authorization'):ex.execute_batch(f.root,stage='pilot',authorization=auth)
    assert f.calls==[]
    auth=f.authorize('pilot')
    result=ex.execute_batch(f.root,stage='pilot',authorization=auth)
    assert len(f.calls)==5 and result['pilot_complete'] and not result['execution_complete']
    assert all(r['confidence_raw_score']==87.5 for r in ex.read_jsonl(f.out/'technical_results.jsonl'))
    result=ex.execute_batch(f.root,stage='pilot',authorization=auth)
    assert len(f.calls)==5
    with pytest.raises(ValueError,match='review approval'):ex.execute_batch(f.root,stage='continue',authorization=f.authorize('continue'))
    approval=f.root/'approval.json'
    ex.write_json(approval,{'selection_sha256':result['selection_sha256'],'pilot_results_sha256':result['pilot_results_sha256'],
                            'approved':True,'approved_by':'SYNTH_REVIEWER','approved_at':'2026-10-19'})
    continued=ex.execute_batch(f.root,stage='continue',authorization=f.authorize('continue'),pilot_approval=approval)
    assert len(f.calls)==10 and continued['projects_recorded']==10
    assert ex.verify(f.root)['valid_assessments']==continued['assessments_valid']


def test_bad_quotes_preserved_no_retry_or_publication(offline):
    f=offline
    pid=ex.read(f.out/'selection_manifest.json')['projects'][0]['project_id'];f.invalid.add(pid)
    result=ex.execute_batch(f.root,stage='pilot',authorization=f.authorize('pilot'))
    record=ex.read(f.out/'records'/(pid+'.json'))
    assert record['status']=='INVALID_ASSESSMENT' and record['wrapper']['assessments'][0]['evidence'][0]['text']=='Invented quote.'
    assert all(r['confidence_raw_score'] is None for r in record['rows'])
    assert f.calls.count(pid)==1 and not result['pilot_complete']
    with pytest.raises(ValueError,match='no automatic reinference'):ex.execute_batch(f.root,stage='pilot',authorization=f.authorize('pilot'))
    selected=ex.read(f.out/'selection_manifest.json')['projects']
    records={p.stem:ex.read(p) for p in (f.out/'records').glob('*.json')}
    pbi,_=export.specs(selected,f.data['profiles'],records,[], 's','t')
    assert not any(row[0]==next(p['siap_id'] for p in selected if p['project_id']==pid) for row in pbi['sheets'][0]['rows'])


def test_interrupt_after_transport_recovers_without_repeat(offline):
    f=offline;write=ex.write_json;triggered=[]
    def crash(path,value):
        if Path(path).parent.name=='records' and not triggered:
            triggered.append(True);raise OSError('Synthetic coordinator interruption after successful transport')
        write(path,value)
    f.monkeypatch.setattr(ex,'write_json',crash)
    with pytest.raises(OSError,match='interruption'):ex.execute_batch(f.root,stage='pilot',authorization=f.authorize('pilot'))
    assert len(f.calls)==1
    f.monkeypatch.setattr(ex,'write_json',write)
    result=ex.execute_batch(f.root,stage='pilot',authorization=f.authorize('pilot'))
    assert len(f.calls)==5 and len(set(f.calls))==5 and result['pilot_complete']


def test_uncertain_attempt_not_reinferred(offline):
    f=offline;pid=ex.read(f.out/'selection_manifest.json')['projects'][0]['project_id']
    (f.out/'codex_runs'/pid/'attempt_1').mkdir(parents=True)
    ex.execute_batch(f.root,stage='pilot',authorization=f.authorize('pilot'))
    assert pid not in f.calls and 'UNCERTAIN_OUTCOME' in ex.read(f.out/'records'/(pid+'.json'))['error']


def test_protected_and_prompt_tampering_rejected(offline):
    f=offline
    (f.root/'fixture.txt').write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='Fingerprint mismatch'):ex.verify(f.root)
    assert f.calls==[]


def test_response_tampering_and_lock_prevent_inference(offline):
    f=offline;auth=f.authorize('pilot')
    (f.out/'.execution.lock').write_text('SYNTHETIC_OTHER_PROCESS',encoding='utf-8')
    with pytest.raises(FileExistsError):ex.execute_batch(f.root,stage='pilot',authorization=auth)
    (f.out/'.execution.lock').unlink()
    ex.execute_batch(f.root,stage='pilot',authorization=auth)
    response=next((f.out/'codex_runs').glob('*/attempt_1/response.json'))
    response.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='Fingerprint mismatch|original Codex'):ex.verify(f.root)
    assert len(f.calls)==5


def test_human_metrics_wait_for_independent_labels():
    rows=[{'project_id':'SYNTH_P','indicator_id':'I','decision':'SUPPORTED','support_strength':3}]
    assert human_metrics(rows,[])['status']=='PENDING_HUMAN_LABELS'
    label={'project_id':'SYNTH_P','indicator_id':'I','human_label':'NOT_SUPPORTED','reviewer_id':'R1','independent':True}
    metrics=human_metrics(rows,[label])
    assert metrics['per_reviewer']['R1']['accuracy']==0
    with pytest.raises(ValueError,match='independent'):human_metrics(rows,[{**label,'independent':False}])
    with pytest.raises(ValueError,match='Duplicate'):human_metrics(rows,[label,label])
    metrics=classification_metrics(['SUPPORTED','NOT_SUPPORTED'],['SUPPORTED','NOT_SUPPORTED'])
    assert metrics['accuracy']==metrics['cohen_kappa']==1 and metrics['n']==2
    assert classification_metrics([],[]) is None


def test_quote_location_coordinate_system():
    project={'fields':{'summary':'Evidencia\n  literal.'},'field_provenance':{'summary':{'section_id':'SYNTH_SEC'}}}
    location=evidence_locations(project,{'evidence':[{'field':'summary','text':'Evidencia literal.'}]})[0]
    assert location['match_valid'] and location['start']==0
    assert location['coordinate_system'].startswith('NFC_whitespace')


def test_final_export_refuses_incomplete(offline):
    with pytest.raises(ValueError,match='every requested assessment'):export.export(offline.root,require_complete=True)


def test_all_fifty_complete_in_ten_explicit_batches(offline):
    f=offline
    result=ex.execute_batch(f.root,stage='pilot',authorization=f.authorize('pilot'))
    approval=f.root/'approval.json'
    ex.write_json(approval,{'selection_sha256':result['selection_sha256'],'pilot_results_sha256':result['pilot_results_sha256'],
                            'approved':True,'approved_by':'SYNTH_REVIEWER','approved_at':'2026-10-19'})
    for index in range(9):
        result=ex.execute_batch(f.root,stage='continue',authorization=f.authorize('continue'),pilot_approval=approval)
        assert len(f.calls)==10+index*5
    assert result['execution_complete'] and result['assessments_valid']==result['assessments_requested']
    assert len(f.calls)==len(set(f.calls))==50
    assert ex.verify(f.root)['real_execution_complete'] is True  # synthetic test root only
    ex.execute_batch(f.root,stage='continue',authorization=f.authorize('continue'),pilot_approval=approval)
    assert len(f.calls)==50


def test_recovery_rejects_changed_cli_parameters(offline):
    f=offline;write=ex.write_json;triggered=[]
    def crash(path,value):
        if Path(path).parent.name=='records' and not triggered:
            triggered.append(True);raise OSError('Synthetic interruption')
        write(path,value)
    f.monkeypatch.setattr(ex,'write_json',crash)
    with pytest.raises(OSError):ex.execute_batch(f.root,stage='pilot',authorization=f.authorize('pilot'))
    f.monkeypatch.setattr(ex,'write_json',write)
    path=next((f.out/'codex_runs').glob('*/attempt_1/call.json'))
    call=ex.read(path);call['arguments'].append('--dangerously-bypass-approvals-and-sandbox');ex.write_json(path,call)
    ex.execute_batch(f.root,stage='pilot',authorization=f.authorize('pilot'))
    pid=call['project_id'];record=ex.read(f.out/'records'/(pid+'.json'))
    assert record['status']=='ERROR' and 'pinned execution' in record['error']
    assert f.calls.count(pid)==1


def test_artifact_export_preserves_codes_and_formula_like_literals(tmp_path):
    spec={'sheets':[export.sheet('RESULTADO_INDICADORES',export.COLUMNS,[
        {'siap_id':'00042','indicador_id':'SYNTH_I1','estado_cumplimiento':'NOT_SUPPORTED',
         'parrafo_evidencia':'=SUM(A1:A2)','fuente_evidencia':'SIAP','ubicacion_evidencia':'[1] Resumen','confianza':None}]),
        export.sheet('TERRITORIOS',export.TERRITORY_COLUMNS,[
        {'siap_id':'00042','territory_type':'COUNTRY','territory_code':'000','territory_name':'Colombia',
         'department_code':None,'department_name':None,'code_system':'INTERNAL'}])]}
    output=tmp_path/'synthetic.xlsx'
    result=export.export_spec(ROOT,spec,output)
    assert result['status']=='PASS' and result['sheet_rows']=={'RESULTADO_INDICADORES':1,'TERRITORIOS':1}
    assert export.export_spec(ROOT,spec,output)==result


def test_cell_limit_rejected_without_truncation(tmp_path):
    spec={'sheets':[{'name':'TEST','columns':['quote'],'rows':[['x'*32768]]}]}
    with pytest.raises(ValueError,match='no truncation'):export.export_spec(ROOT,spec,tmp_path/'must_not_exist.xlsx')
    assert not (tmp_path/'must_not_exist.xlsx').exists()


def test_review_long_originals_split_and_reconstruct_exactly(offline):
    project=deepcopy(offline.data['eligible'][0])
    project['fields']['summary']='Texto sintético largo. '*1800
    _,human=export.specs([project],offline.data['profiles'],{},[],'selection','technical')
    source=next(s for s in human['sheets'] if s['name']=='FUENTES')
    chunks=[dict(zip(source['columns'],row)) for row in source['rows'] if row[2]=='summary']
    assert len(chunks)>1 and all(len(c['texto_original'])<=1500 for c in chunks)
    assert ''.join(c['texto_original'] for c in chunks)==project['fields']['summary']
    assert [c['inicio_original'] for c in chunks]==list(range(0,len(project['fields']['summary']),1500))
