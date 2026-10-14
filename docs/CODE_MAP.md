# CODE_MAP — abrir el repositorio

Los entrypoints principales son run_layer1, run_layer2 y run_layer3. src conserva
responsabilidades separadas; los outputs privados no son código. Las funciones
auxiliares no se catalogan por separado. Tests usan fixtures sintéticas y tienen
opt-in para integration real. Los fixtures estáticos de Capa 1 están en data/samples/synthetic y usan
config/sources.synthetic.yaml. Capa 4 se reserva en docs/architecture/layer4.md,
docs/pending/indicator_profiles.md y schemas/layer3/indicator_profile.schema.json;
no tiene un paquete de código vacío. Capa 5 no está implementada.
Los controladores temporales de cierre se eliminaron tras consolidar su evidencia.

## common

| Archivo | Responsabilidad | Entrada | Salida | Lo llama |
|---|---|---|---|---|
| `src/common/config.py` | Config/rutas/logging | Configuración o paths del repo | Valores validados / logs | audit_identity_alias_forensics.py, audit_identity_aliases.py, conftest.py, pipeline.py |
| `src/common/logging.py` | Config/rutas/logging | Configuración o paths del repo | Valores validados / logs | pipeline.py |
| `src/common/paths.py` | Config/rutas/logging | Configuración o paths del repo | Valores validados / logs | audit_identity_alias_forensics.py, pipeline.py |
## layer1_data

| Archivo | Responsabilidad | Entrada | Salida | Lo llama |
|---|---|---|---|---|
| `src/layer1_data/canonicalize.py` | ETL canónico e identidad | Filas originales configuradas / canonical intermedio | Canonical, quality y provenance | audit_identity_alias_forensics.py, pipeline.py, test_final_domain.py |
| `src/layer1_data/contracts.py` | One explicit type contract, shared by Parquet writers and JSON Schema generation. | Filas originales configuradas / canonical intermedio | Canonical, quality y provenance | build_contracts.py, canonicalize.py, pipeline.py, quality.py, test_pipeline.py, verify_layer1.py |
| `src/layer1_data/identity.py` | Order-independent identity resolution with conflict blocking at component level. | Filas originales configuradas / canonical intermedio | Canonical, quality y provenance | audit_identity_alias_forensics.py, audit_identity_aliases.py, pipeline.py, test_final_domain.py, test_identity.py |
| `src/layer1_data/ingest.py` | Strict parsing. Every rejected row leaves an audit event. | Filas originales configuradas / canonical intermedio | Canonical, quality y provenance | audit_identity_alias_forensics.py, pipeline.py, test_ingest.py |
| `src/layer1_data/normalize.py` | Pure normalizers: no enrichment, inference, or network access. | Filas originales configuradas / canonical intermedio | Canonical, quality y provenance | audit_identity_alias_forensics.py, audit_identity_aliases.py, canonicalize.py, identity.py, ingest.py, pipeline.py, test_final_domain.py, test_normalization.py, validate.py |
| `src/layer1_data/pipeline.py` | Orchestration with immutable inputs, isolated runs and guarded publication. | Filas originales configuradas / canonical intermedio | Canonical, quality y provenance | audit_identity_alias_forensics.py, run_layer1.py, test_final_domain.py, test_pipeline.py, verify_layer1.py |
| `src/layer1_data/provenance.py` | ETL canónico e identidad | Filas originales configuradas / canonical intermedio | Canonical, quality y provenance | audit_identity_alias_forensics.py, audit_identity_aliases.py, canonicalize.py, identity.py, ingest.py, pipeline.py, quality.py, test_pipeline.py, validate.py, verify_layer1.py |
| `src/layer1_data/quality.py` | ETL canónico e identidad | Filas originales configuradas / canonical intermedio | Canonical, quality y provenance | audit_identity_alias_forensics.py, pipeline.py, test_final_domain.py |
| `src/layer1_data/validate.py` | ETL canónico e identidad | Filas originales configuradas / canonical intermedio | Canonical, quality y provenance | audit_identity_alias_forensics.py, audit_identity_aliases.py, pipeline.py, test_final_domain.py, test_validation.py |
## layer2_knowledge

| Archivo | Responsabilidad | Entrada | Salida | Lo llama |
|---|---|---|---|---|
| `src/layer2_knowledge/chunking.py` | Hierarchical word windows over normalized text; offsets are half-open. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | pipeline.py, reference_builder.py, test_unit.py |
| `src/layer2_knowledge/contracts.py` | Single output schema authority, including typed empty tables and JSON Schemas. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | build_layer2_contracts.py, pipeline.py, test_integration_real.py, test_unit.py, verify_layer2.py |
| `src/layer2_knowledge/document_builder.py` | One canonical project/article record yields one independent source document. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | entity_builder.py, pipeline.py, reference_builder.py |
| `src/layer2_knowledge/entity_builder.py` | Reuse canonical identity, including unresolved occurrences without resolving them. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | pipeline.py |
| `src/layer2_knowledge/pipeline.py` | Explicitly gated orchestration with complete candidates and rollback publication. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | run_layer2.py, test_integration_real.py, test_unit.py |
| `src/layer2_knowledge/provenance.py` | Pure deterministic identities, hashes and preservation of upstream lineage. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | chunking.py, document_builder.py, entity_builder.py, pipeline.py, quality.py, relation_builder.py, section_builder.py, test_integration_real.py, test_unit.py, validate_inputs.py, verify_layer2.py |
| `src/layer2_knowledge/quality.py` | Descriptive quality and complete ancestry validation, without semantic inference. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | pipeline.py, test_integration_real.py, test_unit.py |
| `src/layer2_knowledge/reference_builder.py` | Indicator descriptions are reference knowledge, never evidence of compliance. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | pipeline.py |
| `src/layer2_knowledge/relation_builder.py` | Only explicit canonical memberships; logical attributes participate in identity. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | pipeline.py |
| `src/layer2_knowledge/section_builder.py` | Sections retain nulls, configured field order and upstream field mappings. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | pipeline.py, reference_builder.py |
| `src/layer2_knowledge/security.py` | Explicit deny lists; corpus leakage findings never expose personal values. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | document_builder.py, entity_builder.py, provenance.py, quality.py, section_builder.py, test_integration_real.py, test_unit.py, validate_inputs.py, verify_layer2.py |
| `src/layer2_knowledge/text_normalization.py` | Conservative normalization, retaining original text at section level. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | chunking.py, quality.py, section_builder.py, test_integration_real.py, test_unit.py |
| `src/layer2_knowledge/validate_inputs.py` | Canonical-only reader. Never dereferences provenance file paths. | Snapshot canonical aprobado / estructuras intermedias | Documentos, secciones, chunks, entidades y relaciones | pipeline.py, run_layer2.py, test_integration_real.py, test_unit.py, verify_layer2.py |
## layer3_graphrag

| Archivo | Responsabilidad | Entrada | Salida | Lo llama |
|---|---|---|---|---|
| `src/layer3_graphrag/configuration.py` | Configuration validation and closed-by-default execution approval. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | operations.py, pipeline.py, test_configuration.py, test_integration_pending.py, test_orchestration.py, validate_inputs.py |
| `src/layer3_graphrag/context_builder.py` | Bounded private packages retaining original chunk text and inherited lineage. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | query_engine.py, test_orchestration.py |
| `src/layer3_graphrag/contracts.py` | Layer 3 contracts, independent of executable upstream modules. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | build_layer3_contracts.py, configuration.py, conftest.py, embedding_pipeline.py, indicator_retrieval.py, manifest.py, test_inputs.py, test_orchestration.py, test_source_context.py, validate_inputs.py |
| `src/layer3_graphrag/embedding_pipeline.py` | Bundles, fingerprint y cache compatible | Chunks + modelo/config o bundle verificado | Vectores/mappings checksummed | indicator_retrieval.py, operations.py, pipeline.py, quality.py, test_embeddings.py, test_indicator_retrieval.py, test_integration_pending.py, test_source_context.py |
| `src/layer3_graphrag/embedding_provider.py` | Provider-independent API; optional local adapter is loaded only on execution. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | conftest.py, model_setup.py, pipeline.py, test_embeddings.py, test_integration_pending.py |
| `src/layer3_graphrag/evaluation.py` | Retrieval experiments; unlabeled queries are explicitly unevaluable. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | pipeline.py, test_integration_pending.py |
| `src/layer3_graphrag/graph_builder.py` | Build only structured edges supplied by an approved knowledge snapshot. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | pipeline.py, test_indicator_retrieval.py, test_source_context.py |
| `src/layer3_graphrag/graph_profile.py` | Physical graph topology and identity bridge profile, without inferred facts. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | pipeline.py |
| `src/layer3_graphrag/graph_retriever.py` | Bounded deterministic expansion of existing facts; no identity resolution. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | indicator_retrieval.py, query_engine.py |
| `src/layer3_graphrag/graph_store.py` | Provider-independent graph storage with a deterministic local JSON backend. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | graph_builder.py, graph_profile.py, graph_retriever.py, indicator_retrieval.py, operations.py, pipeline.py, test_integration_pending.py |
| `src/layer3_graphrag/hybrid_retriever.py` | Vector seeds expand through existing structured graph relations. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | query_engine.py |
| `src/layer3_graphrag/indicator_retrieval.py` | Queries REFERENCE, seeds, recheck semántico y ranking SOURCE | REFERENCE + índice SOURCE + grafo | Candidatos, contextos, comparación y métricas | pipeline.py, query_engine.py, test_indicator_retrieval.py, test_integration_pending.py, test_source_context.py |
| `src/layer3_graphrag/manifest.py` | Manifest creation and complete artifact checksum verification. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | operations.py, pipeline.py, test_integration_pending.py, test_orchestration.py |
| `src/layer3_graphrag/model_setup.py` | Preparar BGE fijado, tokens y batch/hardware | Snapshot aprobado y archivos públicos del modelo | Modelo local, census, calibración/config | run_layer3.py |
| `src/layer3_graphrag/operations.py` | Aprobación física, verify, compare y regresiones | Repo/config/publicación/dos runs | Reportes técnicos y checks | run_layer3.py |
| `src/layer3_graphrag/pipeline.py` | Approved local builds and retrieval; plan mode never opens knowledge data. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | model_setup.py, run_layer3.py, test_integration_pending.py, test_orchestration.py |
| `src/layer3_graphrag/provenance.py` | Identifiers and retrieval lineage, without following upstream filesystem paths. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | build_layer3_contracts.py, configuration.py, conftest.py, context_builder.py, embedding_pipeline.py, embedding_provider.py, graph_builder.py, indicator_retrieval.py, manifest.py, model_setup.py, operations.py, pipeline.py, quality.py, query_engine.py, source_context.py, test_inputs.py, test_integration_pending.py, test_orchestration.py, test_provenance.py, test_source_context.py, validate_inputs.py |
| `src/layer3_graphrag/quality.py` | Quality report implementation; files are emitted only for actual candidate builds. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | pipeline.py |
| `src/layer3_graphrag/query_engine.py` | Orquestar vector/graph/hybrid libre | Text query, índices, snapshot y seeds explícitos | Source candidates/context refs + discovery diagnóstico | pipeline.py, test_integration_pending.py |
| `src/layer3_graphrag/ranking.py` | Configurable retrieval signals; no confidence or indicator decisions. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | hybrid_retriever.py, query_engine.py, test_orchestration.py |
| `src/layer3_graphrag/security.py` | Reject sensitive payloads; remove personal identifiers only from graph projection. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | graph_builder.py, quality.py, source_quality.py |
| `src/layer3_graphrag/source_context.py` | Reconstruir todos los campos disponibles; agrupar SOURCE+INDICATOR | Discovery chunks + source_documents/sections/chunks | Candidatos y SOURCE context refs | context_builder.py, indicator_retrieval.py, source_quality.py, test_source_context.py |
| `src/layer3_graphrag/source_quality.py` | Validar SOURCE/discovery/contexto/provenance/privacidad | Candidatos + contextos + snapshot/grafo | Summary e issues | operations.py, pipeline.py, test_indicator_retrieval.py, test_integration_pending.py |
| `src/layer3_graphrag/validate_inputs.py` | Closed boundary: only the eight knowledge files and their approved manifest. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | operations.py, pipeline.py, test_configuration.py, test_inputs.py, test_integration_pending.py |
| `src/layer3_graphrag/vector_index.py` | Provider independent indexes; exact cosine is the reproducible local backend. | Knowledge aprobado / vectores / grafo / query | Artefactos GraphRAG o referencias SOURCE | pipeline.py, test_indicator_retrieval.py, test_integration_pending.py, test_source_context.py |
| `src/layer3_graphrag/vector_retriever.py` | Búsqueda semántica sobre chunks en un único espacio | Query + embedding provider + SOURCE/REFERENCE index | Retrieved chunks de discovery | query_engine.py |
## Herramientas y tests

| Archivo | Responsabilidad | Entrada | Salida | Lo llama |
|---|---|---|---|---|
| `scripts/audit_identity_alias_forensics.py` | Forensic replay in memory. Writes only identity_alias_forensics reports. | Args/config o snapshot local | Publicación/reporte o schemas | Equipo / RUNBOOK |
| `scripts/audit_identity_aliases.py` | Audit alias interpretation from current provenance without publishing canonical. | Args/config o snapshot local | Publicación/reporte o schemas | Equipo / RUNBOOK |
| `scripts/audit_repository.py` | Inventory owned repository files and protected upstream hashes; no data payloads logged. | Args/config o snapshot local | Publicación/reporte o schemas | Equipo / RUNBOOK |
| `scripts/build_contracts.py` | Build empty future-output template and machine-readable contracts; not an ETL stage. | Args/config o snapshot local | Publicación/reporte o schemas | Equipo / RUNBOOK |
| `scripts/build_layer2_contracts.py` | Export only Layer 2 JSON Schemas; never invoke Layer 1 contract generation. | Args/config o snapshot local | Publicación/reporte o schemas | Equipo / RUNBOOK |
| `scripts/build_layer3_contracts.py` | Maintain/check Layer 3 schemas without touching data or upstream contracts. | Args/config o snapshot local | Publicación/reporte o schemas | Equipo / RUNBOOK |
| `scripts/render_template_preview.ps1` | Preview de plantilla vacía desde metadata local | Args/config o snapshot local | Publicación/reporte o schemas | Equipo / RUNBOOK |
| `scripts/run_layer1.py` | Thin CLI; all ETL orchestration lives in layer1_data.pipeline. | Args/config o snapshot local | Publicación/reporte o schemas | Equipo / RUNBOOK |
| `scripts/run_layer2.py` | Thin Layer 2 CLI. Default configuration deliberately cannot publish yet. | Args/config o snapshot local | Publicación/reporte o schemas | Equipo / RUNBOOK |
| `scripts/run_layer3.py` | Safe CLI: defaults to configuration-only preparation plan. | Args/config o snapshot local | Publicación/reporte o schemas | Equipo / RUNBOOK |
| `scripts/verify_layer1.py` | Local acceptance checks; reports only counts, never personal values. | Args/config o snapshot local | Publicación/reporte o schemas | Equipo / RUNBOOK |
| `scripts/verify_layer2.py` | Accept two real publications: hashes, IDs, payloads, privacy and upstream immutability. | Args/config o snapshot local | Publicación/reporte o schemas | Equipo / RUNBOOK |
| `tests/layer1/test_final_domain.py` | Pruebas de final_domain | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer1/test_identity.py` | Pruebas de identity | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer1/test_ingest.py` | Pruebas de ingest | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer1/test_normalization.py` | Pruebas de normalization | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer1/test_pipeline.py` | Pruebas de pipeline | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer1/test_validation.py` | Pruebas de validation | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer2/test_integration_real.py` | Opt-in real integration only; no fixture generation, no RAW, no publication. | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer2/test_unit.py` | Pure technical tests: no fictional domain records or persistent Parquet datasets. | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer3/test_configuration.py` | Configuration and approval tests do not inspect the institutional corpus. | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer3/test_embeddings.py` | Embeddings tests use a small in-memory deterministic provider only. | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer3/test_evaluation.py` | Pruebas de evaluation | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer3/test_graph.py` | Only ephemeral synthetic rows; no reads of institutional snapshots. | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer3/test_indicator_retrieval.py` | Behavioral tests for factual expansion with measured semantic support. | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer3/test_inputs.py` | Knowledge contract tests use temporary Parquet files, never real Layer 2. | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer3/test_integration_pending.py` | Real tests opt in only after final Layer 2 approval; never forced PASS. | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer3/test_orchestration.py` | Unit orchestration with tiny ephemeral fixtures, never the institutional corpus. | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer3/test_provenance.py` | Lineage contains hashes and inherited references without upstream reads. | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer3/test_source_context.py` | SOURCE-level discovery, complete section references and orientation safeguards. | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |
| `tests/layer3/test_vector.py` | Local in-memory fixtures only; no corpus or embeddings are published. | Fixtures o snapshot real según opt-in | PASS/FAIL | pytest / run_layer3 --mode test |

Configuración: config/layer1.yaml, layer2.yaml y layer3.yaml fijan las políticas;
config/sources.example.yaml es la copia segura para config/sources.yaml local.
Schemas derivan de contracts.py mediante build_contracts/build_layer2_contracts/
build_layer3_contracts; docs/contracts conserva sus significados normativos.
Los locks y dependencias se explican en [RUNBOOK](RUNBOOK.md).
