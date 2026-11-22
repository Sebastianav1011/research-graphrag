# Verificación

```powershell
uv run python -m pytest tests/test_architecture_consolidation.py tests/test_flexible_preprocessing.py tests/test_manual_pipeline.py
```

Pruebas controladas sin LLM; la integración GraphRAG inyecta embeddings sintéticos.
`uv run python -m pytest tests` recoge todas las suites canónicas sin duplicarlas por junctions.
Las suites históricas se conservan para trazabilidad; algunas dependen de recursos
privados o contratos anteriores y no equivalen a una validación de instalación.
La consolidación de `main` y sus limitaciones se registran en el
[informe de consolidación](../docs/consolidacion_main_2026-11-22.md).
