# ASSESSMENT_V2 y EVIDENCE_CONFIDENCE_V2

Estado: implementación candidata; aprobación con datos reales y revisión humana pendiente.
V1, sus respuestas, contratos y publicaciones se conservan. Nunca se convierten respuestas
V1 en V2: cambian instrucciones, estructura, rúbrica y fingerprints.

## Interpretación y evidencia

La única inferencia permitida es la LLM ejecutada por `CodexCliAssessmentProvider`.
Python coordina, verifica estructura/identificadores/citas, calcula y exporta. Recibe
los seis campos completos y separados del PROJECT, el perfil operacional v2 completo
y las reglas textuales del catálogo. Solo se evalúan pares publicados por Capa 3.
No se reconstruye retrieval ni se usa su score como prueba.

La equivalencia entre evidencia y criterio es semántica. Las **citas** deben existir
literalmente en el campo tras NFC y whitespace conservador; no se admiten paráfrasis
como citas. La explicación del vínculo conceptual sí puede usar otras palabras.
V1 ya comprobaba pertenencia exacta del nombre del elemento al catálogo; nunca
exigió que ese nombre apareciera literalmente en el proyecto. V2 hace explícita
y auditable la relación criterio → citas, antes implícita en la explicación.

`assessment_version=ASSESSMENT_V2`, `decision`, `support_strength`,
`criterion_assessments`, `evidence`, `explanation` son campos cerrados.
El wrapper contiene `project_id` y exactamente un assessment por indicador solicitado.
La LLM no puede devolver confianza ni probabilidades.

## Rúbrica conceptual fija

`CATALOG_CRITERIA_V2_CANDIDATE` conserva cada elemento clave único NFC/whitespace,
en su orden publicado. Asigna `C01`, `C02`, etc., texto y peso 1. Se fija el hash del
perfil completo. La misma rúbrica se aplica a todos los proyectos del indicador.
No se generan criterios oportunistas por proyecto ni se omiten criterios sin soporte.

Esta operacionalización requiere revisión humana: los elementos del catálogo no
constituyen automáticamente una conjunción de condiciones obligatorias. Por ejemplo,
un perfil que admite interdisciplinariedad **o** transdisciplinariedad no exige ambas.
El significado completo y sus conjunciones/disyunciones gobiernan la decisión de la LLM.
K describe cobertura de la rúbrica; no determina por umbral la decisión.

Cada criterio devuelve `criterion_id`, `support`, `required_stage`, `evidence_indices`
y `explanation`. Los índices base cero referencian el array de citas.

| support | Valor para K | Condición |
|---|---:|---|
| CLEAR | 1 | Correspondencia conceptual clara con cita sustantiva verificada y temporalidad compatible. |
| PARTIAL | 0,5 | Evidencia verificable pero incompleta; se explicita qué falta. |
| NOT_DEMONSTRATED | 0 | Sin demostración del criterio; índices vacíos. |

Todos los criterios deben aparecer una vez. K = suma de valores / número de criterios.
No se cuentan palabras, longitud, campos rellenados ni número de citas. Una sola cita
puede respaldar varios criterios; dos citas equivalentes no duplican su peso.

## Temporalidad

Cada cita tiene `field`, `text`, `stage`. Las etapas son ACTIVITY_PROPOSED,
ACTIVITY_EXECUTED, RESULT_EXPECTED, RESULT_DEMONSTRATED y CONTEXT.
La LLM interpreta `required_stage` desde el perfil y etiqueta la afirmación de la cita.

- Un criterio de actividad ejecutada exige una cita ACTIVITY_EXECUTED para CLEAR.
- Un resultado demostrado exige RESULT_DEMONSTRATED; una expectativa no basta.
- Un criterio de propuesta admite actividad propuesta o ejecutada.
- Un criterio de resultado esperado admite expectativa o resultado demostrado.
- CONTEXT no impone cronología adicional.

Python comprueba compatibilidad **entre etiquetas**; no prueba por sí solo que la LLM
etiquetó bien la frase ni interpretó bien la temporalidad exigida. La revisión humana
comprueba tanto las etiquetas como la inferencia conceptual y la suficiencia global.
El nombre de un campo no demuestra que un hecho ocurrió.

## Decisiones y validación

SUPPORTED conserva strength 3–4 y exige al menos un criterio CLEAR con cita válida
en summary, methodology, objectives o expected_results. No requiere varias secciones.
INSUFFICIENT_EVIDENCE conserva strength 1–2. NOT_SUPPORTED conserva strength 0 y
todos los criterios NOT_DEMONSTRATED. No exige contradicción ni demuestra ausencia
real de impacto. Strength positivo exige una cita verificable; no se crea respaldo
positivo a partir de campos vacíos. Una relación temática puede tener strength 1,
K=0 y explicación contextual sin convertirse en cumplimiento.

Cita inexistente, criterio desconocido/duplicado/omitido, índices inválidos,
temporalidad incompatible o decisión/strength contradictorios producen
INVALID_ASSESSMENT. No se corrigen automáticamente ni se compensan bajando el score.
No hay reintento por discrepancia semántica. Un timeout V2 es resultado incierto:
se registra y exige revisión antes de otra inferencia.

## Confianza candidata

`EVIDENCE_CONFIDENCE_V2 = 100 × (0.55 × S + 0.45 × K)`.
S = strength / 4. Cálculo Decimal, precisión 50, ROUND_HALF_UP a dos decimales.
Los pesos están fijados en código versionado y fingerprint. Todos los assessments
válidos reciben puntuación; un NOT_SUPPORTED válido recibe 0. Un inválido recibe NULL.
`confidence_probability` y `confidence_level` siguen NULL.

El score significa **grado de respaldo de evidencia**. No es probabilidad estadística
calibrada, exactitud ni criterio automático de reclasificación. F y C solo permanecen
como diagnósticos para la comparación V1; no afectan V2. La rúbrica también depende
de juicios de la LLM: la determinación matemática no convierte esos juicios en hechos.

## Comparación con V1

Sobre cada assessment V2 válido se proyectan las mismas citas, strength y los nombres
de los criterios CLEAR al contrato histórico. Se calcula RAW_CONFIDENCE_V1 mediante
su función intacta. Es una comparación de fórmulas sobre **el mismo juicio V2**,
no una respuesta histórica V1 reutilizada ni una prueba de superioridad semántica.
V1 es NOT_APPLICABLE para insuficientes y no soportados; su diferencia numérica queda
NULL y nunca se imputa un cero. Los valores PARTIAL pesan 0,5 en K de V2 y no se
declaran como elementos plenamente respaldados en la proyección binaria de V1.

Caso de control: strength 4, K=1, una sección sustantiva: V1=94 y V2=100.
Dos secciones con el mismo soporte: V1=100 y V2=100. Strength 3 y K=1: V2=86,25.
Strength 2, un PARTIAL de dos criterios: K=0,25 y V2=38,75. Sin soporte: 0.
Son controles sintéticos, no evidencia de mejora en los datos institucionales.

Schemas: `schemas/layer4_assessment_v2/`. API: `assessment_v2.validate`,
`confidence`, `indicator_row`, `validate_wrapper`, `write_contracts(check=True)`.
El schema de transporte respeta el subconjunto nativo de salida estructurada:
no envía uniqueItems, rechazado por la API. El schema normativo de assessment
y Python sí comprueban unicidad de índices; una duplicación invalida la
evaluación, sin usar reintentos de proveedor para repararla.
Procedimiento y bloqueos: [cierre V2](../methodology/layer4_closure_v2.md).
