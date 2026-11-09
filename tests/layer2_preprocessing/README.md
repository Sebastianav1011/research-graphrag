> Suite canónica: `tests/layer2_preprocessing`. Los nombres de contratos y publicaciones que siguen pueden conservar numeración histórica.

# Pruebas de Capa 1

## Propósito

Comprueba ETL e identidad con fixtures ficticias, sin usar fuentes institucionales
para las pruebas ordinarias.

## Archivos principales

| Archivo | Responsabilidad |
|---|---|
| [conftest.py](conftest.py) | Prepara settings, workspace temporal y registros de prueba. |
| [test_ingest.py](test_ingest.py) | CSV multilínea, filas físicas, encoding, faltantes e inmutabilidad RAW. |
| [test_normalization.py](test_normalization.py) | Unicode, ceros iniciales, identificadores, fechas, keywords y comillas configuradas. |
| [test_validation.py](test_validation.py) | Columnas/IDs obligatorios, duplicados, fechas, tipos y privacidad de anomalías. |
| [test_identity.py](test_identity.py) | Reglas exactas, homónimos, conflictos de componentes y orden independiente. |
| [test_final_domain.py](test_final_domain.py) | Títulos consistentes, aliases institucionales/documentales y cuarentena de producción. |
| [test_pipeline.py](test_pipeline.py) | ETL sintético, contratos, plantilla, idempotencia, locks y conservación de publicación ante fallos. |

## Funcionamiento

Las fixtures crean una raíz temporal → ejecutan funciones o pipeline → contrastan
Parquet/provenance/anomalías y rollback. No se usa la configuración real de fuentes
para sobrescribir canonical institucional.

## Entradas y salidas

Fixtures de data/samples/synthetic y configuración de tests. Salidas en temporales
pytest; la plantilla versionada se lee para comprobar su contrato.

## Relación con otras capas

Protege el canonical consumido por Capa 2. Las pruebas de la extensión DANE están
en [territories](../territories/README.md), no en este paquete.

## Ejecución

Desde la raíz: `uv run python -B -m pytest tests/layer2_preprocessing -q -p no:cacheprovider`.
Preparar el padre outputs del basetemp como indica [tests](../README.md).
