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
RETRIEVED_INPUT_CAP = 8000  # Unchanged input ceiling for BASE_RETRIEVED_GRAPH_V1.
RELATIONAL_RESERVE = 1200   # Kept free for verified relational paths packed after evidence.
# Material truncation: the highest-ranked retrieved unit could not be sent intact,
# so the request no longer represents the retrieval ranking. Not dispatched.
EVIDENCE_TRUNCATED = 'EVIDENCE_TRUNCATED'
TRUNCATION_POLICY = 'TOP_RANKED_UNIT_INTACT_V1'
CRITERION_INSTRUCTIONS = '''ORDEN DE EVALUACION EN ESTA UNICA RESPUESTA:
1. Delimita lo que pide cada criterion segun rationale y temporal_requirement.
2. Busca primero fragmentos que respalden esas condiciones y su vinculo con el proyecto, no solo palabras afines.
3. Antes de citar, relee el texto de cada ID: debe respaldar la afirmacion concreta, su sujeto y etapa.
   Antecedentes generales no prueban hechos del proyecto; criterios de inclusion no prueban barreras.
4. En la justificacion existente resume: condiciones exigidas; respaldo con IDs pertinentes; brecha restante.
   Usa en las referencias los mismos IDs que sustentan tu afirmacion; no otros pasajes del mismo tema.
   Ajusta la afirmacion al respaldo disponible o indica lo no demostrado. No copies textos ni agregues campos.
5. Emite soporte y cobertura de ese criterio; conserva respaldo parcial pertinente y explica lo que falta.
6. Solo con todos los juicios fijados determina fuerza y decision global. No reescribas juicios para ajustarlos
   a esa decision. INSUFFICIENT_EVIDENCE admite criterios CLEAR o PARTIAL con citas junto a NOT_DEMONSTRATED.
CONTEXT_ONLY: poblacion delimitada o actores identificados en el diseno pueden respaldar su identificacion;
no exijas participacion ejecutada, recepcion ni mejoras alcanzadas para ese juicio contextual.
Identificar actores no prueba participacion; territorio no prueba impacto regional. La mera mencion no basta.
Diseno o mecanismo se juzgan en su etapa admitida; EXECUTED_ACTIVITY exige actividad realizada;
DEMONSTRATED_RESULT exige resultado alcanzado; impacto exige respaldo del impacto atribuible, no una intencion.
Contexto no compensa REQUIRED incumplidos: conserva REQUIRED, ALTERNATIVE y COMPLEMENTARY y las reglas S/K.
'''

RELATIONAL_INSTRUCTIONS='''\nCONTEXTO RELACIONAL COMPLEMENTARIO: cada relacion es un hecho estructurado con
procedencia y camino desde el proyecto. Compartir investigador NO demuestra que un articulo
sea producto del proyecto, que proyectos colaboren ni que sus resultados sean transferibles.
Las entidades externas conservan su atribucion. No conviertas sus logros en logros del proyecto.
Solo los IDs F del descriptor son citas directas admisibles; los IDs de relacion no son citas
del descriptor ni sustituyen condiciones institucionales. El ranking no es evidencia de impacto.
'''


def with_relations(request,package,schema,settings,reserve,*,tokenizer=None,cap=None):
    """Budget whole verified paths after the complete primary descriptor.

    With a pinned tokenizer the same calibrated count used for evidence applies;
    without it the historical estimator is kept for reproducibility."""
    if package['project_id']!=request['project_id']:raise ValueError('Contexto relacional de otro proyecto')
    relations={r['relation_id']:r for r in package['relations']}
    nodes={n['entity_id']:n for n in package['entities']}
    if len(relations)!=len(package['relations']) or len(nodes)!=len(package['entities']):
        raise ValueError('Identificadores relacionales duplicados')
    seed=package['seed_entity_id'];chosen=set();paths={};selected_nodes={seed}
    if seed not in nodes or nodes[seed]['entity_type']!='PROJECT' or nodes[seed]['canonical_id']!=request['project_id']:
        raise ValueError('Semilla relacional de otro proyecto')
    prefix=request['prompt'].split('INPUT_JSON:\n',1)[0]+RELATIONAL_INSTRUCTIONS
    def build(ids,accepted,entities):
        context={k:v for k,v in package.items() if k not in ('relations','entities','support_paths','metrics')}
        context.update(relations=[relations[rid] for rid in sorted(ids)],
            entities=[nodes[eid] for eid in sorted(entities)],support_paths=accepted)
        payload=dict(request['payload'],relational_context=context)
        return dict(request,payload=payload,prompt=prefix+'INPUT_JSON:\n'+compact(payload))
    result=request;omitted=[]
    for target,path in sorted(package['support_paths'].items(),key=lambda x:(len(x[1]),x[0])):
        if not path:continue
        visited={seed};current=seed
        for rid in path:
            if rid not in relations:raise ValueError('Camino relacional sin evidencia')
            relation=relations[rid];ends={relation['source_entity_id'],relation['target_entity_id']}
            if current not in ends or not ends<=nodes.keys() or not relation['provenance']:
                raise ValueError('Procedencia/camino relacional invalido')
            current=next(e for e in ends if e!=current);visited|=ends
        if current!=target:raise ValueError('Destino relacional incompatible')
        trial=build(chosen|set(path),paths|{target:path},selected_nodes|visited)
        budget=estimate(trial['prompt'],schema,settings,tokenizer=tokenizer,cap=cap,
            conservative=tokenizer is None and request.get('context_mode')==v3.RETRIEVED_CONTEXT)
        if budget['estimated_input_tokens']+reserve<=budget['input_budget']:
            chosen|=set(path);paths[target]=path;selected_nodes|=visited;result=trial
        else:omitted.append(dict(entity_id=target,relation_ids=path,reason='RELATIONAL_CONTEXT_BUDGET_EXCEEDED'))
    receipt=dict(graph_manifest_sha256=package.get('graph_manifest_sha256'),
        selected_relation_ids=sorted(chosen),omitted_paths=omitted,
        retrieval_limits=package['metrics'],
        omitted_relation_ids=sorted(relations.keys()-chosen),primary_descriptor_preserved=request.get('context_mode')!=v3.RETRIEVED_CONTEXT)
    result['relational_context_receipt']=receipt
    return result


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def estimate(prompt, schema, settings, *, tokenizer=None,conservative=False,cap=None):
    if conservative:
        # Local decoding grammar is NOT appended to the chat prompt. Use a
        # conservative byte allowance and independent template reserve, rather
        # than equating UTF8/3 with real Qwen tokens. Historical plans only:
        # new retrieved contexts are budgeted with the pinned tokenizer.
        tokens=math.ceil(len(prompt.encode('utf-8'))/2)+256
        available=min(RETRIEVED_INPUT_CAP,settings['num_ctx']-settings['num_predict']-settings['context_margin_tokens'])
        return dict(version=VERSION,estimator='UTF8_DIV_2_PLUS_TEMPLATE_256_APPROX_V1',approximate=True,
            conservative=True,estimated_input_tokens=tokens,input_budget=available,
            num_ctx=settings['num_ctx'],num_predict=settings['num_predict'],margin_tokens=settings['context_margin_tokens'],
            schema_scope='EXTERNAL_DECODING_GRAMMAR_NOT_APPENDED_TO_PROMPT',fits=tokens<=available)
    if tokenizer:
        from .token_budget import count
        prompt_tokens=count(prompt,tokenizer)
        total=prompt_tokens+tokenizer['template_tokens']
        available=settings['num_ctx']-settings['num_predict']-settings['context_margin_tokens']
        if cap is not None:available=min(cap,available)
        result=dict(version=VERSION,estimator='PINNED_QWEN_TOKENIZER_AND_CALIBRATED_TEMPLATE_V1',approximate=False,
            prompt_tokens=prompt_tokens,template_tokens=tokenizer['template_tokens'],schema_tokens=0,
            schema_bytes=len(compact(schema).encode('utf-8')),schema_scope='EXTERNAL_DECODING_GRAMMAR_NOT_APPENDED_TO_PROMPT',
            estimated_input_tokens=total,input_budget=available,num_ctx=settings['num_ctx'],num_predict=settings['num_predict'],
            margin_tokens=settings['context_margin_tokens'],fits=total<=available,tokenizer=tokenizer)
        # Historical tokenizer budgets carry no cap and must reproduce byte for byte.
        if cap is not None:result['input_cap']=cap
        return result
    prompt_tokens = math.ceil(len(prompt.encode('utf-8')) / 3)
    schema_tokens = math.ceil(len(compact(schema).encode('utf-8')) / 3)
    available = settings['num_ctx'] - settings['num_predict'] - settings['context_margin_tokens']
    return dict(version=VERSION, estimator=ESTIMATOR, approximate=True,
        prompt_tokens=prompt_tokens, schema_tokens=schema_tokens,
        estimated_input_tokens=prompt_tokens + schema_tokens,
        input_budget=available, num_ctx=settings['num_ctx'], num_predict=settings['num_predict'],
        margin_tokens=settings['context_margin_tokens'], fits=prompt_tokens + schema_tokens <= available)


def rebudget(prompt, schema, settings, budget):
    """Recompute a stored budget with its own estimator, tokenizer and cap."""
    budget=budget or {}
    return estimate(prompt,schema,settings,tokenizer=budget.get('tokenizer'),
        conservative=budget.get('conservative',False),cap=budget.get('input_cap'))


def make_request(project, profile, rubric, fields, *, evidence_references=False, evidence_units=None,
                 assessment_version=v3.VERSION, evaluation_mode=None, context_mode=None):
    # Keep the frozen criterion explanations verbatim. Provenance/basis and
    # hashes remain in the sealed plan, without duplicating them in each prompt.
    v3.check_rubric(profile, rubric)
    definition = indicator_input(profile)
    for name in ('related_terms', 'fuentes_relevantes_original', 'ambito', 'tipo',
                 'forma_evaluacion', 'unidad', 'indicator_category', 'indicator_dimension'):
        definition.pop(name, None)
    criteria = [{k: c[k] for k in ('criterion_id', 'criterion', 'role',
        'alternative_group', 'temporal_requirement', 'rationale')} for c in rubric['criteria']]
    if (assessment_version == v3.SK_VERSION and evidence_references and
            definition.get('key_elements') == [c['criterion'] for c in criteria]):
        # The complete labels remain once, alongside their IDs/roles/stages.
        # Full profiles and hashes stay in the plan; historical requests retain
        # their original serialization for read-only verification.
        definition.pop('key_elements')
    payload = dict(project=dict(project_id=project['project_id'], fields=fields),
        indicators=[dict(**definition, rubric=dict(indicator_evidence_type=rubric['indicator_evidence_type'], criteria=criteria))])
    # All existing normative assessment instructions remain verbatim. General
    # discovery/catalog examples do not belong to a per-indicator evidence request.
    instructions = v3.INSTRUCTIONS.replace('Codex es el único intérprete', 'El LLM local es el único intérprete')
    protocol = {}
    if evidence_references:
        from . import evidence_references as refs
        instructions = refs.INSTRUCTIONS
        fragments=[]
        for unit in (evidence_units if evidence_units is not None else [dict(field=f,text=t) for f,t in fields.items()]):
            for fragment in refs.fragments({unit['field']:unit['text']}):
                fragments.append(fragment | dict(fragment_id=f'F{len(fragments):03d}'))
        payload['project'] = dict(project_id=project['project_id'], fragments=fragments)
        for criterion in criteria:
            criterion['compatible_stages'] = sorted(v3.TEMPORAL[criterion['temporal_requirement']])
        protocol['evidence_protocol'] = refs.VERSION
    note = ('Los campos text__ son evidencia autorizada; conserva su significado y temporalidad.' if evidence_references else
            'Los campos text__ son evidencia autorizada; conserva su significado y temporalidad. Cita solo textos suministrados.')
    if assessment_version == v3.SK_VERSION:
        if evidence_references:
            instructions = refs.SK_INSTRUCTIONS
        else:
            instructions = v3.SK_ASSESSMENT_INSTRUCTIONS.replace('Codex es el único intérprete', 'El LLM local es el único intérprete')
        instructions = instructions.replace('ASSESSMENT_V3', v3.SK_VERSION) + v3.SK_INSTRUCTIONS
        protocol['assessment_version'] = assessment_version
        protocol['coverage_policy']=v3.PARTIAL_COVERAGE
        instructions+='\nReconoce respaldo parcial pertinente: no confundas REQUIRED incompleto con ausencia de evidencia en los otros criterios. Usa PARTIAL y coverage 1..3 cuando sus citas lo justifiquen; conserva NOT_DEMONSTRATED y cero si no hay respaldo. S valora la evidencia disponible, no exige cumplimiento completo. REQUIRED sigue siendo obligatorio para SUPPORTED; una confianza positiva no determina esa decision.\n'
    elif assessment_version != v3.VERSION:
        raise ValueError('Unknown confidence assessment contract')
    if evaluation_mode not in (None,v3.DEMONSTRATED,v3.PROSPECTIVE):raise ValueError('Modo de evaluacion desconocido')
    if evaluation_mode==v3.PROSPECTIVE:
        if any(c['temporal_requirement'] in v3.PROSPECTIVE_TEMPORAL for c in rubric['criteria']):
            raise ValueError('Modo prospectivo requiere rubrica temporal derivada')
        instructions+=v3.PROSPECTIVE_INSTRUCTIONS
    if evaluation_mode is not None:protocol['evaluation_mode']=evaluation_mode
    if context_mode is not None:protocol['context_mode']=context_mode
    if context_mode==v3.RETRIEVED_CONTEXT:
        instructions+='\nSolo se suministra un subconjunto recuperado, no el descriptor completo. La falta de respaldo en estos fragmentos no demuestra ausencia documental ni incumplimiento; explica los limites de cobertura. No inventes evidencia externa.\n'
    prompt = CRITERION_INSTRUCTIONS + instructions + '\n' + note + '\nINPUT_JSON:\n' + compact(payload)
    return dict(project_id=project['project_id'], input_version=VERSION, payload=payload, prompt=prompt, **protocol)


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
def prepare_contexts(projects, profiles, rubrics, settings, candidates, chunks, sections, *, evidence_references=False,
                     assessment_version=v3.VERSION, evaluation_mode=None, context_mode=None,relational_contexts=None,
                     tokenizer=None):
    """Select only published GraphRAG hits, preserving original chunk boundaries.

    ``tokenizer`` is the pinned, hash-verified Qwen tokenizer descriptor. When
    given, budgets use exact calibrated counts (retrieved mode keeps its 8000
    cap); without it the historical estimator is reproduced unchanged.
    """
    retrieved = context_mode==v3.RETRIEVED_CONTEXT
    cap = RETRIEVED_INPUT_CAP if retrieved and tokenizer is not None else None
    relational_reserve = RELATIONAL_RESERVE if retrieved else 0
    chunk_index = {c['chunk_id']: c for c in chunks}
    section_index = {s['section_id']: s for s in sections}
    if context_mode not in (None,v3.GRAPHRAG_CONTEXT,v3.FULL_CONTEXT,v3.BASE_CONTEXT,v3.RETRIEVED_CONTEXT):raise ValueError('Modo de contexto desconocido')
    full_descriptor=context_mode in (v3.FULL_CONTEXT,v3.BASE_CONTEXT)
    if context_mode==v3.BASE_CONTEXT and relational_contexts is None:raise ValueError('BASE requiere contexto del grafo verificado')
    section_by_field={}
    if full_descriptor:
        for section in sections:
            key=section['source_id'],section['field_name']
            if key in section_by_field:raise ValueError('Secciones ambiguas del descriptor')
            section_by_field[key]=section
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
        for iid, profile in sorted(profiles.items()):
            units=[]
            def build(fields, evidence_units=None):
                return make_request(project, profile, rubrics[iid], fields, evidence_references=evidence_references,
                    evidence_units=evidence_units if evidence_references else None, assessment_version=assessment_version,
                    evaluation_mode=evaluation_mode,context_mode=context_mode)
            def budget_for(request):
                from .evidence_references import response_schema
                return estimate(request['prompt'], response_schema(request, project['fields']), settings,
                    tokenizer=tokenizer, cap=cap, conservative=tokenizer is None and retrieved)
            from .evidence_references import CORRECTIVE_INPUT_RESERVE
            reserve = CORRECTIVE_INPUT_RESERVE if evidence_references else 0
            def fits_request(request):
                budget = budget_for(request)
                return budget['estimated_input_tokens'] + reserve <= budget['input_budget']-relational_reserve
            candidate = None if full_descriptor else ranked.get((pid, iid))
            fields = {f: '' for f in project['fields']}
            request = build(fields)
            base_budget = budget_for(request)
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
            descriptor_too_long=False
            if full_descriptor:
                complete={f:text or '' for f,text in project['fields'].items()}
                full_refs=[]
                for field,text in complete.items():
                    if not text:continue
                    section=section_by_field.get((pid,field))
                    if (section is None or section.get('source_type','PROJECT')!='PROJECT' or
                            section['text_original']!=text):
                        raise ValueError('Descriptor completo no coincide con la seccion original del proyecto')
                    full_refs.append(dict(chunk_id=None,section_id=section['section_id'],field=field,
                        source_id=pid,coordinate_system='original_unicode_codepoints_0_based_half_open',
                        char_start=0,char_end=len(text),text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                        retrieval_origin=None,vector_rank=None,unit='FULL_SECTION'))
                trial=build(complete)
                if fits_request(trial):fields,request,selected=complete,trial,full_refs
                else:descriptor_too_long=True
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
                elif fields[field] and not evidence_references: reason = 'ONE_INTACT_CHUNK_PER_FIELD'
                else:
                    trial_fields = fields | {field: (fields[field]+'\n\n' if fields[field] else '')+text}
                    trial_units=units+[dict(field=field,text=text)]
                    trial = build(trial_fields,trial_units)
                    if not fits_request(trial):
                        def fits_span(span):
                            return fits_request(build(fields|{field:span},units+[dict(field=field,text=span)]))
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
                            units.append(dict(field=field,text=text[start:end]))
                            request=build(fields,units)
                            selected.append(ref)
                    else:
                        fields, request = trial_fields, trial
                        units=trial_units
                        selected.append(ref)
                seen.add(identity)
                if reason: omitted.append(ref | {'reason': reason})
            if context_mode==v3.BASE_CONTEXT and not descriptor_too_long:
                if pid not in relational_contexts:raise ValueError('Proyecto sin contexto relacional verificado')
                from .evidence_references import response_schema
                request=with_relations(request,relational_contexts[pid],response_schema(request,project['fields']),settings,reserve,
                    tokenizer=tokenizer,cap=cap)
            if context_mode==v3.RETRIEVED_CONTEXT and candidate and candidate.get('relational_context'):
                from .evidence_references import response_schema
                request=with_relations(request,candidate['relational_context'],response_schema(request,project['fields']),settings,reserve,
                    tokenizer=tokenizer,cap=cap)
            budget = budget_for(request)
            # The static check uses the same effective evidence threshold as
            # fits_request: a template that leaves no room is not "no evidence".
            substantive_hits=[(h,c) for h,c in hits if c['field_name'] in substantive_fields(fields)]
            top=substantive_hits[0][1]['chunk_id'] if substantive_hits else None
            top_intact=any(s.get('chunk_id')==top and s.get('unit')!='ORIGINAL_SENTENCE_SPAN' for s in selected)
            has_evidence=any(fields[f].strip() for f in substantive_fields(fields))
            status = ('STATIC_CONTEXT_TOO_LONG' if base_budget['estimated_input_tokens'] + reserve > base_budget['input_budget']-relational_reserve else
                      'FULL_DESCRIPTOR_TOO_LONG' if descriptor_too_long else
                      (EVIDENCE_TRUNCATED if retrieved and not top_intact else 'READY') if has_evidence else
                      ('NO_EVIDENCE_FITS' if substantive_hits
                       else 'NO_SUBSTANTIVE_CONTEXT') if hits else 'NO_RETRIEVED_EVIDENCE')
            # Metadata are reviewed and hashed, but never serialized into the prompt.
            request['context_budget'] = budget
            request['context_selection'] = dict(status=status, selected=selected, omitted=omitted,
                evidence_limited=any(o['reason'] in ('INPUT_BUDGET_EXCEEDED','ONE_INTACT_CHUNK_PER_FIELD','PARENT_CHUNK_SUBSPAN_SELECTED') for o in omitted),
                candidate_id=candidate['candidate_id'] if candidate else None,
                context_package_id=candidate['context_package_id'] if candidate else None)
            if context_mode is not None:request['context_selection']['context_mode']=context_mode
            if context_mode==v3.RETRIEVED_CONTEXT:
                request['context_selection']['coverage']='RETRIEVED_SUBSET_NOT_EXHAUSTIVE_DOCUMENT_REVIEW'
                budget_limited=[o for o in omitted if o['reason'] in ('INPUT_BUDGET_EXCEEDED','PARENT_CHUNK_SUBSPAN_SELECTED')]
                request['context_selection']['truncation']=dict(policy=TRUNCATION_POLICY,
                    material=status==EVIDENCE_TRUNCATED,top_ranked_chunk_id=top,top_ranked_intact=top_intact,
                    budget_omitted_chunk_ids=sorted({o['chunk_id'] for o in budget_limited if o['reason']=='INPUT_BUDGET_EXCEEDED'}),
                    subspan_chunk_ids=sorted({o['chunk_id'] for o in budget_limited if o['reason']=='PARENT_CHUNK_SUBSPAN_SELECTED'}),
                    reason=('TOP_RANKED_UNIT_NOT_INTACT' if status==EVIDENCE_TRUNCATED else
                            'TEMPLATE_EXCEEDS_EVIDENCE_THRESHOLD' if status=='STATIC_CONTEXT_TOO_LONG' else
                            'NO_RETRIEVED_UNIT_FITS' if status=='NO_EVIDENCE_FITS' else
                            'LOWER_RANKED_UNITS_OMITTED_BY_BUDGET' if budget_limited else None),
                    evidence_threshold_tokens=budget['input_budget']-relational_reserve-reserve)
            if 'relational_context_receipt' in request:request['context_selection']['relational']=request['relational_context_receipt']
            if descriptor_too_long:
                request['context_selection'].update(alternative='GRAPHRAG_FRAGMENTS_V1_REQUIRES_NEW_EXPLICIT_SELECTION',
                    full_descriptor_budget=budget_for(trial))
            if evidence_references:
                request['context_selection']['corrective_input_reserve_tokens'] = reserve
            requests[pid][iid] = request
            diagnostics.append(dict(project_id=pid, indicator_id=iid, status=status,
                request_sha256=canonical_hash(request), budget=budget,
                prompt_bytes=len(request['prompt'].encode()), selected=selected, omitted=omitted))
            if 'relational_context_receipt' in request:diagnostics[-1]['relational']=request['relational_context_receipt']
            if 'truncation' in request['context_selection']:
                diagnostics[-1].update(evidence_limited=request['context_selection']['evidence_limited'],
                    truncation=request['context_selection']['truncation'])
    return requests, dict(version=VERSION, evaluation_mode=evaluation_mode,context_mode=context_mode,
        indicator_ids=sorted(profiles),
        indicators_per_project=len(profiles), requests=diagnostics,
        omitted_static_components=['other_47_profiles', 'global_discovery', 'general_rule_reference_material',
            'rubric_basis_and_hashes', 'full_graph', *([] if full_descriptor else ['full_documents']), 'scores_as_confidence'],
        estimator_note=('Pinned Qwen tokenizer plus calibrated template tokens; decoding schema not in prompt; native usage checked after each call. No text truncation.'
            if tokenizer is not None else
            'Approximate, not exact tokenization; schema included; native usage checked after each call. No text truncation.'))
