# Capa 3 — chunk-level retrieval, source-level candidates

Estado: **FINAL_PROJECT_LAYER_3_SOURCE_LEVEL_READY**.
Pipeline 3.2.0, SOURCE_INDICATOR_V1. La [aceptación final](layer3_source_level_acceptance.md)
registra publicación, gates, tests, integridad upstream y repository cleanup
aprobados. El registro privado vigente es
outputs/layer3/reports/source_level_final_acceptance.json. La
[revisión histórica del refactor](../status/layer3_source_refactor_review.md)
conserva la cronología intermedia; la arquitectura funcional permanece intacta.

## Separación de unidades

Discovery unit: source_chunk. Retrieval entity: PROJECT/ARTICLE.
Assessment unit futuro: SOURCE+INDICATOR. Capa 3 responde dónde vale la pena
buscar evidencia; no evalúa cumplimiento ni produce evidencia confirmada.

REFERENCE genera queries reales por indicador. SOURCE conserva los 45.362 chunks
y sus IDs, offsets, campos y textos de Capa 2, sin rechunking ni normalización
nueva. BGE-M3 dense, revisión 5617a9f61b028005a4858fdac845db406aefb181, 1024
dimensiones y cosine, permanece fijado. El snapshot Capa 2 sigue siendo
run_20261005T204120_837354Z, SHA-256
b0ec6990c8dc9d38398c780af4d51ed9c16c80e5504d7d70abd548fbe62d472f.

## Flujo

Queries REFERENCE → exact NumPy cosine sobre chunks SOURCE → agrupar seeds por
SOURCE → expansión del grafo → recheck semántico de chunks de cada SOURCE
expandido → agrupación/ranking SOURCE → resolver todas las source_sections
disponibles → candidatos SOURCE+INDICATOR y contextos normalizados.

Los embeddings compatibles se recargan de bundles publicados con checksums,
alineación de IDs/text_hash/chunk_hash, revisión y fingerprint exactos. De ser
incompatibles, se usa la cache determinística existente; nunca se reutiliza un
vector incompatible. En el refactor real no se recalculó ningún embedding del
corpus: SOURCE 45.362 y REFERENCE 133 reutilizados.

## Source context

PROJECT: title/keywords son orientación; summary, methodology, objectives y
expected_results son contexto sustantivo genérico. ARTICLE: title/keywords son
orientación; abstract es sustantivo. Estas funciones no prueban ningún indicador.
Otros campos desconocidos se tratan conservadoramente como orientación.

SourceContextResolver recorre todas las secciones del documento, incluye las
no vacías y conserva field_name, section_id, hashes y chunk_ids. No crea un
string de documento ni vuelve a embebir documentos completos. Una keyword
recuperada introduce el SOURCE y también expone sus secciones sustantivas,
aunque no hayan sido hits. ASSESSMENT_READY exige al menos una sección
sustantiva no vacía. DISCOVERY_ONLY se mantiene, sin equivaler a NOT_SUPPORTED.

## Ranking y grafo

vector_top_k_per_reference_chunk=30. source candidate limit=50 por indicador;
hasta tres discovery chunks se conservan por SOURCE. v=max(cosines),
g=max(graph retrieval score), h=0.80*((v+1)/2)+0.20*g. No se suman scores por
cantidad de keywords y la corroboración adicional pesa cero en esta versión.
Desempate: source_type, source_id, document_id. Los scores son retrieval.

El grafo local JSON mantiene 33.915 nodos y 24.821 edges explícitos de Capa 2:
12.007 PROJECT_HAS_RESEARCHER y 12.814 ARTICLE_HAS_RESEARCHER. No hay edges
SOURCE→INDICATOR inferidos. max_hops=2, max_neighbors=17,
max_expanded_entities=510 y max_total_nodes=600. Bridges resolved_only;
AMBIGUOUS/UNRESOLVED no son puentes. Organizaciones/indicadores aislados son
válidos. Las fuentes expandidas necesitan cosine>0 y luego el mismo resolver.
g=seed_support/(1+hops) para rutas no vacías; relación factual weight=1,
seed_support=max((seed chunk cosine+1)/2), sujeto a límites de expansión.

## Publicación y aceptación

Outputs nuevos exclusivos: source_indicator_candidates.parquet (2.400 filas,
48 indicadores) y source_context_packages.parquet (464 SOURCE únicos).
Context status por candidato: ASSESSMENT_READY 1.993, DISCOVERY_ONLY 407.
Los outputs chunk-oriented anteriores no existen en la publicación activa;
los runs anteriores quedan en archives privados de rollback/auditoría.

Provenance: candidate → discovery chunk/section references → document/source →
manifest Capa 2 → provenance heredada Capa 1. El nuevo paquete evita duplicar
original_values/textos en cada par. Capa 4 consulta las tablas publicadas Capa 2,
sin reconstruir grafos ni ejecutar retrieval. Quality y privacidad deben ser
PASS, coverage 100%, cero uso de bridges inválidos y cero decisiones.

Safe publishing: candidate → quality → Parquet/index/graph roundtrip → hashes →
directory swap → journal → validación final; rollback ante fallo.
El CLI estable permite plan, validate, build, query, evaluate, verify, compare,
test y setup-model. Compare conserva payloads/IDs/ranks y tolerancia 1e-6 para
embeddings, excluyendo run IDs, tiempos y hashes físicos de metadata operacional.

Los reportes están fuera de Git en outputs/layer3/reports y
outputs/repository_audit. final_acceptance.json corresponde a la arquitectura
anterior y no cierra este refactor. La idempotencia final coincide en datos y code_hashes. Los builds finales
son layer3_2026-10-14T094452_460099+0000_53c5b5f6 y
layer3_2026-10-14T094639_959121+0000_eca9000e; el segundo es la publicación activa.
layer3_source_regression.xml registra 219 PASS: 191 pruebas unitarias y
28 de integración real, sin FAIL, ERROR ni SKIP. La evidencia de las fases está
consolidada en outputs/layer3/reports/source_closure_evidence.json. No hay
ground truth final: Precision@K, Recall@K, HitRate@K y MRR siguen N/A.

Los perfiles de indicador siguen PENDING_GROUP_REVIEW, sin definiciones,
applicability, preferred fields o decisiones inventadas. Capa 4 permanece en
progreso; el benchmark antiguo es diagnóstico y no se reutiliza como final.
