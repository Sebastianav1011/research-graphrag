"""Versioned operational interpretation; official profiles and historical V1 stay intact.

No scoring formula, retrieval, keyword classifier or inference lives here.
Applicability and evidence relations are documented semantic judgments, not facts
that a structural validator can establish on its own.
"""
from copy import deepcopy

MODE = 'PROSPECTIVE_V2'
VERSION = 'ASSESSMENT_PROSPECTIVE_V2'
PROMPT_V1 = 'PROSPECTIVE_V2_APPLICABILITY_V1'
PROMPT_V2 = 'PROSPECTIVE_V2_APPLICABILITY_V2'
PROMPT_V3 = 'PROSPECTIVE_V2_APPLICABILITY_V3'
PROMPT = 'PROSPECTIVE_V2_CRITERIA_DECISION_V1'
PROMPTS = (PROMPT_V1, PROMPT_V2, PROMPT_V3, PROMPT)
COHERENT_APPLICABILITY = 'APPLICABILITY_DECISION_SCHEMA_V1'
DECISION_POLICY = 'VALIDATED_CRITERIA_DECISION_V1'
CORRECTION = 'PROSPECTIVE_V2_COMPACT_CORRECTION_V1'

# All 48 operational interpretations are independent of any project. These are
# prospective counterparts, never replacements for the institutional definitions.
INTERPRETATIONS = {
    'COL-01': 'Articulacion prevista del problema, metodos, analisis y perspectivas; no basta nombrar disciplinas.',
    'COL-02': 'Actores externos previstos con papeles, aportes y etapas de participacion definidos.',
    'COL-03': 'Participacion prevista e incidencia en formulacion, ejecucion y evaluacion; sin inventar escala institucional.',
    'ASC-01': 'Mecanismo previsto de dialogo con reciprocidad entre saberes y actores identificados.',
    'ASC-02': 'Ruta concreta de uso, adaptacion, replica o sostenimiento por el beneficiario; entrega sola no prueba esa ruta.',
    'ASC-03': 'Productos y entrega previstos, adecuacion, comprensibilidad, calidad y valoracion esperada fundamentada; evaluar no garantiza valoracion positiva.',
    'DIV-01': 'Productos y estrategia previstos para comunicar conocimiento propio a no especialistas y fundamento de eficacia esperada.',
    'DIV-02': 'Piezas, contenido, uso comunicativo y publicos previstos; conteos son metas documentadas, no productos realizados.',
    'DIV-03': 'Menciones externas de hallazgos: una estrategia de difusion no garantiza menciones independientes ni su registro.',
    'DIV-04': 'Difusion comprensible, abierta y reutilizable prevista con mecanismos concretos de consulta y aprovechamiento esperados.',
    'DIV-05': 'Espacios publicos de debate previstos, apertura extraacademica y unidades de conteo delimitadas.',
    'CUL-01': 'Acciones previstas de construccion, preservacion y revitalizacion de memoria e identidad vinculadas a actores y referentes culturales.',
    'CUL-02': 'Acciones previstas sobre patrimonio material o inmaterial identificado; valor cultural no equivale a valor economico.',
    'SOC-01': 'Mejora de bienestar esperada, poblacion, referencia y mecanismo de contribucion; sin atribucion causal ya demostrada.',
    'SOC-02': 'Acciones y acuerdos previstos que consolidan redes; mencionar actores no demuestra colaboracion.',
    'SOC-03': 'Respuesta prevista a desigualdad, exclusion o injusticia con mecanismo de equidad o derechos; estudiar vulnerabilidad no basta.',
    'SOC-04': 'Beneficio, destinatarios y recepcion previstos; metas de beneficiarios delimitadas, sin confundir muestra con beneficiarios.',
    'TEC-01': 'Producto tecnologico previsto con participacion aplicada y aportes de actores no academicos.',
    'TEC-02': 'Validacion tecnologica participativa prevista con usuarios destinatarios, tareas y condiciones de uso concretos.',
    'TEC-03': 'Resultado tecnologico previsto y potencial comercial fundamentado en aplicacion o demanda; no exige ventas.',
    'TEC-04': 'Tecnologia instrumental prevista, destinatarios, funcion y mecanismo de beneficio esperado; no exige optimo medido.',
    'TEC-05': 'Desarrollo original previsto y ruta concreta de aplicacion extraacademica; no afirmar aplicacion ya demostrada.',
    'TEC-06': 'Uso previsto novedoso de tecnologia preexistente, adaptacion local y mecanismo de solucion.',
    'TEC-07': 'Ruta prevista de adopcion, adaptacion o sostenimiento y accion del actor extraacademico; entrega no equivale a adopcion.',
    'ECO-01': 'Ingreso adicional esperado, receptor y mecanismo mediante implementacion, validacion o comercializacion previstos.',
    'ECO-02': 'Ahorro esperado en un proceso, mejora prevista y referencia documentada para interpretar la reduccion.',
    'ECO-03': 'Oportunidades laborales concretas previstas, destinatarios y vinculo directo o indirecto; no mera empleabilidad.',
    'ECO-04': 'Fortalecimiento previsto de eslabones identificados y su funcion en una cadena productiva o de suministros.',
    'ECO-05': 'Mejoras previstas de practicas productivas sostenibles y mecanismo sectorial o territorial.',
    'ECO-06': 'Crecimiento economico esperado para grupos identificados, referencia y medida pertinente; no inventar TIR ni escala.',
    'ECO-07': 'Creacion prevista de redes colaborativas o estrategias de economia solidaria y mecanismo que promueve capacidades productivas; no exige ingresos finales.',
    'AMB-01': 'Solucion ambiental prevista y funcion frente a necesidad ecosistemica, biodiversidad o sostenibilidad.',
    'AMB-02': 'Mejoras sostenibles esperadas en las tres dimensiones ambiental, economica y social; conservar la conjuncion.',
    'SAL-01': 'Mejoras esperadas de bienestar fisico y mental, diferenciadas y vinculadas al proyecto.',
    'SAL-02': 'Accion preventiva prevista, riesgo poblacional y mecanismo de prevencion en salud publica.',
    'SAL-03': 'Acciones previstas para personas con discapacidad y mecanismo orientado a su calidad de vida.',
    'SAL-04': 'Intervencion prevista, poblacion y disminucion esperada de tasa de mortalidad con referencia poblacional y temporal; no confundir riesgo con tasa.',
    'SAL-05': 'Dialogo e integracion previstos entre medicina occidental y tradicional o ancestral con actores y acciones concretos.',
    'SAL-06': 'Estrategias participativas de cuidado previstas y mecanismos de fortalecimiento con diversos actores.',
    'POL-01': 'Mecanismos previstos para facilitar participacion en politica publica o ciencia ciudadana; no exige norma modificada.',
    'POL-02': 'Cita de hallazgos en documento oficial externo: una recomendacion o entrega prevista no garantiza esa cita.',
    'POL-03': 'Ruta concreta prevista de modificacion o implementacion de politica, actores y contribucion; recomendaciones solas no bastan.',
    'POL-04': 'Instrumentos previstos y ruta documentada de adopcion estatal; no confundir entrega con decision de adoptar.',
    'POL-05': 'Participacion prevista en audiencia legislativa o judicial identificable, representacion y unidad de registro.',
    'POL-06': 'Colaboracion prevista con entidades o actores en formulacion o evaluacion de politica y aporte conjunto.',
    'POL-07': 'Documentos propios y entrega gubernamental previstos, receptor y unidades documentales delimitados.',
    'POL-08': 'Organizacion prevista de eventos formativos para funcionarios, contenido propio y metas de eventos.',
    'POL-09': 'Participacion o creacion prevista de redes multisectoriales de politica, papeles y redes delimitados.',
}

# A purely planned project cannot establish an independent third-party record.
# Keep these cases pertinent/insufficient, not N/A. Human review may subsequently
# use documented observations, without pretending the observation was predicted.
LIMITATIONS = {
    'DIV-03': 'No se puede afirmar una mencion independiente ni contar menciones ocurridas desde un plan de difusion.',
    'POL-02': 'No se puede afirmar una cita oficial de hallazgos desde una entrega o incidencia propuesta.',
}
EXTERNAL_RECORD_CRITERIA = {'DIV-03': ('C02','C04'), 'POL-02': ('C01','C02','C05')}

INSTRUCTIONS_V1 = '''
PROSPECTIVE_V2: juzga contribuciones concretamente previstas, no ejecucion ni impacto ocurrido.
El texto oficial se conserva como definicion. Su contraparte operativa y las etapas efectivas
rigen esta modalidad. Objetivos, metodologias, actividades, productos y resultados esperados son
evidencia valida si describen que hara ESTE proyecto, como y para quien cuando el criterio lo pide.
Una propuesta concreta puede ser CLEAR. No exijas ejecucion, adopcion o impacto ya ocurrido.
Tampoco conviertas una finalidad vaga, una palabra afin o una expectativa sin mecanismo en CLEAR.
No exijas mediciones o cifras que el criterio no pide. Conteos previstos son metas, nunca logros.
Conserva roles, conjunciones y alternativas. Primero juzga cada criterio de modo independiente;
despues decide. SUPPORTED exige todos REQUIRED y una alternativa por grupo CLEAR y fuerza 3/4.
Si todos los esenciales son CLEAR, la decision debe ser coherente; explica limitaciones operativas.
SUPPORTED significa contribucion prevista respaldada, nunca cumplimiento institucional ya ocurrido.
ACTIVITY_PROPOSED y RESULT_EXPECTED describen futuro; no los etiquetes como ejecutados/demostrados.
Antecedentes, objetos de estudio y mecanismos ajenos no son contribuciones del proyecto. Ejemplo:
mentoria o cultura etica no son tecnologia instrumental; una poblacion no demuestra una intervencion.
Cada criterio declara evidence_relation: PROJECT_CONTRIBUTION para accion/mecanismo/resultado propio;
CONTEXT_IDENTIFICATION solo identifica contexto exigido; UNRELATED para dominio o sujeto ajeno;
NO_SUPPORT cuando no hay respaldo. Criterios sustantivos no reciben soporte positivo solo contextual.
APLICABILIDAD se juzga separadamente: status APPLICABLE, UNDETERMINED o NOT_APPLICABLE,
con explanation, basis y referencias verificables. NOT_APPLICABLE requiere EXPLICIT_EXCLUSION o
DOCUMENTED_SCOPE: una cita positiva que delimite alcance incompatible y una explicacion del conflicto
con el indicador. No uses ausencia de palabras, falta de citas, silencio, recuperacion incompleta
ni incumplimiento como prueba de no aplicabilidad. Ante duda: UNDETERMINED e INSUFFICIENT_EVIDENCE.
APPLICABLE requiere basis RELEVANT_SCOPE y citas. UNDETERMINED usa UNKNOWN.
NOT_APPLICABLE exige decision homonima, criterios NOT_DEMONSTRATED, cobertura y fuerza 0,
dimensiones de fuerza 0 y referencias de fuerza vacias; sus citas de alcance van en applicability.
INSUFFICIENT_EVIDENCE admite fuerza 0 sin respaldo o 1/2 parcial. Errores tecnicos nunca son decisiones.
Las limitaciones de registros externos impiden SUPPORTED desde una mera prevision: conserva
insuficiencia y explica el limite. Solo citas documentales de registros externos ya existentes pueden
acreditar esas condiciones; distingue expresamente esa observacion del resto de la propuesta.
No rebajes criterios ni declares NOT_APPLICABLE por esa limitacion.
'''

# Contract clarification only: no rubric, validator, evidence or score changes.
CONTRACT_CLARIFICATION = '''
COMPROBACION DEL CONTRATO ANTES DE RESPONDER (revision de instrucciones V2):
- NOT_DEMONSTRATED y coverage 0 requieren evidence_refs=[] en ese criterio. Explica
  la falta o irrelevancia en explanation; no adjuntes citas como si fueran respaldo.
- UNRELATED y NO_SUPPORT no permiten PARTIAL ni CLEAR. CONTEXT_IDENTIFICATION solo
  permite respaldo positivo en criterios cuya temporal_requirement sea CONTEXT_ONLY.
- La ausencia de tecnologia, actividad o mecanismo en los fragmentos NO demuestra
  un alcance incompatible. Si no puedes citar una delimitacion incompatible suficiente,
  usa applicability UNDETERMINED, basis UNKNOWN y decision INSUFFICIENT_EVIDENCE.
  No cambies a NOT_APPLICABLE para resolver un error de respaldo o de referencias.
- APPLICABLE y NOT_APPLICABLE requieren citas de alcance sustantivas; nunca referencias
  vacias. No inventes una exclusion desde la naturaleza academica o social del estudio.
- Para EXPECTED_OR_DEMONSTRATED, CLEAR requiere al menos una cita RESULT_EXPECTED o
  RESULT_DEMONSTRATED que realmente describa ese resultado. Clasifica la proposicion
  citada, no solo su campo: una actividad prevista no es por si misma un beneficio esperado.
Estas comprobaciones no autorizan a cambiar los juicios para hacerlos positivos.
'''
INSTRUCTIONS_V2 = INSTRUCTIONS_V1 + CONTRACT_CLARIFICATION
INSTRUCTIONS_V3 = INSTRUCTIONS_V2 + '''
El esquema vincula aplicabilidad y decision: UNDETERMINED/UNKNOWN solo admite
INSUFFICIENT_EVIDENCE; APPLICABLE/RELEVANT_SCOPE admite SUPPORTED o
INSUFFICIENT_EVIDENCE; NOT_APPLICABLE con exclusion o alcance incompatible
documentado solo admite NOT_APPLICABLE, sin puntuaciones de respaldo positivas.
Selecciona la rama por la evidencia, nunca para resolver una falta de respaldo.
'''
INSTRUCTIONS = INSTRUCTIONS_V2 + '''
En esta revision Python determina la decision final desde los criterios esenciales,
la aplicabilidad documentada y las reglas de fuerza ya vigentes. Tu campo decision
es una recomendacion original para auditoria, no el estado final. Evalua cada criterio,
cobertura, evidencia, fuerza y aplicabilidad con independencia de esa recomendacion.
No cambies referencias ni puntuaciones para hacerlas coincidir con tu decision.
Una evaluacion invalida de criterios, fuerza o aplicabilidad sigue siendo error tecnico.
'''


def instructions_for(prompt_version):
    if prompt_version == PROMPT_V1:
        return INSTRUCTIONS_V1
    if prompt_version == PROMPT_V2:
        return INSTRUCTIONS_V2
    if prompt_version == PROMPT_V3:
        return INSTRUCTIONS_V3
    if prompt_version == PROMPT:
        return INSTRUCTIONS
    raise ValueError('Revision de instrucciones PROSPECTIVE_V2 desconocida')


def derive(rubric):
    from . import assessment_v3 as v3
    value = deepcopy(rubric)
    value.pop('rubric_sha256')
    note = INTERPRETATIONS.get(value['indicator_id'], 'Contribucion prevista concreta segun los criterios documentados.')
    for c in value['criteria']:
        c['temporal_requirement'] = v3.PROSPECTIVE_TEMPORAL.get(c['temporal_requirement'], c['temporal_requirement'])
        stage = c['temporal_requirement']
        meaning = ('identificacion documental del contexto requerido, sin inferir una accion desde su mera presencia'
                   if stage == 'CONTEXT_ONLY' else
                   'resultado esperado concreto con mecanismo de contribucion, sin exigir logro observado'
                   if stage == 'EXPECTED_OR_DEMONSTRATED' else
                   'accion, producto, diseno o mecanismo concreto previsto, sin exigir ejecucion')
        c['rationale'] = f'Interpretacion operativa PROSPECTIVE_V2 de {c["criterion_id"]}: {meaning}. Conserva el contenido y rol del criterio oficial.'
    value['indicator_type_rationale'] = 'Contraparte prospectiva; no acredita resultados ocurridos. ' + note
    value['rubric_sha256'] = v3.canonical_hash(value)
    return value


def extend_schema(assessment):
    from .assessment_v3 import _object
    props = assessment['properties']
    props['decision']['enum'] = ['SUPPORTED', 'INSUFFICIENT_EVIDENCE', 'NOT_APPLICABLE']
    props['applicability'] = _object(dict(
        status=dict(type='string', enum=['APPLICABLE', 'UNDETERMINED', 'NOT_APPLICABLE']),
        basis=dict(type='string', enum=['RELEVANT_SCOPE', 'UNKNOWN', 'EXPLICIT_EXCLUSION', 'DOCUMENTED_SCOPE']),
        explanation=dict(type='string', minLength=1),
        evidence_indices=dict(type='array', items=dict(type='integer', minimum=0), uniqueItems=True)))
    assessment['required'].append('applicability')
    assessment['required'].append('coverage_policy')
    c = props['criterion_assessments']['items']
    c['properties']['evidence_relation'] = dict(type='string', enum=[
        'PROJECT_CONTRIBUTION', 'CONTEXT_IDENTIFICATION', 'UNRELATED', 'NO_SUPPORT'])
    c['required'].append('evidence_relation')


def validate(fields, profile, assessment, rubric, *, components_only=False):
    """Extra semantic-contract gates; common V3 validation still runs unchanged."""
    from .assessment_v3 import STRENGTH_DIMENSIONS
    from .selection import substantive_fields
    errors = []
    app = assessment['applicability']; decision = assessment['decision']
    refs = app['evidence_indices']; evidence = assessment['evidence']
    if not app['explanation'].strip(): errors.append('P2_APPLICABILITY:EXPLANATION_REQUIRED')
    if any(i >= len(evidence) for i in refs): errors.append('P2_APPLICABILITY:INVALID_REFERENCE')
    elif app['status'] != 'UNDETERMINED' and (not refs or not all(evidence[i]['field'] in substantive_fields(fields) for i in refs)):
        errors.append('P2_APPLICABILITY:SUBSTANTIVE_SCOPE_EVIDENCE_REQUIRED')
    allowed = {'APPLICABLE': {'RELEVANT_SCOPE'}, 'UNDETERMINED': {'UNKNOWN'},
               'NOT_APPLICABLE': {'EXPLICIT_EXCLUSION', 'DOCUMENTED_SCOPE'}}
    if app['basis'] not in allowed[app['status']]: errors.append('P2_APPLICABILITY:BASIS_MISMATCH')
    if not components_only and (decision == 'NOT_APPLICABLE') != (app['status'] == 'NOT_APPLICABLE'):
        errors.append('P2_APPLICABILITY:DECISION_MISMATCH')
    if not components_only and decision == 'SUPPORTED' and app['status'] != 'APPLICABLE':
        errors.append('P2_SUPPORTED:APPLICABILITY_REQUIRED')
    if (app['status'] == 'NOT_APPLICABLE' if components_only else decision == 'NOT_APPLICABLE') and (assessment['support_strength'] or
            any(assessment['strength_rubric'][k] for k in STRENGTH_DIMENSIONS) or
            assessment['strength_rubric']['evidence_indices'] or
            any(c['support'] != 'NOT_DEMONSTRATED' or c['coverage'] for c in assessment['criterion_assessments'])):
        errors.append('P2_APPLICABILITY:NOT_A_SUPPORT_ASSESSMENT')
    criteria = {c['criterion_id']: c for c in rubric['criteria']}
    for c in assessment['criterion_assessments']:
        if c['criterion_id'] not in criteria: continue  # Exact-ID gate reports it.
        if c['support'] != 'NOT_DEMONSTRATED':
            relation = c['evidence_relation']
            contextual = criteria[c['criterion_id']]['temporal_requirement'] == 'CONTEXT_ONLY'
            if relation not in (('PROJECT_CONTRIBUTION', 'CONTEXT_IDENTIFICATION') if contextual else ('PROJECT_CONTRIBUTION',)):
                errors.append('P2_CRITERION:CONTEXT_OR_UNRELATED_IS_NOT_SUBSTANTIVE_SUPPORT')
            if not contextual and not any(0<=i<len(evidence) and evidence[i]['stage']!='CONTEXT' and
                    evidence[i]['field'] in substantive_fields(fields) for i in c['evidence_indices']):
                errors.append('P2_CRITERION:CONTEXT_ONLY_REFERENCES')
    external_ids=EXTERNAL_RECORD_CRITERIA.get(profile['indicator_id'],())
    judgments={c['criterion_id']:c for c in assessment['criterion_assessments']}
    external_verified=bool(external_ids) and all(cid in judgments and judgments[cid]['support']=='CLEAR' and any(
        0<=i<len(evidence) and evidence[i]['stage'] in ('ACTIVITY_EXECUTED','RESULT_DEMONSTRATED') and
        evidence[i]['field'] in substantive_fields(fields) for i in judgments[cid]['evidence_indices']) for cid in external_ids)
    if not components_only and decision == 'SUPPORTED' and external_ids and not external_verified:
        errors.append('P2_SUPPORTED:EXTERNAL_RECORD_NOT_PROSPECTIVELY_ESTABLISHED')
    # The gate is one-way for V1. V2 also rejects an unexplained negative when
    # all essential judgments have already declared full support.
    clear = {c['criterion_id'] for c in assessment['criterion_assessments'] if c['support'] == 'CLEAR'}
    groups = {c['alternative_group'] for c in criteria.values() if c['role'] == 'ALTERNATIVE'}
    complete = bool(clear) and all(c['criterion_id'] in clear for c in criteria.values() if c['role'] == 'REQUIRED') and all(
        any(c['criterion_id'] in clear and c['alternative_group'] == g for c in criteria.values()) for g in groups)
    if not components_only and complete and decision == 'INSUFFICIENT_EVIDENCE' and (not external_ids or external_verified):
        errors.append('P2_DECISION:ESSENTIAL_CRITERIA_CLEAR_BUT_INSUFFICIENT')
    return errors


def resolve_decision(fields, profile, assessment, rubric):
    """Derive only the decision; invalid model components remain technical errors."""
    from . import assessment_v3 as v3
    from .validation_diagnostics import AssessmentValidationError

    def require_valid(errors):
        if errors:
            raise AssessmentValidationError([dict(category='INVALID_FIELD_VALUE', path='$',
                indicator_id=profile['indicator_id'], rule=e) for e in errors])

    # Includes exact IDs, quotes, stages, coverage, evidence relations, all strength
    # anchors and scope evidence. Only the model's decision-dependent gates defer.
    require_valid(v3.validate(fields, profile, assessment, rubric, components_only=True))
    clear = {c['criterion_id'] for c in assessment['criterion_assessments'] if c['support'] == 'CLEAR'}
    groups = {c['alternative_group'] for c in rubric['criteria'] if c['role'] == 'ALTERNATIVE'}
    blockers = [c['criterion_id'] for c in rubric['criteria'] if c['role'] == 'REQUIRED' and c['criterion_id'] not in clear]
    blocked_groups = sorted(g for g in groups if not any(c['alternative_group'] == g and c['criterion_id'] in clear for c in rubric['criteria']))
    app = assessment['applicability']['status']
    complete = bool(clear) and not blockers and not blocked_groups
    external = EXTERNAL_RECORD_CRITERIA.get(profile['indicator_id'], ())
    judgments = {c['criterion_id']: c for c in assessment['criterion_assessments']}
    from .selection import substantive_fields
    external_verified = all(judgments[cid]['support'] == 'CLEAR' and any(
        assessment['evidence'][i]['stage'] in ('ACTIVITY_EXECUTED', 'RESULT_DEMONSTRATED') and
        assessment['evidence'][i]['field'] in substantive_fields(fields)
        for i in judgments[cid]['evidence_indices']) for cid in external)
    decision = ('NOT_APPLICABLE' if app == 'NOT_APPLICABLE' else
        'SUPPORTED' if app == 'APPLICABLE' and complete and external_verified else 'INSUFFICIENT_EVIDENCE')
    result = deepcopy(assessment)
    result['decision'] = decision
    result['explanation'] = (f'Decision derivada por {DECISION_POLICY}: {decision}; aplicabilidad {app}; '
        f'esenciales sin CLEAR {blockers}; grupos alternativos sin CLEAR {blocked_groups}; '
        f'condiciones de registro externo satisfechas {external_verified}. '
        'Se conservan los juicios, evidencias, fuerza y cobertura originales validados.')
    # Full, unchanged final gates: e.g. strength 0 with positive criteria, strength
    # 3/4 with missing essentials, or strength 1/2 with all essentials CLEAR fail.
    require_valid(v3.validate(fields, profile, result, rubric))
    receipt = dict(version=DECISION_POLICY, original_decision=assessment['decision'],
        original_explanation=assessment['explanation'], derived_decision=decision,
        applicability=app, required_blockers=blockers, alternative_blockers=blocked_groups,
        external_record_verified=external_verified, changed=assessment['decision'] != decision)
    return result, receipt


def common_assessment(assessment):
    """Validation-only projection, retaining all literal evidence for quote checks."""
    from .assessment_v3 import SK_VERSION
    value = deepcopy(assessment)
    value['assessment_version'] = SK_VERSION
    value.pop('applicability')
    for c in value['criterion_assessments']: c.pop('evidence_relation')
    if value['decision'] == 'NOT_APPLICABLE': value['decision'] = 'INSUFFICIENT_EVIDENCE'
    return value
