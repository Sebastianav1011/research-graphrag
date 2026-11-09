# Capa 3 — conocimiento

Reutiliza el constructor original de documentos, secciones, chunks, entidades y relaciones.
Recibe canonical validado de preprocesamiento. Los campos textuales adicionales seleccionados
se reconstruyen desde su procedencia canónica; no se incorpora el resto de columnas privadas.
Conserva fuentes, campos originales, hashes, offsets y separación SOURCE/REFERENCE.

La secuencia vigente se ejecuta con `scripts/run_pipeline_manual.py run --through knowledge`.
GraphRAG está implementado en `layer4_graphrag`. `run_layer2.py` conserva el CLI original
de perfilado/validación/publicación, con contratos y configuraciones históricas `layer2`.
Suite: `tests/layer3_knowledge`. Ver [informe](../../docs/architecture/AUDITORIA_CONSOLIDACION_RAW.md).
