# Contrato Capa 3 v3.2

CHUNK-LEVEL RETRIEVAL + SOURCE-LEVEL CANDIDATES. Fuente exclusiva de verdad:
snapshot publicado data/knowledge, validado físicamente y congelado por hash.
No se modifican Capa 1/Capa 2, textos, offsets, IDs o chunking 220/340/20.

## Embeddings, índice y grafo

BGE-M3 dense 1024, revisión 5617a9f61b028005a4858fdac845db406aefb181; SOURCE y
REFERENCE separados. Exact NumPy cosine, backend graph local_json. Las matrices
compatibles y la cache usan fingerprint de texto/modelo/revisión/config/runtime.
Se verifican checksum, IDs, dimensiones, normas, NaN/Inf y alineación.

## Candidato SOURCE+INDICATOR

Una fila única por indicator_id + source_type + source_id + document_id.
candidate_id determinístico; context_package_id es FK al SOURCE normalizado.
discovery_chunk_ids, discovery_field_names y discovery_retrieval_origins están
alineados. discovery_chunks contiene chunk_id, field_name, vector_score,
vector_rank nullable, retrieval_origin y reference_chunk_ids. No son evidence IDs.

Se conservan best_vector_score, top_chunk_scores, best_vector_rank nullable,
graph_score, graph_hops nullable, graph_path_json, hybrid_retrieval_score,
source_rank, retrieval_mode y reference_chunk_ids. context_status,
orientation_section_ids, substantive_section_ids, available_field_names,
source_context_hash, provenance_json y layer3_run_id completan el contrato.

Artefacto: data/graphrag/retrieval/source_indicator_candidates.parquet.
Schema formal: [source indicator candidate](../../schemas/layer3/source_indicator_candidate.schema.json).

## Contexto normalizado

Una fila por SOURCE, compartida entre indicadores; context_package_id deriva de
source_context_hash y snapshot. Contiene source_id/type/document_id,
context_status, title_section_id nullable, orientation_sections,
substantive_sections, available_field_names, hashes, provenance y layer3_run_id.
Cada sección conserva field_name, section_id, text_hash y chunk_ids completos.
No se duplican textos completos o metadata personal.

Artefacto: data/graphrag/retrieval/source_context_packages.parquet.
Schema: [source context package](../../schemas/layer3/source_context_package.schema.json).
Capa 4 hace JOIN por context_package_id y resuelve section_id contra
source_sections.parquet. Cada campo conserva su identidad; discovery orienta.
La cadena heredada se resuelve en las tablas públicas del snapshot aprobado,
nunca siguiendo record_source hacia archivos originales.

Manifest SUCCESS: arquitectura SOURCE_INDICATOR_V1, discovery/candidate units,
storage NORMALIZED_SECTION_REFERENCES, hashes, model/config/runtime, conteos y
quality. Publicación safe con rollback. Los outputs anteriores no coexisten.
No hay indicator_match, confidence, evidence_explanation o decisiones.
Perfiles operacionales: [PENDING_GROUP_REVIEW](../pending/indicator_profiles.md).
