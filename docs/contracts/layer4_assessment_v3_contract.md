# ASSESSMENT_V3 — rúbrica semántica fija de catálogo

Estado: **experimental; aceptación humana pendiente**. V1/V2, el baseline de veinte
proyectos, su publicación oficial y la rama territorial aceptada permanecen intactos.
La propuesta no acredita por sí sola mayor calidad ni cobertura.

## Defectos concretos y alcance de la corrección

V2 conserva el significado completo del indicador, pero permite que cada assessment
determine `required_stage`. Esa interpretación puede variar entre proyectos del mismo
indicador. Además, sus etiquetas no distinguen un diseño vigente o un mecanismo
establecido de una propuesta y su media incluye por igual todos los elementos del
catálogo, aunque algunos sean alternativas, controles o detalles complementarios.

Ejemplos que requieren diferenciación documental: COL-01 admite evidencia de diseño
integrado sin afirmar métodos ejecutados; TEC-03 exige potencial comercial fundamentado,
sin ventas; SAL-03 exige una acción implementada orientada a calidad de vida, sin añadir
una mejoría medida solo por la etiqueta CAMBIO; POL-08 documenta organización sin asumir
realización final. En cambio, ASC-02/TEC-07 requieren apropiación efectiva, SAL-01 conserva
la conjunción físico **y** mental y AMB-02 las dimensiones ambiental, económica **y** social.
No se decide sobre ningún proyecto mediante estas referencias documentales.

V3 fija la interpretación del catálogo antes de recibir proyectos. **Codex CLI** propone
esa rúbrica; Python comprueba estructura, identidad y citas de su fundamento. Ninguna
regla de palabras, etiqueta PRESENCIA/CAMBIO o project_id asigna roles ni cumplimiento.

## Primera etapa: rúbrica de catálogo

`make_rubric_input(profiles)` recibe uno a cuarenta y ocho perfiles; permite bloques
de dieciséis sin incluir textos de proyectos. Preserva definición, criterios originales,
evidencia favorable/insuficiente, contexto y modalidades del perfil. El transporte
reutiliza el adaptador existente con un único ítem `CATALOG_RUBRIC_V3`; la respuesta
contiene exclusivamente el subconjunto de perfiles suministrado, sin inventar ids.

Cada indicador devuelve:

- `indicator_id` y `profile_sha256` exactos.
- `indicator_evidence_type`: INCORPORATED_APPROACH, MECHANISM_OR_COLLABORATION,
  PRODUCT_OR_ACTIVITY, RESULT_OR_IMPACT o QUANTITATIVE.
- `indicator_type_basis` y `indicator_type_rationale`: fundamento literal y explicación
  de la naturaleza del indicador. La categoría no sustituye temporalidad por criterio.
- Todos los criterios originales, una sola vez y con su `criterion_id` fijo.

Cada criterio devuelve `role`, `alternative_group`, `temporal_requirement`, `basis`
y `rationale`. `basis` referencia citas literales en indicator_name, descripcion_ampliada,
key_elements, favorable_evidence, insufficient_evidence o relational_context. Una lista
de elementos por sí sola no justifica un rol: al menos una cita debe provenir de otro
campo del perfil. Citas y explicaciones vacías no son válidas.

| Rol | Significado | Contribución conceptual |
|---|---|---|
| REQUIRED | Condición esencial del significado institucional. | Una unidad por criterio. |
| ALTERNATIVE | Una vía de un grupo esencial de alternativas. | El máximo del grupo aporta una unidad. |
| COMPLEMENTARY | Contexto, comprobación o detalle que no debe añadirse como requisito. | Diagnóstico; fuera de K. |

Solo ALTERNATIVE tiene `alternative_group` no nulo. Las alternativas contenidas dentro
de un elemento original pueden permanecer en una unidad, sin partirla artificialmente.
No se convierten conjunciones en alternativas ni se rebajan requisitos para aumentar
SUPPORTED. Una rúbrica compuesta únicamente por complementarios es inválida.

`validate_rubric_wrapper` congela los resultados como `CATALOG_ROLES_V3_CANDIDATE`,
añade los textos originales de criterio y un `rubric_sha256`, y registra
`acceptance=PENDING_HUMAN_REVIEW`. Congelar **no** equivale a aprobación humana.
`check_rubric` rechaza modificaciones posteriores de roles, grupos, temporalidad,
fuentes o hashes. Todos los proyectos del indicador utilizan la misma rúbrica.

## Temporalidad fija y citas del proyecto

Las etapas históricas ACTIVITY_PROPOSED, ACTIVITY_EXECUTED, RESULT_EXPECTED,
RESULT_DEMONSTRATED y CONTEXT se conservan. Se añaden:

- DESIGN_DOCUMENTED: diseño vigente descrito; no demuestra ejecución ni resultados.
- MECHANISM_ESTABLISHED: mecanismo existente documentado; no demuestra impacto posterior.

La LLM clasifica la afirmación, sin inferir cronología por el nombre del campo.
Una frase con hechos y expectativas debe separarse en fragmentos literales cuando
sea posible. Python valida pertenencia de la cita y compatibilidad de etiquetas;
la revisión humana debe comprobar que la etiqueta y la interpretación son correctas.

| temporal_requirement fijo | Etapas que pueden respaldar CLEAR |
|---|---|
| CONTEXT_ONLY | Cualquier etapa; reservado al contenido contextual, no sustituye hechos requeridos. |
| DESIGN_OR_EXECUTION | DESIGN_DOCUMENTED, MECHANISM_ESTABLISHED, ACTIVITY_EXECUTED, RESULT_DEMONSTRATED. |
| ESTABLISHED_OR_EXECUTED | MECHANISM_ESTABLISHED, ACTIVITY_EXECUTED, RESULT_DEMONSTRATED. |
| EXECUTED_ACTIVITY | ACTIVITY_EXECUTED, RESULT_DEMONSTRATED. |
| DEMONSTRATED_RESULT | RESULT_DEMONSTRATED. |
| PROPOSAL_OR_HIGHER | ACTIVITY_PROPOSED y las etapas de DESIGN_OR_EXECUTION. Solo si el indicador admite propuesta. |
| EXPECTED_OR_DEMONSTRATED | RESULT_EXPECTED, RESULT_DEMONSTRATED. Solo para un propósito/expectativa que el indicador permite acreditar como tal. |

La temporalidad requerida se interpreta desde el significado, no mediante un requisito
universal de resultados finales. Un potencial sectorial tampoco demuestra acción ni
cumplimiento. RULE_TEXT continúa como orientación documental, sin evaluadores activos.

## Segunda etapa: assessment por proyecto

`make_input(project, profiles, rules, rubrics)` exige exactamente los seis campos
originales: title, keywords, summary, methodology, objectives y expected_results.
Incluye perfiles completos y rúbricas congeladas. Retrieval no es prueba y no aporta
confianza. La respuesta conserva:

`assessment_version=ASSESSMENT_V3`, `decision`, `support_strength`,
`criterion_assessments`, `evidence` y `explanation`.

Cada evaluación de criterio contiene `criterion_id`, `support`, `evidence_indices`
y `explanation`. No vuelve a decidir `required_stage` ni roles por proyecto.
CLEAR=1, PARTIAL=0,5 y NOT_DEMONSTRATED=0. Todo soporte positivo cita evidencia
verificable; NOT_DEMONSTRATED mantiene índices vacíos. Una sola cita puede respaldar
varios criterios sin multiplicar su peso.

SUPPORTED conserva strength 3–4 y requiere evidencia sustantiva compatible para los
REQUIRED y al menos una alternativa por grupo. Un complementario ausente no invalida
el soporte. INSUFFICIENT_EVIDENCE conserva strength 1–2. NOT_SUPPORTED conserva
strength 0 y no atribuye soporte conceptual positivo. Una evaluación incoherente es
INVALID_ASSESSMENT con confianza NULL, nunca una reclasificación automática.
La clasificación la propone Codex; los gates verifican coherencia del juicio con la
rúbrica declarada, sin decidir por coincidencia de palabras o umbral numérico.

SUPPORTED siempre exige al menos una cita en summary, methodology, objectives o
expected_results. Title y keywords aportan contexto. Cada cita debe existir literalmente
tras normalización NFC y whitespace conservadora; paráfrasis no valen como citas.
La interpretación conceptual sí puede expresar equivalencias con otras palabras.

## Confianza y comparabilidad

Se preserva la fórmula y sus pesos:

`EVIDENCE_CONFIDENCE_V2 = 100 * (0.55*S + 0.45*K)`; `S=strength/4`.

`conceptual_coverage_version=CONCEPTUAL_UNITS_V3_REQUIRED_ALTERNATIVE` identifica
la operacionalización nueva:

`K = mean(valores REQUIRED + máximos de cada grupo ALTERNATIVE)`.

COMPLEMENTARY no entra en el numerador ni denominador. K está entre 0 y 1 y los
scores entre 0 y 100; Decimal precisión 50 y ROUND_HALF_UP a dos decimales. Ningún
contador de campos, citas, palabras o longitud del proyecto modifica los pesos.
La LLM no devuelve el score final. Una evaluación válida NOT_SUPPORTED recibe 0;
un inválido recibe NULL, sin imputarlo como cero.

La coherencia de REQUIRED/ALTERNATIVE implica K=1 para un SUPPORTED válido bajo esta
rúbrica: strength 3 produce 86,25 y strength 4 produce 100. Esta consecuencia debe
revisarse antes de aprobar V3; **no** demuestra confianza probabilística ni calidad
superior. Complementos sin evidencia pueden coexistir con ese 100 si se ha justificado
que son complementarios. La revisión de los roles evita ocultar condiciones esenciales.

Una comparación V2/V3 no es una comparación de pesos: cambian el juicio y la definición
de K. Deben registrarse ambos, el hash de rúbrica y las etapas, sin llamar calibración
estadística a una comparación documental ni optimizar para aumentar SUPPORTED.

## Auditoría y aceptación

`audit_catalog` contrasta los 48 perfiles y sus 246 criterios con las ocho columnas del
catálogo institucional original, el source_record enriquecido y los hashes publicados.
No asigna roles ni etiquetas por Python. Los campos de rol/tipo/temporalidad permanecen
sin asignar hasta la ejecución de catálogo por Codex. Los resultados privados se guardan
en `outputs/layer4/pruebas/validacion_v3_3/rubric_audit.json` y `.md`.

La auditoría documental, validación estructural, interpretación de proyectos y aprobación
humana son etapas distintas. Una rúbrica estructuralmente válida sigue pendiente de
aceptación. No se reutilizan respuestas V2 como si hubieran sido evaluadas con V3, ni se
alteran las publicaciones anteriores. La ejecución institucional requiere autorización
ligada a los nuevos inputs y alcance. La publicación oficial vigente no se reemplaza
mediante estas funciones experimentales.

API: `schemas`, `make_rubric_input`, `rubric_response_schema`, `validate_rubric_wrapper`,
`check_rubric`, `make_input`, `validate_wrapper`, `validate`, `confidence`, `indicator_row`
y `audit_catalog`. `write_contracts(check=True)` contrasta los tres schemas nuevos en
`schemas/layer4_assessment_v3/` sin reescribirlos. Se reutiliza `CodexCliAssessmentProvider`; el schema de transporte
excluye uniqueItems y la validación normativa comprueba unicidad en Python.

## Confianza SK para nuevas evaluaciones (2026-11-12)

La CLI autónoma compacta y la preparación manual usan `ASSESSMENT_V3_SK_V1`,
`EVIDENCE_CONFIDENCE_SK_V1` y `CRITERIA_COVERAGE_SK_V1_REQUIRED_GATE`.
`assessment_v3.schemas(version=SK_VERSION)` genera el contrato en los artefactos
de cada ejecución; los schemas V3 históricos y sus cálculos anteriores se conservan.

S es la media normalizada de cuatro juicios de Qwen: relación directa, especificidad
documental, claridad y adecuación temporal. Cada dimensión tiene niveles 0..4
anclados en `SK_INSTRUCTIONS`, referencias verificadas y una justificación que debe
explicar las cuatro dimensiones. `S = suma(niveles)/16`. Una cita o SUPPORTED no
asigna notas máximas. El 4 temporal exige la etapa que pide el catálogo: intención,
resultado esperado, actividad realizada y resultado demostrado no son equivalentes;
un diseño documentado puede bastar cuando ese sea el requisito institucional.

Cada criterio conserva soporte, referencias y explicación, y añade `coverage`:
0 sin respaldo, 1 indicio indirecto, 2 parcial sustancial, 3 casi completo con brecha
explícita, 4 completo. NOT_DEMONSTRATED exige 0, PARTIAL 1..3 y CLEAR 4.
K parte de la media de REQUIRED y del mejor criterio de cada grupo ALTERNATIVE,
divididos por 4. COMPLEMENTARY no participa. Si hay REQUIRED, K se limita además
al menor grado obligatorio normalizado: los demás criterios no compensan su ausencia.
Los roles y condiciones proceden de la rúbrica congelada; no se inventan requisitos.

`CONFIDENCE = 100 * (0.55*S + 0.45*K)`, con Decimal y redondeo HALF_UP a dos decimales.
S y K están en [0,1]; confianza en [0,100], sin techo artificial. Es respaldo
documental, no probabilidad calibrada. BGE-M3 no aporta un sumando ni multiplicador.
El 86.25 repetido anterior resulta de `S=3/4` y `K=1`, impuesto por los juicios
discretos y los gates de SUPPORTED. Ahora S tiene cuatro dimensiones y PARTIAL
tres grados; coincidencias numéricas legítimas siguen siendo posibles.

Los estados de cumplimiento SK son SUPPORTED e INSUFFICIENT_EVIDENCE. Este último
admite support_strength 0, 1 o 2. Cero exige todos los criterios NOT_DEMONSTRATED,
coverage=0 y dimensiones de fuerza=0; admite citas contextuales verificadas sin
atribuirles soporte. Fuerza positiva conserva las referencias y validaciones SK.
Una evaluación válida, incluso insuficiente, recibe confianza. Un inválido recibe
NULL. La nota entera support_strength se conserva para los gates y no calcula S.

NOT_SUPPORTED se admite como alias de entrada para compatibilidad. Solo un
assessment SK válido con ese alias se proyecta como INSUFFICIENT_EVIDENCE en la
fila interna; la respuesta original, fuerza, criterios y recibos se conservan.
El adaptador compacto conserva también semantic_answer con el código recibido.
No se reclasifican contradicciones ni se reescriben filas o checkpoints existentes.
V1, V2 y V3 histórico conservan sus contratos, decisiones y cálculos anteriores.

Las nuevas respuestas guardan los juicios de S y K internamente y usan las columnas
de exportación existentes. Una respuesta antigua carece de estos juicios: no se
recalcula ni se migra automáticamente. Resume exige hashes/contrato compatibles;
no se omiten fingerprints para aceptar código nuevo sobre checkpoints históricos.
La importación a un manifiesto nuevo SK rechaza confianza de otra versión.

## Estados y evidencias: revisión de 2026-11-13

### Comportamiento anterior y definitivo

La LLM asigna el juicio semántico. Python verifica su coherencia, no lo deduce de
palabras, porcentajes, similitud ni de la nota de confianza.

| Caso | Antes de esta etapa | Contrato SK actual |
|---|---|---|
| Evidencia suficiente | SUPPORTED, fuerza 3–4; REQUIRED CLEAR y una alternativa CLEAR por grupo; cita sustantiva temporalmente compatible | Igual |
| Respaldo débil o parcial | INSUFFICIENT_EVIDENCE, fuerza 1–2; referencias verificables para criterios positivos | Igual; COMPUTED incluso con K parcial o cero |
| Análisis completado sin respaldo | NOT_SUPPORTED, fuerza 0 y ningún criterio positivo | INSUFFICIENT_EVIDENCE, fuerza 0; S=K=0 y confianza 0 |
| Juicio indispensable ausente o ambiguo | REVIEW_REQUIRED del transporte compacto, aclaración y eventual bloqueo | Sigue siendo incidencia interna, sin evaluación calculable ni confianza |
| Error técnico, esquema o cita inválida | INVALID_ASSESSMENT u otro código técnico; trabajo bloqueado; proyección diagnóstica REVIEW_REQUIRED | Igual separación técnica, confianza NULL; nunca imputación de cero |

V3 y SK ya computaban confianza en todos los assessments válidos; la restricción
NOT_APPLICABLE a negativos pertenece al contrato histórico V1. El defecto activo
era rechazar INSUFFICIENT_EVIDENCE con fuerza 0 como INCONSISTENT_DECISION. Eso
podía terminar en bloqueo y REVIEW_REQUIRED aunque describiera ausencia de respaldo.

REVIEW_REQUIRED tiene usos distintos que no son decisiones de cumplimiento:
`minimal.schema/assemble` recibe un juicio de criterio o conclusión explícitamente
ambiguo; tras una aclaración no resuelta se conserva CLARIFICATION_UNRESOLVED.
`final_output.project_records` lo usa como marcador en la proyección diagnóstica
de cualquier job distinto de PASS, siempre con confianza NULL y status en audit.
`lifecycle.prepare`, preparación de controles, recuperación y revisión de políticas
lo usan antes de autorización, sin evaluación ni score. `experiment.execute`
marca FINISHED_REVIEW_REQUIRED al terminar un lote experimental, incluso con
filas válidas; tampoco es un gate para calcular confianza. Esos estados
técnicos no sustituyen un assessment válido con evidencia parcial.

La salida final vigente de tesis sigue publicando exclusivamente SUPPORTED VALID;
parciales, ceros, pendientes y errores permanecen en estructuras y diagnósticos
existentes. No se modifica el filtro de publicación, plantilla, hojas ni columnas.

### Procedencia de los errores y correcciones seguras

- INVALID_ASSESSMENT es un código de Python que agrupa JSON, schema, semántica
  o evidencia inválida. El contenido incoherente puede proceder de la LLM; una
  excepción interna del validador también se distingue en validation.json/issues.
- EVIDENCE_INDEX_OUT_OF_RANGE lo detecta Python sobre índices generados por la
  LLM. En el caso histórico documentado había dos citas y referencias [1,2,3]:
  solo 0 y 1 existían. No se pueden reasignar 2 y 3 con seguridad, ni inferir una
  intención base uno; se conserva el rechazo y su diagnóstico específico.
- QUOTE_NOT_IN_SENT_GRAPHRAG_CONTEXT lo detecta Python aunque una cita exista en
  campos completos si no pertenece al contexto enviado. También podía rechazar
  cambios meramente NFC/whitespace que el validador normativo ya admitía. Ahora
  ambos usan la misma normalización conservadora en el transporte textual.
  Se preservan mayúsculas, acentos y puntuación; no se aceptan paráfrasis, elipsis
  añadidas ni texto no enviado. Los originales y recibos no se modifican.
- Se reutilizan los IDs existentes: F de fragmentos enviados y E del registro
  compacto ligado a proyecto, campo, intervalo y hash. La LLM selecciona IDs y
  etapa; Python recupera el texto original y construye índices base cero.
  El registro compacto verifica intervalo y hash contra el campo original.
- En transporte por referencias, repetir exactamente (fragment_id,stage) se
  deduplica sin cambiar juicios, cobertura, etapas ni fuerza. Etapas diferentes
  permanecen separadas. El adaptador compacto deduplica también IDs de fuerza
  repetidos. Los índices numéricos inválidos o duplicados del contrato
  normativo siguen rechazándose; no se eliminan citas falsas para salvar un score.
- Un registro de fragmentos con IDs duplicados se rechaza por ambigüedad. Los IDs
  desconocidos se rechazan; los errores de strength_rubric apuntan ahora a su ruta
  real y no a un criterio inexistente. Todo diagnóstico usa estructuras existentes.
- Un registro vacío admite únicamente arrays vacíos de referencias, con schema
  válido (sin enum vacío). Esto permite validar una respuesta sintética completada
  sin evidencia; no convierte bloqueos previos de contexto o transporte en análisis.

Las correcciones no prueban que una cita verdadera implique el criterio: pertinencia,
atribución y etapa siguen siendo juicios semánticos contrastables. Esta etapa solo
usa mocks y controles sintéticos, sin validar calidad con modelos reales. No se
ejecuta recuperación ni migración sobre resultados históricos.

### Archivos de esta etapa y verificación

Se editaron únicamente estos archivos existentes, conservando sus cambios previos:

- `src/layer4_evaluation/indicators/assessment_v3.py`
- `src/layer4_evaluation/indicators/evidence_references.py`
- `src/layer4_evaluation/indicators/context_budget.py`
- `src/layer4_evaluation/indicators/ollama_provider.py`
- `src/layer4_evaluation/indicators/validation_diagnostics.py`
- `src/layer4_evaluation/live_execution.py`
- `src/autonomous_execution/minimal.py`
- `src/autonomous_execution/batching.py`
- `tests/layer5_experiment/test_assessment_v3.py`
- `tests/test_evidence_references.py`
- `tests/test_assessment_recovery.py`
- `docs/contracts/layer4_assessment_v3_contract.md`

```powershell
.\.venv\Scripts\python.exe -m pytest tests/layer5_experiment/test_assessment_v3.py tests/test_evidence_references.py tests/test_assessment_recovery.py tests/test_thesis_output.py -q
```

Resultado final: **148 passed**. Casos suficientes, débiles, parciales, sin respaldo,
citas contextuales sin soporte, cero/NULL, alias conservado, índices incorrectos,
citas falsas, normalización, IDs desconocidos/ambiguos/repetidos, etapas distintas,
registro vacío, mocks de timeout/JSON/esquema/error interno, aclaración acotada y
reanudación sintética. Incluye esquema y render de las ocho columnas vigentes de
tesis. `git diff --check` pasó. Temporales administrados fuera de outputs.

Una ejecución ampliada anterior, incluyendo `test_context_budget.py` y
`test_ollama_provider.py`, dio **170 passed, 9 failed**. Ocho fallos corresponden
a expectativas/fixtures de contexto 4096 frente al default existente 8192 y uno a
esperar «detenida» donde la reanudación devuelve UNCERTAIN_OUTCOME. No se cambian
configuración ni reanudación de producción para satisfacer esas expectativas.
La fixture de recuperación sí toma su reserva del contexto configurado, para
alcanzar el fallo de evidencia que pretende verificar. No se afirma que toda la
suite general esté verde.

No se invocaron modelos ni endpoints reales, no se ejecutaron proyectos reales,
no se cambiaron preprocessing, knowledge, GraphRAG o BGE-M3, no se crearon módulos,
ni se modificaron resultados/checkpoints históricos o el Excel institucional.
