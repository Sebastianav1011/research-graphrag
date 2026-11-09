"""Versioned GraphRAG evidence packing, without changing assessment or scoring.

Ollama exposes usage after inference, but no public preflight tokenizer endpoint.
UTF-8 bytes / 3 is an explicitly approximate allowance, not an exact token count
or a mathematical bound. The configured safety margin remains reserved separately.
"""
import hashlib
import json
import math
import re
from .performance import timed

from . import assessment_v3 as v3
from .prompt import indicator_input
from .selection import FIELDS, substantive_fields, canonical_hash

VERSION = 'GRAPH_CONTEXT_PER_INDICATOR_V1'
ESTIMATOR = 'UTF8_BYTES_DIV_3_APPROX_V1'


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def estimate(prompt, schema, settings, *, tokenizer=None):
    if tokenizer:
        from .token_budget import count
        prompt_tokens=count(prompt,tokenizer)
        total=prompt_tokens+tokenizer['template_tokens']
        available=settings['num_ctx']-settings['num_predict']-settings['context_margin_tokens']
        return dict(version=VERSION,estimator='PINNED_QWEN_TOKENIZER_AND_CALIBRATED_TEMPLATE_V1',approximate=False,
            prompt_tokens=prompt_tokens,template_tokens=tokenizer['template_tokens'],schema_tokens=0,
            schema_bytes=len(compact(schema).encode('utf-8')),schema_scope='EXTERNAL_DECODING_GRAMMAR_NOT_APPENDED_TO_PROMPT',
            estimated_input_tokens=total,input_budget=available,num_ctx=settings['num_ctx'],num_predict=settings['num_predict'],
            margin_tokens=settings['context_margin_tokens'],fits=total<=available,tokenizer=tokenizer)
    prompt_tokens = math.ceil(len(prompt.encode('utf-8')) / 3)
    schema_tokens = math.ceil(len(compact(schema).encode('utf-8')) / 3)
    available = settings['num_ctx'] - settings['num_predict'] - settings['context_margin_tokens']
    return dict(version=VERSION, estimator=ESTIMATOR, approximate=True,
        prompt_tokens=prompt_tokens, schema_tokens=schema_tokens,
        estimated_input_tokens=prompt_tokens + schema_tokens,
        input_budget=available, num_ctx=settings['num_ctx'], num_predict=settings['num_predict'],
        margin_tokens=settings['context_margin_tokens'], fits=prompt_tokens + schema_tokens <= available)


def make_request(project, profile, rubric, fields):
    # Validate the unchanged rubric first. Provenance/basis and duplicate examples
    # stay in the sealed plan, not in every inference. Criteria and roles are exact.
    v3.check_rubric(profile, rubric)
    definition = indicator_input(profile)
    for name in ('related_terms', 'fuentes_relevantes_original', 'ambito', 'tipo',
                 'forma_evaluacion', 'unidad', 'indicator_category', 'indicator_dimension'):
        definition.pop(name, None)
    criteria = [{k: c[k] for k in ('criterion_id', 'criterion', 'role',
        'alternative_group', 'temporal_requirement')} for c in rubric['criteria']]
    payload = dict(project=dict(project_id=project['project_id'], fields=fields),
        indicators=[dict(**definition, rubric=dict(indicator_evidence_type=rubric['indicator_evidence_type'], criteria=criteria))])
    # All existing normative assessment instructions remain verbatim. General
    # discovery/catalog examples do not belong to a per-indicator evidence request.
    instructions = v3.INSTRUCTIONS.replace('Codex es el único intérprete', 'El LLM local es el único intérprete')
    prompt = instructions + '\nLos campos text__ son evidencia autorizada; conserva su significado y temporalidad. Cita solo textos suministrados.\nINPUT_JSON:\n' + compact(payload)
    return dict(project_id=project['project_id'], input_version=VERSION, payload=payload, prompt=prompt)


def sentence_span(text, fits):
    """First fitting whole-sentence window, expanded without altering any byte.

    Parent chunk ranking is inherited; this performs no new search or semantic
    judgement. Long indivisible sentences remain omitted. Every removed interval
    is reported, rather than silently cutting a document or an evidence quote.
    """
    ends=[m.end() for m in re.finditer(r'[.!?]["\u201d\u2019)\]]*\s+|(?:\r?\n){2,}',text)]
    ends=sorted(set([0,*ends,len(text)]))
    if len(ends)<3:return None
    for index,start in enumerate(ends[:-1]):
        end=ends[index+1]
        if not text[start:end].strip() or not fits(text[start:end]):continue
        for following in ends[index+2:]:
            if not fits(text[start:following]):break
            end=following
        return start,end
    return None


def original_chunk(chunk, section, offsets):
    """Translate normalized word-window boundaries to literal original offsets.

    Knowledge chunks use text_normalized coordinates. Align tokens by position,
    never by searching a possibly repeated quote. Only the existing conservative
    normalization is accepted; the LLM receives the untouched original interval.
    """
    original = section['text_original'] or ''
    start, end = chunk['char_start'], chunk['char_end']
    normalized = section.get('text_normalized', original)
    if normalized[start:end] != chunk['text']:
        raise ValueError('GraphRAG chunk is not an exact normalized text interval')
    if normalized == original:
        return chunk
    if section['section_id'] not in offsets:
        from layer2_processing.knowledge.text_normalization import normalize
        options = dict(unicode='NFC', linebreaks=True, remove_invisible=True, whitespace=True)
        if normalize(original, options) != normalized:
            raise ValueError('GraphRAG section normalization cannot be verified')
        raw_tokens = [(token, normalize(token.group(), options)) for token in re.finditer(r'\S+', original)]
        raw_tokens = [(token, text) for token, text in raw_tokens if text]
        normalized_tokens = list(re.finditer(r'\S+', normalized))
        if [text for _, text in raw_tokens] != [token.group() for token in normalized_tokens]:
            raise ValueError('GraphRAG normalized/original token alignment differs')
        starts, ends = {}, {}
        for token, (raw, _) in zip(normalized_tokens, raw_tokens):
            starts[token.start()], ends[token.end()] = raw.start(), raw.end()
        offsets[section['section_id']] = starts, ends
    starts, ends = offsets[section['section_id']]
    if start not in starts or end not in ends:
        raise ValueError('GraphRAG chunk boundaries are not complete original words')
    start, end = starts[start], ends[end]
    return chunk | dict(text=original[start:end], char_start=start, char_end=end)


@timed('recuperacion')
def prepare_contexts(projects, profiles, rubrics, settings, candidates, chunks, sections):
    """Select only published GraphRAG hits, preserving original chunk boundaries."""
    chunk_index = {c['chunk_id']: c for c in chunks}
    section_index = {s['section_id']: s for s in sections}
    ranked = {}
    for candidate in candidates:
        key = candidate['source_id'], candidate['indicator_id']
        if key in ranked:
            raise ValueError('Duplicate GraphRAG SOURCE+INDICATOR candidate')
        ranked[key] = candidate
    requests, diagnostics, offsets = {}, [], {}
    for project in projects:
        pid = project['project_id']
        requests[pid] = {}
        schema = v3.schemas(project['fields'])['assessment_batch']
        for iid, profile in sorted(profiles.items()):
            candidate = ranked.get((pid, iid))
            fields = {f: '' for f in project['fields']}
            request = make_request(project, profile, rubrics[iid], fields)
            base_budget = estimate(request['prompt'], schema, settings)
            selected, omitted, seen = [], [], set()
            hits = []
            if candidate:
                if candidate['source_type'] != 'PROJECT':
                    raise ValueError('GraphRAG source domain mismatch')
                for hit in candidate['discovery_chunks']:
                    c = chunk_index.get(hit['chunk_id'])
                    if c is None or c['source_id'] != pid or c['field_name'] != hit['field_name']:
                        raise ValueError('GraphRAG hit outside selected project or missing chunk')
                    section = section_index.get(c['section_id'])
                    if section is None or section['source_id'] != pid or section['field_name'] != c['field_name']:
                        raise ValueError('GraphRAG chunk/section provenance mismatch')
                    c = original_chunk(c, section, offsets)
                    original = section['text_original'] or ''
                    if original[c['char_start']:c['char_end']] != c['text']:
                        raise ValueError('GraphRAG chunk is not an exact original text interval')
                    if c['field_name'] not in project['fields'] or c['text'] not in (project['fields'][c['field_name']] or ''):
                        raise ValueError('Chunk outside authorized project fields')
                    hits.append((hit, c))
            # Preserve GraphRAG's vector/graph hit order within substantive and
            # orientation groups. Scores never enter assessment/confidence.
            hits.sort(key=lambda pair: (pair[1]['field_name'] not in substantive_fields(fields),
                pair[0].get('vector_rank') or 10**9, -float(pair[0].get('vector_score') or 0), pair[1]['chunk_id']))
            for hit, chunk in hits:
                field, text = chunk['field_name'], chunk['text']
                ref = dict(chunk_id=chunk['chunk_id'], section_id=chunk['section_id'], field=field,
                    source_id=pid, coordinate_system='original_unicode_codepoints_0_based_half_open',
                    char_start=chunk['char_start'], char_end=chunk['char_end'],
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    retrieval_origin=hit.get('retrieval_origin'), vector_rank=hit.get('vector_rank'))
                identity = field, text
                reason = None
                if identity in seen: reason = 'DUPLICATE_EXACT_FIELD_TEXT'
                elif fields[field]: reason = 'ONE_INTACT_CHUNK_PER_FIELD'
                else:
                    trial_fields = fields | {field: text}
                    trial = make_request(project, profile, rubrics[iid], trial_fields)
                    if not estimate(trial['prompt'], schema, settings)['fits']:
                        def fits_span(span):
                            return estimate(make_request(project,profile,rubrics[iid],fields|{field:span})['prompt'],schema,settings)['fits']
                        span=sentence_span(text,fits_span)
                        if span is None:
                            reason = 'INPUT_BUDGET_EXCEEDED'
                        else:
                            start,end=span
                            omitted.append(ref|dict(reason='PARENT_CHUNK_SUBSPAN_SELECTED',
                                excluded_intervals=[[chunk['char_start'],chunk['char_start']+start],
                                    [chunk['char_start']+end,chunk['char_end']]]))
                            ref=ref|dict(unit='ORIGINAL_SENTENCE_SPAN',parent_char_start=chunk['char_start'],
                                parent_char_end=chunk['char_end'],char_start=chunk['char_start']+start,
                                char_end=chunk['char_start']+end,text_sha256=hashlib.sha256(text[start:end].encode()).hexdigest())
                            fields=fields|{field:text[start:end]}
                            request=make_request(project,profile,rubrics[iid],fields)
                            selected.append(ref)
                    else:
                        fields, request = trial_fields, trial
                        selected.append(ref)
                seen.add(identity)
                if reason: omitted.append(ref | {'reason': reason})
            budget = estimate(request['prompt'], schema, settings)
            status = ('STATIC_CONTEXT_TOO_LONG' if not base_budget['fits'] else
                      'READY' if any(fields[f].strip() for f in substantive_fields(fields)) else
                      'NO_EVIDENCE_FITS' if hits else 'NO_RETRIEVED_EVIDENCE')
            # Metadata are reviewed and hashed, but never serialized into the prompt.
            request['context_budget'] = budget
            request['context_selection'] = dict(status=status, selected=selected, omitted=omitted,
                evidence_limited=any(o['reason'] in ('INPUT_BUDGET_EXCEEDED','ONE_INTACT_CHUNK_PER_FIELD','PARENT_CHUNK_SUBSPAN_SELECTED') for o in omitted),
                candidate_id=candidate['candidate_id'] if candidate else None,
                context_package_id=candidate['context_package_id'] if candidate else None)
            requests[pid][iid] = request
            diagnostics.append(dict(project_id=pid, indicator_id=iid, status=status,
                request_sha256=canonical_hash(request), budget=budget,
                prompt_bytes=len(request['prompt'].encode()), selected=selected, omitted=omitted))
    return requests, dict(version=VERSION, indicator_ids=sorted(profiles),
        indicators_per_project=len(profiles), requests=diagnostics,
        omitted_static_components=['other_47_profiles', 'global_discovery', 'general_rule_reference_material',
            'rubric_basis_rationale_and_hashes', 'full_graph', 'full_documents', 'scores_as_confidence'],
        estimator_note='Approximate, not exact tokenization; schema included; native usage checked after each call. No text truncation.')
