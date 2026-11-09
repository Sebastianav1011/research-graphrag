> Suite canónica: `tests/layer3_knowledge`. Los nombres de contratos y publicaciones que siguen pueden conservar numeración histórica.

# Pruebas de Capa 2

## Propósito

Verifica preparación determinística y contratos knowledge, separando pruebas
técnicas del consumo de datos institucionales.

## Archivos principales

| Archivo | Responsabilidad |
|---|---|
| [test_unit.py](test_unit.py) | Normalización, chunking/offsets, schemas, IDs/lineage, privacidad, reportes y rollback con fixtures/mocks. |
| [test_integration_real.py](test_integration_real.py) | Documentos y campos reales, provenance, relaciones explícitas, calidad, idempotencia y publicación existente. |

## Funcionamiento

Unitarias prueban funciones y fallos de publicación sin corpus institucional.
Las reales cargan canonical aprobado, construyen paquetes en memoria y contrastan
knowledge existente; no publican una nueva instantánea.

## Entradas y salidas

Técnicas: valores controlados y temporales. Reales: canonical/knowledge oficiales,
configuración aprobada, manifests y archivos de runs anteriores para comprobar
dos publicaciones. Las validaciones no reconstruyen RAW.

## Relación con otras capas

Comprueba que el productor de Capa 1 mantiene sus contratos y que Capa 3 recibirá
tablas completas, trazables y separadas de REFERENCE.

## Ejecución

Ligera: `uv run python -B -m pytest tests/layer3_knowledge/test_unit.py -q -p no:cacheprovider`.

Para reales activar LAYER2_REAL_INTEGRATION=1; la comprobación de publicación
exige además LAYER2_VERIFY_PUBLICATION=1. LAYER2_CONFIG permite configuración
alternativa revisada. Comandos y limpieza de variables: [tests](../README.md).
