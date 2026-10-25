"""Explicit preliminary run over historical candidates; never rebuild upstream layers."""
from collections import Counter
import csv
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import pyarrow as pa
import pyarrow.parquet as pq
from layer4.history import verify_historical_files
from layer4.indicators.profiles import load_profiles
from layer4.territories.inputs import load_projects,sha256
from layer4.territories.contracts import consumption_rows
from layer4.indicators.codex_cli import CodexCliAssessmentProvider,CodexCliBlocked,installed_command
from layer4.indicators.contracts import INDICATOR_COLUMNS
from .selection import SEED,METHOD,eligible_projects,select_projects
from .prompt import make_input
from .contracts import write_or_check
from .preliminary_output import indicator_row,validate_rows,export_and_verify,verify_workbook,spec,summary

ROOT=Path(__file__).resolve().parents[3]
OUT=Path('outputs/layer4/auditoria/historicos/preliminar_20')
RUN='layer3_2026-10-14T094639_959121+0000_eca9000e'
CATALOG_SHA='1aeb1a376c24bca7bdd7acd228da527ef0043f0574541649589badb54e1cf88f'
WORKBOOK='resultado_preliminar_20_proyectos.xlsx'


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def json_file(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def json_lines(path,rows):Path(path).write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True,allow_nan=False)+'\n' for r in rows),encoding='utf-8')
def lines(path):return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def assert_integrity(root,baseline):
    changed=[name for name,expected in baseline.items() if not(root/name).is_file() or sha256(root/name)!=expected]
    if changed:raise ValueError('Protected inputs changed: '+', '.join(changed))
    return {'status':'PASS','protected_files':len(baseline),'changed_files':[]}


def inputs(root):
    root=Path(root);preparation=read(root/'outputs/layer4/auditoria/historicos/preparacion_inicial/preparation_acceptance.json')
    if preparation['status']!='LAYER4_PRELIMINARY_INPUTS_READY':raise ValueError('Preparation not READY')
    baseline=read(root/'outputs/layer4/auditoria/historicos/preparacion_inicial/integrity_before.json')
    for record in preparation['confidence_files']:baseline[record['path']]=record['source_sha256']
    for folder in ('data/reference/processed','schemas/layer4_confidence'):
        for p in (root/folder).rglob('*'):
            if p.is_file():baseline[p.relative_to(root).as_posix()]=sha256(p)
    for path in ('docs/contracts/layer4_confidence_contract.md','docs/contracts/layer4_assessment_contract.md',
                 'docs/contracts/layer4_output_contract.md','config/layer4_confidence.yaml'):
        baseline[path]=sha256(root/path)
    verify_historical_files(root,baseline)
    # A new execution pins the migrated runtime independently of historical inputs.
    # Never copy the archived checksum onto a current-code path.
    baseline={name:sha256(root/name) for name in baseline if (root/name).is_file()}
    baseline.update({p.relative_to(root).as_posix():sha256(p)
                     for p in (root/'src/layer4').rglob('*.py')})
    profile_rows,profile_manifest=load_profiles(root);profiles={p['indicator_id']:p for p in profile_rows}
    if profile_manifest['source_hash']!=CATALOG_SHA or len(profiles)!=48:raise ValueError('Unexpected v2 reference')
    if any(p['preferred_evidence_fields'] or p['preferred_fields_mapping_status']!='UNMAPPED' for p in profiles.values()):
        raise ValueError('Preferred fields differ from approved all48 UNMAPPED')
    manifest=read(root/'data/graphrag/_manifest.json')
    if (manifest['layer3_run_id']!=RUN or manifest['pipeline_version']!='3.2.0'
            or manifest['candidate_architecture']!='SOURCE_INDICATOR_V1' or manifest['status']!='SUCCESS'):
        raise ValueError('Active Layer3 publication mismatch')
    tables={}
    for name in ('source_indicator_candidates','source_context_packages'):
        rel='retrieval/'+name+'.parquet';path=root/'data/graphrag'/rel
        if sha256(path)!=manifest['output_hashes'][rel]:raise ValueError('Layer3 published artifact hash mismatch')
        tables[name]=pq.read_table(path).to_pylist()
    documents,sections,layer2=load_projects(root)
    eligible=eligible_projects(tables['source_indicator_candidates'],tables['source_context_packages'],documents,sections,run_id=RUN)
    selected=select_projects(eligible)
    if any(c['indicator_id'] not in profiles for p in selected for c in p['candidates']):raise ValueError('Candidate profile missing')
    rules=read(root/'data/reference/processed/indicator_assessment_rules.json')['rules']
    request=[make_input({'project_id':p['project_id'],'fields':p['fields']},[profiles[c['indicator_id']] for c in p['candidates']],rules)
             for p in selected]
    # Fail closed, do not replace a deterministically selected project to avoid a
    # privacy issue. Names/provenance tables are never loaded for model inputs.
    email_pattern=re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
    if any(email_pattern.search(v or '') for p in selected for v in p['fields'].values()):
        raise ValueError('Email in authorized project text; stop for explicit privacy handling')
    territory_manifest=read(root/'outputs/layer4/territorios/publicacion/territory_manifest.json')
    relationships=pq.read_table(root/'outputs/layer4/territorios/publicacion/project_territories.parquet').to_pylist()
    ids={p['project_id'] for p in selected}
    territories=consumption_rows([r for r in relationships if r['project_id'] in ids],
                                pq.read_table(root/'data/reference/processed/dane_territories.parquet').to_pylist())
    ambiguous=[r for r in pq.read_table(root/'outputs/layer4/territorios/publicacion/project_territory_ambiguous.parquet').to_pylist()
               if r['project_id'] in ids]
    return {'selected':selected,'profiles':profiles,'requests':request,'territories':territories,'ambiguous':ambiguous,
            'baseline':baseline,'layer3':manifest,'layer2':layer2,'profile_manifest':profile_manifest,
            'eligible_count':len(eligible),'rules':rules,'territory_manifest':territory_manifest}


def prepare(root=ROOT):
    root=Path(root);out=root/OUT
    if out.exists():raise FileExistsError('Preserve existing preliminary directory; use execute/verify for this prepared run')
    data=inputs(root);write_or_check(root,check=True)
    command=installed_command()
    version=subprocess.run([*command,'--version'],capture_output=True,text=True,encoding='utf-8',check=True).stdout.strip()
    help_text=subprocess.run([*command,'exec','--help'],capture_output=True,text=True,encoding='utf-8',check=True).stdout
    for flag in ('--ignore-user-config','--ignore-rules','--output-schema','--ephemeral','--sandbox','--strict-config'):
        if flag not in help_text:raise CodexCliBlocked('Installed CLI lacks required option '+flag)
    out.mkdir(parents=True)
    json_file(out/'integrity_before.json',data['baseline'])
    (out/'codex_cli_exec_help.txt').write_text(help_text,encoding='utf-8')
    selected=data['selected'];columns=['project_id','document_id','title','primary_indicator_id',
        'candidate_count_selected','selection_order','selection_method']
    with (out/'selected_projects.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for p in selected:
            writer.writerow({k:p[k] for k in ('project_id','document_id','title','selection_order','selection_method')}|
                {'primary_indicator_id':p['candidates'][0]['indicator_id'],'candidate_count_selected':len(p['candidates'])})
    json_lines(out/'assessment_inputs.jsonl',data['requests'])
    audit=[]
    for p in selected:
        for c in p['candidates']:
            audit.append({k:c[k] for k in ('source_id','document_id','indicator_id','candidate_id','context_package_id',
                         'hybrid_retrieval_score','source_rank','retrieval_mode','source_context_hash','layer3_run_id')}|
                         {'selection_order':p['selection_order']})
    json_lines(out/'selected_candidates.jsonl',audit)
    json_file(out/'sample_selection.json',{'sample_version':SEED,'selection_method':METHOD,'seed_delimiter':':',
        'eligible_projects':data['eligible_count'],'selected_projects':len(selected),'selected_candidates':len(audit),
        'primary_indicator_distribution':dict(Counter(p['candidates'][0]['indicator_id'] for p in selected)),
        'source_rank_scope':'within indicator; not a cross-indicator ranking',
        'cross_indicator_order':'historical hybrid_retrieval_score DESC, indicator_id ASC',
        'territory_used_for_selection':False,'selection_project_ids':[p['project_id'] for p in selected],
        'privacy':{'project_fields_whitelisted':True,'researcher_tables_read':False,'email_scan':'PASS'},
        'project_field_characters':{p['project_id']:{k:len(v or '') for k,v in p['fields'].items()} for p in selected}})
    manifest={'status':'PREPARED_FOR_CODEX_CLI','sample_version':SEED,'codex_cli_version':version,
        'prepared_at':datetime.now(timezone.utc).isoformat(),'selection_method':METHOD,
        'inputs':{str(path):sha256(root/path) for path in data['baseline']},
        'prepared_artifact_hashes':{p.name:sha256(p) for p in sorted(out.glob('*')) if p.is_file()},
        'layer3_run':RUN,'layer3_pipeline_version':'3.2.0','layer3_architecture':'SOURCE_INDICATOR_V1',
        'retrieval_indicator_version':'catalogo_indicadores.xlsx@L2_'+data['layer3']['layer2_run_id'],
        'assessment_indicator_version':'catalogo_indicadores_v2.xlsx','assessment_indicator_sha256':CATALOG_SHA,
        'confidence_version':'RAW_CONFIDENCE_V1','territory_version':'PROJECT_TERRITORY_V1',
        'assessment_engine':'CODEX_CLI','assessment_engine_status':'PROVISIONAL',
        'codex_call_count':0,'codex_retry_count':0,'project_count':20,'assessments_requested':len(audit)}
    json_file(out/'preliminary_manifest.json',manifest)
    return {'status':manifest['status'],'projects':20,'candidates':len(audit),'eligible_projects':data['eligible_count'],
            'codex_cli_version':version,'primary_indicators':len(set(p['candidates'][0]['indicator_id'] for p in selected))}


def check_prepared(root,data,manifest):
    out=root/OUT
    if any(name.startswith('src/layer4_') for name in manifest.get('code_hashes',{})):
        verify_historical_files(root,read(out/'integrity_before.json'))
    else:
        assert_integrity(root,read(out/'integrity_before.json'))
    for name,digest in manifest['prepared_artifact_hashes'].items():
        if sha256(out/name)!=digest:raise ValueError('Prepared artifact changed: '+name)
    if lines(out/'assessment_inputs.jsonl')!=data['requests']:raise ValueError('Inputs changed after deterministic selection')
    chosen=read(out/'sample_selection.json')['selection_project_ids']
    if chosen!=[p['project_id'] for p in data['selected']]:raise ValueError('Selection is not reproducible')


def validate_test_report(out):
    suite=ET.parse(out/'tests.xml').getroot().find('testsuite')
    if suite is None or any(int(suite.attrib[k]) for k in ('failures','errors','skipped')):raise ValueError('Tests not passing')
    for name in ('layer4_confidence','territories','layer4_preparation','layer4_preliminary'):
        if not any('.'+name+'.' in c.attrib['classname'] for c in suite.findall('testcase')):
            raise ValueError('Missing test suite '+name)
    return {'passed':int(suite.attrib['tests']),'failed':0,'skipped':0,'seconds':float(suite.attrib['time'])}


def parquet_rows(path,rows):
    list_columns={'supported_key_elements','evidence_source_fields','evidence_texts','validation_errors'}
    number_columns={'key_element_coverage','field_relevance_score','corroboration_score','support_strength_score','confidence_raw_score','confidence_probability'}
    fields=[pa.field(k,pa.list_(pa.string()) if k in list_columns else pa.float64() if k in number_columns
                     else pa.int64() if k=='support_strength' else pa.string(),nullable=True) for k in rows[0]]
    pq.write_table(pa.Table.from_pylist(rows,schema=pa.schema(fields)),path,compression='zstd')


def execute(root=ROOT,provider_factory=CodexCliAssessmentProvider):
    root=Path(root);out=root/OUT;manifest=read(out/'preliminary_manifest.json')
    if manifest['status']!='PREPARED_FOR_CODEX_CLI':raise ValueError('Run already started; never repeat assessments implicitly')
    data=inputs(root);check_prepared(root,data,manifest);test_report=validate_test_report(out)
    requests={r['project_id']:r for r in data['requests']}
    provider=provider_factory(out/'codex_runs',root/'schemas/layer4_preliminary/assessment_batch.schema.json',
                              lambda p,i:requests[p['project_id']])
    assessments=[];rows=[]
    manifest.update(status='RUNNING',started_at=datetime.now(timezone.utc).isoformat(),tests=test_report)
    json_file(out/'preliminary_manifest.json',manifest)
    try:
        for p in data['selected']:
            profiles=[data['profiles'][c['indicator_id']] for c in p['candidates']]
            print(f"CODEX_START {p['selection_order']}/20 {p['project_id']}",flush=True)
            try:result=provider.evaluate({'project_id':p['project_id'],'fields':p['fields']},profiles)
            finally:
                json_lines(out/'assessment_raw_outputs.jsonl',provider.raw_outputs)
                json_file(out/'codex_calls.json',{'calls':provider.calls,'call_count':len(provider.calls),
                    'retry_count':sum(c['retry']>0 for c in provider.calls)})
            for a in result:
                assessments.append({'project_id':p['project_id'],**a})
                rows.append(indicator_row(p,data['profiles'][a['indicator_id']],a['assessment']))
            json_lines(out/'assessments.jsonl',assessments)
            print(f"CODEX_DONE {p['selection_order']}/20 assessments={len(rows)} invalid={sum(r['assessment_validation_status']!='VALID' for r in rows)}",flush=True)
    except Exception as exc:
        manifest.update(status='BLOCKED_CODEX_CLI' if isinstance(exc,CodexCliBlocked) else 'BLOCKED',
            error=type(exc).__name__+': '+str(exc)[:500],codex_call_count=len(provider.calls),
            codex_retry_count=sum(c['retry']>0 for c in provider.calls),assessments_returned=len(rows))
        json_file(out/'preliminary_manifest.json',manifest)
        raise
    metadata={'output_status':'PRELIMINARY','sample_version':SEED,'project_count':20,'candidate_limit_per_project':2,
        'selection_method':METHOD,'layer3_run':RUN,'layer3_pipeline_version':'3.2.0','layer3_architecture':'SOURCE_INDICATOR_V1',
        'retrieval_indicator_version':manifest['retrieval_indicator_version'],
        'assessment_indicator_version':'catalogo_indicadores_v2.xlsx','assessment_indicator_sha256':CATALOG_SHA,
        'assessment_engine':'CODEX_CLI','assessment_engine_status':'PROVISIONAL','codex_cli_version':manifest['codex_cli_version'],
        'codex_call_count':len(provider.calls),'codex_retry_count':sum(c['retry']>0 for c in provider.calls),
        'confidence_version':'RAW_CONFIDENCE_V1','confidence_is_probability':False,'confidence_probability':None,'confidence_level':None,
        'preferred_evidence_fields_status':'UNMAPPED_FOR_ALL_48','field_relevance_without_preferences':'Any valid substantive field: F=1.00',
        'territory_version':'PROJECT_TERRITORY_V1','country_internal_code':'000','country_internal_code_system':'INTERNAL',
        'dane_reference_sha256':read(root/'data/reference/processed/dane_reference_manifest.json')['source_sha256'],
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'territory_ambiguous_mentions':len(data['ambiguous']),
        'territory_ambiguous_projects':len({r['project_id'] for r in data['ambiguous']}),
        'warnings':['technical preliminary sample','not statistically representative','assessment engine provisional',
            'raw confidence is not probability','Layer3 candidates were retrieved with previous indicator reference',
            'enriched v2 indicators are used at assessment time','preferred evidence fields are not yet mapped']}
    validate_rows(data['selected'],data['profiles'],assessments,rows,data['territories'],metadata)
    parquet_rows(out/'project_indicator_preliminary.parquet',rows)
    # Save workbook inputs before rendering, enabling verification without any new LLM call.
    json_file(out/'workbook_metadata.json',metadata)
    json_lines(out/'project_territories_selected.jsonl',data['territories'])
    result=summary(data['selected'],rows,data['territories'],data['ambiguous'],provider.calls)
    json_file(out/'preliminary_summary.json',result)
    return finalize(root)


def finalize(root=ROOT):
    """Resume ONLY validation/export of persisted results. Never invoke a provider."""
    root=Path(root);out=root/OUT;manifest=read(out/'preliminary_manifest.json')
    if manifest['status'] not in ('RUNNING','BLOCKED_EXPORT'):
        raise ValueError('Finalize requires persisted assessment results from this run')
    data=inputs(root);check_prepared(root,data,manifest)
    tests=validate_test_report(out)
    rows=pq.read_table(out/'project_indicator_preliminary.parquet').to_pylist()
    assessments=lines(out/'assessments.jsonl');metadata=read(out/'workbook_metadata.json')
    calls=read(out/'codex_calls.json')['calls']
    validate_rows(data['selected'],data['profiles'],assessments,rows,data['territories'],metadata)
    # Establish exact correspondence to each successful raw CLI response.
    from .contracts import validate_wrapper
    raw={r['project_id']:r for r in lines(out/'assessment_raw_outputs.jsonl') if r['technical_error'] is None}
    for p in data['selected']:
        output=validate_wrapper(json.loads(raw[p['project_id']]['raw_output']),p['project_id'],[c['indicator_id'] for c in p['candidates']])
        expected={a['indicator_id']:{k:v for k,v in a.items() if k!='indicator_id'} for a in output['assessments']}
        actual={a['indicator_id']:a['assessment'] for a in assessments if a['project_id']==p['project_id']}
        if actual!=expected:raise ValueError('Stored assessment differs from actual Codex response')
    path=out/WORKBOOK
    if path.exists():
        try:verify_workbook(path,spec(data['selected'],rows,data['territories'],metadata))
        except ValueError:
            archive=out/'codex_runs/workbook_export_attempt_1.bin'
            if archive.exists():raise FileExistsError('Preserve earlier failed export; inspect before another export')
            if not path.resolve().is_relative_to(out.resolve()) or not archive.resolve().is_relative_to(out.resolve()):
                raise ValueError('Export archive escaped this run directory')
            manifest['export_recovery']={'reason':'Literal ISO timestamp coerced into native date by exporter',
                'failed_export_sha256':sha256(path),'archive':'codex_runs/workbook_export_attempt_1.bin',
                'llm_calls_repeated':0,'assessment_rows_modified':0}
            path.rename(archive)
            json_file(out/'preliminary_manifest.json',manifest)
    try:
        qa=verify_workbook(path,spec(data['selected'],rows,data['territories'],metadata)) if path.exists() else export_and_verify(
            data['selected'],rows,data['territories'],metadata,path)
    except Exception as exc:
        manifest.update(status='BLOCKED_EXPORT',error=type(exc).__name__+': '+str(exc)[:500])
        json_file(out/'preliminary_manifest.json',manifest)
        raise
    integrity=assert_integrity(root,read(out/'integrity_before.json'))
    json_file(out/'output_verification.json',{'workbook':qa,'integrity':integrity,'assessments':'PASS','selection_reproducibility':'PASS'})
    manifest.update(status='PRELIMINARY_LAYER4_20_PROJECTS_READY',finished_at=datetime.now(timezone.utc).isoformat(),
        codex_call_count=len(calls),codex_retry_count=sum(c['retry']>0 for c in calls),tests=tests,
        assessments_returned=len(rows),workbook_verification=qa,integrity=integrity,
        code_hashes={p.relative_to(root).as_posix():sha256(p) for folder in ('src/layer4','schemas/layer4_preliminary')
                     for p in sorted((root/folder).rglob('*')) if p.is_file() and p.suffix in ('.py','.json')},
        provider_sha256=sha256(root/'src/layer4/indicators/codex_cli.py'),
        export_code_hashes={name:sha256(root/name) for name in
            ('src/layer4/indicators/export.py','scripts/render_layer4_workbook.mjs','scripts/run_layer4_preliminary.py')
            if (root/name).is_file()},
        output_hashes={p.relative_to(out).as_posix():sha256(p) for p in sorted(out.rglob('*'))
                       if p.is_file() and p.name!='preliminary_manifest.json'})
    json_file(out/'preliminary_manifest.json',manifest)
    return {'status':manifest['status'],**read(out/'preliminary_summary.json'),'workbook':qa}


def verify(root=ROOT):
    root=Path(root);out=root/OUT;manifest=read(out/'preliminary_manifest.json')
    if manifest['status']!='PRELIMINARY_LAYER4_20_PROJECTS_READY':raise ValueError('Run not READY')
    historical=any(name.startswith('src/layer4_') for name in manifest.get('code_hashes',{}))
    if historical:
        verify_historical_files(root,manifest['code_hashes'])
        verify_historical_files(root,manifest.get('export_code_hashes',{}))
        verify_historical_files(root,{'src/layer4_assessment/codex_cli.py':manifest['provider_sha256']})
    else:
        assert_integrity(root,manifest['code_hashes'])
        assert_integrity(root,manifest.get('export_code_hashes',{}))
        assert_integrity(root,{'src/layer4/indicators/codex_cli.py':manifest['provider_sha256']})
    data=inputs(root);check_prepared(root,data,manifest)
    rows=pq.read_table(out/'project_indicator_preliminary.parquet').to_pylist()
    assessments=lines(out/'assessments.jsonl');metadata=read(out/'workbook_metadata.json')
    validate_rows(data['selected'],data['profiles'],assessments,rows,data['territories'],metadata)
    qa=verify_workbook(out/WORKBOOK,spec(data['selected'],rows,data['territories'],metadata))
    for name,digest in manifest['output_hashes'].items():
        if sha256(out/name)!=digest:raise ValueError('Output hash changed: '+name)
    calls=read(out/'codex_calls.json')['calls']
    if len({c['project_id'] for c in calls if c['successful_transport']})!=20:raise ValueError('Codex did not assess20 projects')
    if max(Counter(c['project_id'] for c in calls).values())>2:raise ValueError('Retry limit exceeded')
    if summary(data['selected'],rows,data['territories'],data['ambiguous'],calls)!=read(out/'preliminary_summary.json'):
        raise ValueError('Summary metrics mismatch')
    integrity=(verify_historical_files if historical else assert_integrity)(root,read(out/'integrity_before.json'))
    return {'status':manifest['status'],'workbook':qa,'integrity':integrity}
