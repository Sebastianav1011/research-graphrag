# Capa 4B — territorios

## Propósito

Caracteriza menciones territoriales de todos los PROJECT mediante catálogo autorizado y reglas determinísticas, con evidencia separada de la bridge resuelta.

## Archivos principales

| Archivo | Responsabilidad |
|---|---|
| [inputs.py](inputs.py) | Verifica manifest real/SUCCESS, hashes, schemas y claves de source_documents/source_sections; comprueba invariancia. |
| [matching.py](matching.py) | Detecta nombres exactos, conserva offsets y resuelve con nivel/contexto local; aplica guardias léxicas y registra ambigüedad. |
| [contracts.py](contracts.py) | Define tablas Arrow tipadas y proyección de consumo con code_system DANE/INTERNAL. |
| [pipeline.py](pipeline.py) | Valida resultados, CSV/workbook e idempotencia; publica candidato con lock, archivo previo y rollback. |
| [workbook.py](workbook.py) | Construye vista de revisión con contextos y metadata; exporta con Artifact Tool o fallback openpyxl. |
| [__init__.py](__init__.py) | Declara la frontera independiente de 4B. |

## Funcionamiento

load_projects + load_reference → extract_territories → calidad/roundtrip → workbook/CSV → publicación. Varias menciones conservan evidencia completa, pero la bridge deduplica project_id + territory_type + dane_code. AMBIGUOUS nunca asigna código.

## Entradas y salidas

Lee data/knowledge/source_documents.parquet y source_sections.parquet, y data/reference/processed/dane_reference_manifest.json con su dimensión. Escribe project_territories.parquet, evidencia, ambiguos, menciones nacionales, resumen, manifest, CSV y revision_territorios.xlsx en outputs/layer4/territorios/publicacion; archiva anteriores en outputs/layer4/territorios/versiones.

## Relación con otras capas

Consume datos de Capa 2 y referencia DANE construida en Capa 1. No importa ni ejecuta GraphRAG, embeddings, geocoding o LLM. COUNTRY/000 es INTERNAL, exige mención explícita y se suprime si existe municipio/departamento resuelto.

## Ejecución

Usar [Capa 4B en la guía](../../../README.md#6-capa-4b--ejecución-independiente). [run_territories.py](../../../scripts/run_territories.py) publica; [verify_territories.py](../../../scripts/verify_territories.py) verifica una publicación compatible con dos builds y baseline existente. No reemplazar baselines históricos.
