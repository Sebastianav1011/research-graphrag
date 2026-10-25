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
