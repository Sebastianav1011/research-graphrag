"""Conservative file adapters. No inference, guessed identity, or corpus fallback."""
from run_paths import file_path as run_file
import csv
from datetime import date, datetime
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

import openpyxl
import yaml

DOMAINS = ('proyectos', 'articulos', 'investigadores')
IDENTIFIERS = {'proyectos': ('source_project_id',), 'articulos': ('source_article_id', 'eid', 'doi'),
               'investigadores': ('institutional_id', 'document_number')}
PROJECT_FIELDS = ('title', 'keywords', 'summary', 'methodology', 'objectives', 'expected_results')
PROJECT_HEADERS = ('id_actividad', 'titulo_proyecto', 'convocatoria_codigo', 'convocatoria_nombre',
    'objetivo_socioeconomico', 'palabras_clave', 'gran_area', 'area', 'resumen',
    'actividades_formacion', 'justificacion', 'metodologia', 'resultados_esperados', 'objetivos')
PROJECT_MAPPING = dict(source_project_id=['id_actividad'], title=['titulo_proyecto'],
    socioeconomic_objective=['objetivo_socioeconomico'], keywords=['palabras_clave'],
    knowledge_area=['gran_area'], knowledge_subarea=['area'], summary=['resumen'],
    methodology=['metodologia'], expected_results=['resultados_esperados'], objectives=['objetivos'])
PROJECT_EXTRA = {f'text__{c}': c for c in ('justificacion', 'actividades_formacion')}
PROJECT_TEMPLATE = 'Utilice la plantilla oficial data/templates/plantilla_entrada_proyectos.xlsx.'


def project_upload(path, domain):
    """The public intake is incoming; base and historical runners keep their readers."""
    pairs = set(zip(path.parts, path.parts[1:]))
    return domain == 'proyectos' and ('layer1_sources', 'incoming') in pairs


def validate_project_input(path, headers, rows, sheet):
    """Atomic project contract, shared by preview and preparation through discovery."""
    def reject(message):
        raise ValueError(message + ' ' + PROJECT_TEMPLATE)
    if path.suffix.lower() != '.xlsx':
        reject('Los proyectos deben entregarse en un Excel .xlsx, con hoja Proyectos.')
    if sheet != 'Proyectos':
        reject('Falta la hoja requerida Proyectos (nombre exacto).')
    missing = [c for c in PROJECT_HEADERS if c not in headers]
    unexpected = [c for c in headers if c not in PROJECT_HEADERS]
    duplicates = [c for c in dict.fromkeys(headers) if headers.count(c) > 1]
    if missing or unexpected or duplicates:
        reject(f'Encabezados en fila 1: faltantes={missing}; inesperados={unexpected}; duplicados={duplicates}. '
               'Se esperan los 14 encabezados oficiales, sin importar su orden.')
    seen = {}
    for number, row in rows:
        for column, value in row.items():
            if value is not None and (isinstance(value, bool) or not isinstance(value, (str, int, float))):
                reject(f'Fila {number}, columna {column}: se espera texto o un valor numérico simple.')
            if column in (*PROJECT_EXTRA.values(), 'resumen', 'metodologia', 'objetivos', 'resultados_esperados'):
                if value is not None and not isinstance(value, str):
                    reject(f'Fila {number}, columna {column}: se espera texto o una celda vacía.')
        identity = row['id_actividad']
        if identity is None or not str(identity).strip():
            reject(f'Fila {number}, columna id_actividad: identificador obligatorio vacío.')
        identity = str(identity)
        if identity in seen:
            reject(f'Fila {number}, columna id_actividad: identificador duplicado {identity!r}; primera aparición en fila {seen[identity]}.')
        seen[identity] = number
        if not any(isinstance(row[c], str) and clean(row[c]) and any(ch.isalpha() for ch in clean(row[c]))
                   for c in ('resumen', 'justificacion', 'metodologia', 'objetivos', 'resultados_esperados', 'actividades_formacion')):
            reject(f'Fila {number}: se espera contenido textual en resumen, justificacion, metodologia, '
                   'objetivos, resultados_esperados o actividades_formacion; no basta con título o palabras clave.')
EXTRA = {
    'source_project_id': ['siap_id', 'id_siap', 'id siap', 'codigo siap', 'id_actividad', 'source_project_id'],
    'title': ['title', 'titulo', 'titulo del proyecto', 'nombre del proyecto'],
    'summary': ['summary', 'resumen', 'resumen ejecutivo'],
    'methodology': ['methodology', 'metodologia', 'metodos'],
    'objectives': ['objectives', 'objetivos', 'objetivo general', 'objetivos especificos'],
    'expected_results': ['expected_results', 'resultados esperados'],
    'keywords': ['keywords', 'palabras clave', 'palabras_clave'],
}


def read(path):
    from layer2_processing.checkpoints import locate
    path=locate(path)
    def unique_keys(pairs):
        value = {}
        for name, item in pairs:
            if name in value:
                raise ValueError('JSON con clave duplicada: ' + name)
            value[name] = item
        return value
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=unique_keys)


def write(path, value):
    from run_paths import resolve_file
    path = resolve_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.pending')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def sha(path):
    from layer2_processing.checkpoints import locate
    path=locate(path)
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


DATASETS = ('prueba_controlada', 'prueba_en_vivo')


def inventory(root, dataset, raw_base='data/layer1_sources'):
    root = Path(root).resolve()
    if dataset is not None and dataset not in DATASETS:
        raise ValueError('Seleccionar prueba_controlada o prueba_en_vivo')
    folder = (root / 'tests/fixtures' / dataset).resolve() if dataset else (root / raw_base).resolve()
    if not folder.is_relative_to(root):
        raise ValueError('RAW fuera del repositorio')
    files = source_files(folder)
    if not files:
        raise ValueError('RAW vacio: no se utiliza otra muestra')
    result = []
    for path in files:
        if not path.resolve().is_relative_to(folder):
            raise ValueError('RAW contiene enlaces fuera del conjunto')
        checksum = sha(path)
        result.append(dict(path=str(path), name=path.name, relative_path=path.relative_to(folder).as_posix(),
            format=path.suffix.lower(), bytes=path.stat().st_size, sha256=checksum))
    return dict(dataset=dataset, raw=str(folder), files=result)


def key(value):
    text = ''.join(c for c in unicodedata.normalize('NFD', str(value)) if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def select_text_columns(headers, rows, mapping, policy):
    """Select evidence candidates conservatively; preserve every other column locally.

    A semantic header or explicit include is required. Length alone never authorizes
    model input. Denial and privacy checks take precedence over explicit includes.
    No header implies that a described result has actually happened.
    """
    include = {key(h) for h in policy.get('include', [])}
    exclude = {key(h) for h in policy.get('exclude', [])}
    absent = include - {key(h) for h in headers}
    keywords = {key(h) for h in policy.get('auto_keywords', [
        'resultado', 'resultados', 'conclusion', 'conclusiones', 'hallazgos',
        'impacto', 'impactos', 'evidencia', 'evidencias', 'descripcion', 'aporte'])}
    denied = {'id', 'codigo', 'documento', 'cedula', 'dni', 'email', 'correo',
              'telefono', 'celular', 'direccion', 'nacimiento', 'salario', 'password',
              'token', 'clave', 'sexo', 'genero', 'historia', 'clinica', 'salud',
              'diagnostico', 'cuenta', 'bancaria', 'url', 'ruta', 'hash', 'orcid', 'doi',
              'nombre', 'nombres', 'persona', 'personas', 'personal', 'personales',
              'investigador', 'investigadores', 'autor', 'autores', 'ip', 'log', 'logs',
              'credencial', 'credenciales', 'latitud', 'longitud', 'fecha', 'hora',
              'timestamp', 'checksum', 'sensible', 'confidencial'}
    mapped = {c for columns in mapping.values() for c in columns}
    selected = {}
    decisions = [dict(column=label, selected=False, reason='CONFIGURED_OPTIONAL_COLUMN_ABSENT') for label in sorted(absent)]
    for column in headers:
        if column in mapped:
            continue
        label = key(column)
        values = [r.get(column) for _, r in rows if r.get(column) not in (None, '')]
        reason = 'UNREVIEWED_COLUMN_PRESERVED'
        if label in exclude or set(label.split()) & denied:
            reason = 'EXCLUDED_OR_SENSITIVE_HEADER'
        elif values and all(isinstance(v, str) for v in values):
            if any(re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://|\b\d{7,}\b', v) for v in values):
                reason = 'POSSIBLE_PERSONAL_OR_TECHNICAL_CONTENT'
            elif label in include or ((label in keywords or set(label.split()) & keywords) and
                    max(len(v.strip()) for v in values) >= policy.get('min_characters', 20)):
                field = 'text__' + label.replace(' ', '_')
                selected[field] = column
                reason = 'CONFIGURED_TEXT' if label in include else 'SEMANTIC_HEADER_TEXT'
            else:
                reason = 'TEXT_CANDIDATE_PRESERVED_REQUIRES_CONFIGURATION'
        decisions.append(dict(column=column, selected=column in selected.values(), reason=reason))
    return selected, decisions


def docx_text(path):
    with zipfile.ZipFile(path) as archive:
        body = ET.fromstring(archive.read('word/document.xml')).find('{*}body')
    def paragraph(node):
        return ''.join((e.text or '') if e.tag.endswith('}t') else ('\t' if e.tag.endswith('}tab') else '\n')
                       for e in node.iter() if e.tag.endswith(('}t', '}tab', '}br')))
    lines = []
    for child in body:
        if child.tag.endswith('}p'):
            lines.append(paragraph(child))
        elif child.tag.endswith('}tbl'):
            for row in child.findall('{*}tr'):
                cells = ['\n'.join(paragraph(p) for p in cell.findall('.//{*}p')) for cell in row.findall('{*}tc')]
                lines.append(cells[0] + ': ' + '\n'.join(cells[1:]) if len(cells) > 1 else '\n'.join(cells))
    return '\n'.join(lines)


def heading_fields(text):
    """Keep labelled sections, including unknown headings, without inventing identity."""
    fields, current = {}, None
    for line in text.splitlines():
        label, separator, value = line.strip().partition(':')
        if separator and 0 < len(label) <= 80 and not re.search(r'[.!?;/\\]', label):
            current = label.strip()
            fields.setdefault(current, []).append(value.strip())
        elif current:
            fields[current].append(line)
    return {name: '\n'.join(lines).strip() for name, lines in fields.items()}



def _read_tabular(path, sheet=None):
    """Return (headers, (record locator, values)...), preserving textual identifiers."""
    ext = path.suffix.lower()
    if ext == '.json':
        value = read(path)
        if isinstance(value, dict):
            value = value.get('projects', value.get('proyectos', [value]))
        if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
            raise ValueError('JSON debe contener objetos o una lista projects/proyectos')
        result = []
        for index, row in enumerate(value, 1):
            row = dict(row)
            nested = row.pop('fields', {})
            if not isinstance(nested, dict) or set(nested) & set(row):
                raise ValueError('JSON fields invalido o columnas duplicadas')
            result.append((index, row | nested))
        return list(dict.fromkeys(k for _, r in result for k in r)), result, None
    if ext in ('.csv', '.tsv'):
        try:
            text = path.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            text = path.read_text(encoding='cp1252')
        try:
            delimiter = csv.Sniffer().sniff(text.splitlines()[0], delimiters=',;\t|').delimiter
        except (csv.Error, IndexError):
            delimiter = ','
        csv.field_size_limit(10_000_000)
        parsed = csv.DictReader(io.StringIO(text), delimiter=delimiter, strict=True)
        headers = parsed.fieldnames or []
        rows = []
        for row in parsed:
            if None in row or any(v is None for v in row.values()):
                raise ValueError('CSV con cantidad de columnas inconsistente')
            rows.append((parsed.line_num, row))
        return headers, rows, None
    if ext == '.xlsx':
        with zipfile.ZipFile(path) as archive:
            types = ET.fromstring(archive.read('[Content_Types].xml'))
            if not any(item.get('ContentType') ==
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'
                       for item in types):
                raise ValueError('Se espera contenido de Excel .xlsx, no otro formato renombrado.')
        book = openpyxl.load_workbook(path, data_only=False, read_only=True)
        try:
            if sheet is None and 'Proyectos' in book.sheetnames:
                sheet = 'Proyectos'
            if sheet is not None and sheet not in book.sheetnames:
                raise ValueError(f'Falta la hoja requerida {sheet}.')
            if sheet is None and len(book.worksheets) != 1:
                raise ValueError('XLSX con varias hojas: configurar sheet explicitamente; disponibles: ' + ', '.join(book.sheetnames))
            ws = book[sheet] if sheet else book.worksheets[0]
            records = iter(ws.iter_rows())
            headers = [str(c.value or '') for c in next(records, [])]
            official = project_upload(path, 'proyectos') and ws.title == 'Proyectos' and set(headers) == set(PROJECT_HEADERS)
            rows = []
            for index, cells in enumerate(records, 2):
                if all(c.value is None for c in cells):
                    continue
                row = {}
                for name, cell in zip(headers, cells):
                    value = cell.value
                    if cell.data_type == 'e':
                        raise ValueError(f'Celda con error en {ws.title}!{cell.coordinate}; entregar un valor válido')
                    if isinstance(value, datetime) and not official:
                        value = value.isoformat(sep=' ')
                    elif isinstance(value, date) and not official:
                        value = value.isoformat()
                    if cell.data_type == 'f':
                        raise ValueError(f'Formula no admitida en {ws.title}!{cell.coordinate}; entregar valores')
                    if not official and isinstance(value, (int, float)) and not isinstance(value, bool) and value == int(value) and re.fullmatch('0+', cell.number_format or ''):
                        value = str(int(value)).zfill(len(cell.number_format))
                    row[name] = value
                rows.append((index, row))
            return headers, rows, ws.title
        finally:
            book.close()
    raise ValueError('Formato tabular no soportado: ' + ext)


READERS = {extension: _read_tabular for extension in ('.csv', '.tsv', '.json', '.xlsx')}


def tabular(path, sheet=None):
    """Reader extension point: extension -> callable(path, sheet) returning headers/rows/sheet."""
    path = Path(path)
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        raise ValueError('Formato tabular no soportado: ' + path.suffix.lower() +
                         '. Para proyectos se espera Excel .xlsx. ' + PROJECT_TEMPLATE)
    return reader(path, sheet)


def clean(value):
    if value is None:
        return ''
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        value = ';'.join(value)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if not isinstance(value, (str, int, float)):
        raise ValueError('Valor de campo no escalar')
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    value = str(value)
    if value in ('NULL', 'null', 'N/A', 'n/a', 'NaN', 'nan'):
        return ''
    return unicodedata.normalize('NFC', value).replace('\r\n', '\n').replace('\r', '\n').strip()


def domain_for(path, headers, override, known=None):
    if override:
        if override not in DOMAINS:
            raise ValueError('domain debe ser proyectos, articulos o investigadores')
        return override
    if path.suffix.lower() == '.xlsx' and 'titulo_proyecto' in headers:
        return 'proyectos'
    if path.parent.name in DOMAINS:
        return path.parent.name
    if 'incoming' not in path.parts:
        # Established base/fixture adapters retain their historical filename contract.
        for prefix, domain in (('descriptores', 'proyectos'), ('produccion', 'articulos'), ('miembros', 'investigadores')):
            if key(path.stem).startswith(prefix):
                return domain
    known = known or {}
    candidates = []
    people = set(mapping_for('investigadores', headers, known.get('investigadores', {}), None))
    for domain in DOMAINS:
        fields = set(mapping_for(domain, headers, known.get(domain, {}), None))
        if domain == 'proyectos' and 'source_project_id' in fields and not ('full_name' in people and people & {'institutional_id', 'document_number'}):
            candidates.append(domain)
        elif domain == 'articulos' and fields & {'source_article_id', 'doi', 'eid'}:
            candidates.append(domain)
        elif domain == 'investigadores' and 'full_name' in fields and fields & {'institutional_id', 'document_number'}:
            candidates.append(domain)
    if len(candidates) == 1:
        return candidates[0]
    if path.suffix.lower() == '.xlsx' and project_upload(path, 'proyectos'):
        return 'proyectos'  # Unrecognized new workbooks must satisfy the official contract.
    raise ValueError('Dominio ambiguo: configurar domain y mapping en files')


def mapping_for(domain, headers, source_spec, override):
    index = {key(h): h for h in headers}
    aliases = {field: value if isinstance(value, list) else [value] for field, value in source_spec.get('mapping', {}).items()}
    from layer2_processing.preprocessing.contracts import FIELDS
    for field in set(FIELDS.get(domain, {})) - {'project_id', 'article_id', 'researcher_id', 'organization_id'}:
        aliases.setdefault(field, [field])
    for field in list(aliases):
        aliases[field] = [field] + aliases[field]
    if domain == 'proyectos':
        for field, names in EXTRA.items():
            aliases[field] = list(dict.fromkeys(aliases.get(field, []) + names))
    if override:
        allowed = set(FIELDS.get(domain, {})) | {'source_project_id', 'project_title', 'role', 'is_responsible'}
        if domain != 'optional' and set(override) - allowed:
            raise ValueError('Campo canonico no admitido en mapping: ' + str(sorted(set(override) - allowed)))
        for field, name in override.items():
            names = name if isinstance(name, list) else [name]
            if any(key(n) not in index for n in names):
                raise ValueError('Columna configurada ausente: ' + str(name))
            aliases[field] = names
    return {field: list(dict.fromkeys(index[key(n)] for n in names if key(n) in index)) for field, names in aliases.items() if any(key(n) in index for n in names)}


def source_files(folder, paths=None):
    """Official intake is base + incoming; reference is processed separately."""
    folder = Path(folder)
    if paths is not None:
        if not isinstance(paths, list) or not paths or len(paths) != len(set(paths)):
            raise ValueError('Seleccion de archivos vacia o duplicada')
        selected = []
        for relative in paths:
            path = folder / relative
            if Path(relative).is_absolute() or not path.resolve().is_relative_to(folder.resolve()) or path.is_symlink() or not path.is_file():
                raise ValueError('Archivo seleccionado inexistente o fuera de las fuentes')
            if folder.name == 'layer1_sources' and Path(relative).parts[0] not in ('base', 'incoming'):
                raise ValueError('Solo se seleccionan archivos de base o incoming; las referencias se configuran aparte')
            selected.append(path)
        return sorted(selected)
    roots = [folder / name for name in ('base', 'incoming')] if folder.name == 'layer1_sources' else [folder]
    return sorted(p for root in roots for p in root.rglob('*') if p.is_file() and p.name != 'README.md' and not p.name.startswith('.'))


def source_registry(root, config):
    path = root / config.get('sources_path', 'config/sources.yaml')
    if not path.is_file() and 'sources_path' not in config:
        path = root / 'config/sources.example.yaml'
    known = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
    defaults = root / 'config/sources.example.yaml'
    standard = yaml.safe_load(defaults.read_text(encoding='utf-8-sig')).get('knowledge_detection', {}) if defaults.is_file() else {}
    custom = known.get('knowledge_detection', {})
    catalog = standard | custom
    for section in ('categories', 'mapping_aliases', 'identifier_namespaces', 'column_overrides'):
        catalog[section] = standard.get(section, {}) | custom.get(section, {})
    known['knowledge_detection'] = catalog
    for domain, fields in catalog.get('mapping_aliases', {}).items():
        if domain not in DOMAINS or domain not in known:
            continue
        mapping = known[domain].setdefault('mapping', {})
        for field, aliases in fields.items():
            existing = mapping.get(field, [])
            mapping[field] = list(dict.fromkeys((existing if isinstance(existing, list) else [existing]) + aliases))
    if config.get('project_selection') or config.get('knowledge_scope')=='BASE_GLOBAL_V1':
        # Institutional audit: id_investigador has many-to-many values against
        # id_empleado. It is not a verified alias of employee identity. Retain
        # its original value in lineage, never use it to bridge persons.
        mapping = known.get('investigadores', {}).get('mapping', {})
        aliases = mapping.get('institutional_id', [])
        aliases = aliases if isinstance(aliases, list) else [aliases]
        mapping['institutional_id'] = [a for a in aliases if key(a) != 'id investigador']
    return known


def file_configuration(config, relative):
    from fnmatch import fnmatchcase
    # A folder selection keeps registry paths relative to the official intake root.
    qualified = config.get('source_prefix', '') + relative
    matches = [spec for pattern, spec in config.get('files', {}).items() if fnmatchcase(qualified, pattern)]
    if not matches and qualified != relative:
        matches = [spec for pattern, spec in config.get('files', {}).items() if fnmatchcase(relative, pattern)]
    if len(matches) > 1:
        raise ValueError('Varias reglas de files coinciden: ' + relative)
    return matches[0] if matches else {}


def required_fields(root, domain, override):
    if 'required_fields' in override:
        return override['required_fields']
    path = root / 'config/layer1.yaml'
    if path.is_file():
        settings = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
        return settings['validation']['required_fields'].get(domain, [])
    return {'proyectos': ['source_project_id'], 'articulos': ['title'], 'investigadores': []}[domain]


def read_source(path, override, extracted=None):
    """Same existing document and tabular adapters for discovery and processing."""
    if path.suffix.lower() not in ('.docx', '.pdf', '.txt', '.md'):
        try:
            return tabular(path, override.get('sheet'))
        except Exception as exc:
            if path.suffix.lower() == '.xlsx':
                detail = (str(exc) if isinstance(exc, ValueError) and str(exc).startswith(
                    ('XLSX ', 'Formula ', 'Falta ', 'Se espera ', 'Celda '))
                    else 'El contenido no es un Excel .xlsx válido o está dañado.')
                raise ValueError(detail + ' ' + PROJECT_TEMPLATE) from exc
            raise
    if path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ValueError('PDF cifrado: proporcionar copia legible')
        text = '\n\n'.join(page.extract_text() or '' for page in reader.pages)
    elif path.suffix.lower() == '.docx':
        text = docx_text(path)
    else:
        text = path.read_text(encoding='utf-8-sig')
    if extracted is not None:
        extracted.parent.mkdir(parents=True, exist_ok=True)
        extracted.write_text(text, encoding='utf-8')
    if not text.strip():
        raise ValueError('Documento sin texto extraible; OCR no implementado')
    obj = heading_fields(text)
    return list(obj), [(1, obj)], None


def column_kind(column):
    tokens = set(key(column).split())
    if tokens & {'correo', 'email', 'telefono', 'cedula', 'documento', 'nacimiento', 'salario', 'sexo', 'genero', 'clinica', 'salud', 'sensible', 'confidencial'}:
        return 'sensitive'
    if tokens & {'id', 'codigo', 'identificador', 'doi', 'eid', 'orcid'}:
        return 'identifier'
    if tokens & {'ruta', 'hash', 'url', 'timestamp', 'checksum', 'token'}:
        return 'technical'
    return 'potential_text_requires_authorization'


def base_source(root,path,config):
    return path.resolve().is_relative_to((root/'data/layer1_sources/base').resolve()) and config.get('documentary_source_policy')!='SELECTED_ONLY_V1'


def base_valid_rows(domain,mapping,rows):
    """Isolate unverifiable BASE identities; preserve original occurrence locators."""
    from .normalize import identifier,doi,eid
    fields=('source_project_id',) if domain=='proyectos' else ('source_article_id','eid','doi') if domain=='articulos' else ()
    if fields and not any(f in mapping for f in fields):
        raise ValueError('Columnas estructurales de identidad ausentes: '+', '.join(fields))
    valid,rejected=[],[]
    for number,values in rows:
        identifiers=[]
        for field in fields:
            for column in mapping.get(field,[]):
                value=clean(values.get(column))
                normalized=doi(value) if field=='doi' else eid(value) if field=='eid' else identifier(value)
                pattern=r'10\.\d{4,9}/\S+' if field=='doi' else r'2-s2\.0-\d+' if field=='eid' else r'[\w.:/-]+'
                if normalized and re.fullmatch(pattern,normalized,re.I):identifiers.append(normalized)
        if fields and not identifiers:
            rejected.append(dict(row=number,reasons=['Identificador obligatorio ausente o sin identidad verificable: '+', '.join(fields)]))
        else:valid.append((number,values))
    return valid,rejected


def discover_sources(root, config=None, folder=None):
    """Read-only preview; never canonicalizes, merges identities, indexes or calls LLM.

    Exact unknown values stay in local records, with a cell locator for every field.
    READY_FOR_VALIDATION is not publication or identity-resolution acceptance.
    """
    root = Path(root).resolve()
    config = config if config is not None else read(root / 'config/pipeline_manual.json')
    folder = (root / (folder or config.get('raw_base', 'data/layer1_sources'))).resolve()
    if not folder.is_relative_to(root) or not folder.is_dir():
        raise ValueError('Carpeta de fuentes inexistente o fuera del repositorio')
    known = source_registry(root, config)
    result = []
    identities = {}
    for path in source_files(folder, config.get('source_paths')):
        rel = path.relative_to(folder).as_posix()
        item = dict(file=rel, status='PENDING_CONFIGURATION', diagnostics=[])
        result.append(item)
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(folder):
                raise ValueError('Fuente redirigida fuera de la entrega')
            item['sha256'] = sha(path)
            item['delivery'] = rel.split('/')[1] if rel.startswith('incoming/') and len(rel.split('/')) > 2 else path.parent.name
            override = file_configuration(config, rel)
            headers, rows, sheet = read_source(path, override)
            item.update(headers=headers, sheet=sheet, record_count=len(rows), records=[dict(file=str(path), sheet=sheet, row=n,
                original_values=values, field_provenance={c: dict(file=str(path), sheet=sheet, row=n, column=c) for c in headers}) for n, values in rows])
            domain = domain_for(path, headers, override.get('domain'), known)
            official = project_upload(path, domain)
            if official:
                validate_project_input(path, headers, rows, sheet)
                item['project_contract'] = True
            if not headers or len({key(h) for h in headers}) != len(headers) or any(not key(h) for h in headers) or not rows:
                raise ValueError('Encabezados vacios/duplicados o archivo sin registros. ' + (PROJECT_TEMPLATE if official else ''))
            from .knowledge_fields import describe_columns
            item['column_classification'] = describe_columns(headers, rows, {}, known.get('knowledge_detection', {}))
            item['record_validation'] = dict(valid=0, rejected=0, pending=len(rows), scope='domain_and_identity_not_yet_validated')
            mapping = PROJECT_MAPPING.copy() if official else mapping_for(domain, headers, known[domain], override.get('mapping'))
            from .knowledge_fields import analyze_columns
            policy = config.get('text_columns', {}) | override.get('text_columns', {}) | {'auto_keywords': []}
            tolerant=base_source(root,path,config)
            if tolerant and domain=='proyectos':
                policy['include']=list(dict.fromkeys(policy.get('include',[])+[c for c in ('justificacion','actividades_formacion') if c in headers]))
            mapping, extra, decisions, classification = analyze_columns(headers, rows, mapping,
                known.get('knowledge_detection', {}), policy, select_text_columns)
            if official:
                extra = PROJECT_EXTRA.copy()
                from .knowledge_fields import describe_columns
                classification = describe_columns(headers, rows, mapping, known.get('knowledge_detection', {}), extra)
            isolated=[]
            if tolerant:
                rows,isolated=base_valid_rows(domain,mapping,rows)
                accepted={n for n,_ in rows}
                item['records']=[r for r in item['records'] if r['row'] in accepted]
            primary = override.get('primary_id') or next((f for f in IDENTIFIERS[domain] if f in mapping), None)
            if not primary or primary not in mapping:
                item['diagnostics'].append('Identificador institucional principal ausente o ambiguo; configurar mapping/primary_id')
                continue
            additional = set(headers) - {c for columns in mapping.values() for c in columns}
            if override.get('source_role') not in (None, 'entity_records', 'complementary'):
                raise ValueError('source_role debe ser entity_records o complementary')
            item.update(domain=domain, mapping=mapping, primary_id=primary,
                        extra_columns={c: column_kind(c) for c in sorted(additional)}, text_columns=extra, text_decisions=decisions,
                        column_classification=classification,
                        pending_authorization=[c['column'] for c in classification if c['authorization']=='PENDING_AUTHORIZATION'],
                        ambiguous_columns=[c['column'] for c in classification if c['role']=='ambiguous'],
                        source_role=override.get('source_role') or ('complementary' if any(key(c) in {key(a) for a in known.get('knowledge_detection', {}).get('complementary_identifier_aliases', [])} for c in headers) else 'entity_records'),
                        relations=[dict(column=c['column'], namespace=ns, canonical_field=c['canonical_field'], resolution='requires_canonical_validation')
                            for c in classification for ns in c['identifier_namespaces']])
            required = ['source_project_id'] if official else required_fields(root, domain, override)
            if tolerant and domain=='articulos':required=[]
            rejected = list(isolated)
            for n, values in rows:
                errors = []
                for field in required + ([primary] if override.get('primary_id') else []):
                    if official and field == 'source_project_id':
                        continue  # Already checked without normalizing identifiers.
                    if field not in mapping or not any(clean(values.get(c)) for c in mapping[field]):
                        errors.append(f'Fila {n}: falta campo obligatorio {field}')
                for field, columns in mapping.items():
                    if len({clean(values.get(c)) for c in columns if clean(values.get(c))}) > 1:
                        if field not in ('institutional_id', 'document_number'):
                            errors.append(f'Fila {n}: aliases contradictorios de {field}; evidencia conservada')
                        item['diagnostics'].append(dict(code='IDENTITY_ALIASES_PRESERVED', row=n, field=field))
                available = [(f, clean(values.get(c))) for f in IDENTIFIERS[domain] for c in mapping.get(f, []) if clean(values.get(c))]
                if official:
                    available = [('source_project_id', str(values['id_actividad']))]
                if not available and 'incoming' in path.relative_to(root).parts:
                    errors.append(f'Fila {n}: identificador ausente; configurar identidad antes de incorporar')
                if errors:
                    rejected.append(dict(row=n, reasons=errors))
                    continue
                if not available:
                    item['diagnostics'].append(dict(code='BASE_IDENTITY_REQUIRES_EXISTING_RESOLVER', row=n))
                identity = (domain, available[0] if available else ('source_occurrence', rel, n))
                previous = identities.setdefault(identity, [])
                if previous:
                    item['diagnostics'].append(dict(code='REPEATED_ID_REQUIRES_CANONICAL_VALIDATION', row=n, previous=previous.copy()))
                previous.append(dict(file=rel, sheet=sheet, row=n))
            item['record_validation'] = dict(valid=item['record_count']-len(rejected), rejected=len(rejected),
                rejected_rows=rejected, scope='structural_only_not_canonical_identity_acceptance')
            if rejected and not tolerant:
                raise ValueError('; '.join(reason for row in rejected for reason in row['reasons']))
            if not item['record_validation']['valid']:raise ValueError('Ningun registro utilizable en la fuente')
            if rejected:item['diagnostics'].append(dict(code='BASE_ROWS_EXCLUDED',count=len(rejected),rows=rejected))
            item['status'] = 'READY_FOR_VALIDATION'
            if domain in ('proyectos', 'articulos') and not extra and not any(f in mapping for f in PROJECT_FIELDS if f not in ('title','keywords')) and 'abstract' not in mapping:
                item['diagnostics'].append('Sin texto sustantivo autorizado; revisar pending_authorization y configurar text_columns.include o authorized_categories antes de procesar')
            if sha(path) != item['sha256']:
                raise ValueError('El archivo cambio durante la lectura')
        except ValueError as exc:
            item['diagnostics'].append(str(exc))
            item['status'] = 'PENDING_CONFIGURATION' if 'ambiguo' in str(exc).lower() or 'configurar' in str(exc).lower() or 'varias hojas' in str(exc).lower() else 'INVALID'
        except Exception as exc:
            item.update(status='INVALID', diagnostics=[type(exc).__name__ + ': ' + str(exc)])
    # Independent documentary collections establish their own entity scope.
    # Their project keys are not assertions of membership in the institutional base.
    independent = config.get('documentary_source_policy') == 'SELECTED_ONLY_V1'
    # Exact registered identity namespaces only; never bridge proposal and project IDs.
    base_ids = {}
    for item in result:
        if item['status'] != 'READY_FOR_VALIDATION' or not item.get('records') or (not independent and 'base' not in Path(item['records'][0]['file']).parts):
            continue
        for field in IDENTIFIERS[item['domain']]:
            base_ids.setdefault((item['domain'], field), set()).update(
                clean(record['original_values'].get(column)) for record in item['records']
                for column in item['mapping'].get(field, []) if clean(record['original_values'].get(column)))
    for item in result:
        for relation in item.get('relations', []):
            field = relation['canonical_field']
            if relation['namespace'] == 'proposal' or not field:
                relation['resolution'] = 'distinct_namespace_not_joined'
                continue
            candidates = base_ids.get((item['domain'], field))
            if candidates is not None:
                values = {clean(r['original_values'].get(relation['column'])) for r in item['records']} - {''}
                relation.update(**{('exact_selected_matches' if independent else 'exact_base_matches'):len(values & candidates)},
                                unmatched_identifiers=len(values-candidates),
                                resolution='source_local_identity_requires_canonical_validation' if independent else 'exact_registered_key_matches_require_canonical_validation')
        unresolved = [r for r in item.get('relations', []) if r.get('unmatched_identifiers', 0)]
        if item.get('source_role') == 'complementary' and unresolved:
            item['relationship_status'] = 'UNRESOLVED_REFERENCES'
            item['diagnostics'].append('Estructura valida, pero existen relaciones sin correspondencia exacta en la base. Procesamiento bloqueado: aportar una relacion institucional verificable o configurar source_role=entity_records solo si son entidades nuevas confirmadas')
    return dict(status='READY_FOR_VALIDATION' if result and all(i['status'] == 'READY_FOR_VALIDATION' for i in result) else 'PENDING_OR_INVALID', files=result)


def preserve_columns(row, original):
    return row | {h: clean(v) if isinstance(v, (str, int, float, bool, type(None))) or isinstance(v, list) and all(isinstance(x, str) for x in v)
                  else json.dumps(v, ensure_ascii=False) for h,v in original.items() if h not in row}


def adapter_positions(headers, rows, mapping):
    """Physical positions in the full adapter, without normalizing ordinary rows.

    Only records with embedded newlines require rendering to count CSV lines.
    These positions are the legacy occurrence-identity seed, not new IDs.
    """
    columns=list(dict.fromkeys([*mapping,*headers]))
    position=2+sum(len(re.findall(r'\r\n|\r|\n',c)) for c in columns)
    result={}
    for locator,original in rows:
        result[locator]=position
        newline=any(isinstance(v,str) and ('\n' in v or '\r' in v) or isinstance(v,list) and
                    any(isinstance(s,str) and ('\n' in s or '\r' in s) for s in v) for v in original.values())
        if newline:
            values=preserve_columns({f:next((clean(original.get(c)) for c in cs if clean(original.get(c))), '')
                                     for f,cs in mapping.items()},original)
            position+=1+sum(len(re.findall(r'\r\n|\r|\n',str(v))) for v in values.values())
        else:
            position+=1
    return result


def csv_record_starts(path):
    with path.open(encoding='utf-8',newline='') as stream:
        reader=csv.reader(stream);next(reader)
        while True:
            start=reader.line_num+1
            try:next(reader)
            except StopIteration:return
            yield start


def prepare_files(root, raw, run, config):
    """Produce normalized CSV for the proven ETL plus exact RAW occurrence lineage."""
    files = source_files(raw, config.get('source_paths'))
    if not files:
        raise ValueError('RAW vacio: no se utilizan otras muestras como fallback')
    if any(not p.resolve().is_relative_to(raw.resolve()) or p.is_symlink() for p in files):
        raise ValueError('RAW contiene enlaces fuera del conjunto seleccionado')
    fingerprints = {p.relative_to(raw).as_posix(): sha(p) for p in files}
    write(run_file(run, 'raw_manifest.json'), {'raw': str(raw), 'files': fingerprints})
    known = source_registry(root, config)
    structural = {item['file']: item for item in discover_sources(root, config, raw)['files']}
    invalid = [f"{name}: {'; '.join(str(d) for d in item['diagnostics'])}" for name, item in structural.items()
               if item['status'] == 'INVALID']
    if invalid:
        raise ValueError('Archivo rechazado antes del procesamiento: ' + '; '.join(invalid))
    from .source_scope import plan_scope
    scope = plan_scope(root, raw, config, structural, known)
    if scope:
        write(run / 'preprocess/scope.json', scope['summary'])
    sources = {d: {'enabled': False} for d in DOMAINS}
    lineage, events, records = {}, [], []
    identity_positions={}
    for number, path in enumerate(files, 1):
        rel = path.relative_to(raw).as_posix()
        try:
            if structural[rel].get('relationship_status') == 'UNRESOLVED_REFERENCES':
                raise ValueError('Relaciones institucionales no corroboradas en la base: ' + rel +
                    '; no se crean proyectos/articulos desde referencias desconocidas. Aportar una relacion verificable o confirmar entidades nuevas con source_role=entity_records')
            override = file_configuration(config, rel)
            extracted = run / 'preprocess/extracted' / (str(number) + '.txt')
            headers, rows, sheet = read_source(path, override, extracted)
            if not headers or any(not key(h) for h in headers) or len({key(h) for h in headers}) != len(headers):
                raise ValueError('Encabezados vacios o duplicados tras normalizacion')
            if not rows:
                raise ValueError('Archivo sin registros')
            domain = domain_for(path, headers, override.get('domain'), known)
            spec = known[domain]
            official = structural[rel].get('project_contract', False)
            mapping = PROJECT_MAPPING.copy() if official else mapping_for(domain, headers, spec, override.get('mapping'))
            if 'incoming' in path.relative_to(root).parts:
                identifiers = {'proyectos': {'source_project_id'}, 'articulos': {'source_article_id', 'doi', 'eid'}, 'investigadores': {'institutional_id', 'document_number'}}[domain]
                if not set(mapping) & identifiers:
                    raise ValueError('Identificador principal ambiguo o ausente; configurar mapping')
            policy = config.get('text_columns', {}) | override.get('text_columns', {})
            tolerant=base_source(root,path,config)
            if tolerant:
                rows,isolated=base_valid_rows(domain,mapping,rows)
                reported={r['row']:r for r in structural[rel].get('record_validation',{}).get('rejected_rows',[])}
                reported.update({r['row']:r for r in isolated})
                isolated=list(reported.values())
                rows=[(n,v) for n,v in rows if n not in reported]
                for rejected in isolated:
                    events.append(dict(severity='WARNING',file=rel,row=rejected['row'],
                        code='BASE_ROW_EXCLUDED',reason='; '.join(rejected['reasons'])))
                if not rows:raise ValueError('Ningun registro utilizable en la fuente')
                if domain=='proyectos':
                    policy['include']=list(dict.fromkeys(policy.get('include',[])+[c for c in ('justificacion','actividades_formacion') if c in headers]))
            if 'incoming' in path.relative_to(root).parts:
                policy = policy | {'auto_keywords': []}
            from .knowledge_fields import analyze_columns
            mapping, extra, decisions, classification = analyze_columns(headers, rows, mapping,
                known.get('knowledge_detection', {}), policy, select_text_columns)
            if official:
                extra = PROJECT_EXTRA.copy()
                from .knowledge_fields import describe_columns
                classification = describe_columns(headers, rows, mapping, known.get('knowledge_detection', {}), extra)
            if domain not in ('proyectos', 'articulos'):
                extra = {}
            events.append(dict(severity='INFO', file=rel, code='TEXT_COLUMN_POLICY', decisions=decisions,
                               column_classification=classification))
            if scope:
                identity_positions[rel]=adapter_positions(headers,rows,mapping)
                rows = [(n,values) for n,values in rows if n in scope['rows'][rel]]
                if not rows:
                    events.append(dict(severity='INFO', file=rel, code='OUTSIDE_PROCESSING_SCOPE', rows=0))
                    continue
            normalized, refs = [], []
            required = ['source_project_id'] if official else required_fields(root, domain, override)
            if tolerant and domain=='articulos':required=[]
            for locator, original in rows:
                row = {}
                for field, cols in mapping.items():
                    values = [clean(original.get(c)) for c in cols]
                    nonempty = set(v for v in values if v)
                    if len(nonempty) > 1 and field not in ('institutional_id', 'document_number'):
                        raise ValueError(f'Registro {locator}: aliases contradictorios de {field}')
                    if len(nonempty) > 1:
                        events.append(dict(severity='WARNING', file=rel, row=locator,
                                           code='IDENTITY_ALIASES_PRESERVED', field=field))
                    row[field] = (str(original['id_actividad']) if official and field == 'source_project_id'
                                  else next((v for v in values if v), ''))
                if 'incoming' in path.relative_to(root).parts and not any(row.get(f) for f in IDENTIFIERS[domain]):
                    raise ValueError(f'Registro {locator}: identificador ausente; configurar identidad antes de incorporar')
                if any(not row.get(f) for f in required):
                    raise ValueError(f'Registro {locator}: faltan campos requeridos {required}; no se inventan IDs')
                text_status = None
                if domain == 'proyectos':
                    text_status = 'AUTHORIZED_SUBSTANTIVE_TEXT' if (
                        any(row.get(f) for f in PROJECT_FIELDS if f not in ('title', 'keywords')) or
                        any(clean(original.get(c)) for c in extra.values())) else 'NO_AUTHORIZED_SUBSTANTIVE_TEXT'
                    if text_status == 'NO_AUTHORIZED_SUBSTANTIVE_TEXT':
                        events.append(dict(severity='WARNING', file=rel, row=locator,
                            project_id=row.get('source_project_id'), code=text_status,
                            reason='Metadatos conservados; esta ocurrencia no aporta evidencia textual autorizada. No es un error de integridad'))
                if domain == 'proyectos':
                    missing = [f for f in PROJECT_FIELDS if not row.get(f)]
                    if missing:
                        events.append(dict(severity='WARNING', file=rel, row=locator, code='MISSING_FIELDS', fields=missing))
                # Embedded people and organizations remain explicit source columns.
                row = preserve_columns(row, original)
                normalized.append(row)
                refs.append(dict(record_source=str(path), source_row=locator, source_sheet=sheet,
                    original_values=original, field_provenance={c: dict(file=str(path), sheet=sheet, row=locator, column=c) for c in headers}, field_mapping={f: c[0] if len(c) == 1 else c for f, c in mapping.items()} | extra,
                    extra_text_fields=list(extra), text_status=text_status,
                    delivery=rel.split('/')[1] if rel.startswith('incoming/') else path.parent.name,
                    source_occurrence_id='OCC_' + hashlib.sha256(json.dumps([rel, sheet, locator,
                        fingerprints[rel]], ensure_ascii=False).encode('utf-8')).hexdigest(),
                    knowledge_fields={f: dict(category=c['category'], statement_kind=c.get('statement_kind'),
                        column=c['column'], authorization=c['authorization']) for c in classification
                        for f in ([c['canonical_field']] if c['canonical_field'] else [k for k,v in extra.items() if v==c['column']])
                        if f and c['category'] and c['authorization']=='AUTHORIZED'},
                    raw_sha256=fingerprints[rel], transformations=['null_tokens', 'NFC', 'CRLF_to_LF', 'trim'],
                    extracted_text_file=str(extracted) if path.suffix.lower() in ('.docx', '.pdf', '.txt', '.md') else None))
                records.append(dict(domain=domain, source=rel, row=locator, fields={f: row.get(f, '') for f in mapping},
                    text_status=text_status, extra_text_fields=extra, preserved_columns=headers))
            target = run / 'preprocess/adapted' / (str(number) + '.csv')
            target.parent.mkdir(parents=True, exist_ok=True)
            columns = list(dict.fromkeys([*mapping,*headers]))
            with target.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(normalized)
            entry = dict(path=str(target), type='csv', delimiter=',', mapping={f: f for f in mapping})
            if tolerant:entry['base_record_policy']='BASE_VALID_ROWS_V1'
            if official:
                entry['project_contract'] = True
            # The proven identity resolver must see every alias, including conflicts.
            for field in ('institutional_id', 'document_number'):
                if field in mapping:
                    columns = mapping[field]
                    entry['mapping'][field] = columns if len(columns) > 1 else columns[0]
            # Preserve source occurrence identities independently of run-local adapters.
            from layer2_processing.checkpoints import legacy
            # Occurrence identities must survive relocation of the same original file.
            entry.update(identity_source=legacy(root, path).relative_to(root).as_posix(), identity_sheet=sheet)
            # Sparse projections must not renumber unresolved occurrence identities.
            starts=list(csv_record_starts(target))
            if scope:
                entry['identity_rows'] = {str(i):identity_positions[rel][ref['source_row']] for i,ref in zip(starts,refs)}
            for section in ('researcher_mapping',):
                available = override.get(section, spec.get(section, {}))
                found = mapping_for('optional', headers, {'mapping': available}, None)
                if found:
                    entry[section] = {f: cols[0] if len(cols) == 1 else cols for f, cols in found.items()}
            entry['organizations'] = [o for o in override.get('organizations', spec.get('organizations', [])) if o['column'] in headers]
            if 'unwrap_quoted_fields' in spec:
                entry['unwrap_quoted_fields'] = spec['unwrap_quoted_fields']
            sources[domain]['enabled'] = True
            sources[domain].setdefault('sources', []).append(entry)
            lineage[str(target)] = {str(i): ref for i, ref in zip(starts,refs)}
            unused = sorted(set(headers) - {c for cols in mapping.values() for c in cols})
            events.append(dict(severity='INFO', file=rel, code='FILE_ADAPTED', domain=domain, rows=len(rows), unmapped_columns=unused))
        except Exception as exc:
            events.append(dict(severity='ERROR', file=rel, code='INPUT_REJECTED', reason=str(exc)))
    if scope:
        from .normalize import header
        from .ingestion import mapped_values
        from ..checkpoints import legacy
        contexts=[]
        for item in scope['contexts']:
            ref=item['record'];original=ref['original_values'];mapping=item['mapping']
            payload=preserve_columns({field:next((clean(original.get(c)) for c in columns if clean(original.get(c))), '')
                                      for field,columns in mapping.items()},original)
            payload={c:payload.get(c,'') for c in dict.fromkeys([*mapping,*structural[item['file']]['headers']])}
            parsed={header(k):v for k,v in payload.items()}
            person={f:columns if len(columns)>1 and f in ('institutional_id','document_number') else columns[0]
                    for f,columns in item['person_mapping'].items()}
            path=Path(ref['file'])
            candidate=mapped_values(parsed,person)
            candidate.update(_file=str(path),_row=ref['row'],_sheet=ref['sheet'],_raw=payload,_parsed=parsed,
                _mapping=person,_candidate_domain='scope_identity_context',
                _spec=dict(unwrap_quoted_fields=item['spec'].get('unwrap_quoted_fields',[]),
                           identity_source=legacy(root,path).relative_to(root).as_posix(),identity_sheet=ref['sheet'],
                           identity_rows={str(ref['row']):identity_positions[item['file']][ref['row']]}))
            contexts.append(candidate)
            lineage.setdefault(str(path),{})[str(ref['row'])]=dict(record_source=str(path),source_row=ref['row'],source_sheet=ref['sheet'],
                original_values=original,field_mapping=person,extra_text_fields=[],identity_context_only=True,
                field_provenance=ref['field_provenance'],raw_sha256=structural[item['file']]['sha256'])
        write(run/'preprocess/identity_context.json',contexts)
    write(run / 'preprocess/diagnostics.json', events)
    write(run / 'preprocess/lineage.json', lineage)
    write(run / 'preprocess/review.json', records)
    verify_raw(raw, fingerprints, config.get('source_paths'))
    if any(e['severity'] == 'ERROR' for e in events):
        raise ValueError('Entrada rechazada; consultar preprocess/diagnostics.json. No se continua parcialmente en silencio')
    if not any(sources[d]['enabled'] for d in DOMAINS):
        raise ValueError('Se requiere al menos una fuente institucional configurada')
    sources['indicadores'] = dict(known['indicadores'], path=str(root / config['reference_catalog']), sheet=config['reference_sheet'])
    sources['indicadores']['mapping'] = dict(known['indicadores']['mapping'], indicator_description='descripcion_ampliada') if config['reference_sheet'] == 'Indicadores_enriquecidos' else dict(known['indicadores']['mapping'])
    return sources, lineage


def verify_raw(raw, fingerprints, paths=None):
    current = {p.relative_to(raw).as_posix(): sha(p) for p in source_files(raw, paths)}
    if raw.name == 'layer1_sources':
        fingerprints = {(('base/' + k) if '/' not in k and (raw / 'base' / k).is_file() else k): v for k, v in fingerprints.items()}
    if current != fingerprints:
        raise ValueError('RAW cambio: falta, se agrego o se modifico un archivo; crear otra ejecucion')
