> Suite canónica: `tests/layer5_preparation`. Los nombres de contratos y publicaciones que siguen pueden conservar numeración histórica.

# Pruebas de preparación y contratos de Capa 4

## Propósito

Protege perfiles, assessments estructurados, exportación y equivalencia de
migraciones sin ejecutar LLM. La suite completa también lee evidencias locales;
no es una suite sintética autónoma de un clon sin datos.

## Archivos principales

| Archivo | Responsabilidad |
|---|---|
| [conftest.py](conftest.py) | Fixtures PROJECT/perfil/assessment, metadata y workbook sintético. |
| [test_profiles.py](test_profiles.py) | Parseo conservador, preferencias explícitas, publicación/tamper de perfiles y comprobación del catálogo v2 real. |
| [test_assessment_contract.py](test_assessment_contract.py) | Transporte estructurado, combinaciones de decisión/strength, citas, campos y filas con confianza. |
| [test_output.py](test_output.py) | Cuatro hojas, evidencia alineada, límites de exportación, proveedor falso y metadata preparada local. |
| [test_territory_contract.py](test_territory_contract.py) | Proyección de territorios a consumo, códigos string y distinción COUNTRY/INTERNAL. |
| [test_migration.py](test_migration.py) | Bytes históricos, ZIP, seguridad de rutas, cuerpos AST y ausencia de wrappers obsoletos. |
| [test_dane_unification.py](test_dane_unification.py) | DANE unificado en layer1_data, equivalencia archivada y ROOT de scripts auxiliares. |

## Funcionamiento

Fixtures → validación/formas → componentes/filas → exportación sintética.
Las pruebas de migración leen originales de archives/layer4 para comprobar
preservación; no importan esos ZIP como código ni reescriben sus hashes.

## Entradas y salidas

Inputs en memoria, XLSX temporales, catálogos/metadata de preparación privados y
ZIP históricos esperados por history.py. Estos últimos están ausentes del árbol
inspeccionado y son necesarios para los tests de migración. Workbooks y referencias de fixtures se escriben en
temporales; las comprobaciones de datos reales leen el estado local.

## Relación con otras capas

Protege contratos de 4A y consumo de 4B sin reconstruir Capa 3. Distingue aceptación
histórica de una nueva aceptación del código migrado.

## Ejecución

En entorno autorizado: `uv run python -B -m pytest tests/layer5_preparation -q -p no:cacheprovider`.
No hay opt-in global que omita todos los accesos reales. Para confianza pura o
runner con mocks usar las suites descritas en [tests](../README.md).
