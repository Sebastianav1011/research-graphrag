# Layer 4 — evaluación y resultados

El flujo actual se inicia desde `run.py`: Qwen local mediante Ollama evalúa
los indicadores institucionales con evidencia GraphRAG verificable. Python
valida citas y contratos, calcula confianza S/K y exporta Excel/CSV. La API
requiere autorización y presupuesto separados. La resolución territorial es
determinista y no depende del LLM.

La [guía principal](../../README.md#flujo-base-y-ejecución-manual) reúne ejecución,
Knowledge compartido, estados, limitaciones y contrato de siete columnas.

## Módulos del flujo actual

- `live_execution.py`: ejecución, validación, checkpoints y verificación de recibos.
- `indicators/scoped_retrieval.py`: ranking vectorial propio del proyecto y contexto relacional.
- `indicators/context_budget.py`: empaquetado y cobertura del contexto enviado.
- `indicators/ollama_provider.py`: transporte local y reparación focalizada.
- `indicators/evidence_references.py`: referencias a fragmentos y materialización literal.
- `indicators/assessment_v3.py`: criterios, validación y cálculo S/K.
- `thesis_output.py` e `indicator_csv.py`: exportaciones del run.
- `territories/`: extracción y resolución territorial.

Codex CLI, los cierres V2, `global_discovery_v3_3.py` y `consumer_v3_3.py`
conservan estudios y contratos históricos. No representan el flujo BASE actual,
que prepara los 48 indicadores salvo selección CLI explícita.
