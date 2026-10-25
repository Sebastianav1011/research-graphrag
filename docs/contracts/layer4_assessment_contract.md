# Assessment PROJECT + INDICATOR v1

Contrato histórico preservado. La versión candidata de cierre se define en
[ASSESSMENT_V2](layer4_assessment_v2_contract.md); su aprobación real está pendiente.

Unidad: **PROJECT + INDICATOR**. La preparación y el preliminar se limitan a
PROJECT. ARTICLE queda fuera de esta fase. El histórico conserva 31 assessments
de 20 proyectos; la ejecución vigente se rige por el experimento de 50 proyectos.

## Input y frontera de versiones

El futuro proveedor recibe un perfil operacional derivado del catálogo v2,
las reglas generales preservadas como texto y el PROJECT completo por campos:
title, keywords, summary, methodology, objectives y expected_results.
Se conservan los campos separados, los NULL y su procedencia. No se utilizan
únicamente los discovery chunks como si fueran el contexto completo.

Capa 3 aportará candidatos históricos SOURCE_INDICATOR_V1, generados con la
referencia anterior de indicadores de R8, ligada al snapshot L2
`run_20261005T204120_837354Z`. Capa 4 evalúa esos mismos IDs con
`catalogo_indicadores_v2.xlsx`. `retrieval_indicator_version` y
`assessment_indicator_version` son distintos y se registran por separado.
La preparación comprobó cobertura de los 48 IDs históricos sin seleccionar
ningún PROJECT. No se actualizaron queries, ranking, embeddings ni manifests
de Capa 3. Decidir una futura versión enriquecida de retrieval queda para después
del preliminar.

## Respuesta del proveedor

Objeto cerrado definido por `schemas/layer4_assessment/assessment.schema.json`:
decision, support_strength, supported_key_elements, evidence y explanation.
Cada evidence contiene exclusivamente field y text. La explicación debe ser
texto no vacío. El proveedor no devuelve confidence, probabilidades, niveles
de confianza, retrieval scores ni otros campos ajenos al contrato.

| decision | Definición | support_strength |
|---|---|---|
| SUPPORTED | Existe evidencia sustantiva suficiente para afirmar soporte según la definición enriquecida. | entero 3 o 4 |
| INSUFFICIENT_EVIDENCE | Hay relación parcial, temática o indicios relevantes, pero la evidencia no basta para afirmar cumplimiento. | entero 1 o 2 |
| NOT_SUPPORTED | La información disponible no aporta evidencia suficiente que soporte el indicador. | entero 0 |

NOT_SUPPORTED **no requiere contradicción explícita**. Expresa falta de soporte
en la información disponible, no demuestra incumplimiento real ni ausencia de
impacto. Esto preserva la distinción de RG-07 entre falta de información y
evidencia negativa. No se inventa una rúbrica institucional para los ordinales.

## Gates implementados

Toda respuesta se valida antes del cálculo. Los únicos evidence.field permitidos
son los seis campos PROJECT del input. Deben existir realmente en el proyecto
y contener evidence.text. Solo se admite Unicode NFC, colapso conservador de
whitespace y eliminación de whitespace exterior. Se preservan caso, acentos y
puntuación. La comprobación es substring literal tras esa normalización.
No hay fuzzy matching, embeddings, similitud semántica ni corrección automática.

- Cualquier cita inexistente invalida el assessment completo, también en
  INSUFFICIENT_EVIDENCE o NOT_SUPPORTED: INVALID_ASSESSMENT y score NULL.
- Strength debe ser entero, nunca bool/float/string, consistente con decision.
- SUPPORTED exige evidencia y al menos un campo sustantivo: summary,
  methodology, objectives o expected_results. Title/keywords solos no bastan.
- supported_key_elements deben pertenecer al perfil mediante igualdad NFC y
  whitespace conservador. Con catálogo disponible, SUPPORTED exige al menos uno.
- Si falta key_elements se difiere únicamente su pertenencia/cobertura; todos
  los otros gates continúan. Un SUPPORTED válido será NOT_COMPUTABLE.

Estos gates comprueban estructura, fidelidad de citas y pertenencia. No prueban
semánticamente que una cita soporte cada elemento, ni implementan por sí solos
las doce guías RULE_TEXT del catálogo. La interpretación futura pertenece al
proveedor y queda expuesta en explanation y supported_key_elements.

`validate_structured_assessment` aplica schema cerrado y los gates existentes
de confidence. `build_indicator_row` nunca invoca un proveedor: transforma una
respuesta válida y calcula su confidence. Respuestas inválidas permanecen en
diagnósticos técnicos; el generador rechaza su publicación como filas válidas.

## Confidence formal

Se integra sin modificar el paquete del worktree ni sus nueve archivos.
Contrato normativo: [RAW_CONFIDENCE_V1](layer4_confidence_contract.md).

`confidence_raw_score = 100 × (0.35K + 0.30F + 0.20C + 0.15S)`.

K es cobertura de elementos únicos; F es máxima relevancia de campos citados;
C es corroboración por campos sustantivos distintos; S es strength/4.
Solo SUPPORTED válido y con elementos disponibles produce score. Para
INSUFFICIENT_EVIDENCE/NOT_SUPPORTED es NOT_APPLICABLE; sin elementos es
NOT_COMPUTABLE; ante errores es INVALID_ASSESSMENT. En los tres casos el score
es NULL. Probability y level siempre son NULL. Retrieval queda totalmente fuera.
Ejemplo contractual K=.75, F=1, C=1, S=.75: **87.50**.

## Protocolo e implementación vigente

`AssessmentProvider.evaluate(project, indicators)` devuelve una secuencia de
pares indicator_id + assessment estructurado. Es un Protocol que separa
preparación, transporte y validación. Su implementación operativa es exclusivamente
`CodexCliAssessmentProvider` en `src/layer4/indicators/codex_cli.py`. No se incorporan
otros motores ni APIs de inferencia. Codex CLI ejecuta el modelo LLM configurado;
Python valida y calcula. El agente que desarrolla el repositorio no reemplaza las
inferencias del sistema. Véase [implementación y reproducción de 50 proyectos](../methodology/layer4a_codex_50.md).
