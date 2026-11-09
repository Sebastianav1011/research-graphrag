from copy import deepcopy
import pytest

from layer4_evaluation.indicators.final_projection import TERRITORY_COLUMNS, territories


def fixture_data():
    dimension = []
    for kind, code in [('COUNTRY', '000'), ('DEPARTMENT', '05'), ('MUNICIPALITY', '05001')]:
        dimension.append(dict(territory_id=('USER_DEFINED' if kind == 'COUNTRY' else 'DANE') + ':' + kind + ':' + code,
            territory_type=kind, dane_code=code, territory_name='Colombia' if kind == 'COUNTRY' else 'Synthetic',
            department_code=None if kind == 'COUNTRY' else '05',
            department_name=None if kind == 'COUNTRY' else 'Synthetic',
            territory_origin='USER_DEFINED_COUNTRY' if kind == 'COUNTRY' else 'DANE'))
    relationships = [dict(project_id='P' + str(i), territory_type=r['territory_type'], dane_code=r['dane_code'])
                     for i, r in enumerate(dimension)]
    selected = [dict(project_id='P' + str(i), siap_id='00' + str(i)) for i in range(3)]
    return dict(dimension=dimension, relationships=relationships), selected


def test_minimal_keys_preserve_zeros_and_country_system():
    data, selected = fixture_data()
    rows = territories(data, selected)
    assert all(list(row) == TERRITORY_COLUMNS for row in rows)
    assert rows[0] == dict(siap_id='000', territory_type='COUNTRY', territory_code='000', code_system='INTERNAL')
    assert rows[1]['territory_code'] == '05'
    assert rows[2]['territory_code'] == '05001'
    assert len(territories(data, selected[:1])) == 1


@pytest.mark.parametrize('mutation', [
    lambda d: d['relationships'][0].update(resolution_status='AMBIGUOUS'),
    lambda d: d['relationships'].append(deepcopy(d['relationships'][0])),
    lambda d: d['dimension'].append(deepcopy(d['dimension'][0])),
    lambda d: d['dimension'][0].update(territory_origin='DANE'),
    lambda d: d['dimension'][0].update(dane_code=0),
    lambda d: d['dimension'][1].update(territory_id=d['dimension'][0]['territory_id']),
])
def test_rejects_ambiguous_duplicate_or_incompatible_identity(mutation):
    data, selected = fixture_data()
    mutation(data)
    with pytest.raises(ValueError):
        territories(data, selected)
