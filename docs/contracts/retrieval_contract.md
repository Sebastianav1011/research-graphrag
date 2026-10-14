# Retrieval v3.2 — discovery de chunks, candidatos SOURCE

Discovery localiza zonas relevantes; retrieval ordena fuentes potenciales;
evidence es soporte confirmado en Capa 4; assessment evalúa SOURCE+INDICATOR.
Capa 3 solo realiza los dos primeros. TITLE/KEYWORDS nunca implican cumplimiento.

REFERENCE no puede ser SOURCE ni evidencia. Se ejecutan todos los reference
chunks reales de cada indicador; NULL upstream permanece NULL. Para cada
chunk se usa el máximo cosine entre queries y se conservan query contributors.
GRAPH recibe seeds SOURCE visibles de vector retrieval, o seeds explícitos en
modo graph-only. No se usan labels/ground truth como seeds.

cosine(q,x)=q·x/(||q|| ||x||), rango [-1,1]; el producto interno de vectores
normalizados es equivalente. Un score mayor indica mayor relevancia de retrieval.
Después de expansión, cada SOURCE se valida semánticamente mediante sus chunks.
Se reconstruyen todas sus secciones publicadas no vacías, incluso no-top hits.

Agregación SOURCE: v=max(chunk cosine), g=max(graph_score),
h=0.80*((v+1)/2)+0.20*g. No suma lineal de chunks; bonus de corroboración=0.
top_chunk_scores es auditoría, no confianza. Se conservan hasta tres discovery
chunks y se ordenan/limitan SOURCES (50 por indicador), no pares chunk/indicador.
Desempates de SOURCE: source_type, source_id, document_id.

PROJECT substantive: summary/methodology/objectives/expected_results.
ARTICLE substantive: abstract. title/keywords son orientación. Otros campos se
consideran orientación. La clasificación es genérica y no define semántica por
indicador. ASSESSMENT_READY exige al menos un substantive field no vacío;
DISCOVERY_ONLY se conserva y no significa una evaluación negativa.

El batch y queries libres incluyen candidatos SOURCE y SOURCE context references.
Las queries pueden conservar chunks/textos para diagnóstico de discovery con
is_discovery_chunk; la entrega de assessment es source_candidates/source_contexts.
Las salidas batch usan los [contratos source-level](layer3_graphrag_contract.md).

La comparación VECTOR/GRAPH/HYBRID describe cambios de ranking/diversidad/latencia
y acceso a seeds. Los indicadores están aislados para GRAPH con seed INDICATOR.
Sin ground truth no se afirma superioridad y las métricas semánticas son N/A.
