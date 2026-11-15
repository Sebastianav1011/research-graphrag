# Ejecución

Entrada actual: `uv run python run.py`; ver [ejecución manual](../README.md#flujo-base-y-ejecución-manual).

El wrapper compatible para documentos nuevos conserva su interfaz:

```powershell
uv run python -B scripts/run_pipeline_manual.py run --through results --approve-build --authorize
```

El mismo comando admite checkpoints `--through preprocessing`, `knowledge`, `graphrag`
y `results`, y `--run-id` para reanudar. No hay wrappers por capa añadidos recientemente.

`run_layer1.py`, `run_layer2.py` y `run_layer3.py` son herramientas originales de publicación,
perfilado, calibración y mantenimiento. Los scripts `run_layer4_*`, exportadores y verificadores
conservan estudios V2/V3.3 y sus contratos específicos; no son otro lector RAW.
Los generadores de schemas, referencias y verificaciones también se conservan.

Ver [informe](../docs/architecture/AUDITORIA_CONSOLIDACION_RAW.md).
