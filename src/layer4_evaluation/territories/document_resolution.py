"""Resolve cited geography using the same-source GraphRAG documentary context.

Embeddings discover documents; only literal SOURCE text and official parent links
can establish geography. No title, affiliation, model answer or vector similarity
is geographical evidence. Offsets always refer to the unmodified source field.
"""
from collections import defaultdict
import json
import re

from layer2_processing.preprocessing.dane_reference import normalize_name
from layer4_evaluation.indicators.review import normalize, evidence_locations
from layer4_evaluation.indicators.selection import substantive_fields
from .catalog import load_catalog
from .matching import _mentions, _name_pattern, _resolve

REFERENCE = re.compile(r'\b(?:antecedentes?|estudios? previos?|otras investigaciones|segun|a diferencia de|por ejemplo|bibliografia|referencias|afiliacion|authors? affiliations?|previous studies|background|according to)\b')
ACTIVITY = re.compile(r'\b(?:este estudio|esta investigacion|este proyecto|se centra|zona de estudio|area de estudio|poblacion de estudio|trabajo de campo|muestra|participantes|talleres|entrevistas|recoleccion|recopilacion|se realiz\w*|se implementar\w*|se implement\w*|se desarroll\w*|se evaluar\w*|se escoger\w*|se seleccion\w*|estudio busca|investigacion es|study area|fieldwork|participants|conducted)\b')
LOWER = re.compile(r'\b(vereda|corregimiento|centro poblado|caserío|caserio|barrio|localidad)\s+(?:(?:de|del)\s+)*([\wáéíóúüñ -]+)', re.I)
ABBREVIATIONS = re.compile(r'\b(mpio\.?|mun\.|dpto\.?|depto\.?|dto\.|distrito(?: especial| capital| turistico| turístico)?)\s+', re.I)


def expanded(text):
    """Expand administrative abbreviations with an exact original-offset map."""
    chunks, starts, ends, cursor = [], [], [], 0
    for hit in ABBREVIATIONS.finditer(text):
        chunks.append(text[cursor:hit.start()])
        starts.extend(range(cursor, hit.start())); ends.extend(range(cursor+1, hit.start()+1))
        value = 'departamento ' if normalize_name(hit.group(1)) in ('dpto', 'depto', 'dto') else 'municipio '
        chunks.append(value)
        starts.extend([hit.start()]*len(value)); ends.extend([hit.end()]*len(value))
        cursor = hit.end()
    chunks.append(text[cursor:]); starts.extend(range(cursor, len(text))); ends.extend(range(cursor+1,len(text)+1))
    return ''.join(chunks), starts, ends


class DocumentaryResolver:
    def __init__(self, dimension=None):
        self.catalog = load_catalog()
        self.dimension = dimension if dimension is not None else self.catalog.dimension
        self.index = defaultdict(list)
        for row in self.dimension:
            # Aliases can share the official normalized name: never create ambiguity
            # by repeating exactly the same administrative identity.
            key = row['normalized_name']
            if not any(t['dane_code'] == row['dane_code'] and t['territory_type'] == row['territory_type'] for t in self.index[key]):
                self.index[key].append(row)
        self.pattern = _name_pattern(self.index)
        self._context_key = None
        self._context = []

    def mentions(self, text):
        original = text
        text, starts, ends = expanded(text)
        mentions = _mentions(text, self.index, self.pattern)
        lower_spans = []
        for hit in LOWER.finditer(text):
            boundary = re.search(r'\b(?:municipio|departamento|del municipio|donde)\b', hit.group(2), re.I)
            lower_spans.append((hit.start(), hit.start(2)+boundary.start() if boundary else hit.end()))
        mentions = [m for m in mentions if not any(left <= m['start'] < right for left,right in lower_spans)]
        resolved, pending = [], []
        for mention in mentions:
            row, method, candidates = _resolve(mention, mentions)
            if row is None:
                # "Municipality (Department, Colombia)" expresses a parent,
                # even when the department also names several municipalities.
                previous = [m for m in mentions if m['end'] <= mention['start']
                            and re.fullmatch(r'\s*[,\(]\s*', text[m['end']:mention['start']])]
                for preceding in previous:
                    town, _, _ = _resolve(preceding, mentions)
                    parents = [c for c in candidates if c['territory_type'] == 'DEPARTMENT'
                               and town and town['territory_type'] == 'MUNICIPALITY'
                               and c['dane_code'] == town['department_code']]
                    if len(parents) == 1:
                        row, method = parents[0], 'EXPLICIT_MUNICIPAL_PARENT_CONTEXT'
            if (row is None and mention['name'] in ('bogota', 'bogota d c')
                    and mention['explicit'] != 'DEPARTMENT' and '11001' in self.catalog.by_code):
                row, method = self.catalog.by_code['11001'], 'CAPITAL_DISTRICT'
            left, right = mention['sentence']
            start, end = starts[mention['start']], ends[mention['end']-1]
            left = starts[left] if left < len(starts) else len(original)
            right = ends[right-1] if right else 0
            sentence = original[left:right]
            fact = dict(text=original[start:end], start=start, end=end,
                        sentence=sentence, sentence_start=left, sentence_end=right)
            if row:
                resolved.append(dict(fact, code=row['dane_code'], kind=row['territory_type'], method=method))
            else:
                pending.append(dict(fact, reason='AMBIGUOUS_NAME',
                                    candidates=sorted({c['dane_code'] for c in candidates})))
        return resolved, pending

    @staticmethod
    def scope(sentence, field):
        text = normalize_name(sentence)
        if REFERENCE.search(text):
            return 'REFERENCE_OR_BACKGROUND'
        if ACTIVITY.search(text) or field in ('objectives', 'expected_results'):
            return 'STUDY_OR_IMPACT'
        return 'UNVERIFIED_ROLE'

    def resolve(self, project, assessment):
        fields = project.get('fields', {})
        allowed = substantive_fields(fields) | ({'abstract'} if 'abstract' in fields else set())
        facts, pending = [], []
        key = (project.get('project_id'), tuple((f,fields.get(f) or '') for f in sorted(allowed)),
               json.dumps(project.get('field_provenance', {}), sort_keys=True, ensure_ascii=False))
        if key != self._context_key:
            context = []
            for field in sorted(allowed):
                found, _ = self.mentions(fields.get(field) or '')
                for fact in found:
                    fact.update(field=field, role=self.scope(fact['sentence'], field),
                                coordinate_system='original_field_unicode_codepoints_0_based_half_open',
                                provenance=project.get('field_provenance', {}).get(field, {}))
                    context.append(fact)
            self._context_key, self._context = key, context
        context = self._context
        # A department elsewhere in a document can narrow a homonym ONLY when
        # it is an asserted study location, unique and compatible with the quote.
        departments = {f['code'] for f in context
                       if f['role'] == 'STUDY_OR_IMPACT' and f['kind'] == 'DEPARTMENT'}
        evidence = assessment.get('evidence', [])
        locations = evidence_locations(project, assessment)
        indices = sorted({i for c in assessment.get('criterion_assessments', [])
                          if c['support'] in ('CLEAR', 'PARTIAL') for i in c['evidence_indices']})
        for i in indices:
            item = evidence[i]
            field, quote = item['field'], item['text']
            original = fields.get(field) or ''
            if field not in allowed or not quote.strip() or normalize(quote) not in normalize(original):
                pending.append(dict(evidence_index=i, field=field, reason='NON_SUBSTANTIVE_OR_NON_LITERAL'))
                continue
            found, unresolved = self.mentions(quote)
            for fact in found+unresolved:
                fact.update(coordinate_system='citation_unicode_codepoints_0_based_half_open',
                            citation_location=locations[i])
            for fact in found:
                role = self.scope(fact['sentence'], field)
                # A fragment may omit the study verb; consult its full same-source
                # sentence through the factual section, never a neighbouring project.
                supporting = [f for f in context if f['field'] == field and f['code'] == fact['code']
                              and normalize(quote) in normalize(f['sentence'])]
                if supporting and all(f['role'] == 'REFERENCE_OR_BACKGROUND' for f in supporting):
                    role = 'REFERENCE_OR_BACKGROUND'
                if role == 'UNVERIFIED_ROLE' and supporting:
                    role = supporting[0]['role']
                if role == 'UNVERIFIED_ROLE' and any(f['code'] == fact['code'] and f['role'] == 'STUDY_OR_IMPACT' for f in context):
                    role = 'STUDY_OR_IMPACT'
                if role != 'STUDY_OR_IMPACT':
                    pending.append(dict(fact, evidence_index=i, field=field, reason=role))
                    continue
                facts.append(dict(fact, field=field, evidence_index=i, role=role,
                                  provenance=project.get('field_provenance', {}).get(field, {})))
            for mention in unresolved:
                candidates = [code for code in mention['candidates'] if code in self.catalog.by_code
                              and self.catalog.by_code[code]['territory_type'] == 'MUNICIPALITY'
                              and self.catalog.by_code[code]['department_code'] in departments]
                if (not any(self.catalog.by_code[c]['territory_type'] == 'DEPARTMENT'
                            for c in mention['candidates'] if c in self.catalog.by_code)
                        and len(departments) == 1 and len(candidates) == 1
                        and self.scope(mention['sentence'], field) == 'STUDY_OR_IMPACT'):
                    facts.append(dict(mention, code=candidates[0], kind='MUNICIPALITY', field=field,
                                      evidence_index=i, method='DOCUMENT_STUDY_DEPARTMENT', role='STUDY_OR_IMPACT',
                                      provenance=project.get('field_provenance', {}).get(field, {})))
                else:
                    pending.append(dict(mention, evidence_index=i, field=field))
            # Sublocalities: official populated-place parents OR explicit textual
            # parent statements in this same source; never treat a vereda as a town.
            for hit in LOWER.finditer(quote):
                tail = normalize_name(quote[hit.start(2):])
                names = [n for n in self.catalog.settlements if tail == n or tail.startswith(n+' ')]
                name = max(names, key=len) if names else re.split(r',|\b(?:municipio|departamento|donde|del municipio)\b', hit.group(2), maxsplit=1)[0].strip()
                normalized = normalize_name(name)
                parents = {s['parent'] for s in self.catalog.settlements.get(normalized, [])}
                if departments:
                    parents = {p for p in parents if p[:2] in departments}
                linked = [f for f in context if f['kind'] == 'MUNICIPALITY'
                          and f['role'] == 'STUDY_OR_IMPACT'
                          and re.search(r'\b(?:vereda|corregimiento|centro poblado|caserio|barrio|localidad)\s+(?:de\s+)?'+re.escape(normalized)+r'\b', normalize_name(f['sentence']))]
                # An explicit municipality inside the quote takes precedence over
                # a non-exhaustive settlement catalogue and makes the link auditable.
                explicit_parents = {f['code'] for f in linked}
                if explicit_parents:
                    parents = explicit_parents
                if len(parents) == 1 and self.scope(quote, field) == 'STUDY_OR_IMPACT':
                    parent = next(iter(parents))
                    if self.catalog.by_code[parent]['territory_type'] == 'MUNICIPALITY':
                        facts.append(dict(code=parent, kind='MUNICIPALITY', field=field, evidence_index=i,
                                          text=hit.group(0), locality=name, locality_type=hit.group(1),
                                          citation_location=locations[i],
                                          provenance=project.get('field_provenance', {}).get(field, {}),
                                          method='DOCUMENT_EXPLICIT_PARENT' if explicit_parents else 'DIVIPOLA_SETTLEMENT_PARENT',
                                          role='STUDY_OR_IMPACT'))
                else:
                    pending.append(dict(field=field, evidence_index=i, text=hit.group(0),
                                        reason='UNVERIFIED_LOCALITY_PARENT', candidates=sorted(parents)))
        codes = {f['code'] for f in facts if f['kind'] in ('MUNICIPALITY', 'DEPARTMENT')}
        for fact in facts:
            if fact['kind'] == 'NON_MUNICIPAL_AREA':
                codes.add(self.catalog.by_code[fact['code']]['department_code'])
                pending.append(dict(fact, reason='NON_MUNICIPAL_AREA_NOT_A_MUNICIPALITY'))
        # A municipality already carries its department: do not count its parent
        # again as an additional territory of the same evaluation.
        codes -= {c[:2] for c in codes if len(c) == 5}
        if not codes:
            pending.append(dict(reason='NO_VERIFIABLE_INDICATOR_TERRITORY'))
        return dict(codes=sorted(codes), evidence=facts, pending=pending,
                    document_territories=context, project_id=project.get('project_id'),
                    siap_id=project.get('siap_id'), indicator_id=assessment.get('indicator_id'),
                    catalog_version=self.catalog.manifest['version'])
