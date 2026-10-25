# Pruebas territoriales

## Propósito

Comprueba referencia DANE, detección/resolución y publicación PROJECT_TERRITORY_V1.
Incluye pruebas sintéticas y comprobaciones de datos reales en los mismos módulos.

## Archivos principales

| Archivo | Responsabilidad |
|---|---|
| [test_dane_reference.py](test_dane_reference.py) | Códigos/ceros, esquema XLSX, nombres duplicados, COUNTRY interno, versiones y detección de cambios; exige el catálogo real en una prueba. |
| [test_matching.py](test_matching.py) | Matching exacto, offsets, contexto local, ambigüedad, guardias léxicas, deduplicación y política Colombia/000 con fixtures y catálogo real. |
| [test_publication.py](test_publication.py) | Tablas vacías tipadas, inputs cerrados, calidad, locks/rollback y checks de publicación real, CSV/workbook/idempotencia. |

## Funcionamiento

Fixtures crean catálogos/raíces efímeras para casos controlados. Los tests reales
cargan la referencia y publicaciones existentes; la fixture real_publication
omite esas pruebas si falta el manifest. Otras pruebas reales de catálogo fallan
si falta el XLSX: no existe un opt-in global uniforme.

## Entradas y salidas

XLSX sintéticos en temporales y referencia DANE autorizada. Para aceptación real:
knowledge, dimensión procesada, outputs territoriales y evidencias de integridad.
Las pruebas técnicas escriben solo sus temporales; no reconstruyen GraphRAG.

## Relación con otras capas

La referencia es Capa 1 y los textos PROJECT son Capa 2. La suite protege la
independencia respecto a Capa 3, modelos, red y LLM. Los ambiguos no se publican
como relaciones y los códigos conservan ceros iniciales.

## Ejecución

En entorno con los inputs autorizados:
`python -B -m pytest tests/territories -q -p no:cacheprovider`.

El [verificador territorial](../../scripts/verify_territories.py) exige además
dos builds idénticos, baseline previo y publicación compatible. No se ejecuta el
pipeline para obtener documentación. Véase [tests](../README.md).
