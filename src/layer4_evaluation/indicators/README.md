# Indicadores — componentes históricos

Para la campaña BASE actual con Qwen/Ollama, GraphRAG y S/K, consultar la
[guía principal](../../../README.md#flujo-base-y-ejecución-manual) y el
[mapa de módulos actuales](../README.md). Lo siguiente documenta estudios
V1/V2 y preliminares conservados, no el procedimiento vigente de la campaña.

El cierre candidato V2 extiende `experiment.py` y el mismo `codex_cli.py`.
`assessment_v2.py` define contratos, rúbrica, validación y fórmula V2;
`performance.py` mide recursos locales y `performance_report.py` informa
observaciones, ausencias y proyecciones. `closure_audit.py` verifica el diagnóstico
histórico y `closure_export.py` prepara revisión/comparaciones y la publicación
oficial con aceptación humana. No son proveedores ni pipelines alternativos.
V1 y sus resultados se preservan. Véase el [procedimiento de cierre](../../../docs/methodology/layer4_closure_v2.md).

## Procedimiento histórico de cierre

Usar `scripts/run_layer4_closure.py --settings config/layer4_closure_definitive.yaml`.
El cierre mantiene dos candidatos y fallback desactivado; su implementación y
plan experimental permanecen conservados y configurables. La extensión
`semantic_fallback.py` añade una ronda configurable con el mismo adaptador;
`closure_runtime.py` conserva los hashes y valida por separado opiniones humanas.
`final_projection.py` y `final_export.py` son la proyección oficial del cierre histórico
de siete columnas de indicadores y cuatro territoriales. `cleanup.py` registra
inventario, dry-run y recuperación antes de retirar temporales demostrados.

Las rutas de 20/50 proyectos descritas abajo son componentes e históricos
reutilizados, no procedimientos alternativos de publicación. La preparación
original sigue en su ruta por sus fingerprints; los estudios nuevos se controlan
desde `outputs/layer4/pruebas/`, sin duplicar las respuestas originales.

## Propósito

Prepara perfiles y contratos, valida assessments y calcula confianza determinística. Incluye un runner técnico provisional ligado a snapshots históricos; la evaluación final y calibración siguen pendientes.

## Archivos principales

| Archivo | Responsabilidad |
|---|---|
| [profiles.py](profiles.py) | Proyecta el catálogo v2 a perfiles versionados, conserva originales y separa reglas RULE_TEXT de lógica implementada. |
| [contracts.py](contracts.py) | Autoridad de schemas de perfil/assessment/exportación y envoltorios del preliminar; comprueba o exporta JSON. |
| [assessment.py](assessment.py) | Define AssessmentProvider, valida respuestas y citas y construye PROJECT_INDICATOR con confianza calculada. |
| [confidence.py](confidence.py) | Carga/valida YAML y calcula K/F/C/S con Decimal y ROUND_HALF_UP; ignora retrieval y mantiene probability/level NULL. |
| [preparation.py](preparation.py) | Verifica referencias congeladas y escribe metadata de preparación sin selección ni assessment. |
| [selection.py](selection.py) | Selecciona determinísticamente PROJECT/candidatos del snapshot fijado, con máximo dos indicadores por proyecto. |
| [prompt.py](prompt.py) | Construye instrucciones e inputs por campos y perfiles; no transmite scores de retrieval o confianza. |
| [codex_cli.py](codex_cli.py) | Adaptador provisional de transporte Codex CLI con subprocess aislado, schema y un retry técnico; no decide la confianza. |
| [preliminary.py](preliminary.py) | Coordina prepare/execute/finalize/verify, fija snapshot/catálogo y preserva auditoría y fingerprints. |
| [preliminary_output.py](preliminary_output.py) | Valida filas/diagnósticos, métricas y workbook de cuatro hojas del preliminar. |
| [export.py](export.py) | Valida y exporta datos reutilizables de cuatro hojas sin seleccionar proyectos ni invocar proveedores; fallback openpyxl. |
| [powerbi.py](powerbi.py) | Proyecta IDs institucionales, citas y scores ya calculados; añade territorios al workbook sin reevaluarlos. |
| [__init__.py](__init__.py) | Declara el namespace 4A. |

## Funcionamiento

Perfiles → campos/candidatos → prompt → AssessmentProvider → validación literal → confidence → filas → exportación. La preparación solo valida entradas/metadata. El runner preliminar habilita etapas distintas mediante CLI, y --execute invoca al proveedor.

## Entradas y salidas

Recibe PROJECT por seis campos, candidatos SOURCE_INDICATOR_V1 y catálogo enriquecido. Escribe referencias procesadas, preparación o outputs/layer4/auditoria/historicos/preliminar_20; las proyecciones de consumo usan outputs/layer4/auditoria/historicos/powerbi_preliminar_20.

## Relación con otras capas

No modifica Capa 3 ni sustituye su catálogo congelado. Puede incorporar la bridge territorial resuelta a resultados de los proyectos seleccionados. RULE_TEXT y preferencias UNMAPPED no son reglas semánticas implementadas.

## Ejecución

La ruta histórica de 50 proyectos está en `experiment.py`, con selección diversa
en `experiment_selection.py`, lectura verificada en `experiment_inputs.py`,
revisión/métricas en `review.py` y exportación reusable en `experiment_export.py`.
Usa exclusivamente el adaptador `codex_cli.py`. Configuración:
`config/layer4_experiment.yaml`. Entrypoint: `scripts/run_layer4_experiment.py`.
Las etapas prepare/verify/report/export son determinísticas y no infieren;
execute-batch separa piloto y continuación autorizada. Las rutas y los resultados
del preliminar de 20 se conservan como históricos.

Véase [metodología, autorización y reproducción](../../../docs/methodology/layer4a_codex_50.md).

Véase [guía operativa actual](../../../README.md#flujo-base-y-ejecución-manual). El YAML conserva ejecución de preparación deshabilitada, pero el runner provisional tiene un --execute explícito independiente. Requiere autorización, CLI compatible y snapshots exactos; nunca es parte de una verificación documental.
