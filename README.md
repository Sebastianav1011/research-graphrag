# GraphRag — tesis

El proyecto organiza conocimiento institucional de proyectos y artículos para
encontrar fuentes potencialmente relevantes a un catálogo de indicadores y,
posteriormente, evaluar su evidencia con criterios revisados por el grupo.

## Arquitectura y estado

| Capa | Responsabilidad | Estado |
|---|---|---|
| 1 | Ingesta, normalización, identidad y canonical | FINAL_PROJECT_LAYER_1_READY |
| 2 | Documentos, secciones, chunks, entidades y relaciones | FINAL_PROJECT_LAYER_2_READY |
| 3 | Chunk-level retrieval, grafo y SOURCE-level candidates | FINAL_PROJECT_LAYER_3_SOURCE_LEVEL_READY |
| 4 | Evaluación de evidencia, modelos y confianza | IN PROGRESS / indicator profiles pending |
| 5 | Visualización | NOT IMPLEMENTED |

**CHUNK-LEVEL RETRIEVAL + SOURCE-LEVEL ASSESSMENT.** Un hit de título/keywords
puede descubrir una fuente; no demuestra cumplimiento. Capa 3 entrega un
candidato por SOURCE+INDICATOR con todas sus secciones disponibles referenciadas.
ASSESSMENT_READY describe disponibilidad de contexto sustantivo; DISCOVERY_ONLY
se conserva sin convertirlo en una decisión negativa.

La [aceptación final SOURCE-LEVEL](docs/architecture/layer3_source_level_acceptance.md)
registra el cierre técnico y de repositorio de Capa 3. Los dos builds con código
idéntico, idempotencia 13/13, verify e integración real (191 unitarias y 28 reales)
pasaron. El registro privado vigente es
outputs/layer3/reports/source_level_final_acceptance.json; final_acceptance.json
pertenece al diseño anterior. La [revisión histórica](docs/status/layer3_source_refactor_review.md)
conserva el motivo metodológico de la migración.

## Estructura

- `src/`: módulos por capa y utilidades comunes; consulta [CODE_MAP](docs/CODE_MAP.md).
- `scripts/run_layer1.py`, `run_layer2.py`, `run_layer3.py`: entrypoints principales.
- `config/`, `schemas/`, `tests/`, `docs/`: contratos, configuración y validaciones.
- `requirements/`: runtime y lock verificado; `templates/`: plantilla final permitida.
- `data/` y `outputs/`: publicaciones, datos y auditoría privados, excluidos de Git.

## Requisitos e instalación

Camino verificado: Windows x64, PowerShell, Python 3.14. BGE-M3 local usa CUDA,
float16 y GPU de 8 GiB en la configuración actual. Los embeddings del corpus
pueden reutilizarse cuando coinciden snapshot, textos, revisión y fingerprint.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements/layer3-windows-cuda.lock.txt
python -m pip check
Copy-Item config/sources.example.yaml config/sources.yaml
```

Configura únicamente `config/sources.yaml` para tus archivos autorizados; es local
y no se sube a Git. No necesitas modificar Python. Para solo Capas 1–2 instala
`requirements-dev.txt`; para otros runtimes usa `requirements/layer3.txt` y
calibra el hardware antes de ejecutar. La lista de dependencias y versiones está
en [RUNBOOK](docs/RUNBOOK.md).

## Datos requeridos

Git no contiene CSV institucionales, catálogo real, canonical, knowledge,
embeddings, pesos BGE-M3 ni outputs privados. El grupo debe entregar los inputs
autorizados o los snapshots oficiales completos con sus manifests. Las rutas
portables de inputs figuran en `config/sources.example.yaml`.

No se sustituyen los datos reales por ejemplos ficticios. Las fixtures de tests
son sintéticas y únicamente sirven para verificar comportamiento.

## Ejecutar y verificar

```powershell
python scripts/run_layer1.py
python scripts/run_layer2.py --mode validate
python scripts/run_layer2.py --mode publish
python scripts/run_layer3.py --mode validate
python scripts/run_layer3.py --mode build
python scripts/run_layer3.py --mode verify
python scripts/run_layer3.py --mode query --query "restauración ambiental y biodiversidad" --retrieval-mode hybrid
python scripts/run_layer3.py --mode test --real-integration
```

Estos comandos requieren los snapshots/manifests aprobados. No reconstruyas
Capas 1–2 si solo vas a reutilizar knowledge oficial. El [RUNBOOK](docs/RUNBOOK.md)
detalla aprobación de hashes, transferencia de datos, modelo local, verificación
e idempotencia desde un clon nuevo. Los builds usan candidate, validación,
roundtrip, hashes y publicación con journal/rollback.

## Outputs y privacidad

La publicación activa es `data/graphrag/_manifest.json`. Sus outputs principales:
`retrieval/source_indicator_candidates.parquet` y
`retrieval/source_context_packages.parquet`. Los contextos están normalizados
por SOURCE y contienen section_id/chunk_id, sin concatenar o duplicar campos.
Capa 4 resolverá section_id en `data/knowledge/source_sections.parquet`.

No se envían datos a proveedores externos; Capa 3 no utiliza LLMs ni produce
decisiones, evidencia confirmada o confianza. Los scores significan relevancia
de retrieval. La política de bridges es resolved_only. No se indexa metadata
personal ni se reabren archivos originales para resolver provenance.

No subir datos institucionales, snapshots, pesos, caches, logs, outputs, .venv,
tokens, archivos .env ni configuración local. Sí subir código, configuración
segura, schemas, tests, documentación, locks y plantilla vacía autorizada.

## Pendientes

Los [perfiles operacionales de indicadores](docs/pending/indicator_profiles.md)
están PENDING_GROUP_REVIEW. El benchmark/revisión anterior se conserva fuera de
Git en outputs/layer4/diagnostic_pre_source_refactor como diagnóstico de diseño;
no es ground truth final ni se pide completar sus filas. La selección de LLM,
evaluación final, confianza y Capa 5 siguen pendientes.
