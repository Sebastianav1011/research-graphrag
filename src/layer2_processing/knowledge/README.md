# Layer 2 — conocimiento

Reutiliza el constructor original de documentos, secciones, chunks, entidades y relaciones.
Recibe canonical validado de preprocesamiento. Los campos textuales adicionales seleccionados
se reconstruyen desde su procedencia canónica; no se incorpora el resto de columnas privadas.
Conserva fuentes, campos originales, hashes, offsets y separación SOURCE/REFERENCE.

La ejecución actual se inicia desde `run.py`; BASE se construye en staging
compartido y los runs la reutilizan por referencia. Ver [guía principal](../../../README.md#knowledge-compartido).
GraphRAG está implementado en `src/layer3_graphrag/`. `run_layer2.py` conserva el CLI original
de perfilado/validación/publicación, con contratos y configuraciones históricas `layer2`.
Suite: `tests/layer3_knowledge`. Ver [informe](../../../docs/architecture/AUDITORIA_CONSOLIDACION_RAW.md).
