# Contexto técnico — Tesis GraphRAG

Fecha de transferencia: 14 de noviembre de 2026. Este documento describe el código del checkpoint de `dev` y los artefactos locales inspeccionados; no constituye una validación académica de los resultados. No ejecutar modelos, reconstrucciones ni limpiezas automáticamente al retomar el trabajo.

## 1. Objetivo de la tesis

**Analítica de datos para la caracterización de la investigación y la identificación de su impacto regional.**

El sistema analiza proyectos de investigación y producción académica de la Pontificia Universidad Javeriana para identificar su relación con indicadores institucionales de impacto. Los resultados documentales se utilizarán para análisis y visualización en Power BI. Una contribución prevista respaldada no equivale a un impacto regional ya ocurrido ni a una probabilidad estadística de éxito.

## 2. Arquitectura actual

| Componente real | Responsabilidad y puntos de entrada |
|---|---|
| `run.py` | Menú principal, parser CLI, selección BASE/INCOMING, IDs, conocimiento y proveedor; `dispatch_pipeline`, `menu`, `confirm_action`. |
| `scripts/pipeline_coordinator.py` | `execute_pipeline` encadena preprocessing → knowledge → graphrag → evaluation → export; `selected_configuration`, `prepare_evaluation`, `verify_sources`, `scope_projects`, `export`. |
| `src/layer2_processing/pipeline.py` | `prepare`, `knowledge`, `check`, `seal`, `restore_lineage`, `reuse_global_base`; workspace privado y checkpoints verificables por run. |
| `src/layer2_processing/preprocessing/` | `adapters.prepare_files`/`discover_sources`, lectura y mapeos; `ingestion`, `normalize`, `identity.resolve`, `canonicalize`: entidades canónicas y relaciones explícitas. |
| `src/layer2_processing/knowledge/` | `pipeline.run`, `documents`, `chunking`, `graph_data`, `validate_inputs`: documentos, secciones, fragmentos y tablas del grafo a partir del canónico. |
| `src/layer3_graphrag/` | `pipeline.run`/`load_artifacts`, `embeddings`, `vector_index`, `graph`, `graph_retriever`, `indicator_retrieval`, `manifest`: BGE-M3, índices y publicación verificable. |
| `src/layer4_evaluation/indicators/scoped_retrieval.py` | `from_published_cache`, `rank_project_passages`, `project_relations`: recuperación por PROJECT+INDICATOR utilizando publicación e índices globales existentes. |
| `context_budget.py`, `evidence_references.py`, `ollama_provider.py` en el mismo directorio | Empaquetado presupuestado; IDs de fragmentos; materialización literal de citas; solicitud a Ollama y controles de transporte. |
| `src/layer4_evaluation/live_execution.py` | Planes/lotes, ejecución por indicador, recibos, reintentos, validación y recuperación de evaluaciones persistidas. |
| `assessment_v3.py`, `thesis_output.py`, `indicator_csv.py` | Juicios por criterio, confianza determinista, proyección Excel y CSV, territorios derivados solo de evidencias verificadas. |

La numeración histórica de configuración difiere de los nombres de carpetas: `config/layer1.yaml` configura preprocessing, `layer2.yaml` configura Knowledge y `layer3.yaml` configura GraphRAG. No crear otro pipeline para corregir la recuperación. `src/autonomous_execution/` contiene además el flujo avanzado histórico `prepare/start --autonomous`; no asumir que todas sus rutas tienen exactamente la política del menú principal.

Configuración principal: `config/pipeline_manual.json`. Runtime Python y dependencias: `pyproject.toml` y `uv.lock` (Python 3.14). El proveedor principal es Ollama, modelo `qwen3.5:4b-q4_K_M`. Existen rutas alternativas de proveedor, pero no son el objetivo de la tesis actual.

## 3. Datos de entrada

Fuentes privadas reales en `data/layer1_sources/base/`:

* `descriptores-limpio.csv`: proyectos identificados por `id_actividad`; resumen, metodología, objetivos, resultados previstos y demás campos autorizados se aprovechan individualmente. `justificacion` y `actividades_formacion` se conservan como campos adicionales autorizados cuando existen. No se rellenan vacíos.
* `miembros-doc-limpio.csv`: cada fila representa al miembro descrito por sus propios `id_empleado`, `documento` y `nombre_completo`; `id_actividad` expresa su participación. Rol y responsable son atributos de esa relación.
* `produccion-limpio.csv`: publicaciones con `eid`, `doi` o identificador de publicación explícito admitido; autor individual en `cedula` e `investigador_docente`. ISSN/ISBN identifica una revista/libro y no sirve para fusionar publicaciones.

El cuarto archivo que suele contar la consola es el catálogo de referencia, no otro CSV BASE: `data/layer1_sources/reference/indicadores/catalogo_indicadores_v2.xlsx`, hoja `Indicadores_enriquecidos`. Se emplean 48 indicadores y rúbricas institucionales congeladas V3.3. `evaluation_settings` verifica además `outputs/layer4/pruebas/validacion_v3_3/cierre_homogeneo_v3_3/closure.plan.json`, `closure.manifest.json` y recursos no ejecutables referenciados allí. Son requisitos locales privados: el clon Git por sí solo no contiene todo lo necesario para evaluar.

Mapeos institucionales: `config/sources.example.yaml` y `adapters.source_registry`. En BASE global, `id_investigador` se excluye como alias no verificado de `id_empleado`; `nombre_investigador` del principal no sustituye a `nombre_completo` del miembro. No hay correspondencia automática entre espacios de identificadores.

`identity.resolve` comparte nodo mediante coincidencia exacta de identificadores del mismo espacio, si el componente completo no contiene contradicciones. Institucional y documento personal son espacios separados. El resolver genérico también admite ID externo o nombre+email exactos; nombres solos no unen personas. Identidades insuficientes o contradictorias se conservan por ocurrencia como `unresolved`/`ambiguous`; el recuperador prohíbe usarlas como puentes.

Relaciones nativas admitidas: `PROJECT_HAS_RESEARCHER` y `ARTICLE_HAS_RESEARCHER`. Los IDs canónicos incluyen `PROJ_21844`, `RES_…` y publicaciones derivadas de ID explícito/EID/DOI. Compartir investigador permite un camino indirecto proyecto → investigador ← artículo u otro proyecto; **no declara que ese artículo sea producto del proyecto, ni colaboración, ni transferencia de resultados**. Organizaciones e indicadores también pueden tener nodos; no existen aristas nuevas inventadas para conectarlos.

`adapters.base_valid_rows` aísla filas BASE sin identidad verificable y registra archivo, fila y motivo. Un proyecto con ID puede carecer de texto. Un artículo sin título puede conservarse con identidad admitida; el título permanece NULL. Se mantienen deduplicación, cuarentena de conflictos y procedencia de ocurrencias. Archivos ilegibles, esquemas indispensables ausentes o cero registros utilizables siguen bloqueando. INCOMING conserva sus contratos independientes.

Último `verify --source base` realizado durante las correcciones (no se repitió para esta transferencia): 2.232 descriptores válidos/1 excluido, 12.026 miembros válidos/0 excluidos, 11.373 filas de producción válidas/1.955 excluidas por identidad no verificable. Son conteos de filas de entrada, no cantidades de entidades canónicas tras deduplicar.

## 4. Construcción del conocimiento

Para BASE, `selected_configuration` marca `knowledge_scope=BASE_GLOBAL_V1` y `source_scope.plan_scope` no reduce la ingesta por los IDs evaluados. La selección limita Evaluation/Excel; el conocimiento incluye todas las fuentes BASE válidas.

`prepare_files` crea adaptadores de trabajo, nunca modifica los CSV originales. `restore_lineage` restaura localizadores y valores originales antes de Knowledge, conservando narrativas distintas como ocurrencias separadas. Se guardan `preprocess/diagnostics.json`, `lineage.json`, `review.json` y, cuando aplica, `selection_manifest.json`.

El canónico produce `workspace/outputs/layer2/canonical/{proyectos,articulos,investigadores,organizaciones,indicadores,proyecto_investigador,articulo_investigador}.parquet` y `_manifest.json`. Knowledge produce ocho tablas en `workspace/outputs/layer2/knowledge/`: `source_documents`, `source_sections`, `source_chunks`, `reference_documents`, `reference_sections`, `reference_chunks`, `entities`, `relations`, además del manifiesto. Los documentos/secciones conservan originales; los fragmentos tienen texto normalizado, IDs, hashes, campo, coordenadas y `provenance_json`.

`knowledge.chunking.spans/build_chunks` usa ventanas jerárquicas de palabras: objetivo 220, máximo 340, solapamiento 20 según `config/layer2.yaml`; las fronteras favorecen párrafos y oraciones. Las coordenadas de fragmentación son del texto normalizado. `context_budget.original_chunk` verifica y traduce a intervalos literales originales antes de citar.

GraphRAG usa BGE-M3 fijado a revisión local, dimensión 1024, normalización de vectores, CUDA/float16 y backend `numpy_exact` (`config/layer3.yaml`). `embeddings.SentenceTransformersProvider` carga el modelo perezosamente; generar embeddings es una etapa costosa. Se separan espacios SOURCE y REFERENCE y codificación documental/consulta. No sustituir pesos ni revisiones sin invalidar la compatibilidad.

Publicación: `workspace/outputs/layer3/publication/`, con `graph/graph.json`, `indexes/source`, `indexes/reference`, bundles, resultados de recuperación global y `_manifest.json`. Las cachés están en `workspace/outputs/layer3/cache` y `query_cache`. Los manifiestos comprueban hashes, snapshot aprobado, configuración y proveedor; las publicaciones de capas conservan mecanismos de validación y reemplazo seguro existentes.

Menú BASE: después de los IDs permite **reutilizar** (predeterminado) o **reconstruir**. Desde la estabilización del 14/11/2026 la reutilización consulta un **registro de conocimiento compartido** (sección 4.1), no las ejecuciones históricas, y **no copia** artefactos al run. No copia evaluaciones.

Si no existe versión compatible e íntegra, devuelve `KNOWLEDGE_REBUILD_REQUIRED` con el motivo y ofrece reconstruir antes de etapas costosas. Reconstruir usa todas las fuentes válidas en un run nuevo, sin borrar la versión anterior. Resume conserva los artefactos, la configuración y la referencia de conocimiento originales; no vuelve a buscar otro conocimiento. Verificaciones estrictas de código/datos pueden rechazar un checkpoint antiguo: no desactivarlas ni reescribir sus fingerprints para forzar resume.

### 4.1 Conocimiento BASE compartido (implementado)

Módulo `src/knowledge_store.py`. Solo añade JSON pequeños bajo `outputs/shared/base/`:

```text
outputs/shared/base/
  active.json                      puntero atómico: version_id + sha256 del manifiesto
  activations.jsonl                historial de activaciones (append-only)
  versions/<version_id>/manifest.json
```

* **Versión** = checkpoint sellado `PREPARED` con GraphRAG publicado, con la disposición de run existente (`manifiestos/run.json`, `preprocess/`, `workspace/config`, `workspace/outputs/layer2/{canonical,knowledge}`, `workspace/outputs/layer3/{publication,query_cache,cache}`). El manifiesto registra `location` (ruta del checkpoint), `identity`, `fingerprint` y digests por componente: preprocessing (manifiesto canónico y `prepared_hashes`), knowledge (manifiesto), embeddings (config hash, modelo, revisión, conteos SOURCE/REFERENCE), índices vectoriales, grafo (nodos/aristas), publicación (sha del `_manifest.json`) y `query_cache` (digest de todos sus archivos).
* **Fingerprint** = sha256 de `identity`: dataset, ruta RAW, hash de cada archivo RAW, sha del catálogo, alcance `BASE_GLOBAL_V1`, configuración de datos (configuración sin `llm`, `evaluation`, `evaluation_policy`, `project_selection`, `processing_scope`, `runs_base`, `base_knowledge_action`, `base_knowledge_source`) y hashes del código/configuración que construyen conocimiento (`src/layer2_processing/preprocessing/`, `src/layer2_processing/knowledge/`, `src/layer3_graphrag/`, `config/`). Cambiar prompt, política de confianza, contrato de exportación o proyecto seleccionado **no** invalida el conocimiento; cambiar datos, catálogo, tokenización documental, modelo de embeddings o construcción del grafo sí.
* **Reutilizar**: `reuse_global_base` → `knowledge_store.compatible` toma la versión activa (o la fijada en `base_knowledge_source='shared:<id>'`), compara dataset/RAW/catálogo/configuración de datos y verifica integridad: `check(..., knowledge_only=True)` del checkpoint (RAW, código de conocimiento y todos los archivos sellados), digests de componentes, `validate_publication` y la carga profunda de vectores/índices/grafo (`load_artifacts`, proveedor perezoso: sin modelo ni embeddings). Si todo es correcto, el run nuevo guarda solo `run.json` con `storage_layout=SHARED_KNOWLEDGE_REFERENCE_V1` y `knowledge_ref` (version_id, sha del manifiesto, fingerprint, ubicación, sha de Knowledge y de la publicación), un `raw_manifest.json` propio y `prepared_hashes.json`. No se crea `workspace/` en el run.
* **Lectura**: `knowledge_workspace(run)` devuelve el workspace de la versión referenciada (o `run/workspace` en runs antiguos) y `evaluation_dir(run)` devuelve `run/layer5_results`, `run/evaluation` (runs nuevos) o `run/workspace/outputs/layer4` (runs antiguos). Los usan coordinador, selección, exportación y `thesis_output`.
* **Verificación continua**: `check(root, run)` de un run con `knowledge_ref` verifica además el pin exacto de la versión y su checkpoint sellado; si los artefactos compartidos cambian, el run falla en lugar de leer otro conocimiento. Activar después otra versión **no** cambia la referencia de runs anteriores.
* **Reconstruir**: se construye en el run nuevo (ubicación nueva, sin tocar la versión activa). Solo después de `graph(build=True)` y `validated_graph` se registra **en el mismo sitio** y se activa (`register_built_knowledge`; idempotente al reanudar). Un fallo a mitad de construcción nunca alcanza el registro: la versión anterior sigue activa. La activación verifica de nuevo y escribe `active.json` con reemplazo atómico (`os.replace`).
* **Limitaciones actuales (no implementado)**: la versión reconstruida queda físicamente dentro del run que la construyó (registrada en su sitio); no se mueve a `versions/<id>/`, porque los sellos del checkpoint son relativos a ese run. Tampoco existe reconstrucción parcial por componente (p. ej. solo REFERENCE): el manifiesto ya separa digests por componente, pero una reconstrucción produce una versión completa nueva. No se usan enlaces simbólicos ni hardlinks.
* **Retención**: `run_retention.plan` fija como dependencia todo checkpoint que respalda una versión registrada.
* CLI: `uv run python run.py knowledge-status` y `uv run python run.py knowledge-register --run-id <checkpoint> [--activate]` (verifica en profundidad y registra en su sitio; no copia, no mueve, no edita). Ninguno llama modelos ni genera embeddings.

## 5. Evaluación de indicadores

`prepare_evaluation` resuelve IDs seleccionados contra `source_project_id` canónico; actualmente prepara lotes de hasta dos proyectos y una solicitud por indicador, con reintentos existentes. Evaluación automática de ARTICLE como objetivo independiente sigue pendiente; sus documentos/nodos sí enriquecen Knowledge y relaciones.

`scoped_retrieval.from_published_cache` valida la publicación, carga el índice SOURCE y consulta vectores REFERENCE ya cacheados; no genera embeddings al recuperar. `rank_project_passages` filtra fragmentos propios por `source_id`, tipo PROJECT y campos sustantivos, y ordena por el máximo coseno con las referencias del indicador. **Esta ruta no depende del corte de candidatos del ranking global publicado.** Una consulta cacheada ausente es error explícito, no permiso para crear embeddings o leer el descriptor como fallback.

`project_relations` valida nodos/aristas contra el snapshot y `GraphRetriever.project_context` parte del nodo PROJECT con `canonical_id` exacto. Expansión acotada: hasta dos saltos, vecinos/nodos limitados y solo investigadores resueltos como puente. Los documentos externos alcanzables se ordenan con la misma consulta BGE; se seleccionan hasta tres caminos complementarios verificables. Sus textos no se convierten en evidencia propia del proyecto. Se deduplican fragmentos/caminos y se conservan las relaciones con procedencia.

Contexto principal BASE: `BASE_RETRIEVED_GRAPH_V1`. No envía descriptor completo. Qwen recibe instrucciones, rúbrica del indicador, fragmentos propios recuperados y relaciones complementarias que quepan. Los modos históricos `FULL_DESCRIPTOR_V1`/`BASE_DESCRIPTOR_GRAPH_V1` siguen siendo interpretables, pero el flujo BASE nuevo requiere recuperación. No introducir un fallback silencioso hacia ellos.

`PROSPECTIVE_V1` deriva temporalidad sin cambiar el catálogo original: actividades/mecanismos concretos previstos pueden respaldar `PROPOSAL_OR_HIGHER`; resultados concretos esperados, `EXPECTED_OR_DEMONSTRATED`. `CONTEXT_ONLY` no exige ejecución. Se conservan criterios, rationale, roles y grupos. Una intención vaga o una mención aislada no prueba contribución. `DEMONSTRATED_V1` conserva los requisitos de ejecución/logro establecidos. El modo y la derivación quedan en configuración, plan, manifiesto y fingerprints; no mezclar resultados entre modos.

Qwen emite juicios por criterio, `support_strength`, `coverage`, referencias y `strength_rubric`; no emite el porcentaje de confianza. `evidence_references.response_schema/materialize` limita IDs admisibles y Python convierte referencias F en citas literales. `review.evidence_locations` resuelve archivo, columna original, fila/sección e intervalo. Se validan esquema, IDs, citas, estados, temporalidad para CLEAR, referencias de fuerza, requisitos y consistencia. Literalidad no demuestra por sí sola pertinencia semántica; esa interpretación corresponde a Qwen y requiere revisión académica.

### Confianza implementada

En `assessment_v3.confidence` se mantiene **C = 100 × (0.55 × S + 0.45 × K)**. Se usa Decimal y redondeo final a dos decimales con `ROUND_HALF_UP`.

* S: suma de `directness`, `specificity`, `clarity` y `temporal_alignment`, cada una entera 0..4, dividida por 16. Qwen interpreta esas dimensiones; Python normaliza y suma. No es similitud BGE ni probabilidad. En prospectivo, alineación temporal se juzga frente a la etapa prevista exigida, no se anula por no estar ejecutada.
* Cobertura por criterio: NOT_DEMONSTRATED=0; PARTIAL=1,2,3; CLEAR=4. Se normaliza dividiendo por 4. Se exige evidencia verificable para criterios positivos.
* K nuevo: `CRITERIA_COVERAGE_SK_V2_ESSENTIAL_MEAN`. Una unidad por REQUIRED y una por grupo ALTERNATIVE, usando el máximo de sus alternativas; promedio de esas unidades. COMPLEMENTARY no suma nuevas obligaciones. El marcador interno `coverage_policy` lo introduce Python desde la solicitud, queda en el resultado y sobrevive a la lectura de recibos.
* K histórico SK V1: además limitaba el promedio al mínimo REQUIRED; se conserva cuando falta el marcador nuevo. Antes de SK, S era `support_strength/4` y K usaba niveles discretos. No reinterpretar ni recalcular resultados históricos como si fueran nuevos.

El cambio de K reconoce respaldo parcial sin satisfacer automáticamente un requisito pendiente. SUPPORTED sigue exigiendo fuerza global 3/4, criterios REQUIRED CLEAR y una alternativa CLEAR por grupo; no se decide por confianza sola. INSUFFICIENT_EVIDENCE admite apoyo pertinente parcial y confianza baja, intermedia o cero legítimo. S=K=0 sigue siendo válido si realmente no hay soporte; no se impone puntuación positiva. Los ceros sistemáticos no se explicaron completamente mediante inspección de código: no afirmar que esta corrección ya resolvió el comportamiento semántico real.

### Presupuesto y estados técnicos

BASE recuperado usa `num_ctx=16384`, salida inicial 4096, margen 1024 y tope de entrada de 8000 (`RETRIEVED_INPUT_CAP`). **Corrección C1 (14/11/2026)**: el presupuesto de los contextos recuperados nuevos se calcula con el tokenizador Qwen fijado (`config/qwen_tokenizer.json`, verificado por SHA-256 en `pipeline_coordinator.pinned_tokenizer` y en `token_budget.load`) más 12 tokens de plantilla calibrados (`estimate(..., tokenizer=..., cap=8000)`, estimador `PINNED_QWEN_TOKENIZER_AND_CALIBRATED_TEMPLATE_V1`). La auditoría comprobó que ese recuento coincide exactamente con `prompt_eval_count` de Ollama en los 6 recibos reales de 21844, mientras que el estimador anterior bytes/2 + 256 sobreestimaba unas 2,25 veces. El esquema de decodificación no forma parte del prompt. Se conservan las reservas de 384 (corrección) y 1200 (relaciones, empaquetadas después de la evidencia); el umbral efectivo para evidencia es `8000 − 1200 − 384 = 6416`. `with_relations` usa el mismo presupuesto calibrado. `context_budget.rebudget` reproduce el presupuesto guardado (tokenizador, tope) para que `ollama_provider.context_guard` y las solicitudes correctivas comparen exactamente; `RUNTIME_DRIFT` sigue exigiendo que el digest y los metadatos del modelo en Ollama coincidan con los calibrados. Los planes históricos sin tokenizador reproducen el estimador antiguo sin cambios. `truncate=False`/`shift=False`, la comprobación de consumo real posterior y los errores explícitos se mantienen.

Estados de contexto preparados (solo `READY` se despacha a Qwen):

| Estado | Significado |
|---|---|
| `READY` | El fragmento mejor clasificado entra intacto. Si otros fragmentos de menor rango no caben, `evidence_limited=true` y `truncation.reason=LOWER_RANKED_UNITS_OMITTED_BY_BUDGET` quedan en auditoría. Evidencia breve pero completa (p. ej. una sola frase) sigue siendo `READY`. |
| `EVIDENCE_TRUNCATED` | **C2**: hay evidencia, pero la unidad mejor clasificada no pudo enviarse intacta (solo una subfrase, `TOP_RANKED_UNIT_NOT_INTACT`): la solicitud ya no representa la recuperación. No se envía; nunca produce una fila válida ni un cero. Política `TOP_RANKED_UNIT_INTACT_V1`, solo en `BASE_RETRIEVED_GRAPH_V1`. |
| `NO_EVIDENCE_FITS` | Hay evidencia sustantiva recuperada, la plantilla deja espacio, pero ninguna unidad cabe. |
| `STATIC_CONTEXT_TOO_LONG` | **M1**: la plantilla sola supera el umbral efectivo (el mismo que se usa para fragmentos, incluida la reserva de 1200); antes se informaba erróneamente como `NO_EVIDENCE_FITS`. |
| `NO_SUBSTANTIVE_CONTEXT` / `NO_RETRIEVED_EVIDENCE` | No existe evidencia sustantiva recuperada para el proyecto. |

Cada solicitud recuperada guarda `context_selection.truncation` (política, `material`, unidad mejor clasificada, unidades omitidas por presupuesto, subfrases, motivo y umbral de evidencia en tokens). La exportación copia `context_status`, `evidence_limited` y `truncation` a `resultados/estado_indicadores.json` (todos los indicadores) y a `manifiestos/evidence_lineage.json` (filas válidas). Las siete columnas del contrato V2 no cambian.

`SUPPORTED` e `INSUFFICIENT_EVIDENCE` son decisiones de evaluaciones válidas. `BLOCKED_ERROR` es fallo técnico o de validación; nunca evaluación válida ni confianza cero imputada. También existen estados históricos y otros límites/pending que deben interpretarse desde sus recibos. Las 4 filas `INSUFFICIENT_EVIDENCE` con confianza 0 de `run_20261114_043344_433242` se produjeron con una sola subfrase por solicitud (truncamiento material); con la política actual esas solicitudes serían `EVIDENCE_TRUNCATED`. Los resultados históricos no se reescriben.

## 6. Resultados y exportación

Contrato nuevo predeterminado: **`THESIS_VALID_ASSESSMENTS_V2`** (`thesis_output.DEFAULT_CONTRACT`, `GENERAL_COLUMNS`). Excel conserva hojas `Proyectos` y `Artículos` con siete columnas generales, en este orden:

1. `proyecto/articulo_siap_id`
2. `indicador_id`
3. `estado_cumplimiento`
4. `parrafo_evidencia`
5. `fuente_evidencia`
6. `ubicacion_evidencia`
7. `confianza`

Se conservan SUPPORTED e INSUFFICIENT_EVIDENCE válidos sin filtrar confianza baja/cero. El proyector genérico también puede representar NOT_SUPPORTED histórico válido; SK actual lo normaliza a INSUFFICIENT_EVIDENCE al crear la fila. NO_EVIDENCE_FITS, errores y pendientes quedan fuera de la salida principal y siguen en auditoría. Confianza numérica; nunca porcentaje textual ni NULL convertido a cero. La hoja Artículos permanece vacía cuando no se evaluaron artículos.

Salidas: `resultados/resultado_indicadores.xlsx`, `indicadores.csv` (separador `;`, UTF-8 BOM) e `indicadores_territorios.csv` (códigos DANE verificados por cita, columna `codigo_dane`). Territorio no aparece en las siete columnas generales. No se inventan relaciones geográficas ni códigos. Power BI debe tratar IDs/códigos como texto y confianza como número. No se verificó importación en Power BI Desktop en esta transferencia.

Auditoría: `resultados/evaluaciones_validas.json`, `estado_indicadores.json`, `manifiestos/export.json`, `evidence_lineage.json`, planes/contextos y recibos de cada llamada. Los contratos históricos `THESIS_POSITIVE_OUTPUT_V1` y `THESIS_ALL_INDICATORS_V1` conservan su interpretación de ocho columnas. La plantilla física `data/templates/plantilla_resultado_tesis.xlsx` es la histórica de ocho columnas; `thesis_output.render` deriva siete para el contrato nuevo sin modificar el archivo original. Los scripts `export_verified_partial*` son utilidades históricas, no el contrato predeterminado actual.

## 7. Ejecución del sistema

Comandos del parser real; en esta transferencia solo se consultó `--help`, no se ejecutaron estos procesos:

```powershell
uv run python run.py
uv run python run.py verify --source base
uv run python run.py run --source base --projects 21844 --evaluation-mode prospective --knowledge-action reuse
uv run python run.py run --source base --projects 21750,21736,22022,21869,21844 --evaluation-mode prospective --knowledge-action reuse
uv run python run.py run --source base --projects 21844 --evaluation-mode prospective --knowledge-action rebuild
uv run python run.py status --run-id run_20261114_053532_061299
uv run python run.py resume --run-id <ID_COMPATIBLE> --through export
```

`--context-mode retrieved-graph` permite hacer explícita la política BASE predeterminada. `--evaluation-mode demonstrated` selecciona el otro modo temporal. `--through preprocessing|knowledge|graphrag|evaluation|export` limita la ejecución solicitada; no equivale a una inspección inocua. La selección de IDs es textual y no debe perder ceros iniciales.

`verify --source base` lee fuentes/configuraciones y no crea embeddings ni llama modelos. `status` consulta estado, aunque puede verificar productos. `run`, `resume` y reconstrucción pueden usar CPU/RAM/disco/GPU y hacer llamadas a Qwen, sujetos a permisos y checkpoints. Reutilizar evita reconstrucción compatible, pero verificar/copiar artefactos consume lectura/disco y la evaluación posterior sí usa Qwen. No ejecutar los ejemplos costosos automáticamente.

`src/run_paths.py` resuelve buckets `outputs/runs/local`, `api`, `anteriores` y rutas históricas. No mover runs manualmente.

Disposición de outputs tras la estabilización:

```text
outputs/
  shared/base/                 registro de conocimiento compartido (sección 4.1)
  runs/local/run_<id>/         run nuevo que reutiliza: solo artefactos propios
    estado/                    execution.json, progress.json, evaluation_readiness.json
    manifiestos/               run.json (knowledge_ref), raw_manifest.json, prepared_hashes.json,
                               model.binding.json, export.json, evidence_lineage.json, runtime.manifest.json
    evaluation/batch_*/        plan, contextos, autorizaciones, llamadas y recibos de Qwen
    resultados/                Excel, CSV, estado_indicadores.json, evaluaciones_validas.json
    logs/
  runs/local/run_<id>/         run que construye (rebuild) o run antiguo: conserva workspace/,
                               preprocess/ y su evaluación en workspace/outputs/layer4
  historico/                   copias de exportación por run (sin cambios)
```

Qué se construye una vez (por versión): preprocessing, canónico, Knowledge, embeddings SOURCE/REFERENCE, índices, grafo, publicación y `query_cache`. Qué se genera por ejecución: selección, política de evaluación, plan y contextos, llamadas a Qwen, validaciones, confianza, exportación, auditoría y logs.

Compatibilidad: los runs anteriores (incluidos `run_20261114_043344_433242` y `run_20261114_053532_061299`) no se modifican y se leen con su disposición original (`workspace/` propio o copiado; `global_reuse` identifica las copias). `status`, `resume`, `verify`, checkpoints y export siguen funcionando con ambas disposiciones. Un `base_knowledge_source` histórico que nombra un run explícito todavía usa la copia antigua al reanudar un run registrado antes del cambio; ya no es el procedimiento ordinario.

Acciones que requieren Qwen: `run`/`resume` hasta `evaluation` o `export` con solicitudes READY pendientes. Acciones que requieren regenerar embeddings: `--knowledge-action rebuild` o cualquier cambio de datos RAW, catálogo, configuración de datos, código/configuración de Knowledge o GraphRAG (modelo/revisión, fragmentación, grafo). No requieren embeddings ni Qwen: `verify`, `status`, `knowledge-status`, `knowledge-register`, preparación offline de contextos y export de resultados existentes.

## 8. Último estado conocido

Artefactos locales inspeccionados el 14/11/2026, sin llamar al evaluador:

| Run | Evidencia persistida |
|---|---|
| `run_20261114_043344_433242` | Primera publicación global usada aquí: 2232 proyectos, 7197 artículos, 7707 investigadores, 150 organizaciones y 48 indicadores canónicos; 42749 fragmentos SOURCE, 181 REFERENCE, 17334 nodos y 22873 relaciones. Manifiesto de preparación PREPARED y `graph_result` SUCCESS. Selección 21844. Exportación PARTIAL: 4 evaluaciones válidas, 43 NO_EVIDENCE_FITS y 1 BLOCKED_ERROR; contexto: 5 READY/43 NO_EVIDENCE_FITS. Hay 6 archivos `call.json`, sin certificar aquí su calidad semántica. Contrato histórico ALL de ocho columnas. |
| `run_20261114_053532_061299` | Reutiliza la fuente anterior, selección 21844, modo PROSPECTIVE_V1 y prompt V2_PARTIAL. Exportación PARTIAL, contrato VALID_ASSESSMENTS_V2: 48 esperados, 0 válidos, 48 bloqueados por contexto, 0 pendientes y 0 filas generales. Los 48 contextos tienen NO_EVIDENCE_FITS; no hay recibos `call.json` de nuevas llamadas. `estado/evaluation_readiness.json` indica READY. |

La verificación comunicada del último run es Preprocessing VERIFIED, Knowledge VERIFIED, GraphRAG VERIFIED, Evaluation PARTIAL_OR_BLOCKED. En los archivos inspeccionados se observan PREPARED/PARTIAL y READY; no confundir esas etiquetas con una evaluación efectuada. `evaluation_readiness=READY` solo acredita que el proyecto dispone de texto autorizado para preparar evaluación, no que sus 48 solicitudes contengan evidencia utilizable.

Se confirmó por lectura de la columna `id_actividad` que 21844 existe en el CSV. En ambas publicaciones `retrieval/source_indicator_candidates.parquet` contiene 2400 candidatos globales y ninguno con `source_id=PROJ_21844`. **No está comprobado que eso sea la causa definitiva**: el recuperador por proyecto implementado vuelve a ordenar fragmentos propios desde el índice, sin depender de ese corte global.

Hallazgo adicional verificable para orientar el diagnóstico: el último `context_selection.json` registra 192 omisiones `INPUT_BUDGET_EXCEEDED`, con fragmentos nombrados para `PROJ_21844` y cero seleccionados. El primer contexto inspeccionado tiene estimación estática de 6615 tokens frente al máximo de 8000; también hay reservas internas. Esto apunta a revisar el empaquetado y sus reservas, pero no demuestra por sí solo la correspondencia completa CSV → índice ni autoriza reducir instrucciones o umbrales. No se cargó el índice entero ni se verificaron todos sus registros durante esta transferencia.

## 9. Problema principal pendiente

El conocimiento y el grafo llegan a publicación verificable, pero el último flujo no entrega evidencia utilizable por indicador a Evaluation. Hay que rastrear **21844** a través de:

```text
CSV original → adaptador/lineage → canónico PROJ_21844
→ source_sections/source_chunks → índice SOURCE y nodos/aristas
→ rank_project_passages → prepare_contexts/context_selection
→ solicitud autorizada → respuesta y validación de Qwen
```

Comprobar existencia y cantidades de fragmentos propios, IDs exactos, procedencia original, metadatos del índice y hashes de la publicación reutilizada. Contrastar los fragmentos propuestos con los descartados y con las reservas del presupuesto. Verificar que los filtros permiten objetivos/resumen/resultados y campos autorizados adicionales cuando metodología esté vacía. Diferenciar corte global, recuperación local y rechazo por presupuesto; evitar diagnosticar todo como «sin evidencia».

No está demostrado de extremo a extremo que el proyecto y sus fragmentos estén correctamente disponibles en el índice efectivamente empleado por Evaluation. Los IDs propios presentes en diagnósticos son una pista concreta, no la validación completa pendiente. Primero reunir evidencia; después modificar exclusivamente la causa comprobada.

## 10. Restricciones y decisiones del proyecto

* Mantener Qwen como intérprete semántico y Python como calculador determinista de confianza.
* No forzar positivos, confianza positiva, máximos ni eliminación de INSUFFICIENT_EVIDENCE con confianza baja/cero. Admitir evidencia parcial justificada.
* Mantener recuperación GraphRAG/BGE-M3, citas originales, archivo/columna/ID/procedencia; no volver automáticamente al descriptor completo.
* No atribuir al proyecto artículos ni logros de entidades relacionadas sin respaldo explícito.
* No modificar originales, catálogo, rúbricas, resultados históricos ni fingerprints para hacer pasar validaciones.
* No reconstruir BASE sin necesidad comprobada ni ejecutar proyectos/modelos al diagnosticar sin autorización.
* No reorganizar outputs hasta resolver recuperación. No hacer limpieza ni borrar checkpoints.
* Trabajar en `dev`. **No modificar `main`**, referencia anterior a la última reunión. Su commit al iniciar esta transferencia fue `fee5b9d38dc27692197cc8145a8aec70156f3358`; respaldo local `respaldo-main-pre-claude`.
* Los CSV, catálogo privado, planes congelados, modelos, índices y resultados no se publican en GitHub. Requieren acceso local autorizado. Existen comandos de retención/cleanup: no usarlos como parte de este diagnóstico.

## 11. Próximas tareas y prioridades

1. Diagnosticar y corregir recuperación por ID con evidencia de las etapas indicadas, incluyendo presupuesto efectivo y fuente reutilizada.
2. Comprobar que Qwen recibe fragmentos pertinentes del proyecto; READY por sí solo no lo demuestra.
3. Verificar confianza diferenciada y procedencia exacta, sin objetivos de cantidad de SUPPORTED.
4. Validar académicamente con una muestra pequeña y fuentes comparables, después de pruebas sintéticas.
5. Solo después, separar almacenamiento de conocimiento reutilizable e históricos, conservando compatibilidad con checkpoints/resume y sin perder datos.

## 12. Estado de verificación

| Estado | Alcance real |
|---|---|
| Implementado y comprobado con pruebas sintéticas | Identidades propias y espacios separados, nodos ambiguos sin puentes, deduplicación, alcance global BASE, aislamiento de filas incompletas, procedencia literal, selección por ID, relaciones complementarias, ausencia de descriptor completo, preflight, opción reuse/rebuild, referencia estable en resume, K nuevo sin anular cobertura parcial y proyección general de siete columnas. |
| Evidencia real inspeccionada | Manifiestos, conteos, contextos, estados y ausencia de llamadas del último run; existencia de 21844 en CSV; 2400 candidatos globales sin ese ID; omisiones por presupuesto. No se ejecutó el pipeline para comprobarlos. |
| Implementado pero sin validación real satisfactoria | Flujo completo del contrato V2 con recuperación y Qwen sobre 21844; confianza nueva diferenciada en una ejecución institucional válida. El último run no llegó a Qwen. |
| Problema conocido | 48 contextos NO_EVIDENCE_FITS, cero filas válidas en la última ejecución, pese a Knowledge/GraphRAG publicados y readiness READY. La causa definitiva sigue pendiente. |
| Pendiente | Trazabilidad completa CSV–índice–contexto, evaluación real pequeña, revisión humana de semántica, importación Power BI y almacenamiento compartido sin duplicación por run. |

Pruebas relevantes existentes: `tests/test_flexible_preprocessing.py`, `test_project_selection.py`, `test_scoped_identity.py`, `test_pipeline_scope_fixes.py`, `test_context_budget.py`, `test_evidence_references.py`, `tests/layer4_graphrag/test_graph.py`, `tests/layer5_experiment/test_assessment_v3.py`, `test_thesis_output.py`, `test_manual_pipeline.py`, `test_unified_runner.py` y `test_selection_console.py`.

Antes de esta transferencia se ejecutaron tandas puntuales: 13 pruebas de identidad/relaciones, 4 de fuentes incompletas, 8 de reuse/rebuild y 10 de confianza/procedencia/exportación; esas cifras corresponden a sus momentos de ejecución, no a una certificación de toda la suite actual. No se ejecutó una regresión completa después de todos los cambios acumulados; hay expectativas históricas de salida/defaults que pueden necesitar ajuste explícito de contrato. No afirmar que todos los tests del repositorio están aprobados. Esta última tarea solo agrega documentación y prepara Git, sin correcciones funcionales adicionales.

## 13. Estabilización del 14/11/2026 (C1, M1, C2, M6)

Implementado en `dev` sin ejecutar Qwen/Ollama, sin generar embeddings y sin reconstruir Knowledge/GraphRAG.

* **C1/M1/C2** (sección 5): presupuesto con tokenizador fijado, umbral estático coherente y estado `EVIDENCE_TRUNCATED`. Verificación offline sobre los artefactos reales de 21844 (recuperación publicada, sin modelos): **48/48 `READY`**, los 4 fragmentos propios intactos en cada solicitud (33 fragmentos F), 2 caminos relacionales por indicador, entrada calibrada 6874–7203 tokens (≤ 8000 con la reserva de 384), recuento idéntico al del tokenizador, presupuesto reproducido por `context_guard`, referencias F literales del propio proyecto y presentes en el esquema de respuesta, sin `evidence_limited`. Sin tokenizador, los mismos prompts (idénticos byte a byte a `plan.json`) se clasifican ahora `STATIC_CONTEXT_TOO_LONG` en vez de `NO_EVIDENCE_FITS`. Con una ventana artificialmente reducida, el truncamiento material se identifica (`EVIDENCE_TRUNCATED`) y no se despacha.
* **M6** (secciones 4.1 y 7): registro compartido, reutilización por referencia sin copias y activación atómica. El conocimiento original de `run_20261114_043344_433242` quedó registrado y activo como versión `78420dc8b249600b-78f4d320` (verificación profunda: 42.749 vectores SOURCE, 181 REFERENCE, 17.334 nodos, 22.873 aristas, 214 consultas en caché), sin copiar ni modificar el run. `run_20261114_053532_061299` es una copia (`global_reuse`) y no se registra.
* **Fin de línea y sellos**: los sellos de código se calculan sobre bytes. Los checkpoints existentes registraron `src/layer2_processing/preprocessing/project_selection.py` con finales LF; un `git checkout` en Windows (`core.autocrlf=true`) lo reescribe con CRLF y el checkpoint deja de ser reutilizable aunque el contenido sea idéntico. El archivo se mantiene con LF; `git diff` no muestra cambios de contenido, aunque `git status` puede listarlo. Otros archivos de evaluación (`assessment_v3.py`, `evidence_references.py`, `live_execution.py`) ya diferían en bytes de los sellos de los runs antiguos antes de esta tarea, por lo que la verificación completa (`status`/`resume`) de esos runs ya fallaba; la verificación de conocimiento (`knowledge_only`) sí pasa.
* **Pendiente (no implementado)**: mover físicamente versiones reconstruidas a `outputs/shared/base/versions/<id>/`; reconstrucción parcial por componente (solo REFERENCE); conocimiento compartido sin copia para selecciones por muestreo/contrato (`project_selection`), que conservan la copia histórica desde la versión registrada porque su validador es código de conocimiento sellado; hallazgos A1, A3, A4 y A5 de la auditoría.
* **Pruebas (14/11/2026)**: nuevas `tests/test_calibrated_context.py` (9), `tests/test_knowledge_store.py` (17) y una de auditoría en `tests/test_manual_pipeline.py`; todas aprueban. Ajustadas por esta tarea: fixture `tokenizer_stub` en `tests/conftest.py`, `planner` y la prueba de relaciones de `tests/test_context_budget.py`, y el fixture `system` de `tests/test_unified_runner.py` (registro simulado). Comparación prueba por prueba contra el código de `HEAD` sobre el mismo entorno: sin regresiones. Siguen fallando, igual que antes de la tarea, las pruebas de contratos antiguos (`tests/test_thesis_output.py`: 21, que esperan ocho columnas/`THESIS_ALL_INDICATORS_V1`; `tests/test_evidence_references.py`: 6, que esperan la política K V1) y otras que dependen de artefactos históricos eliminados, movidos a `outputs/runs/local/` o con sellos de bytes antiguos. No se ejecutó la suite contra Qwen.
* **Dependencias históricas (14/11/2026)**: los runs `phase1_20_v1`, `phase11_8_v2`, `phase12_6_v1`, `minimal_3_v1` y `run_20261102_004408_677016` existen en `outputs/runs/local/` y se resuelven con `run_paths.relocate` (nunca se mueven ni copian). `run_institutional_minimal_3x3_20261102` y `run_institutional_resultados_20261102` solo sobreviven compactados en `outputs/historico/` y se reproducen únicamente con `GRAPHRAG_HISTORICAL_RUNS=1`. Producción (`src/autonomous_execution/`): `comparison.historical_run` resuelve la ubicación real y falla con `Dependencia historica ausente` antes de escribir; `minimal.prepare`, `followup.prepare`, `comparison.prepare` y `offline_synthesis` leen desde esa ruta (sin globs vacíos silenciosos) y la conexión SQLite comprueba antes que el índice exista. Las claves de los manifiestos conservan sus convenciones previas. Pruebas: `tests/historical.py` (carga diferida, omisión explícita, parámetros nunca vacíos), `tests/test_title_only_rule.py` (regla de título sin datos institucionales) y `tests/test_historical_dependencies.py` (ausencias simuladas). `tests/test_output_layout.py` enumera las carpetas permitidas de `outputs/` con su función (`reviews/` contiene revisiones manuales que el pipeline no escribe). Editar `src/autonomous_execution/` cambia la huella de `preparation_integrity.runtime_files()` (flujo autónomo) y los `code_hashes` de runs creados antes de la edición; no afecta la reutilización de conocimiento.
* **Selección opcional de indicadores (flujo principal)**: `run`/`resume` aceptan `--indicators ID1,ID2,...`. La selección queda congelada en `execution.json` (reanudar con otra lista se rechaza), en `plan.json` (`indicator_selection`) y en la revisión. El plan conserva el catálogo sellado completo (48 perfiles y rúbricas); solo los indicadores seleccionados se recuperan, empaquetan, despachan, cuentan en `maximum_calls` y se exportan. Un plan con contextos incompletos y sin selección declarada sigue rechazándose. En `prepare --autonomous`, `--indicators` conserva su uso de depuración anterior.
* **Prompt `PROSPECTIVE_SK_PROMPT_V3_CONSISTENT` (A3/A4)**: las políticas prospectivas nuevas usan V3; los planes y políticas V2 existentes se reproducen sin cambios (`make_request` produce V2 por defecto y valida la versión). V3: (1) sustituye la escala `temporal_alignment` orientada a hechos realizados por una escala prospectiva frente a la etapa efectiva de cada criterio; (2) añade una regla de coherencia S/K idéntica a lo que ya exigen los validadores (sin citas: `support_strength`, coberturas y dimensiones en 0; con cita positiva: valores mayores que 0 y referencias de fuerza); (3) adapta la frase de etapas de `CRITERION_INSTRUCTIONS`; (4) envía `project.title` como contexto de identificación no citable (no es fragmento F ni entra en el esquema de referencias). Los textos forman parte de `instructions_sha256`. No cambian las rúbricas, el `rationale` (A1), los validadores ni la fórmula de confianza. Verificación offline con los artefactos reales de 21844: 48/48 `READY`, 4 fragmentos intactos y 2 relaciones por indicador, entrada calibrada de 7065–7394 tokens (umbral 8000 con reserva de 384).
