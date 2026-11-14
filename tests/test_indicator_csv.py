"""CSV roundtrips and real territorial recognition on synthetic citations; no LLM."""
import csv

import pytest

from layer4_evaluation import indicator_csv as export
from layer2_processing.preprocessing.dane_reference import normalize_name


@pytest.fixture
def resolver(tmp_path):
    def territory(name, code, kind='MUNICIPALITY', dept='05'):
        return dict(territory_type=kind, dane_code=code, territory_name=name,
                    normalized_name=normalize_name(name), department_code=dept,
                    department_name='Antioquia' if dept == '05' else 'Meta')
    resolve = export.TerritoryCodes(tmp_path)
    resolve.dimension = [territory('Medellín', '05001'), territory('Bello', '05088'),
                         territory('Antioquia', '05', 'DEPARTMENT'),
                         territory('Granada', '05313'), territory('Granada', '50313', dept='50'),
                         territory('Caldas', '05129'), territory('Caldas', '17', 'DEPARTMENT', '17'),
                         territory('Colombia', '000', 'COUNTRY')]
    return resolve


def case(text, extra=''):
    project = dict(project_id='PROJ_0007', siap_id='0007',
                   fields=dict(methodology=text, summary=extra, title='Medellín'))
    assessment = dict(evidence=[dict(field='methodology', text=text)],
                      criterion_assessments=[dict(support='CLEAR', evidence_indices=[0])])
    return project, assessment


def read(path):
    assert path.read_bytes().startswith(b'\xef\xbb\xbf')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter=';')
        return reader.fieldnames, list(reader)


def test_multiple_indicators_territories_and_csv_consistency(tmp_path, resolver):
    from autonomous_execution.final_output import COLUMNS
    quotes = ['Se realizaron talleres en el municipio de Medellín y en el municipio de Bello.',
              'Se implementó la estrategia en el departamento de Antioquia.',
              'Se desarrolló el método sin ubicación verificable.']
    codes = {}
    records = []
    for i, quote in enumerate(quotes):
        project, assessment = case(quote, 'Otra actividad en Medellín.')
        iid = f'I{i}'
        codes['0007', iid] = resolver(project, assessment)
        records.append(dict(zip(COLUMNS, ['0007', '00012', iid, 'SUPPORTED',
                            'Evidencia; "literal"\nsegunda línea', 'fuente.xlsx', 'fila 2', 83.25, 'ignorar'])))
    assert list(codes.values()) == [['05001', '05088'], ['05'], []]
    performance = tmp_path/'resultados/performance'
    performance.mkdir(parents=True)
    for name in ['resumen.csv', 'por_proyecto.csv', 'metadatos.json']:
        (performance/name).write_bytes(b'untouched measurement')
    export.write_results(tmp_path, COLUMNS, records+records[:1], codes)
    columns, normal = read(tmp_path/'resultados/indicadores.csv')
    territory_columns, territorial = read(tmp_path/'resultados/indicadores_territorios.csv')
    assert columns == COLUMNS[:-1] and territory_columns == columns+['codigo_dane']
    assert len(normal) == 3 and len(territorial) == 3
    assert {r['codigo_dane'] for r in territorial} == {'05', '05001', '05088'}
    assert all({k: r[k] for k in columns} in normal for r in territorial)
    assert len({(r['siap_id'], r['indicador_id'], r['codigo_dane']) for r in territorial}) == 3
    assert all(r['siap_id'] == '0007' and r['investigador_id'] == '00012' for r in normal)
    assert all(p.read_bytes() == b'untouched measurement' for p in performance.iterdir())


@pytest.mark.parametrize('text,expected', [
    ('Talleres en Granada.', []),
    ('Talleres en Caldas.', []),
    ('Talleres en el municipio de Caldas.', ['05129']),
    ('Talleres en el departamento de Caldas.', ['17']),
    ('Talleres en Colombia.', []),
    ('Se construyó un modelo.', []),
])
def test_ambiguity_level_and_no_project_location_join(resolver, text, expected):
    assert resolver(*case(text, 'El proyecto se desarrolla en Medellín.')) == expected


def test_only_literal_positive_criterion_evidence_is_used(resolver):
    project, assessment = case('Talleres en Medellín.')
    assessment['criterion_assessments'][0]['support'] = 'NOT_DEMONSTRATED'
    assert resolver(project, assessment) == []
    assessment['criterion_assessments'][0]['support'] = 'CLEAR'
    assessment['evidence'][0]['text'] = 'Talleres en Bello.'
    assert resolver(project, assessment) == []


def test_empty_results_and_researcher_grain(tmp_path):
    columns = ['siap_id', 'investigador_id', 'indicador_id']
    records = [dict(zip(columns, ['0007', person, 'I'])) for person in ['001', '002']]
    result = export.write_results(tmp_path, columns, records, {('0007', 'I'): ['05001', '05001']})
    assert result['indicator_rows'] == result['territory_rows'] == 2
    result = export.write_results(tmp_path, columns, [], {})
    assert result['indicator_rows'] == result['territory_rows'] == 0
    assert read(tmp_path/'resultados/indicadores_territorios.csv') == (columns+['codigo_dane'], [])


def test_missing_reference_does_not_invent_codes(tmp_path):
    assert export.TerritoryCodes(tmp_path)(*case('Talleres en Medellín.')) == []


def test_installed_corrupt_reference_is_not_silently_ignored(tmp_path):
    directory = tmp_path/'outputs/layer2/reference'
    directory.mkdir(parents=True)
    (directory/'dane_reference_manifest.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='DANE reference manifest'):
        export.TerritoryCodes(tmp_path)(*case('Talleres en Medellín.'))


def test_title_location_alone_does_not_assign_indicator(resolver):
    project, assessment = case('Se desarrolló un método.')
    assessment['evidence'] = [dict(field='title', text='Medellín')]
    assert resolver(project, assessment) == []


def test_autonomous_export_integration(tmp_path, monkeypatch):
    from autonomous_execution import final_output as final
    from autonomous_execution import store
    run = tmp_path/'outputs/runs/synthetic'
    store.write(run/'autonomous/main/manifest.json', {})
    template = final.template_path(tmp_path)
    template.parent.mkdir(parents=True)
    template.write_bytes(final.template_path().read_bytes())
    record = dict(zip(final.THESIS_COLUMNS, ['0007', 'I', 'SUPPORTED', 'Cita', 'Fuente', 'Fila', None, 90]))
    def project_records(root, run, codes, **kwargs):
        assert kwargs['output_contract']=='THESIS_ALL_INDICATORS_V1'
        codes['0007', 'I'] = ['05001']
        return [record], dict(evaluations=[dict(status='PASS')],export_exclusions=[],
            selected_projects=1,processed_projects=1,completed_projects=1,expected_assessments=1,
            valid_assessments=1,supported=1,insufficient_evidence=0,not_supported=0,
            blocked_assessments=0,pending_assessments=0,processing_complete=True,results_available=True)
    monkeypatch.setattr(final, 'project_records', project_records)
    result = final.export(tmp_path, run)
    assert result['csv']['indicator_rows'] == result['csv']['territory_rows'] == 1
    assert 'territorio' not in read(run/'resultados/indicadores.csv')[0]
    assert result['path'].endswith('resultado_indicadores.xlsx')
