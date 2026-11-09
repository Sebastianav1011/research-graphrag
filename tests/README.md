# Verificación

```powershell
uv run python -m pytest tests/test_architecture_consolidation.py tests/test_flexible_preprocessing.py tests/test_manual_pipeline.py
```

Pruebas controladas sin LLM; la integración GraphRAG inyecta embeddings sintéticos.
`uv run python -m pytest tests` recoge todas las suites canónicas sin duplicarlas por junctions.
Los resultados completos y limitaciones se registran en el [informe](../docs/architecture/AUDITORIA_CONSOLIDACION_RAW.md).
