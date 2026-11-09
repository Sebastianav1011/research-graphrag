# Configuración

`pipeline_manual.json` es la configuración compartida del coordinador:
fuentes en `data/layer1_sources`, ejecuciones en `outputs/runs`, catálogo
institucional separado y mapeos/textos autorizados por archivo.

`openai.json` define límites, razonamiento y tarifas de referencia, sin claves.
`autonomous.json` fija la política inicial de los runs autónomos. Las preferencias
personales se guardan en `model.local.json`, excluido de Git; cada run congela
su configuración. Cambiar la preferencia no modifica un checkpoint existente.

`sources.example.yaml` documenta aliases; `sources.yaml` es local e ignorado.
No usar las rutas históricas `data/raw` o `outputs/pipeline_manual` para un run nuevo.

Se conservan los nombres de configuración contractuales: `layer1.yaml` configura
el ETL, `layer2.yaml` el conocimiento, `layer3.yaml` GraphRAG y `layer4_*.yaml`
los estudios/evaluación. No renumerarlos ni cambiar hashes de snapshots históricos.

Iniciar desde la raíz con `uv run python run.py`. Para claves, contratos y recursos
privados requeridos, consultar [la guía experimental](../docs/OPENAI_EXPERIMENTS.md).
