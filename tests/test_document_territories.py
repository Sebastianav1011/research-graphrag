"""Real pinned national catalogue, synthetic SOURCE documents, no network or LLM."""
import csv
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from layer4_evaluation.territories.catalog import Catalog, DIRECTORY, SOURCE, load_catalog, municipal_component
from layer4_evaluation.territories.document_resolution import DocumentaryResolver
from layer4_evaluation.indicator_csv import TERRITORIAL_COLUMNS, MEASURE_COLUMNS, write_results


def resolve(text, *, quote=None, extra='', field='methodology', title=''):
    project = dict(project_id='P', siap_id='0007', source_type='ARTICLE' if field=='abstract' else 'PROJECT',
        fields={field: text, 'summary': extra, 'title': title},
        field_provenance={field: dict(section_id='SEC_7', raw_sources=[dict(record_source='original.csv', source_row=7)])})
    assessment = dict(indicator_id='I1', evidence=[dict(field=field, text=quote if quote is not None else text)],
                      criterion_assessments=[dict(support='PARTIAL', evidence_indices=[0])])
    return DocumentaryResolver().resolve(project, assessment)


@pytest.mark.parametrize('text,codes', [
    ('Se realizaron talleres en Medellín.', ['05001']),
    ('Se realizaron talleres en el municipio de Pasto.', ['52001']),
    ('Se realizaron talleres en Bogotá, D.C.', ['11001']),
    ('Se realizaron talleres en Bogota DC.', ['11001']),
    ('Se realizaron talleres en el distrito de Cartagena de Indias.', ['13001']),
    ('Se realizaron talleres en Santiago de Cali.', ['76001']),
    ('Se realizaron talleres en Mpio. de San José del Guaviare, Dpto. de Guaviare.', ['95001']),
    ('Se realizaron talleres en el departamento de Norte de Santander.', ['54']),
    ('Se realizaron talleres en el depto. de N. de Santander.', ['54']),
    ('Se realizaron talleres en Granada (Meta).', ['50313']),
    ('Se realizaron talleres en Granada (Antioquia).', ['05313']),
    ('Se realizaron talleres en Granada (Cundinamarca).', ['25312']),
    ('Se realizaron talleres en Granada.', []),
    ('Se realizaron talleres en el departamento de Nariño.', ['52']),
    ('Se realizaron talleres en el municipio de Nariño.', []),
    ('Se realizaron talleres en el municipio de Caldas, Antioquia.', ['05129']),
    ('Se realizaron talleres en el departamento de Caldas.', ['17']),
    ('Se realizaron talleres en el departamento del Vaupés.', ['97']),
    ('Se realizaron talleres en Quibdó.', ['27001']),
    ('Se realizaron talleres en el municipio de Leticia.', ['91001']),
    ('Se realizaron talleres en el municipio de Soledad.', ['08758']),
    ('Se realizaron talleres en el municipio de Puerto Carreño.', ['99001']),
    ('Se realizaron talleres en el municipio de Yopal.', ['85001']),
    ('Se realizaron talleres en el municipio de Sincelejo.', ['70001']),
    ('Se realizaron talleres en el municipio de Inírida.', ['94001']),
    ('Se realizaron talleres en La Chorrera, Amazonas.', ['91']),
    ('Se construyó un algoritmo sin ámbito geográfico.', []),
    ('La Universidad de Nariño presentó el algoritmo.', []),
    ('La afiliación institucional es Universidad Nacional de Colombia, Bogotá.', []),
    ('Los estudios previos realizaron talleres en Medellín.', []),
    ('Según los antecedentes, se realizaron talleres en Bogotá.', []),
    ('Se realizaron talleres en la vereda Granada.', []),
    ('Se realizaron talleres en el corregimiento Nariño.', []),
    ('Se realizaron talleres en la vereda Matarredonda, municipio de Chachagüí (Nariño, Colombia).', ['52240']),
    ('Se realizaron talleres en el municipio de Medellín y el municipio de Pasto.', ['05001','52001']),
])
def test_national_geography_and_context(text, codes):
    assert resolve(text)['codes'] == codes


def test_department_in_document_disambiguates_cited_homonym():
    result = resolve('Se realizaron talleres en Granada.', extra='Este estudio se desarrolla en el departamento de Meta.')
    assert result['codes'] == ['50313']
    assert result['evidence'][0]['method'] == 'DOCUMENT_STUDY_DEPARTMENT'


def test_multiple_document_departments_do_not_disambiguate_homonym():
    assert resolve('Se realizaron talleres en Granada.', extra='Este estudio se desarrolla en los departamentos de Meta y Antioquia.')['codes'] == []


def test_title_affiliation_and_other_unrelated_document_locations_cannot_assign():
    assert resolve('Se desarrolló un algoritmo.', title='Estudio en Bogotá', extra='Este estudio se desarrolla en Bogotá.')['codes'] == []
    assert resolve('Se realizaron talleres en Granada.', extra='La Universidad de Antioquia participa.')['codes'] == []


def test_sub_locality_parent_from_same_source_context():
    text = 'Se realizaron talleres en la vereda Matarredonda. Esta investigación se centra en la vereda Matarredonda, municipio de Chachagüí (Nariño).'
    result = resolve(text, quote='Se realizaron talleres en la vereda Matarredonda.')
    assert result['codes'] == ['52240']
    assert result['evidence'][0]['method'] == 'DOCUMENT_EXPLICIT_PARENT'
    assert result['evidence'][0]['locality_type'] == 'vereda'


def test_official_settlement_parent_and_ambiguity():
    catalog = load_catalog()
    # Exercise official records across departments, excluding municipal cabeceras.
    samples = []
    for name, candidates in catalog.settlements.items():
        parents = {c['parent'] for c in candidates}
        if len(parents) == 1 and not any(r['normalized_name'] == name for r in catalog.dimension):
            parent = next(iter(parents))
            if catalog.by_code[parent]['territory_type']=='MUNICIPALITY' and parent[:2] not in {p[:2] for _,p in samples}:
                samples.append((candidates[0]['name'],parent))
        if len(samples)==8:
            break
    assert len(samples)==8
    for name, parent in samples:
        result = resolve(f'Se realizaron talleres en el centro poblado {name}.')
        assert result['codes'] == [parent], (name,result)
        assert result['evidence'][0]['method']=='DIVIPOLA_SETTLEMENT_PARENT'
    assert resolve('Se realizaron talleres en la vereda Desconocida Total.')['pending']


def test_abstract_source_and_literal_offsets():
    text='Se realizaron talleres en Mpio. de Inírida (Guainía).'
    result=resolve(text,field='abstract')
    assert result['codes']==['94001']
    for fact in result['evidence']:
        assert text[fact['start']:fact['end']]==fact['text']
        assert fact['provenance']['section_id']=='SEC_7'


def test_official_catalog_complete_parent_integrity_and_corruption(tmp_path):
    catalog=load_catalog()
    assert len([t for t in catalog.by_code.values() if t['territory_type']=='DEPARTMENT'])==33
    assert len(catalog.by_code)==1153
    assert catalog.manifest['municipality_count']==1120
    assert catalog.manifest['source_sha256']==sha256(SOURCE.read_bytes()).hexdigest()
    assert catalog.names('52240')==('Nariño','Chachagüí')
    assert catalog.names('11001')==('Bogotá, D.C.','Bogotá, D.C.')
    for t in catalog.by_code.values():
        assert t['department_code'] in catalog.by_code
    bad=tmp_path/'damaged.xlsx'
    bad.write_bytes(b'Invalid XLSX')
    from zipfile import BadZipFile
    with pytest.raises(BadZipFile):
        Catalog(bad)


def test_every_official_municipal_unit_resolves_with_its_department():
    resolver=DocumentaryResolver()
    count=0
    for code,row in load_catalog().by_code.items():
        if row['territory_type']!='MUNICIPALITY':
            continue
        text=f"Se realizaron talleres en el municipio de {row['territory_name']} ({row['department_name']})."
        facts,_=resolver.mentions(text)
        assert {f['code'] for f in facts if f['kind']=='MUNICIPALITY'}=={code}, text
        count+=1
    assert count==len([r for r in load_catalog().by_code.values() if r['territory_type']=='MUNICIPALITY'])
    assert count>1100


def test_entire_excel_exports_valid_scalar_join_keys(tmp_path):
    catalog=load_catalog()
    original=SOURCE.read_bytes()
    records,codes=[],{}
    for i,(code,territory) in enumerate(catalog.by_code.items()):
        iid=f'I{i}'
        records.append(dict(zip(MEASURE_COLUMNS,['0007',iid,'INSUFFICIENT_EVIDENCE','Cita; intacta','fuente','fila=7',37.81])))
        codes['0007',iid]=[code]
        if len(code)==5:
            assert code==territory['department_code']+territory['municipality_code']
            assert len(territory['department_code'])==2 and len(territory['municipality_code'])==3
        assert territory['source_sheet']=='Sheet1' and territory['source_row']>=4
    result=write_results(tmp_path,MEASURE_COLUMNS,records,codes)
    assert result['territory_rows']==len(catalog.by_code)==1153
    with (tmp_path/'resultados/indicadores_territorios.csv').open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream,delimiter=';')
        assert reader.fieldnames==TERRITORIAL_COLUMNS
        for row in reader:
            assert row['proyecto/articulo_siap_id']=='0007'
            assert len(row['codigo_dane'])==2 and row['codigo_dane'].isdigit()
            assert catalog.by_code[row['codigo_dane']]['territory_name']==row['departamento']
            municipal=row['codigo_municipio_dane']
            if municipal:
                assert len(municipal)==3 and municipal.isascii() and municipal.isdigit()
                full=row['codigo_dane']+municipal
                assert catalog.by_code[full]['municipality_name']==row['municipio']
                assert catalog.by_code[full]['municipality_code']==municipal
            else:
                assert row['municipio']==''
            assert row['confianza']=='37.81' and row['parrafo_evidencia']=='Cita; intacta'
    assert SOURCE.read_bytes()==original


def test_excel_is_authoritative_even_without_secondary_catalog():
    catalog=Catalog(secondary_directory=None)
    assert len(catalog.by_code)==1153
    assert catalog.geography('05001')['codigo_dane']=='05'
    assert catalog.geography('05001')['codigo_municipio_dane']=='001'
    assert catalog.manifest['secondary_knowledge'] is None
    with pytest.raises(ValueError,match='Unknown XLSX'):
        catalog.geography('23682')  # Present in secondary MGN, absent from supplied XLSX.
    assert load_catalog().by_code.get('23682') is None


def test_primary_name_typography_correction_has_code_and_row_provenance():
    catalog=load_catalog()
    row=catalog.by_code['52240']
    assert row['primary_name']=='CHACHAGsI' and row['source_row']==733
    assert catalog.names('52240')==('Nariño','Chachagüí')
    correction=next(x for x in catalog.manifest['display_normalizations'] if x['code']=='52240')
    assert correction['primary_name']=='CHACHAGsI' and correction['secondary_name']=='CHACHAGÜÍ'


def test_normalized_bridge_conserves_grain_and_all_original_measures(tmp_path):
    base=dict(zip(MEASURE_COLUMNS,['0007','I1','INSUFFICIENT_EVIDENCE',
                  'Texto; "literal"\nChachagüí','original.csv','fila=7',37.81]))
    records=[base,dict(base,indicador_id='I2'),dict(base,indicador_id='I3')]
    before=deepcopy(records)
    result=write_results(tmp_path,MEASURE_COLUMNS,records,
        {('0007','I1'):['05001','52001'],('0007','I2'):['52']})
    def read(name):
        with (tmp_path/'resultados'/name).open(encoding='utf-8-sig',newline='') as stream:
            reader=csv.DictReader(stream,delimiter=';'); return reader.fieldnames,list(reader)
    columns,rows=read('indicadores_territorios.csv')
    assert columns==TERRITORIAL_COLUMNS and columns[-4:]==['codigo_dane','departamento','codigo_municipio_dane','municipio']
    assert len(rows)==len(records)==3 and result['territorial_relationships']==3
    assert all(rows[0][c]=='' for c in columns[-4:])  # Multiple departments: bridge has scalar join keys.
    assert rows[1]['departamento']=='Nariño' and rows[1]['municipio']==''
    assert rows[2]['departamento']==rows[2]['municipio']==''
    assert records==before
    for row,original in zip(rows,records):
        assert all(row[k]==str(v) for k,v in original.items())
    bridge_columns,bridge=read('indicadores_territorios_relaciones.csv')
    assert 'confianza' not in bridge_columns and len(bridge)==3
    assert {(r['indicador_id'],r['codigo_dane'],r['codigo_municipio_dane']) for r in bridge}=={('I1','05','001'),('I1','52','001'),('I2','52','')}
    audit=json.loads((tmp_path/'resultados/territorios_auditoria.json').read_text(encoding='utf-8'))
    assert {a['reason'] for a in audit['pending']}=={'DEPARTMENT_ONLY','NO_VERIFIABLE_INDICATOR_TERRITORY','MULTIPLE_TERRITORIES_IN_RELATIONS'}


def test_unrecognized_code_is_rejected_and_not_guessed(tmp_path):
    row=dict(zip(MEASURE_COLUMNS,['0007','I','SUPPORTED','x','s','l',80]))
    with pytest.raises(ValueError,match='Unknown XLSX DIVIPOLA'):
        write_results(tmp_path,MEASURE_COLUMNS,[row],{('0007','I'):['99999']})


def test_repaired_historical_csv_preserves_all_24_original_results():
    directory=Path(__file__).resolve().parents[1]/'outputs/runs/local/run_20261116_094429_222507/resultados'
    receipt_path=directory/'correccion_componente_municipal.receipt.json'
    if not receipt_path.exists():
        pytest.skip('Private historical run is not installed')
    receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
    root=Path(__file__).resolve().parents[1]
    backup=root/receipt['backup']
    target=directory/'indicadores_territorios.csv'
    assert sha256(backup.read_bytes()).hexdigest()==receipt['original_sha256']
    assert sha256(target.read_bytes()).hexdigest()==receipt['corrected_sha256']
    def rows(path):
        with path.open(encoding='utf-8-sig',newline='') as stream:
            return list(csv.DictReader(stream,delimiter=';'))
    original,fixed=rows(backup),rows(target)
    assert len(original)==len(fixed)==24
    assert list(fixed[0])==TERRITORIAL_COLUMNS
    for old,new in zip(original,fixed):
        assert all(old[c]==new[c] for c in MEASURE_COLUMNS)
        assert all(old[c]==new[c] for c in old if c!='codigo_municipio_dane')
        expected=('Nariño','Chachagüí') if new[TERRITORIAL_COLUMNS[0]]=='21736' else ('Bogotá, D.C.','Bogotá, D.C.')
        assert (new['departamento'],new['municipio'])==expected
        expected_codes=('52','240') if new[TERRITORIAL_COLUMNS[0]]=='21736' else ('11','001')
        assert (new['codigo_dane'],new['codigo_municipio_dane'])==expected_codes
    with (root/receipt['original_department_backup']).open(encoding='utf-8-sig',newline='') as stream:
        initial=list(csv.DictReader(stream,delimiter=';'))
    assert [r['codigo_dane'] for r in initial]==[r['codigo_dane'] for r in fixed]


@pytest.mark.parametrize('value,expected',[(1,'001'),(10,'010'),(240,'240'),('001','001'),(1.0,'001')])
def test_municipal_component_is_three_digit_text(value,expected):
    assert municipal_component(value)==expected
    assert isinstance(municipal_component(value),str)


@pytest.mark.parametrize('value',[11001,'11001',True,None,-1,1.5])
def test_municipal_component_rejects_full_codes_and_invalid_values(value):
    with pytest.raises(ValueError):
        municipal_component(value)


@pytest.mark.parametrize('value,expected',[(1,'001'),(10,'010'),(240,'240')])
def test_numeric_column_c_is_normalized_without_changing_internal_identity(tmp_path,value,expected):
    from tests.layer5_territories.test_dane_reference import workbook_at
    source=workbook_at(tmp_path,[('05','ANTIOQUIA',value,'Municipio de prueba')])
    before=source.read_bytes()
    catalog=Catalog(source,secondary_directory=None)
    full='05'+expected
    assert full in catalog.by_code
    assert catalog.by_code[full]['municipality_code']==expected
    assert catalog.geography(full)['codigo_municipio_dane']==expected
    assert source.read_bytes()==before
