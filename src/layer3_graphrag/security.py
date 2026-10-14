"""Reject sensitive payloads; remove personal identifiers only from graph projection."""
import re
from copy import deepcopy

FORBIDDEN = frozenset({'cedula', 'cedula_empleado', 'cedula_investigador', 'document_number',
    'documento', 'id_documento', 'numero_documento', 'email', 'correo', 'correo_electronico',
    'birth_date', 'fecha_nacimiento', 'sex', 'sexo', 'marital_status', 'estado_civil'})
PERSONAL_IDENTIFIERS = FORBIDDEN | {'institutional_id', 'id_empleado', 'id_investigador', 'external_id'}
EMAIL = re.compile(r'[A-Za-z0-9.!#$%&*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')


def key_name(value):
    return str(value).strip().casefold().replace(' ', '_')


def remove_personal_identifiers(value):
    if isinstance(value, dict):
        return {k: remove_personal_identifiers(v) for k,v in value.items() if key_name(k) not in PERSONAL_IDENTIFIERS}
    if isinstance(value, list):
        return [remove_personal_identifiers(v) for v in value]
    return deepcopy(value)


def privacy_issues(value, location='payload'):
    import json
    issues = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key_name(key) in FORBIDDEN:
                issues.append({'id': location, 'reason': 'Sensitive structured field'})
            else:
                if isinstance(item, str) and key.endswith('_json'):
                    item = json.loads(item)
                issues.extend(privacy_issues(item, location + '.' + str(key)))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            issues.extend(privacy_issues(item, location + '[' + str(i) + ']'))
    elif isinstance(value, str) and EMAIL.search(value):
        issues.append({'id': location, 'reason': 'Residual email pattern'})
    return issues
