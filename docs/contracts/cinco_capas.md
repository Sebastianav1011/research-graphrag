> Ubicación vigente de originales: `data/raw/`. El código de inventario forma parte de preprocesamiento. Este documento conserva el historial; consultar el README raíz para ejecutar.

> Documento histórico anterior a la consolidación del 29-10-2026. La operación vigente está en el README raíz y `docs/architecture/AUDITORIA_CONSOLIDACION_RAW.md`.

# Contratos vigentes con numeración de cinco capas

Se conserva el contenido, nombre y campos de los contratos existentes. Sus números
de capa corresponden al historial de ejecución; no se alteran filas ni manifiestos.

| Capa actual | Contratos conservados |
|---|---|
| 1 RAW | Archivos originales sin transformación; SHA-256 e identidad del conjunto |
| 2 PREPROCESSING | [Canonical](canonical_data_contract.md) |
| 3 KNOWLEDGE | [Knowledge](layer2_knowledge_contract.md), [chunking](chunking_contract.md) |
| 4 GRAPHRAG | [GraphRAG](layer3_graphrag_contract.md), [grafo](graph_contract.md), [retrieval](retrieval_contract.md) |
| 5 RESULTS | [Assessment V3](layer4_assessment_v3_contract.md), [discovery V3.3](layer4_discovery_v3_3_contract.md), [salida](layer4_output_contract.md), [Power BI](layer4_powerbi_contract.md) |

No se añade un formato intermedio que sustituya los Parquet existentes. Los IDs,
provenance, separación SOURCE/REFERENCE y validaciones permanecen vigentes. La
confianza V3 se conserva como `100 × (0.55S + 0.45K)`. No se renombra el contenido
de un assessment para atribuirlo a una metodología distinta.
