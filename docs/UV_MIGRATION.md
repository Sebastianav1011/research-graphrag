# Migración a uv — 2026-11-08

uv es el gestor oficial de dependencias y ejecución. No se modificaron archivos
de lógica bajo `src/`, modelos, indicadores, contratos de datos, performance,
checkpoints o resultados. Los cambios de esos subsistemas que ya estaban en el
workspace pertenecen al trabajo previo, no a esta migración.

## Archivos

Creados:

- `pyproject.toml`
- `uv.lock`
- `.python-version`
- `docs/UV_MIGRATION.md`

Modificados:

- `.gitignore`, `setup.ps1`, `README.md`
- `docs/OPENAI_EXPERIMENTS.md`, `docs/instalacion.md`, `docs/RUNBOOK.md`
- `docs/autonomous_execution.md`, `docs/optimizacion.md`, `docs/README.md`
- `requirements/README.md`, `scripts/README.md`, `scripts/auxiliary/README.md`
- `schemas/README.md`, `schemas/layer2/README.md`
- `schemas/layer4_assessment/README.md`, `schemas/layer4_confidence/README.md`
- `schemas/layer4_preliminary/README.md`
- `tests/README.md`, `tests/fixtures/synthetic/README.md`
- `tests/layer2_preprocessing/README.md`, `tests/layer3_knowledge/README.md`
- `tests/layer5_preparation/README.md`, `tests/layer5_territories/README.md`

Los README secundarios solo cambian la forma de invocar Python mediante uv.
Los archivos requirements y el lock histórico CUDA conservan sus versiones.

## Configuración y validación

- uv utilizado: **0.13.7**; versión mínima declarada en pyproject.
- Python fijado: **3.14.0**, sin reemplazar el intérprete ni el entorno existente.
- Lock universal de **96 paquetes**, incluyendo los grupos dev, pdf y performance.
- Se conservaron las restricciones del entorno previo. PyTorch sigue en
  **2.11.0+cu128** para Windows/Linux; macOS arm64 resuelve 2.11.0 sin CUDA.
- SDK OpenAI fijado por lock: **2.54.0**. keyring: **25.7.0**. pytest: **9.1.1**.
- `uv sync --locked --inexact` completado: **18 paquetes ausentes añadidos,
  cero actualizaciones y cero eliminaciones**. No se volvió a descargar torch.
- `uv lock --check --offline` correcto. Índices públicos: PyPI y PyTorch CUDA 12.8.
- Importaciones del runtime, ayuda CLI y menús normal/modelos/contratos/estado
  correctos. El smoke test bloqueó conexiones de red y usó raíces sintéticas.
- **29 pruebas ligeras pasaron en 2,12 segundos**: instalación, API/contratos con
  mocks y contrato CSV; no se ejecutó toda la suite.
- Se comprobó el arranque mediante uv en una copia temporal de código sin
  `data/`, `outputs/`, credenciales o pesos. Se reutilizó el entorno ya instalado
  para evitar una segunda descarga de PyTorch; no fue una instalación desde cero.
- Sintaxis de `setup.ps1` y formato del diff correctos. Se revisaron exclusiones
  de entorno, cachés, credenciales y contratos; escáner preventivo sin hallazgos.

uv se descargó como herramienta temporal dentro de `.tmp/uv-bootstrap/` para
esta validación, sin modificar la instalación global ni el PATH del usuario.
Para usar el comando `uv` en una terminal normal, instalarlo una vez con las
instrucciones de [Inicio rápido](../README.md#inicio-rápido).

No se ejecutaron inferencias, embeddings, llamadas de pago ni proyectos
institucionales; tampoco se instalaron servicios Ollama ni se descargaron pesos.

## Publicación y límites

Los archivos uv están listos para versionarse y no contienen rutas del computador,
credenciales o índices privados. No se hizo commit ni push, ni se preparó un commit
con cambios previos del usuario. Los entrypoints y paquetes actuales que todavía
están sin seguimiento deben publicarse junto con esta configuración: consultar
[Git y mantenimiento](instalacion.md#git-y-mantenimiento).

Después de esa publicación, el flujo del clon es `uv sync` y
`uv run python run.py`. La resolución incluye Linux y macOS, pero solo se
sincronizó y verificó un runtime Windows durante esta tarea. Ejecutar todo
GraphRAG continúa requiriendo pesos, datos/catálogos autorizados y el hardware
CUDA configurado. OpenAI no necesita Ollama; sí conserva los requisitos del
pipeline local de recuperación. Los contratos se comparten solo con autorización.
