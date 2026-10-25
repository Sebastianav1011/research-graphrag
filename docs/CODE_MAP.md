# Mapa del código

El cierre V2 de 4A amplía `indicators/experiment.py` y el mismo `codex_cli.py`.
`assessment_v2.py` concentra schema/rúbrica/validación/fórmula versionados;
`performance.py` y `performance_report.py` miden e informan recursos observables;
`closure_audit.py` reproduce el diagnóstico histórico y `closure_export.py` prepara
revisión/comparación y publica con aceptación explícita. Véase el
[procedimiento único](methodology/layer4_closure_v2.md). No se cambian 4B ni Capas 1–3.

Los módulos representan conceptos de cada capa. `pipeline.py` coordina etapas; la lógica de parsing, proyección, recuperación y validación permanece en sus módulos.

`common/` se retiró: sus tres utilidades solo eran consumidas por Capa 1 y ahora viven en `layer1_data/runtime.py`.

Capa 3 mantiene **chunk-level retrieval + source-level candidates**. `discovery_chunk != evidence`, `retrieval_score != confidence` y `candidate_source != indicator_match`. Este flujo no produce decisiones de indicadores ni implementa el assessment de Capa 4A.

## Extensiones territoriales

Extensión territorial independiente: `src/layer1_data/dane_reference.py`
inspecciona el XLSX autorizado, valida DD/MMM, normaliza nombres, construye la
dimensión y sus índices, y publica snapshots/manifest separados. Su entrypoint
es `scripts/build_dane_reference.py`; no forma parte del ETL canonical histórico.

## layer4/territories

| Archivo | Responsabilidad |
|---|---|
| `src/layer4/territories/matching.py` | Detección exacta, resolución local, ambigüedad, deduplicación y política COUNTRY000. |
| `src/layer4/territories/inputs.py` | Lectura verificada de PROJECT documents/sections publicados por Capa 2. |
| `src/layer4/territories/contracts.py` | Schemas Arrow de bridge, evidencia y ambiguos, incluidos outputs vacíos tipados. |
| `src/layer4/territories/pipeline.py` | Calidad, outputs, idempotencia, lock, publicación y archivo con rollback. |
| `src/layer4/territories/workbook.py` | Vista de revisión humana y fallback offline cuando Artifact Tool no está disponible. |
| `scripts/render_territory_workbook.mjs` | Exportación y render local del workbook mediante Artifact Tool. |
| `scripts/run_territories.py` | Entry point exclusivo de caracterización territorial. |
| `scripts/territory_integrity.py` | Fingerprint de canonical, knowledge y publicación/código protegido de Capa 3. |
| `scripts/verify_territories.py` | Verificación read-only de publicación territorial e integridad protegida. |
| `tests/territories/` | Referencia DANE, matching y aceptación real de outputs. |

## Preparación de indicadores y confidence de Capa 4

| Archivo | Responsabilidad |
|---|---|
| `src/layer4/indicators/confidence.py` | Configuración, validación y cálculo RAW_CONFIDENCE_V1; el ZIP con originales históricos no está incluido. |
| `src/layer4/indicators/profiles.py` | Inspección v2, elementos clave conservadores, mapping explícito, reglas RULE_TEXT y referencia versionada. |
| `src/layer4/indicators/contracts.py` | Seis schemas técnicos de assessment, perfil, PROJECT_INDICATOR, territorio, metadata y datos del workbook. |
| `src/layer4/indicators/assessment.py` | Protocolo AssessmentProvider, transporte cerrado, evidence gates y transformación pura con confidence. |
| `src/layer4/territories/contracts.py` | Proyección de consumo con code_system DANE/INTERNAL sin cambiar la bridge v1. |
| `src/layer4/indicators/export.py` | Datos y exportación de cuatro hojas; no ejecuta assessment. |
| `src/layer4/indicators/preparation.py` | Verifica referencias congeladas y escribe metadata con cero proyectos/assessments. |
| `src/layer4/indicators/selection.py`, `prompt.py` | Selección determinística y construcción del input por campos/perfiles, sin llamar al proveedor. |
| `src/layer4/indicators/preliminary.py` | Orquestación explícita del preliminar; verificación histórica separada del baseline de ejecución actual. |
| `src/layer4/indicators/preliminary_output.py` | Validación de filas, métricas y verificación/exportación del workbook preliminar. |
| `src/layer4/indicators/codex_cli.py` | Adaptador provisional ya existente; no se ejecuta durante la migración. |
| `src/layer4/indicators/powerbi.py` | Proyección de consumo y edición del workbook en memoria; sin assessment ni recálculo de confidence. |
| `scripts/build_indicator_assessment_profiles.py` | Publicar únicamente perfiles/reglas v2 de Capa 4. |
| `scripts/build_layer4_contracts.py` | Export/check de schemas, sin assessment. |
| `scripts/prepare_layer4_inputs.py` | Preparación con ejecución deshabilitada. |
| `scripts/auxiliary/verify_layer4_preparation.py` | Cierre de tests, integración e integridad de inputs históricos. |
| `scripts/render_layer4_workbook.mjs` | Exportador offline del generador reusable, sin proveedor ni selección. |
| `config/layer4_confidence.yaml`, `config/layer4_preliminary.yaml` | Fórmula oficial y configuración de preparación sin ejecución. |
| `tests/layer4_confidence/`, `tests/layer4_preparation/` | Confidence, perfiles, contratos, fallback nacional y workbook sintético. |

## layer1_data (módulos históricos)

| Archivo | Responsabilidad | Entrada | Salida | Lo invoca |
|---|---|---|---|---|
| `src/layer1_data/__init__.py` | Identidad del paquete y versión de Capa 1. | Import del paquete | Versión y namespace | Import del paquete por sus consumidores |
| `src/layer1_data/canonicalize.py` | Consolidación de entidades canónicas, títulos y membresías; escritura tipada. | Registros validados, identidad y contexto ETL | Tablas canonical y Parquet con procedencia | `scripts/auxiliary/audit_identity_alias_forensics.py`, `src/layer1_data/pipeline.py`, `tests/layer1/test_final_domain.py` |
| `src/layer1_data/contracts.py` | Autoridad de tipos Arrow y JSON Schema de Capa 1. | Nombre de dataset y definiciones normativas | Schemas y listas de campos contractuales | `scripts/build_contracts.py`, `scripts/verify_layer1.py`, `src/layer1_data/canonicalize.py`, `src/layer1_data/pipeline.py`, `src/layer1_data/quality.py`, `tests/layer1/test_pipeline.py` |
| `src/layer1_data/identity.py` | Resolución determinística de identidades y bloqueo de conflictos. | Ocurrencias y evidencias de identidad declaradas | Asignaciones resolved/ambiguous/unresolved | `scripts/auxiliary/audit_identity_alias_forensics.py`, `scripts/auxiliary/audit_identity_aliases.py`, `src/layer1_data/pipeline.py`, `tests/layer1/test_final_domain.py`, `tests/layer1/test_identity.py` |
| `src/layer1_data/ingestion.py` | Parsing estricto, mapeo explícito de columnas y validación de filas. | Archivos CSV/XLSX y mappings autorizados | Filas aceptadas/rechazadas, metadata y anomalías | `scripts/auxiliary/audit_identity_alias_forensics.py`, `scripts/auxiliary/audit_identity_aliases.py`, `src/layer1_data/pipeline.py`, `tests/layer1/test_final_domain.py`, `tests/layer1/test_ingest.py`, `tests/layer1/test_validation.py` |
| `src/layer1_data/normalize.py` | Normalizadores puros de texto, identificadores, fechas y registros. | Valores originales y opciones de normalización | Valores normalizados sin enriquecimiento ni inferencia | `scripts/auxiliary/audit_identity_alias_forensics.py`, `scripts/auxiliary/audit_identity_aliases.py`, `src/layer1_data/canonicalize.py`, `src/layer1_data/identity.py`, `src/layer1_data/ingestion.py`, `src/layer1_data/pipeline.py`, `tests/layer1/test_final_domain.py`, `tests/layer1/test_normalization.py` |
| `src/layer1_data/pipeline.py` | Orquestación: preflight → ingesta/validación → canonical → calidad → publicación. | Raíz y configuración de fuentes/Capa 1 | Run aislado y publicación canonical controlada | `scripts/auxiliary/audit_identity_alias_forensics.py`, `scripts/run_layer1.py`, `scripts/verify_layer1.py`, `tests/layer1/test_final_domain.py`, `tests/layer1/test_pipeline.py` |
| `src/layer1_data/provenance.py` | Hashes, tiempos UTC, anomalías y trazabilidad de campos/ocurrencias. | Archivos, filas originales y contexto de ejecución | Referencias y provenance_json | `scripts/auxiliary/audit_identity_alias_forensics.py`, `scripts/auxiliary/audit_identity_aliases.py`, `scripts/verify_layer1.py`, `src/layer1_data/canonicalize.py`, `src/layer1_data/identity.py`, `src/layer1_data/ingestion.py`, `src/layer1_data/pipeline.py`, `src/layer1_data/quality.py`, `tests/layer1/test_pipeline.py` |
| `src/layer1_data/quality.py` | Reportes de anomalías, calidad y conflictos explícitos de producción. | Manifest, anomalías y tablas canónicas | Resúmenes y reportes CSV/JSON | `scripts/auxiliary/audit_identity_alias_forensics.py`, `src/layer1_data/pipeline.py`, `tests/layer1/test_final_domain.py` |
| `src/layer1_data/runtime.py` | Configuración local, rutas de entrada/salida y logger de Capa 1. | YAML, raíz y rutas configuradas | Configuración leída, rutas verificadas y logger | `scripts/auxiliary/audit_identity_alias_forensics.py`, `scripts/auxiliary/audit_identity_aliases.py`, `src/layer1_data/pipeline.py`, `tests/layer1/conftest.py` |

## layer2_knowledge

| Archivo | Responsabilidad | Entrada | Salida | Lo invoca |
|---|---|---|---|---|
| `src/layer2_knowledge/__init__.py` | Versión y frontera de preparación determinística de Capa 2. | Import del paquete | Versión y namespace | `src/layer2_knowledge/pipeline.py` |
| `src/layer2_knowledge/chunking.py` | Ventanas jerárquicas por palabras con offsets y solapamiento explícitos. | Secciones normalizadas y configuración de tamaños | Chunks trazables a sección/documento | `src/layer2_knowledge/documents.py`, `src/layer2_knowledge/pipeline.py`, `tests/layer2/test_unit.py` |
| `src/layer2_knowledge/contracts.py` | Autoridad de schemas Arrow/JSON de las ocho tablas y manifest de Capa 2. | Nombre de tabla y definiciones normativas | Schemas contractuales, incluyendo tablas vacías tipadas | `scripts/build_layer2_contracts.py`, `scripts/verify_layer2.py`, `src/layer2_knowledge/pipeline.py`, `tests/layer2/test_integration_real.py`, `tests/layer2/test_unit.py` |
| `src/layer2_knowledge/documents.py` | Construcción de documentos y secciones SOURCE/REFERENCE; composición de referencia. | Canonical aprobado, configuración de campos y contexto | Documentos, secciones y chunks REFERENCE separados | `src/layer2_knowledge/graph_data.py`, `src/layer2_knowledge/pipeline.py` |
| `src/layer2_knowledge/graph_data.py` | Proyección de entidades canónicas y membresías explícitas para el grafo. | Canonical y configuración de entidades/relaciones | entities y relations, sin relaciones inferidas | `src/layer2_knowledge/pipeline.py` |
| `src/layer2_knowledge/pipeline.py` | Orquestación: validación → documentos/secciones → chunks → grafo → calidad → publicación. | Raíz, configuración y autorización de Capa 2 | Run aislado y publicación knowledge controlada | `scripts/run_layer2.py`, `tests/layer2/test_integration_real.py`, `tests/layer2/test_unit.py` |
| `src/layer2_knowledge/provenance.py` | Identidades determinísticas, descendencia, hashes de payload y conservación de linaje. | Filas, provenance heredada y contexto de Capa 1/2 | IDs, hashes y provenance_json | `scripts/verify_layer2.py`, `src/layer2_knowledge/chunking.py`, `src/layer2_knowledge/documents.py`, `src/layer2_knowledge/graph_data.py`, `src/layer2_knowledge/pipeline.py`, `src/layer2_knowledge/quality.py`, `src/layer2_knowledge/validate_inputs.py`, `tests/layer2/test_integration_real.py`, `tests/layer2/test_unit.py` |
| `src/layer2_knowledge/quality.py` | Calidad descriptiva, completitud de linaje y perfiles de campos/chunking. | Paquete SOURCE/REFERENCE y contexto de origen | Resumen, issues y reportes de calidad | `src/layer2_knowledge/pipeline.py`, `tests/layer2/test_integration_real.py`, `tests/layer2/test_unit.py` |
| `src/layer2_knowledge/security.py` | Exclusiones explícitas, privacidad de email y detección de PII en corpus/estructura. | Campos, texto, registros y política de privacidad | Texto permitido, redacciones o issues | `scripts/verify_layer2.py`, `src/layer2_knowledge/documents.py`, `src/layer2_knowledge/graph_data.py`, `src/layer2_knowledge/provenance.py`, `src/layer2_knowledge/quality.py`, `src/layer2_knowledge/validate_inputs.py`, `tests/layer2/test_integration_real.py`, `tests/layer2/test_unit.py` |
| `src/layer2_knowledge/text_normalization.py` | Representación textual y normalización conservadora, compartida por documentos/chunking/calidad. | String, lista de strings o NULL y opciones | Texto normalizado y posiciones de palabras | `src/layer2_knowledge/chunking.py`, `src/layer2_knowledge/documents.py`, `src/layer2_knowledge/quality.py`, `tests/layer2/test_integration_real.py`, `tests/layer2/test_unit.py` |
| `src/layer2_knowledge/validate_inputs.py` | Lectura exclusivamente de canonical aprobado y validación de configuración/snapshot. | Config y manifest/tablas canonical | Snapshot validado o error cerrado | `scripts/run_layer2.py`, `scripts/verify_layer2.py`, `src/layer2_knowledge/pipeline.py`, `tests/layer2/test_integration_real.py`, `tests/layer2/test_unit.py` |

## layer3_graphrag

| Archivo | Responsabilidad | Entrada | Salida | Lo invoca |
|---|---|---|---|---|
| `src/layer3_graphrag/__init__.py` | Versión y namespace de Capa 3; import sin carga de modelos. | Import del paquete | PIPELINE_VERSION | `src/layer3_graphrag/manifest.py`, `src/layer3_graphrag/pipeline.py` |
| `src/layer3_graphrag/configuration.py` | Validación de configuración y aprobación cerrada por defecto. | YAML, raíz y política de ejecución | Configuración aprobada o rechazo explícito | `src/layer3_graphrag/operations.py`, `src/layer3_graphrag/pipeline.py`, `src/layer3_graphrag/validate_inputs.py`, `tests/layer3/test_configuration.py`, `tests/layer3/test_integration_pending.py`, `tests/layer3/test_orchestration.py` |
| `src/layer3_graphrag/contracts.py` | Snapshots/bundles y autoridad de contratos SOURCE+INDICATOR, contextos, embeddings y manifest. | Definiciones normativas y nombres de artefactos | Schemas Arrow/JSON y contenedores tipados | `scripts/build_layer3_contracts.py`, `src/layer3_graphrag/configuration.py`, `src/layer3_graphrag/embeddings.py`, `src/layer3_graphrag/indicator_retrieval.py`, `src/layer3_graphrag/manifest.py`, `src/layer3_graphrag/validate_inputs.py`, `tests/layer3/conftest.py`, `tests/layer3/test_inputs.py`, `tests/layer3/test_orchestration.py`, `tests/layer3/test_source_context.py` |
| `src/layer3_graphrag/embeddings.py` | Interfaz de proveedor, adaptador local lazy, fingerprints, cache y bundles verificados. | Chunks SOURCE/REFERENCE, proveedor y configuración | Vectores, mappings y metadata checksummed; reutilización cuando corresponda | `src/layer3_graphrag/indicator_retrieval.py`, `src/layer3_graphrag/model_setup.py`, `src/layer3_graphrag/operations.py`, `src/layer3_graphrag/pipeline.py`, `src/layer3_graphrag/quality.py`, `tests/layer3/conftest.py`, `tests/layer3/test_embeddings.py`, `tests/layer3/test_indicator_retrieval.py`, `tests/layer3/test_integration_pending.py`, `tests/layer3/test_source_context.py` |
| `src/layer3_graphrag/evaluation.py` | Métricas de recuperación solo con ground truth explícito; comparación de motores. | Consultas etiquetadas y resultados existentes | Métricas o estado de ground truth ausente | `src/layer3_graphrag/pipeline.py`, `tests/layer3/test_evaluation.py`, `tests/layer3/test_integration_pending.py` |
| `src/layer3_graphrag/graph.py` | Representación/persistencia del grafo factual, proyección de filas y perfil de topología/identidad. | Entidades y relaciones canonical trazables | Grafo validado y perfil estructural | `src/layer3_graphrag/graph_retriever.py`, `src/layer3_graphrag/indicator_retrieval.py`, `src/layer3_graphrag/operations.py`, `src/layer3_graphrag/pipeline.py`, `tests/layer3/test_graph.py`, `tests/layer3/test_indicator_retrieval.py`, `tests/layer3/test_integration_pending.py`, `tests/layer3/test_source_context.py` |
| `src/layer3_graphrag/graph_retriever.py` | Expansión acotada del grafo mediante relaciones explícitas y bridges permitidos. | Seeds, grafo, snapshot y límites | Entidades, relaciones, caminos y discovery hits | `src/layer3_graphrag/indicator_retrieval.py`, `src/layer3_graphrag/retrieval.py`, `tests/layer3/test_graph.py` |
| `src/layer3_graphrag/indicator_retrieval.py` | Recuperación guiada por REFERENCE, recheck semántico y selección SOURCE por indicador. | Indicadores REFERENCE, índice SOURCE y grafo | SOURCE+INDICATOR candidates, contextos y comparación técnica | `src/layer3_graphrag/pipeline.py`, `src/layer3_graphrag/retrieval.py`, `tests/layer3/test_indicator_retrieval.py`, `tests/layer3/test_integration_pending.py`, `tests/layer3/test_source_context.py` |
| `src/layer3_graphrag/manifest.py` | Creación y validación de manifests y hashes completos de artefactos. | Artefactos publicados o directorio candidato | Manifest y validación física de publicación | `src/layer3_graphrag/operations.py`, `src/layer3_graphrag/pipeline.py`, `tests/layer3/test_integration_pending.py`, `tests/layer3/test_orchestration.py` |
| `src/layer3_graphrag/model_setup.py` | Preparación del modelo local fijado, census de tokens y calibración de hardware. | Configuración explícita y archivos del modelo | Modelo/tokenización/calibración; solo al invocarse expresamente | `scripts/run_layer3.py` |
| `src/layer3_graphrag/operations.py` | Operaciones CLI de aprobación, verificación, comparación y regresiones. | Configuración y publicaciones/runs existentes | Checks y reportes operacionales | `scripts/run_layer3.py` |
| `src/layer3_graphrag/pipeline.py` | Orquestación: plan/validación → embeddings → índices/grafo → recuperación → calidad → publicación. | Raíz, configuración, autorización y modo CLI | Plan o run/publicación controlados | `scripts/run_layer3.py`, `src/layer3_graphrag/model_setup.py`, `tests/layer3/test_integration_pending.py`, `tests/layer3/test_orchestration.py` |
| `src/layer3_graphrag/provenance.py` | IDs, hashes y linaje de recuperación sin seguir rutas privadas upstream. | Contenido, IDs y snapshot aprobado | Hashes, IDs estables y referencias heredadas | `scripts/build_layer3_contracts.py`, `src/layer3_graphrag/configuration.py`, `src/layer3_graphrag/embeddings.py`, `src/layer3_graphrag/graph.py`, `src/layer3_graphrag/indicator_retrieval.py`, `src/layer3_graphrag/manifest.py`, `src/layer3_graphrag/model_setup.py`, `src/layer3_graphrag/operations.py`, `src/layer3_graphrag/pipeline.py`, `src/layer3_graphrag/quality.py`, `src/layer3_graphrag/retrieval.py`, `src/layer3_graphrag/source_context.py`, `src/layer3_graphrag/validate_inputs.py`, `tests/layer3/conftest.py`, `tests/layer3/test_inputs.py`, `tests/layer3/test_integration_pending.py`, `tests/layer3/test_orchestration.py`, `tests/layer3/test_provenance.py`, `tests/layer3/test_source_context.py` |
| `src/layer3_graphrag/quality.py` | Integridad de embeddings/índices/grafo y provenance/privacidad de candidates/contextos SOURCE. | Snapshot, bundles, índices, grafo y recuperación | Resumen PASS/FAIL, issues y reportes de calidad | `src/layer3_graphrag/operations.py`, `src/layer3_graphrag/pipeline.py`, `tests/layer3/test_indicator_retrieval.py`, `tests/layer3/test_integration_pending.py` |
| `src/layer3_graphrag/retrieval.py` | Composición de consultas vector/graph/hybrid, ranking de discovery y ensamblado de contexto. | Consulta, índices, proveedor, seeds y configuración | Discovery diagnostics y candidatos/contextos SOURCE; sin decisiones | `src/layer3_graphrag/pipeline.py`, `tests/layer3/test_integration_pending.py`, `tests/layer3/test_orchestration.py`, `tests/layer3/test_vector.py` |
| `src/layer3_graphrag/security.py` | Exclusión de identificadores personales de la proyección del grafo y detección de privacidad. | Registros/campos estructurados | Proyección permitida o privacy issues | `src/layer3_graphrag/graph.py`, `src/layer3_graphrag/quality.py` |
| `src/layer3_graphrag/source_context.py` | Resolución de todas las secciones disponibles, agrupación SOURCE+INDICATOR y contexto de consulta. | Discovery hits, documentos/secciones/chunks y límites | Referencias completas SOURCE y diagnóstico acotado de discovery | `src/layer3_graphrag/indicator_retrieval.py`, `src/layer3_graphrag/quality.py`, `src/layer3_graphrag/retrieval.py`, `tests/layer3/test_orchestration.py`, `tests/layer3/test_source_context.py` |
| `src/layer3_graphrag/validate_inputs.py` | Validación cerrada de las ocho tablas knowledge y su manifest aprobado. | Config y publicación knowledge | KnowledgeSnapshot verificado o rechazo | `src/layer3_graphrag/operations.py`, `src/layer3_graphrag/pipeline.py`, `tests/layer3/test_configuration.py`, `tests/layer3/test_inputs.py`, `tests/layer3/test_integration_pending.py` |
| `src/layer3_graphrag/vector_index.py` | Índice numérico persistible y búsqueda exacta por coseno, independiente del motor de consulta. | Bundle verificado, espacio y opciones de índice | Índice validado y hits ordenados | `src/layer3_graphrag/pipeline.py`, `tests/layer3/test_indicator_retrieval.py`, `tests/layer3/test_integration_pending.py`, `tests/layer3/test_source_context.py`, `tests/layer3/test_vector.py` |

## Entrypoints y herramientas

| Archivo | Responsabilidad | Entrada | Salida | Lo invoca |
|---|---|---|---|---|
| `scripts/auxiliary/audit_identity_alias_forensics.py` | Reproducir en memoria decisiones de ingesta/identidad para auditoría. | Staging, mappings y canonical existentes | Reportes privados sin publicación | Equipo / CLI; [RUNBOOK](RUNBOOK.md) para ejecución de capas |
| `scripts/auxiliary/audit_identity_aliases.py` | Auditar interpretación de aliases e identidad canónica. | Canonical y provenance existentes | Reporte privado de identidad | Equipo / CLI; [RUNBOOK](RUNBOOK.md) para ejecución de capas |
| `scripts/build_contracts.py` | Generar contratos de Capa 1 y plantilla final vacía; no ejecutar ETL. | Definiciones de contracts | Schemas, diccionario y plantilla vacía | Equipo / CLI; [RUNBOOK](RUNBOOK.md) para ejecución de capas |
| `scripts/build_layer2_contracts.py` | Exportar o comprobar schemas de Capa 2. | Definiciones de contracts; --check para lectura | Schemas o comprobación sin escrituras | Equipo / CLI; [RUNBOOK](RUNBOOK.md) para ejecución de capas |
| `scripts/build_layer3_contracts.py` | Exportar o comprobar schemas de Capa 3. | Definiciones de contracts; --check para lectura | Schemas o comprobación sin escrituras | Equipo / CLI; [RUNBOOK](RUNBOOK.md) para ejecución de capas |
| `scripts/auxiliary/create_source_level_review_workbook.py` | Preparar revisión humana PROJECT+INDICATOR con candidatos R8/v1 y especificación v2. | R8 cerrado, secciones Capa 2 y catálogo v2 aprobado | Workbook privado; todas las decisiones humanas vacías | Equipo / CLI; [RUNBOOK](RUNBOOK.md) para ejecución de capas |
| `scripts/run_layer1.py` | CLI de Capa 1: argumentos y llamada al pipeline. | Args y config de fuentes/Capa 1 | Exit code y resultado del pipeline | Equipo / CLI; [RUNBOOK](RUNBOOK.md) para ejecución de capas |
| `scripts/run_layer2.py` | CLI de Capa 2: argumentos y llamada al pipeline. | Args, configuración y aprobación de canonical | Exit code y resultado del pipeline | Equipo / CLI; [RUNBOOK](RUNBOOK.md) para ejecución de capas |
| `scripts/run_layer3.py` | CLI de Capa 3: plan por defecto y despacho de modos autorizados. | Args, configuración y autorización | Exit code, plan o resultado operacional | Equipo / CLI; [RUNBOOK](RUNBOOK.md) para ejecución de capas |
| `scripts/verify_layer1.py` | Verificar aceptación local de canonical sin publicar. | Publicación, contratos y plantilla existente | Checks de aceptación | Equipo / CLI; [RUNBOOK](RUNBOOK.md) para ejecución de capas |
| `scripts/verify_layer2.py` | Verificar publicaciones y linaje de Capa 2 sin publicar. | Snapshots/runs existentes y evidencia de upstream | Checks de aceptación histórica | Equipo / CLI; [RUNBOOK](RUNBOOK.md) para ejecución de capas |

## Tests

- `tests/layer1/`: parsing, normalización, identidad, canonical, validación y publicación aislada con fixtures sintéticos.
- `tests/layer2/test_unit.py`: contratos, documentos, chunking, grafo, calidad, privacidad y validación puras.
- `tests/layer3/`: configuración, embeddings con proveedor determinístico en memoria, índices, grafo, recuperación, SOURCE context, provenance, calidad y orquestación.
- Las integraciones reales siguen siendo opt-in en `tests/layer2/test_integration_real.py` y `tests/layer3/test_integration_pending.py`.
- Ejecutar las suites por capa: los `conftest.py` existentes comparten nombre y no deben mezclarse en la misma colección.

## Capa 4: código activo e historia

`src/layer4/indicators/` agrupa perfiles, contratos, assessment, confidence,
preparación, selección/prompt, preliminar y exportadores. La rama
`src/layer4/territories/` contiene entradas, contratos/proyección de consumo,
matching/resolución, publicación y workbook. No existen paquetes antiguos ni shims.

`layer4.history.verify_historical_files` contrasta los hashes originales contra
archivos intactos o, si se obtiene por un canal autorizado, contra
`archives/layer4/pre_namespace_migration.zip`; ese ZIP no está incluido en este árbol.
No mapea hashes viejos a archivos nuevos. La verificación del código actual
continúa siendo estricta; verificar historia no acepta automáticamente un código diferente. Las aceptaciones reales nuevas registran sus propios fingerprints.
Los nombres de `schemas/`, `config/`, tests y outputs permanecen estables.

## Publicaciones y hashes históricos

R8 permanece cerrado y sin cambios. Sus `code_hashes` describen los módulos anteriores a esta reorganización; no se han reescrito para aparentar identidad binaria con el código actual.
El baseline histórico de 57 archivos también incluye código y tests anteriores. Su herramienta de auditoría fue retirada del árbol principal; la versión original puede recuperarse desde Git. Ese registro histórico no se rebasa para ajustarlo al código actual. La garantía de esta reorganización compara cuerpos AST, constantes y firmas, y hashes físicos de datos/publicaciones, schemas, configuración, plantilla y los tres entrypoints.
La herramienta de workbook conserva su guard estricto de `code_hashes` R8: ejecutarla sobre esta estructura modificada requiere resolver explícitamente esa diferencia histórica; no se ha debilitado su validación.
La evidencia local está en `outputs/repository_audit/source_structure_refactor.json` y JUnit de las suites antes/después. `src/layer2_knowledge/README.md` es una nota histórica; el estado vigente pertenece a `docs/architecture/`.

Configuración: `config/layer1.yaml`, `layer2.yaml` y `layer3.yaml`; `config/sources.example.yaml` documenta el mapping privado local. Contratos: `schemas/` y `docs/contracts/`. Dependencias y ejecución: [RUNBOOK](RUNBOOK.md).


## Unificación de Capa 1 y scripts auxiliares

`src/layer1_data/dane_reference.py` sustituye al paquete territorial separado.
Sus funciones de normalización/provenance/versionado son las mismas; la dimensión
DANE conserva rutas, snapshots y manifest propios, fuera del canonical.
El import funcional es `from layer1_data.dane_reference import ...`.

`scripts/auxiliary/` agrupa las dos auditorías de identidad, el workbook humano
y el verificador histórico de preparación. ROOT apunta al repositorio, y el
verificador sigue importando `scripts/territory_integrity.py` y los builders de raíz.
No hay aliases ni wrappers de las rutas retiradas.

`audit_repository.py` y `render_template_preview.ps1` se retiraron. Sus versiones
se recuperan con `git show ab24d442a740973671f2006f7c730194bfa3be9f:scripts/<archivo>`.
Los documentos históricos mantienen sus rutas originales.
