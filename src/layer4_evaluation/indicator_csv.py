"""Offline Power BI projection. No model calls or project-wide territorial joins."""
import csv
from pathlib import Path

from layer2_processing.checkpoints import locate
from layer2_processing.preprocessing.dane_reference import load_reference
from layer4_evaluation.indicators.review import normalize
from layer4_evaluation.indicators.selection import substantive_fields
from layer4_evaluation.territories.matching import extract_territories


class TerritoryCodes:
    """Resolve only literal citations used by positive indicator criteria.

    The existing recognizer resolves names and administrative levels against the
    verified DANE reference. A project location outside these citations cannot
    produce a row. Missing references mean no verifiable territorial results;
    corrupt installed references remain errors.
    """
    def __init__(self, root):
        self.root = Path(root)
        self.dimension = None

    def __call__(self, project, assessment):
        evidence = assessment.get('evidence', [])
        indices = sorted({i for c in assessment.get('criterion_assessments', [])
                          if c['support'] in ('CLEAR', 'PARTIAL') for i in c['evidence_indices']})
        sections = []
        for i in indices:
            item = evidence[i]
            field, quote = item['field'], item['text']
            original = project['fields'].get(field) or ''
            if (field not in substantive_fields(project['fields']) or not quote.strip()
                    or normalize(quote) not in normalize(original)):
                continue
            # The recognizer's field gate predates custom documentary columns.
            # These are already authorized substantive citations, not full fields.
            sections.append(dict(document_id='citation', section_id=str(i),
                                 field_name='methodology', text_original=quote))
        if not sections:
            return []
        if self.dimension is None:
            directory = locate(self.root/'outputs/layer2/reference')
            self.dimension = load_reference(directory)[0] if (directory/'dane_reference_manifest.json').exists() else []
        if not self.dimension:
            return []
        result = extract_territories([dict(source_id=project['project_id'], source_type='PROJECT',
                                           document_id='citation')], sections, self.dimension)
        catalog = {(t['territory_type'], t['dane_code']) for t in self.dimension}
        codes = set()
        for row in result['relationships']:
            kind, code = row['territory_type'], row['dane_code']
            width = {'MUNICIPALITY': 5, 'DEPARTMENT': 2}.get(kind)
            if width and (kind, code) in catalog and isinstance(code, str) and len(code) == width and code.isascii() and code.isdigit():
                codes.add(code)
        return sorted(codes)


def write_results(run, columns, records, codes_by_pair):
    """Preserve the caller's grain (including researcher), expanding only codes.

    CSV has no type metadata: identifiers are literal text, never Excel formulas.
    Power Query must assign Text before automatic numeric type conversion.
    """
    columns = [c for c in columns if c != 'territorio']
    normal, territorial = [], []
    seen = set()
    for record in records:
        row = {c: record[c] for c in columns}
        key = tuple(row.values())
        if key in seen:
            continue
        seen.add(key)
        normal.append(row)
        pair = row['siap_id'], row['indicador_id']
        for code in sorted(set(codes_by_pair.get(pair, []))):
            if not isinstance(code, str) or len(code) not in (2, 5) or not code.isascii() or not code.isdigit():
                raise ValueError('Codigo DANE no textual o incompatible')
            territorial.append(dict(row, codigo_dane=code))
    directory = Path(run)/'resultados'
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, fields, rows in [('indicadores.csv', columns, normal),
                               ('indicadores_territorios.csv', columns+['codigo_dane'], territorial)]:
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
    return dict(paths=paths, indicator_rows=len(normal), territory_rows=len(territorial),
                columns=columns, territorial_columns=columns+['codigo_dane'])
