"""Offline territorial projection shared by every execution backend."""
import csv
import json
from pathlib import Path

from layer4_evaluation.territories.catalog import load_catalog
from layer4_evaluation.territories.document_resolution import DocumentaryResolver

MEASURE_COLUMNS = ['proyecto/articulo_siap_id', 'indicador_id', 'estado_cumplimiento',
    'parrafo_evidencia', 'fuente_evidencia', 'ubicacion_evidencia', 'confianza']
GEOGRAPHY_COLUMNS = ['codigo_dane', 'departamento', 'codigo_municipio_dane', 'municipio']
TERRITORIAL_COLUMNS = MEASURE_COLUMNS + GEOGRAPHY_COLUMNS
RELATION_COLUMNS = ['proyecto/articulo_siap_id', 'indicador_id'] + GEOGRAPHY_COLUMNS


class TerritoryAssignments(dict):
    """Pair-to-codes mapping with separate documentary audit metadata."""
    def __init__(self):
        super().__init__()
        self.audit = []


class TerritoryCodes:
    """Resolve only literal citations used by positive indicator criteria.

    Same-source substantive context disambiguates citations and sublocalities.
    The repository's primary DANE XLSX supplies all territorial codes and parents.
    """
    def __init__(self, root):
        self.root = Path(root)
        self.dimension = None
        self.audit = []
        self._resolver = None

    def __call__(self, project, assessment):
        if self._resolver is None:
            self._resolver = DocumentaryResolver(self.dimension)
        result = self._resolver.resolve(project, assessment)
        self.audit.append(result)
        return result['codes']


def write_results(run, columns, records, codes_by_pair, *, filename='indicadores.csv',
                  territorial_filename='indicadores_territorios.csv', exclusive=False, resolver=None):
    """Preserve measures and emit one territorial row per source/indicator.

    CSV has no type metadata: identifiers are literal text, never Excel formulas.
    Power Query must assign Text before automatic numeric type conversion.
    """
    columns = [c for c in columns if c != 'territorio']
    normal, territorial, relationships, audit = [], [], [], []
    catalog = load_catalog()
    seen = set()
    territorial_pairs = {}
    for record in records:
        row = {c: record[c] for c in columns}
        key = tuple(row.values())
        if key in seen:
            continue
        seen.add(key)
        normal.append(row)
        pair = row.get('proyecto/articulo_siap_id',row.get('siap_id')), row['indicador_id']
        raw_codes = codes_by_pair.get(pair, [])
        if any(not isinstance(c, str) or len(c) not in (2, 5) or not c.isascii() or not c.isdigit() for c in raw_codes):
            raise ValueError('Codigo DANE no textual o incompatible')
        codes = sorted(set(raw_codes))
        codes = [code for code in codes if not (len(code) == 2 and any(c.startswith(code) and len(c) == 5 for c in codes))]
        locations = []
        for code in codes:
            location = catalog.geography(code)
            locations.append(location)
            relationships.append(dict(zip(RELATION_COLUMNS[:2], pair), **location))
        # Scalar join keys only. The bridge retains every individual location.
        # Multiple towns in one department preserve the shared department; a
        # multi-department evaluation leaves scalar geography empty for joining.
        projected = {c: row.get(c, '') for c in MEASURE_COLUMNS}
        projected['proyecto/articulo_siap_id'] = pair[0]
        projected.update(dict.fromkeys(GEOGRAPHY_COLUMNS, ''))
        if len(locations) == 1:
            projected.update(locations[0])
        else:
            departments = {loc['codigo_dane'] for loc in locations}
            if len(departments) == 1:
                projected.update(codigo_dane=locations[0]['codigo_dane'], departamento=locations[0]['departamento'])
        if pair in territorial_pairs:
            if territorial_pairs[pair] != projected:
                raise ValueError('Conflicting source/indicator territorial rows')
        else:
            territorial.append(projected)
            territorial_pairs[pair] = projected
        if len(locations) > 1:
            audit.append(dict(siap_id=pair[0], indicador_id=pair[1], codes=codes,
                              reason='MULTIPLE_TERRITORIES_IN_RELATIONS'))
        elif not locations or not locations[0]['codigo_municipio_dane']:
            audit.append(dict(siap_id=pair[0], indicador_id=pair[1], codes=codes,
                              reason='DEPARTMENT_ONLY' if locations else 'NO_VERIFIABLE_INDICATOR_TERRITORY'))
    directory = Path(run)/'resultados'
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    exports=[(filename,columns,normal)]
    if territorial_filename is not None:
        exports.append((territorial_filename,TERRITORIAL_COLUMNS,territorial))
        bridge = [dict(t) for t in {tuple(r.items()): r for r in relationships}.values()]
        exports.append(('indicadores_territorios_relaciones.csv',RELATION_COLUMNS,bridge))
    for name,_,_ in exports:
        if Path(name).name!=name:raise ValueError('Nombre CSV incompatible')
        if exclusive and (directory/name).exists():raise FileExistsError(directory/name)
    if territorial_filename is not None and exclusive and (directory/'territorios_auditoria.json').exists():
        raise FileExistsError(directory/'territorios_auditoria.json')
    for name, fields, rows in exports:
        target = directory/name
        temporary = target.with_suffix('.csv.pending')
        with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
        with temporary.open(encoding='utf-8-sig', newline='') as stream:
            actual = list(csv.DictReader(stream, delimiter=';'))
        expected = [{k: '' if v is None else str(v) for k, v in row.items()} for row in rows]
        if actual != expected:
            raise ValueError('CSV roundtrip incompatible: '+name)
        temporary.replace(target)
        paths[name] = str(target)
    if territorial_filename is not None:
        target = directory/'territorios_auditoria.json'
        if exclusive and target.exists():
            raise FileExistsError(target)
        temporary = target.with_suffix('.json.pending')
        temporary.write_text(json.dumps(dict(catalog=catalog.manifest, pending=audit,
            resolutions=getattr(resolver, 'audit', []),
            multiple_territory_representation='Scalar codes only; shared department retained; all individual territories in normalized bridge',
            export_municipal_code_rule='XLSX Sheet1 column C (MMM); full DDMMM code retained internally',
            code_types={'codigo_dane':'text, 2 digits', 'codigo_municipio_dane':'text, 3 digits or empty'}),
            ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        temporary.replace(target)
        paths[target.name] = str(target)
    return dict(paths=paths, indicator_rows=len(normal), territory_rows=len(territorial),
                territorial_relationships=len({tuple(r.items()) for r in relationships}),
                columns=columns, territorial_columns=TERRITORIAL_COLUMNS)
