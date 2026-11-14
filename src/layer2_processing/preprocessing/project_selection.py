"""Deterministic project sampling and mandatory audit over the existing ETL.

No identity resolver or publication join is implemented here. Those belong to
source_scope and the native canonical pipeline, including their ambiguity rules.
"""
from run_paths import file_path as run_file
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from .normalize import identifier, text
from .adapters import discover_sources, read, sha, write
from layer4_evaluation.indicators.performance import timed

VERSION = 'STRATIFIED_PROJECTS_V1'
NARRATIVE = ('summary', 'methodology', 'objectives', 'expected_results')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def sample_projects(features, limit, seed=42):
    """Proportional joint strata, largest remainders, seeded SHA-256 ordering.

    Both allocation ties and within-stratum sampling are seeded. Integer
    arithmetic avoids rounding changes; IDs and input order never favor a prefix.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= len(features):
        raise ValueError(f'--limit debe estar entre 1 y {len(features)} proyectos unicos')
    strata = defaultdict(list)
    for pid, values in features.items():
        strata[tuple(values)].append(pid)
    sizes = {key: limit * len(ids) // len(features) for key, ids in strata.items()}
    remainder = limit - sum(sizes.values())
    order = sorted(strata, key=lambda key: (-(limit * len(strata[key]) % len(features)), digest([seed, key])))
    for key in order[:remainder]:
        sizes[key] += 1
    chosen = []
    for key in sorted(strata):
        chosen.extend(sorted(strata[key], key=lambda pid: digest([seed, pid]))[:sizes[key]])
    return sorted(chosen)


@timed('preparacion')
def select(root, raw, config, *, limit=None, all_projects=False, seed=42, project_ids=None, replay=None):
    """Read mapped sources before any text transformation, embedding or model."""
    selectors = sum((limit is not None, bool(all_projects), project_ids is not None, replay is not None))
    if selectors != 1:
        raise ValueError('Elegir exactamente uno: --limit N, --all, IDs o --selection-manifest')
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError('La semilla debe ser un entero')
    discovered = discover_sources(root, config, raw)
    if discovered['status'] != 'READY_FOR_VALIDATION':
        raise ValueError('Fuentes invalidas o pendientes; ejecutar verify y revisar diagnosticos')
    files = discovered['files']
    primary = set(config.get('selected_input_paths', [f['file'] for f in files]))
    projects = defaultdict(lambda: defaultdict(set))
    states = defaultdict(set)
    for item in files:
        mapping = item['mapping']
        for record in item['records']:
            original = record['original_values']
            ids = {str(original[c]) if item.get('project_contract') else identifier(original.get(c))
                   for c in mapping.get('source_project_id', [])} - {None, ''}
            for pid in ids:
                if item['domain'] == 'proyectos' and item['file'] in primary:
                    fields = projects[pid]
                    for field, columns in mapping.items():
                        fields[field].update(text(original.get(c)) for c in columns if text(original.get(c)))
                    for column in ('convocatoria_codigo', 'codigo_convocatoria', 'periodo', 'estado'):
                        if text(original.get(column)):
                            fields[column].add(text(original[column]))
                elif item['domain'] == 'investigadores' and text(original.get('estado')):
                    states[pid].add(text(original['estado']))
    if not projects:
        raise ValueError('No hay proyectos declarados en fuentes de proyectos; las referencias de miembros no crean proyectos')
    features = {}
    for pid, fields in projects.items():
        area = '|'.join(sorted(fields.get('knowledge_area', set()))) or 'SIN_AREA'
        period = '|'.join(sorted(fields.get('periodo') or fields.get('convocatoria_codigo') or fields.get('codigo_convocatoria') or set())) or 'SIN_PERIODO'
        state = '|'.join(sorted(fields.get('estado') or states[pid])) or 'SIN_ESTADO'
        complete = sum(bool(fields.get(f)) for f in NARRATIVE)
        features[pid] = [area, period, state, str(complete)]
    sources = {str((raw / item['file']).relative_to(root).as_posix()): item['sha256'] for item in files}
    sources[config['reference_catalog']] = sha(root / config['reference_catalog'])
    previous = read(replay) if replay else None
    if previous:
        if previous['sources'] != sources or previous['population_sha256'] != digest(features):
            raise ValueError('Fuentes o poblacion distintas del manifiesto conservado')
        project_ids = previous['project_ids']
        seed = previous['seed']
    chosen = (sample_projects(features, limit, seed) if limit is not None else
              sorted(projects) if all_projects else list(project_ids))
    if not chosen or len(set(chosen)) != len(chosen) or set(chosen) - projects.keys():
        raise ValueError('Proyectos ausentes, vacios o duplicados en la seleccion')
    if previous:
        if previous['selection_sha256'] != digest(chosen):
            raise ValueError('Identificadores del manifiesto modificados')
    criteria = dict(method=VERSION, strata=['knowledge_area', 'period_or_call_code', 'state', 'narrative_fields_present'],
                    period_note='El codigo de convocatoria es un proxy cuando no existe periodo explicito',
                    allocation='proportional_largest_remainder_seeded_sha256', indicators_used=False)
    return dict(version=VERSION, mode='replay' if replay else 'limit' if limit is not None else 'all' if all_projects else 'ids',
        requested_count=limit if limit is not None else len(chosen), selected_count=len(chosen), seed=seed,
        project_ids=chosen, criteria=criteria, sources=sources, population_count=len(projects),
        population_sha256=digest(features), selection_sha256=digest(chosen),
        population_strata=dict(Counter(json.dumps(v, ensure_ascii=False) for v in features.values())),
        selected_strata=dict(Counter(json.dumps(features[p], ensure_ascii=False) for p in chosen)),
        project_features={p:features[p] for p in chosen}, inference_calls=0)


def validate_selection(root, run, metadata=None):
    """Validate actual canonical output, not just requested IDs or CSV counts."""
    import pyarrow.parquet as pq
    from .contracts import KEYS
    config = read(run_file(run, 'run.json'))['configuration']
    metadata = metadata or config.get('project_selection')
    if metadata is None:
        return None
    folder = run / 'workspace/outputs/layer2/canonical'
    tables = {name: pq.read_table(folder / (name + '.parquet')).to_pylist() for name in KEYS}
    errors = []
    warnings = []
    selected = metadata['project_ids']
    if len(selected) != len(set(selected)) or metadata['selection_sha256'] != digest(selected):
        errors.append('INVALID_SELECTION_IDENTIFIERS')
    for name, fingerprint in metadata['sources'].items():
        if not (root / name).is_file() or sha(root / name) != fingerprint:
            errors.append('SELECTION_SOURCE_CHANGED:' + name)
    actual = [r['source_project_id'] for r in tables['proyectos']]
    global_base=config.get('knowledge_scope')=='BASE_GLOBAL_V1'
    if (not set(selected)<=set(actual) if global_base else len(actual) != metadata['requested_count'] or set(actual) != set(selected)):
        errors.append('PROJECT_COUNT_OR_SCOPE_MISMATCH')
    for name, rows in tables.items():
        keys = [tuple(json.dumps(row[k], sort_keys=True) for k in KEYS[name]) for row in rows]
        if len(keys) != len(set(keys)):
            errors.append('DUPLICATE_CANONICAL_KEY:' + name)
    ids = {name: {r[KEYS[name][0]] for r in tables[name]} for name in ('proyectos','articulos','investigadores')}
    for name, target, key in (('proyecto_investigador','proyectos','project_id'), ('articulo_investigador','articulos','article_id')):
        for row in tables[name]:
            if row[key] not in ids[target] or row['researcher_id'] not in ids['investigadores']:
                errors.append('ORPHAN_RELATION:' + name)
    if global_base:
        membership=defaultdict(set)
        for row in tables['proyecto_investigador']:membership[row['researcher_id']].add(row['project_id'])
        report=metadata|dict(status='INVALID_SELECTION' if errors else 'VALIDATED_SELECTION',
            knowledge_scope='BASE_GLOBAL_V1',evaluation_project_ids=selected,
            counts={name:len(rows) for name,rows in tables.items()},
            shared_researchers=sum(len(ids)>1 for ids in membership.values()),
            verified_project_publication_relations=0,
            warnings=[dict(code='GLOBAL_KNOWLEDGE_SELECTED_EVALUATIONS',
                note='Shared authorship is relational context, not proof of project production.')],errors=errors)
        write(run/'preprocess/selection_manifest.json',report)
        if errors:raise ValueError('Validacion critica de seleccion: '+', '.join(errors))
        return report
    scope = read(run / 'preprocess/scope.json')
    if set(scope['projects']) != set(selected):
        errors.append('INDIRECT_PROJECT_EXPANSION')
    raw = root / read(run_file(run, 'run.json'))['raw_path']
    permitted_rows = {(str((raw / file).resolve()), row) for file, rows in scope['rows'].items() for row in rows}
    for article in tables['articulos']:
        refs = json.loads(article['provenance_json'])
        # Occurrence-based IDs use the native adapter payload. Validate the
        # original locators instead of guessing that hash from a CSV row.
        if not refs or any((str(Path(ref['record_source']).resolve()), ref['source_row'])
                           not in permitted_rows for ref in refs):
            errors.append('ARTICLE_OUTSIDE_VERIFIED_AUTHOR_SCOPE')
    membership = defaultdict(set)
    for row in tables['proyecto_investigador']:
        membership[row['researcher_id']].add(row['project_id'])
    missing = {p['source_project_id']: [f for f in NARRATIVE if not p.get(f)] for p in tables['proyectos']}
    missing = {p: fields for p, fields in missing.items() if fields}
    if missing:
        warnings.append(dict(code='INCOMPLETE_PROJECT_INFORMATION', projects=missing))
    ambiguous = Counter(r['identity_status'] for r in tables['investigadores'] if r['identity_status'] != 'resolved')
    if ambiguous:
        warnings.append(dict(code='UNRESOLVED_RESEARCHER_IDENTITIES', counts=dict(ambiguous)))
    if scope['unverified_production']:
        warnings.append(dict(code='EXCLUDED_UNVERIFIED_AUTHOR_ASSOCIATIONS', count=len(scope['unverified_production'])))
    warnings.append(dict(code='PROJECT_PUBLICATION_LINK_NOT_DECLARED',
        note='La autoria verificada no demuestra que una publicacion sea resultado de un proyecto. No se crea esa relacion ni se usa como evidencia del proyecto.'))
    warnings.append(dict(code='UNVERIFIED_RESEARCHER_ID_NAMESPACE',
        note='id_investigador se conserva en procedencia; no es alias verificado de id_empleado y no une identidades.'))
    quarantine = read(run / 'preprocess/scope_validation.json')
    if quarantine['conflict_groups']:
        warnings.append(dict(code='QUARANTINED_ARTICLE_ID_CONFLICTS', groups=quarantine['conflict_groups']))
    connected = {r['project_id'] for r in tables['proyecto_investigador']}
    without_members = sorted(ids['proyectos'] - connected)
    if without_members:
        warnings.append(dict(code='PROJECTS_WITHOUT_MEMBERS', projects=without_members))
    report = metadata | dict(status='INVALID_SELECTION' if errors else 'VALIDATED_SELECTION',
        counts={name:len(rows) for name, rows in tables.items()},
        relation_count=len(tables['proyecto_investigador']) + len(tables['articulo_investigador']),
        shared_researchers=sum(len(ps)>1 for ps in membership.values()),
        verified_project_publication_relations=0, warnings=warnings, errors=errors,
        relationship_basis=dict(project_member='id_actividad', author='documento/cedula via native identity resolver',
            researcher='id_empleado; documento in a separate namespace; id_investigador not used for identity',
            publication='source_article_id, EID, DOI; ISSN is not a publication ID',
            entities='facultad/departamento from original occurrences; no declared group membership'))
    write(run / 'preprocess/selection_manifest.json', report)
    if errors:
        raise ValueError('Validacion critica de seleccion: ' + ', '.join(errors))
    return report
