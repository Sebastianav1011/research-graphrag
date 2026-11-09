# Aceptación de Capa 3 SOURCE-LEVEL

Estado: **FINAL_PROJECT_LAYER_3_SOURCE_LEVEL_READY**.

Capa 3 encuentra **dónde vale la pena buscar evidencia**. Su arquitectura final
es SOURCE_INDICATOR_V1, pipeline 3.2.0: retrieval vector/graph/hybrid sobre
source_chunks, entidades PROJECT/ARTICLE y candidatos SOURCE+INDICATOR.
Los contextos referencian todas las secciones disponibles de cada fuente.

Publicación activa: layer3_2026-10-14T094639_959121+0000_eca9000e.

- 2.400 candidatos, 464 contextos y 48 indicadores.
- 1.993 ASSESSMENT_READY y 407 DISCOVERY_ONLY; expresan disponibilidad de contexto.
- 45.362 embeddings SOURCE y 133 REFERENCE reutilizados; 0 computados.
- Grafo: 33.915 nodos, 24.821 edges factuales y bridges resolved_only.
- Quality y privacidad PASS; provenance 100%.

Dos builds con código, configuración y Capa 2 idénticos pasaron idempotencia
13/13 y verify. El JUnit final registra Capa 1: 70 PASS; Capa 2: 63 PASS;
Capa 3: 219 PASS, incluidos 191 unitarios y 28 de integración real, sin fallos,
errores o skips. Las pruebas ligeras post-cleanup pasaron 70/51/191.
Contratos, upstream y repository cleanup pasaron; el inventario está vigente.
No quedan one-off, obsolete, duplicados innecesarios, unreferenced o unknown.
El RUNBOOK pasó validación estática local; la validación desde clon permanece
PENDING_UNTIL_GIT_REMOTE y no bloquea esta aceptación.

## Frontera metodológica

- discovery_chunk != evidence
- retrieval_score != confidence
- candidate_source != indicator_match

| Fuente | Orientación | Contexto sustantivo |
|---|---|---|
| PROJECT | title, keywords | summary, methodology, objectives, expected_results |
| ARTICLE | title, keywords | abstract |

La unidad futura de assessment también es SOURCE+INDICATOR. Capa 4 decidirá
**si esa fuente realmente soporta un indicador**. Capa 3 produce cero decisiones
de indicadores, no selecciona LLM ni implementa confidence. Los perfiles siguen
[PENDING_GROUP_REVIEW](../pending/indicator_profiles.md); no se han definido
criterios operacionales. Capa 4 no está finalizada.

El registro formal privado es outputs/layer3/reports/source_level_final_acceptance.json.
final_acceptance.json corresponde al diseño histórico 3.1.0. La
[arquitectura vigente](layer3.md) conserva el detalle del funcionamiento.
