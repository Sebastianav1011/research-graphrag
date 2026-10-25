"""Minimal final consumption projection; never modify the accepted 4B bridge."""
from .experiment_inputs import selected_territories


TERRITORY_COLUMNS = ['siap_id', 'territory_type', 'territory_code', 'code_system']


def territories(data, selected):
    """Keep the dimension's existing composite identity, without names or new IDs.

    The accepted dimension has a canonical territory_id, but its COUNTRY prefix
    is USER_DEFINED whereas the consumer coding system is INTERNAL. Keep the
    explicit tuple rather than manufacturing a differently formatted ID.
    """
    catalog = {}
    canonical_ids = set()
    for row in data['dimension']:
        kind, code = row['territory_type'], row['dane_code']
        system = 'INTERNAL' if kind == 'COUNTRY' else 'DANE'
        if not isinstance(code, str) or not code:
            raise ValueError('Territorial dimension codes must be strings')
        key = kind, code, system
        if key in catalog:
            raise ValueError('Duplicate canonical territorial composite key')
        canonical = row.get('territory_id')
        if canonical is not None:
            if not isinstance(canonical, str) or not canonical or canonical in canonical_ids:
                raise ValueError('Invalid/duplicate authoritative territory_id')
            canonical_ids.add(canonical)
        if kind == 'COUNTRY' and (code != '000' or row.get('territory_origin') != 'USER_DEFINED_COUNTRY'):
            raise ValueError('COUNTRY/000 must use its accepted internal origin')
        if kind not in ('COUNTRY', 'DEPARTMENT', 'MUNICIPALITY'):
            raise ValueError('Unknown accepted territory type')
        catalog[key] = canonical
    output = []
    # Existing projection validates RESOLVED provenance, duplicate relations,
    # institutional IDs and membership in the authoritative dimension.
    for row in selected_territories(data, selected):
        key = row['territory_type'], row['territory_code'], row['code_system']
        if key not in catalog:
            raise ValueError('Exported territory does not match accepted dimension')
        output.append({name: row[name] for name in TERRITORY_COLUMNS})
    return output
