# Graph context v3.2

Backend reproducible local_json. node_id=entity_id publicado por Capa 2.
Tipos PROJECT, ARTICLE, RESEARCHER, ORGANIZATION e INDICATOR. Los únicos edges
son PROJECT_HAS_RESEARCHER y ARTICLE_HAS_RESEARCHER publicados. No se infieren
SOURCE→INDICATOR, organizaciones o relaciones temáticas como hechos.

Los hits de chunks se agrupan en SOURCE seeds. Expansión max_hops=2,
max_neighbors=17, max_total_nodes=600, max_expanded_entities=510. Política
resolved_only: AMBIGUOUS/UNRESOLVED pueden existir como nodos, pero nunca como
bridges. Preferencia de vecinos: investigadores resueltos antes de bloqueados.

Cada SOURCE expandida requiere recheck semántico de sus chunks (cosine>0),
con discovery_chunk IDs y ruta factual auditables. Luego usa el mismo
SourceContextResolver que los seeds: adjuntar todo contexto por campo, incluso
secciones no recuperadas. Una relación estructural no constituye evidencia.

graph_score=seed_support/(1+hops) en rutas no vacías; hop0 aporta 0.
seed_support=max((seed cosine+1)/2), relación explícita weight=1. Los límites de
expansión están registrados en manifest. GRAPH-only requiere seeds explícitos,
con soporte estructural de seed=1 y validación semántica posterior. No son labels.

graph_path_json incluye seed_entity_id, entity_ids, relation_ids, seed_support,
relation_strength, bounded y researcher_bridge_policy. Se valida contigüidad,
endpoint SOURCE, límite de hops y resolución de researchers. Capa 4 recibe estas
rutas, sin reconstruir el grafo ni volver a ejecutar retrieval.

Los nodos de ORGANIZATION e INDICATOR aislados son válidos; indicator profiles
siguen PENDING_GROUP_REVIEW. El campo upstream evidence_type se preserva solo
como metadata de relación factual del contrato Capa 2; no confirma indicadores.
