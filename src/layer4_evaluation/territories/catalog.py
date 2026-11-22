"""Offline territorial authority: the supplied DANE DD/MMM workbook.

Existing public knowledge supplies optional spelling and populated-place links;
it can never introduce a code absent from the workbook.
"""
import csv
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import math

from layer2_processing.preprocessing.dane_reference import normalize_name, DEFAULT_SOURCE
from .dane_catalog import inspect_catalog

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / DEFAULT_SOURCE
DIRECTORY = ROOT / 'resources/divipola'


def municipal_component(value):
    """CSV representation of the XLSX column C, with literal leading zeros."""
    if isinstance(value, bool):
        raise ValueError('Invalid municipal component')
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError('Invalid municipal component')
        value = int(value)
    text = str(value).strip()
    if not re.fullmatch(r'[0-9]{1,3}', text):
        raise ValueError('Municipal component must contain one to three digits')
    return text.zfill(3)


def display(name, secondary=None):
    """Preserve XLSX names, restoring verified accents/legacy typography."""
    if secondary:
        original, official = normalize_name(name), normalize_name(secondary)
        if (original == official or (original == 'bogota' and official == 'bogota d c')
                or re.search(r'[A-ZÁÉÍÓÚÜÑ]s[A-ZÁÉÍÓÚÜÑ]', name)):
            name = secondary
    return 'Bogotá, D.C.' if normalize_name(name) == 'bogota d c' else name.title()


class Catalog:
    def __init__(self, source=SOURCE, *, secondary_directory=DIRECTORY):
        source = Path(source).resolve()
        initial = source.read_bytes()
        rows, audit, _ = inspect_catalog(source, ROOT, normalize_numeric_components=True)
        if source.read_bytes() != initial:
            raise ValueError('DANE workbook changed during inspection')
        secondary, settlements, secondary_manifest = {}, [], None
        directory = Path(secondary_directory) if secondary_directory is not None else None
        if directory is not None and (directory/'manifest.json').is_file():
            secondary_manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
            tables = {}
            for name, meta in secondary_manifest['files'].items():
                path = directory/name
                if path.name != name or sha256(path.read_bytes()).hexdigest() != meta['sha256']:
                    raise ValueError('Secondary DIVIPOLA checksum mismatch: '+name)
                with path.open(encoding='utf-8', newline='') as stream:
                    tables[path.stem] = list(csv.DictReader(stream))
                if len(tables[path.stem]) != meta['rows']:
                    raise ValueError('Secondary DIVIPOLA count mismatch')
            for row in tables['departments']:
                secondary[row['DPTO_CCDGO']] = dict(name=row['DPTO_CNMBRE'], department=row['DPTO_CCDGO'])
            for row in tables['municipalities']:
                secondary[row['MPIO_CDPMP']] = dict(name=row['MPIO_CNMBRE'], department=row['DPTO_CCDGO'],
                                                   nonmunicipal='NO MUNICIPALIZADA' in row['MPIO_TIPO'])
            settlements = tables['settlements']
        self.by_code, self.dimension, corrections = {}, [], []
        for row in rows:
            if row['territory_type'] == 'COUNTRY':
                continue
            code = row['dane_code']
            other = secondary.get(code, {})
            if other and other['department'] != row['department_code']:
                raise ValueError('Secondary parent contradicts primary XLSX: '+code)
            name = display(row['territory_name'], other.get('name'))
            kind = 'NON_MUNICIPAL_AREA' if other.get('nonmunicipal') else row['territory_type']
            item = dict(row, territory_name=name, normalized_name=normalize_name(name), territory_type=kind,
                        municipality_name=name if kind == 'MUNICIPALITY' else None,
                        primary_name=row['territory_name'])
            if code in self.by_code:
                raise ValueError('Duplicate XLSX territorial code: '+code)
            self.by_code[code] = item
            self.dimension.append(item)
            if name != row['territory_name'].title():
                corrections.append(dict(code=code, source_row=row['source_row'], primary_name=row['territory_name'],
                                        display_name=name, secondary_name=other.get('name')))
        for row in self.by_code.values():
            department = self.by_code.get(row['department_code'])
            if not department or department['territory_type'] != 'DEPARTMENT':
                raise ValueError('Invalid XLSX department parent')
            row['department_name'] = department['territory_name']
            if row['territory_type'] != 'DEPARTMENT' and (len(row['dane_code']) != 5
                    or row['dane_code'] != row['department_code'] + row['municipality_code']):
                raise ValueError('Invalid XLSX DD + MMM structure')
        self.settlements = {}
        for row in settlements:
            code, parent = row['ZU_CDIVI'], row['MPIO_CDPMP']
            if parent not in self.by_code:
                continue
            if not code.startswith(parent) or row['DPTO_CCDGO'] != self.by_code[parent]['department_code']:
                raise ValueError('Populated-place parent contradicts primary XLSX')
            self.settlements.setdefault(normalize_name(row['ZU_CNMBRE']), []).append(
                dict(code=code, name=display(row['ZU_CNMBRE']), parent=parent))
        # Full-table aliases: every identity and parent is present in the XLSX.
        for code, row in self.by_code.items():
            for name in (row['primary_name'], secondary.get(code, {}).get('name')):
                if name and normalize_name(name) != row['normalized_name']:
                    self.dimension.append(dict(row, normalized_name=normalize_name(name)))
        for alias, code in {'bogota':'11001', 'bogota dc':'11001', 'santafe de bogota':'11001', 'santa fe de bogota':'11001',
                            'norte de santander':'54', 'san andres y providencia':'88',
                            'cartagena de indias':'13001', 'santiago de cali':'76001'}.items():
            if code in self.by_code:
                self.dimension.append(dict(self.by_code[code], normalized_name=alias))
        self.manifest = dict(version='DANE_XLSX_DD_MMM_V2', source=str(source),
            source_sha256=sha256(initial).hexdigest(), source_sheet=audit['source_sheet'],
            header_rows=audit['header_rows'], department_count=audit['department_count'],
            municipality_count=audit['municipality_count'],
            columns={'department_code':'A', 'department_name':'B', 'municipality_component':'C', 'municipality_name':'D'},
            municipal_code_rule='Validated DD (2 digits) + MMM (3 digits) = DDMMM (5 digits)',
            display_normalizations=corrections, secondary_knowledge=secondary_manifest,
            secondary_policy='Existing spelling/populated-place knowledge; all exported codes and parents must exist in XLSX')

    def names(self, code):
        row = self.by_code.get(code)
        if row is None:
            raise ValueError('Unknown XLSX DIVIPOLA code: '+str(code))
        return row['department_name'], row['municipality_name'] or ''

    def geography(self, code):
        department, municipality = self.names(code)
        row = self.by_code[code]
        component = municipal_component(row['municipality_code']) if row['territory_type']=='MUNICIPALITY' else ''
        if component and code != row['department_code'] + component:
            raise ValueError('Municipal component contradicts validated full DIVIPOLA code')
        return dict(codigo_dane=row['department_code'], departamento=department,
                    codigo_municipio_dane=component, municipio=municipality)


@lru_cache(maxsize=4)
def _cached_catalog(source, fingerprint, secondary_fingerprint):
    return Catalog(source)


def load_catalog(source=SOURCE):
    source = Path(source).resolve()
    secondary = DIRECTORY/'manifest.json'
    return _cached_catalog(str(source), sha256(source.read_bytes()).hexdigest(),
                           sha256(secondary.read_bytes()).hexdigest() if secondary.is_file() else None)
