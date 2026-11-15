# Evaluación prospectiva V2

Implementación basada en la [revisión del run de referencia](../outputs/runs/local/run_20261115_063255_909981/revision_tecnica_run_20261115_063255_909981.md). No se ejecutaron inferencias ni se modificaron los resultados históricos, los indicadores VRI, BASE, Knowledge, GraphRAG o embeddings. Los cinco archivos de resultados del run coinciden byte a byte con su copia histórica independiente.

## Modalidad y rúbricas

Los runs nuevos usan `--evaluation-mode prospective-v2` o `--evaluation-mode PROSPECTIVE_V2`. El alias `prospective` y el valor predeterminado para nuevos runs BASE seleccionan V2. `prospective-v1`/`PROSPECTIVE_V1` conserva V1. Reanudar sin especificar modalidad conserva la política sellada; no migra resultados. Para comparar se necesita un run nuevo: no editar planes, hashes ni respuestas anteriores. Los controles de código congelado de los runs históricos siguen vigentes.

El nuevo contrato `ASSESSMENT_PROSPECTIVE_V2` reutiliza la evaluación V3/SK. Conserva criterios, roles, grupos, conjunciones y citas; reemplaza exclusivamente su interpretación temporal y los argumentos operativos contradictorios. Las definiciones oficiales permanecen en los perfiles sellados. Los ejemplos de evidencia favorable/insuficiente de modalidad demostrada no se envían como instrucciones prospectivas.

Acciones, métodos, productos, mecanismos y resultados esperados concretos pueden respaldar criterios. Una intención genérica, antecedente o población mencionada no prueba una contribución. Cada juicio distingue `PROJECT_CONTRIBUTION`, `CONTEXT_IDENTIFICATION`, `UNRELATED` y `NO_SUPPORT`. El validador bloquea apoyo sustantivo declarado como contextual/ajeno, y citas exclusivamente `CONTEXT` para criterios sustantivos. Una declaración semántica incorrecta del modelo todavía requiere revisión humana.

La [matriz de los 48 indicadores](prospective_v2_catalogo.md) documenta las interpretaciones y límites. Ejecución, adopción, entrega y cambios se evalúan como acciones o resultados previstos fundamentados, sin afirmarlos como realizados. **DIV-03 y POL-02** tienen un límite: una expectativa no acredita menciones independientes o citas oficiales. Una propuesta sola queda insuficiente, no no-aplicable. Si hay registros externos observados con citas verificables, pueden satisfacer esas condiciones sin ser rechazados por ser observaciones; sus etapas se conservan como tales. Esta delimitación es una propuesta metodológica pendiente de validación humana.

`catalog_derivation` registra la rúbrica de origen, la efectiva, hashes, interpretación y limitaciones. `evidence_stages` diferencia propuestas, expectativas, ejecución y resultados observados; el resultado añade `evaluation_meaning=PLANNED_CONTRIBUTION_NOT_OBSERVED_IMPACT`. El rótulo SUPPORTED no equivale a impacto institucional demostrado.

## Estados, aplicabilidad y confianza

| Decisión | Condición | Confianza |
|---|---|---|
| `SUPPORTED` | Aplicabilidad respaldada; todos los REQUIRED y una alternativa por grupo CLEAR, citas sustantivas compatibles y fuerza 3/4. | Cálculo SK existente. |
| `INSUFFICIENT_EVIDENCE` | Respaldo parcial/ausente o aplicabilidad aún indeterminada; no basta una intención general. | Se conserva el cálculo, incluido cero cuando corresponde; no mide cercanía al cumplimiento. |
| `NOT_APPLICABLE` | Exclusión explícita o alcance documental incompatible, explicación y citas sustantivas verificables. El silencio documental no sirve. | JSON `null`, CSV vacío, Excel `N/A`; nunca cero de cumplimiento. |

La aplicabilidad se registra aparte (`APPLICABLE`, `UNDETERMINED`, `NOT_APPLICABLE`) con fundamento, explicación e índices de evidencia. Si no puede establecerse, se conserva incertidumbre en vez de inventar no aplicabilidad. El denominador `support_denominator` incluye solo aplicabilidad confirmada; no-aplicables, indeterminados y fallos técnicos se cuentan aparte. No se asigna un porcentaje cuando no hay denominador.

**La fórmula permanece exactamente `C = 100 × (0,55 S + 0,45 K)`**, con las mismas dimensiones, media esencial de K, grupos alternativos, aritmética Decimal y redondeo SK. V2 llama al cálculo existente; no introduce otro cálculo ni umbrales. Los placeholders de cobertura/fuerza cero de NOT_APPLICABLE no se convierten en puntuaciones S/K. La confianza documental no decide SUPPORTED. V2 también rechaza una decisión insuficiente incompatible con todos los juicios esenciales CLEAR, salvo el límite documentado de registros externos.

Errores de transporte, esquema, citas, coherencia o contexto siguen siendo técnicos, con confianza nula. `estado_indicadores.json` diferencia `EVALUATED`, `TECHNICALLY_BLOCKED` y `PENDING`, conserva el estado técnico, número de llamadas, último error y aplicabilidad. Un proyecto procesado con bloqueos se presenta como `BLOQUEADO`, no como trabajo aún sin visitar.

## Reintentos y consumidores

`PROSPECTIVE_V2_COMPACT_CORRECTION_V1` reconstruye cada corrección desde la evidencia original, sin añadir respuestas o narrativas previas. Conserva el payload, esquema, presupuesto y validaciones; puede volver a juzgar un criterio inválido sin un veto artificial a aumentar su soporte. Si la corrección no cabe, no se envía: se conserva el error de evaluación inválida real. No hay reparación automática de decisiones ni aceptación de respuestas inválidas.

La salida V2 utiliza **`THESIS_PROSPECTIVE_ASSESSMENTS_V3`**, con las mismas siete columnas y hojas del consumidor actual, tres decisiones y confianza nullable. La justificación de no aplicabilidad se exporta con sus citas y ubicaciones originales. JSON/CSV usan valores tipados nulos; Excel muestra N/A. Los contratos históricos conservan sus estructuras y no aceptan silenciosamente NOT_APPLICABLE. Consumidores que enumeren estados deben optar por el nuevo contrato; consumidores numéricos deben tratar el vacío CSV como null y excluir N/A de promedios. No se exportan errores como decisiones semánticas.

## Archivos y validación

- `indicators/prospective_v2.py`: interpretaciones, límites, aplicabilidad y controles semánticos adicionales.
- `assessment_v3.py`, `context_budget.py`, `evidence_references.py`: modalidad, contrato, prompts, referencias y reutilización exacta de confianza.
- `ollama_provider.py`, `live_execution.py`, `performance.py`: corrección acotada, trazabilidad, estadísticas y estados técnicos.
- `scripts/pipeline_coordinator.py`, `run.py`, `thesis_output.py`: preparación, selección de modalidad y exportación versionada.
- `schemas/layer4_prospective_v2/` y `schemas/thesis_prospective_assessments.v3.schema.json`: contratos nuevos; los anteriores no se reescriben.
- `tests/test_prospective_v2.py` y ajustes acotados de `tests/test_context_budget.py`: pruebas sin servidor, con datos simulados y lectura de artefactos.

Las pruebas nuevas cubren respaldo concreto, intención vaga, no aplicabilidad documentada, citas inventadas/contextuales/ajenas, fórmula exacta, coherencia final, JSON/CSV/Excel, corrección simulada válida y corrección que no cabe. También reproducen las tres confianzas V1 del run sin migración, verifican las 48 rúbricas y comprueban presupuestos de sus tres contextos almacenados con el tokenizer local, sin nueva recuperación.

Resultado final: **288 pruebas aprobadas y 36 casos deseleccionados** en la regresión acotada de siete archivos; **una prueba adicional aprobada** del exportador principal confirma NOT_APPLICABLE, confianza nula, conteos, trazabilidad y separación del bloqueo técnico. El archivo nuevo contiene 40 casos. `git diff --check` no detectó errores de formato.

Se identificaron **27 fallos heredados** de pruebas de exportación/recuperación y cobertura K. Se reprodujeron los mismos 27 con las implementaciones HEAD cargadas solo en memoria: no son regresiones de V2. Las expectativas obsoletas no se usaron para modificar la fórmula o los contratos vigentes. La regresión final excluyó cinco funciones: `test_all_contract_preserves_scores_decisions_and_evidence`, `test_technical_states_have_null_confidence_and_no_fabricated_evidence`, `test_real_persisted_run_is_unambiguous_without_scoring`, `test_persisted_loader_stops_on_ambiguous_or_changed_records` y `test_criterion_first_response_preserves_context_without_claiming_impact`. Sus parametrizaciones suman los 27 fallos previos y nueve casos adicionales; las pruebas originales permanecen intactas.

**Pendiente de revisión humana:** pertinencia de las 48 adaptaciones, límites de registros externos, adopción/valoración de terceros y metas cuantitativas; suficiencia real de mecanismos, destinatarios y justificaciones de no aplicabilidad. No se ha medido el comportamiento de Qwen con estos prompts ni su tasa de errores o resultados positivos: esa validación requiere una futura campaña autorizada.
