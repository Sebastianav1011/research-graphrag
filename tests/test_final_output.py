"""Offline projection and institutional joins; no evaluator/model calls."""
from pathlib import Path
import json
import openpyxl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shutil
from autonomous_execution import final_output as final

ROOT=Path(__file__).resolve().parents[1]


def test_official_template_loads_from_foreign_working_directory(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    book=final.load_template()
    assert book.sheetnames==['Proyectos','Artículos']
    for sheet in book:
        assert list(next(sheet.values))==final.SHEETS[sheet.title]
    book.close()
    assert final.template_path()==ROOT/final.TEMPLATE
    assert not (ROOT/'templates').exists() and not (tmp_path/'templates').exists()


@pytest.mark.parametrize('name,n',[('run_institutional_resultados_20261102',9),('run_manual_5501_tec04',1)])
def test_persisted_results_project_without_inference_or_semantic_changes(name,n,tmp_path,monkeypatch):
    from tests import historical
    run=historical.require('outputs/runs/'+name)  # Resolves outputs/runs/<bucket>/<name>; explicit skip if absent.
    records,audit=final.project_records(ROOT,run)
    assert len({(r['siap_id'],r['indicador_id']) for r in records})==n
    assert len(audit['evaluations'])==n
    # Render into managed temp space; historical workbooks remain untouched.
    before=final.s.sha(final.template_path());target=tmp_path/'result.xlsx'
    monkeypatch.chdir(tmp_path)
    final.render(ROOT,records,target)
    assert final.s.sha(final.template_path())==before
    book=openpyxl.load_workbook(target,read_only=True)
    assert book.sheetnames==['INDICADORES','TERRITORIOS']
    rows=list(book['INDICADORES'].values);assert list(rows[0])==final.SHEETS['INDICADORES']
    exported=[dict(zip(rows[0],r)) for r in rows[1:]]
    expected=[dict(zip(final.SHEETS['INDICADORES'],[r['siap_id'],None,r['investigador_id'],r['indicador_id'],
        r['estado_cumplimiento'],r['confianza'],r['parrafo_evidencia'],r['fuente_evidencia'],r['ubicacion_evidencia']])) for r in records]
    assert exported==expected
    assert list(next(book['TERRITORIOS'].values))==final.SHEETS['TERRITORIOS']
    assert book['TERRITORIOS'].max_row==1
    for r in records:
        assert r['parrafo_evidencia'] and len(r['parrafo_evidencia'])<1000
        assert not any('{' in str(v) or 'chunk_' in str(v).lower() for v in r.values())
        assert 'GraphRAG' not in r['fuente_evidencia']
        assert '.xlsx; hoja ' in r['ubicacion_evidencia']
        if r['estado_cumplimiento']=='REVIEW_REQUIRED':assert r['confianza'] is None
        else:assert isinstance(r['confianza'],(float,int))
    book.close()


def test_contract_builder_preserves_user_template(tmp_path,monkeypatch):
    from scripts import build_contracts
    target=final.template_path(tmp_path);target.parent.mkdir(parents=True)
    shutil.copyfile(final.template_path(),target)
    before=final.s.sha(target)
    (tmp_path/'schemas').mkdir();(tmp_path/'docs/data_dictionary').mkdir(parents=True)
    monkeypatch.setattr(build_contracts,'ROOT',tmp_path);monkeypatch.chdir(tmp_path)
    build_contracts.main()
    assert final.s.sha(target)==before and not (tmp_path/'templates').exists()


def test_missing_official_template_never_uses_old_workbook(tmp_path):
    old=tmp_path/'data/templates/resultado_final_indicadores.xlsx';old.parent.mkdir(parents=True)
    shutil.copyfile(final.template_path(),old)
    with pytest.raises(FileNotFoundError):final.load_template(tmp_path)
    assert not (tmp_path/'templates').exists()


def test_historical_template_locator_preserves_original_bytes():
    from layer2_processing.checkpoints import resolve,verify_expected
    old='templates/resultado_final_indicadores.xlsx'
    current=ROOT/'data/templates/resultado_final_indicadores.xlsx'
    assert resolve(ROOT,old)==current
    verify_expected(ROOT,old,final.s.sha(current))


def test_incompatible_columns_are_rejected_without_rewriting(tmp_path):
    target=final.template_path(tmp_path);target.parent.mkdir(parents=True)
    book=final.load_template();book['Proyectos']['A1']='columna_incorrecta';book.save(target);book.close()
    before=final.s.sha(target)
    with pytest.raises(ValueError,match='Proyectos'):final.load_template(tmp_path)
    assert final.s.sha(target)==before


def test_institutional_researcher_relation_preserves_multiple_ids_without_hash_fallback(tmp_path):
    run=tmp_path/'outputs/runs/test';base=run/'workspace/outputs/layer2/canonical';base.mkdir(parents=True)
    def write(name,rows):pq.write_table(pa.Table.from_pylist(rows),base/(name+'.parquet'))
    write('proyectos',[dict(project_id='PROJ_5501',source_project_id='5501')])
    write('proyecto_investigador',[dict(project_id='PROJ_5501',researcher_id=r) for r in ['HASH_A','HASH_B','HASH_C']])
    write('investigadores',[dict(researcher_id='HASH_A',institutional_id='00012'),dict(researcher_id='HASH_B',institutional_id='00013'),dict(researcher_id='HASH_C',institutional_id=None)])
    assert final.researchers(tmp_path,run,dict(siap_id='5501'))==['00012','00013']
    assert final.researchers(tmp_path,run,dict(siap_id='OTHER'))==[None]


def test_scoped_territories_and_template_are_sealed_before_inference(tmp_path):
    from tests import historical
    history=historical.require('outputs/runs/run_institutional_resultados_20261102',compacted=True)/'autonomous/main'
    manifest=final.s.read(history/'manifest.json')
    run=tmp_path/'outputs/runs/scoped';directory=run/'autonomous/main'
    for pid,receipt in manifest['projects'].items():
        target=directory/receipt['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(history/receipt['path'],target)
    target=final.template_path(tmp_path);target.parent.mkdir(parents=True)
    shutil.copyfile(final.template_path(),target)
    reference=ROOT/'outputs/layer2/reference'
    shutil.copytree(reference,tmp_path/'outputs/layer2/reference',ignore=shutil.ignore_patterns('versions'))
    meta=final.s.read(reference/'dane_reference_manifest.json')
    target=tmp_path/meta['source_file'];target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(final.locate(ROOT/meta['source_file']),target)
    projection,files=final.prepare_projection(tmp_path,run,manifest['projects'])
    assert projection['filename']=='resultado_final.xlsx'
    assert all(final.s.sha(tmp_path/name)==digest for name,digest in files.items())
    receipt=final.s.read(directory/'territories.json')
    assert receipt['quality']['status']=='PASS'
    assert receipt['result']['relationships']==[dict(project_id='PROJ_4836',territory_type='MUNICIPALITY',dane_code='11001')]
    assert receipt['field_adapters']
    assert receipt['project_inputs']=={pid:value['sha256'] for pid,value in manifest['projects'].items()}
    target=tmp_path/'result.xlsx'
    final.render(tmp_path,[],target,receipt['rows'])
    book=openpyxl.load_workbook(target,read_only=True)
    assert book.sheetnames==list(final.SHEETS)
    rows=list(book['TERRITORIOS'].values)
    assert rows[1][:4]==('4836',None,'MUNICIPALITY','11001')
    assert rows[1][4]=='titulo' and '.xlsx; hoja ' in rows[1][5]
    book.close()
    # Changing the official reference is an integrity failure, not an empty map.
    target=tmp_path/meta['source_file'];target.write_bytes(target.read_bytes()+b' ')
    with pytest.raises(ValueError,match='DANE modificada'):
        final.prepare_projection(tmp_path,run,manifest['projects'])
