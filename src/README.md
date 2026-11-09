# Código organizado según el SAD

```text
src/
├── layer2_processing/
│   ├── preprocessing/   # Lectores, ingesta, normalización, identidades y canonical
│   ├── knowledge/       # Documentos, secciones, chunks, entidades y relaciones
│   ├── pipeline.py      # Pipeline interno y checkpoints de procesamiento/conocimiento
│   └── checkpoints.py   # Verificación compartida de rutas y fingerprints
├── layer3_graphrag/     # BGE-M3, caché, vectores, grafo, ranking y recuperación
└── layer4_evaluation/   # Indicadores, LLM, evidencias, confianza, territorios y Excel
```

Capa 1 reside en `data/`; Capa 5 es Power BI externo. No requieren paquetes Python.
La coordinación entre capas reside en `scripts/pipeline_coordinator.py`; el comando
existente `scripts/run_pipeline_manual.py` conserva sus argumentos y autorizaciones.
No existe un paquete `manual_pipeline` ni un segundo motor analítico.

Se conservan los nombres históricos de configuraciones, schemas, claves de
manifiestos y carpetas de resultados. `layer4_evaluation.paths` mantiene su interfaz
pública mediante la implementación única de `layer2_processing.checkpoints`.
`config/sad_relocations.json` registra las reubicaciones y vincula los bytes actuales
con snapshots originales, sin reescribir publicaciones ni hashes aceptados.
