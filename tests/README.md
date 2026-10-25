# Pruebas

## Propósito

Protege contratos, transformaciones y fronteras entre capas. Una prueba sintética
no acredita una publicación institucional ni una aceptación de exactitud semántica.

## Archivos principales

| Carpeta / archivo | Qué protege | Datos o herramientas |
|---|---|---|
| [layer1](layer1/README.md) | Parsing, normalización, identidad, canonical, calidad y publicación | Fixtures públicas y temporales |
| [layer2](layer2/README.md) | Documentos/chunking/provenance y publicación knowledge | Unitarias técnicas; reales con opt-in |
| [layer3](#capa-3-módulos-de-pruebas) | Configuración, índices, grafo, retrieval y SOURCE context | Mocks en ligeras; reales con opt-in y modelos |
| [layer4_confidence/test_confidence.py](layer4_confidence/test_confidence.py) | RAW_CONFIDENCE_V1, gates, Unicode, rangos, redondeo, repetibilidad y exclusión de retrieval | Inputs en memoria; sin proveedor |
| [layer4_preparation](layer4_preparation/README.md) | Perfiles, assessment, contratos, exportación y migraciones | Fixtures ligeros; las pruebas que requieren ZIP históricos ausentes necesitan obtenerlos |
| [layer4_preliminary/test_preliminary.py](layer4_preliminary/test_preliminary.py) | Selección, prompt, wrapper, retry técnico, diagnósticos y exportación preliminar | Proveedores y subprocess simulados; sin LLM real |
| [layer4_powerbi/test_powerbi.py](layer4_powerbi/test_powerbi.py) | Proyección de consumo, IDs/códigos string, citas, scores y edición territorial del workbook | Filas y XLSX en memoria; sin assessment |
| [territories](territories/README.md) | DANE, matching/resolución, calidad y publicación 4B | Fixtures más catálogo/publicación reales |

Las tres carpetas con un solo módulo de tests se explican aquí para evitar
README redundantes. Los archivos de Capa 3 se documentan abajo porque añadir
README dentro de tests/layer3 cambiaría el fingerprint protegido.

## Funcionamiento

Unitarias comprueban funciones con valores controlados. Integraciones simuladas
usan fixtures, Parquet temporales y proveedores determinísticos para comprobar
interacciones y fallos. Integraciones reales leen publicaciones/catálogos
autorizados y, según el test, ejecutan validación o builds locales.

pytest.ini agrega src al import path, define testpaths=tests/layer1 y usa
outputs/test-temp como basetemp. Por eso `python -m pytest` **no cubre todas las
capas**. Ejecutar cada familia por separado, especialmente las que tienen
conftest con nombres compartidos. Los directorios basetemp son temporales:
pytest puede limpiarlos antes de una nueva ejecución; no guardar allí evidencia.

## Entradas y salidas

Fixtures públicas de data/samples/synthetic y datos en memoria; para reales,
canonical/knowledge/graphrag, catálogos, baselines, manifests y actas privadas.
Las salidas de tests son temporales, workbooks de fixtures y reportes JUnit si se
solicitan. No son publicaciones institucionales ni resultados de tesis.

## Relación con otras capas

Los tests verifican contratos de productores y consumidores sin modificar el
código para adaptarse a la documentación. La confianza no usa rankings; los
territorios no dependen de Capa 3. Las pruebas históricas distinguen bytes
archivados de aceptación del código actual.

## Ejecución ligera

Desde la raíz y con el entorno base/dev instalado:

```powershell
New-Item -ItemType Directory -Force outputs | Out-Null
python -B -m pytest tests/layer1 -q -p no:cacheprovider
python -B -m pytest tests/layer2/test_unit.py -q -p no:cacheprovider
python -B -m pytest tests/layer3 --ignore=tests/layer3/test_integration_pending.py -q -p no:cacheprovider
python -B -m pytest tests/layer4_confidence -q -p no:cacheprovider
python -B -m pytest tests/layer4_preliminary -q -p no:cacheprovider
python -B -m pytest tests/layer4_powerbi -q -p no:cacheprovider
```

Si se cambia --basetemp, crear primero su directorio padre. No usar un directorio
de resultados persistidos. Para JUnit, --junitxml debe apuntar a una ubicación
de reportes preparada explícitamente.

## Integraciones reales: solo con autorización

Capa 2 usa dos opt-in; el segundo habilita la prueba de dos publicaciones:

```powershell
$env:LAYER2_REAL_INTEGRATION = '1'
$env:LAYER2_VERIFY_PUBLICATION = '1'
python -B -m pytest tests/layer2/test_integration_real.py -q -p no:cacheprovider
Remove-Item Env:LAYER2_REAL_INTEGRATION
Remove-Item Env:LAYER2_VERIFY_PUBLICATION
```

Lee canonical/knowledge y puede ejecutar validate en memoria; no publica
knowledge. Requiere snapshots, hashes aprobados y dos publicaciones compatibles
para la prueba final.

Capa 3 es más costosa y puede reconstruir embeddings y artefactos en temporales:

```powershell
$env:LAYER3_RUN_REAL_INTEGRATION = '1'
python -B -m pytest tests/layer3/test_integration_pending.py -q -p no:cacheprovider
Remove-Item Env:LAYER3_RUN_REAL_INTEGRATION
```

También existe `python scripts/run_layer3.py --mode test --real-integration`:
habilita integraciones de Capas 2/3 y escribe JUnit/reportes por procesos.
**No activarlo automáticamente ni para comprobar documentación.**

En territories y layer4_preparation no hay un opt-in global equivalente:
algunos tests exigen catálogo/evidencias y fallan si faltan; otros omiten pruebas
cuando no existe publicación. Ejecutar esas suites completas únicamente en el
entorno autorizado. No interpretar un skip como aceptación real.

## Verificadores de aceptación

| Comando desde la raíz | Alcance / efectos |
|---|---|
| python scripts/verify_layer1.py --existing | Lee dos publicaciones canonical y fuentes; escribe reportes. Sin --existing ejecuta dos ETL. |
| python scripts/verify_layer2.py | Reconcilia snapshots/baselines e idempotencia histórica; escribe acceptance.json. |
| python scripts/run_layer3.py --mode verify | Comprueba publicación GraphRAG; escribe reporte, sin nuevos embeddings. |
| python scripts/verify_territories.py | Read-only; exige referencia, publicación, baseline y dos builds compatibles. |
| python scripts/auxiliary/verify_layer4_preparation.py | Read-only del cierre histórico; requiere JUnit, actas, ZIP y referencias; ejecuta contract checks. |
| python scripts/run_layer4_preliminary.py --verify | Read-only del preliminar persistido; no invoca Codex CLI. |

Ninguno sustituye un benchmark humano. Baselines históricos no deben reescribirse
para tolerar cambios. Los schema checks con --check se describen en
[schemas](../schemas/README.md).

## Capa 3: módulos de pruebas

| Archivo | Funcionalidad protegida |
|---|---|
| [conftest.py](layer3/conftest.py) | Snapshots efímeros, configuración cerrada y FakeProvider en memoria. |
| [test_configuration.py](layer3/test_configuration.py) | Gates, hashes y límites seguros de rutas/configuración. |
| [test_inputs.py](layer3/test_inputs.py) | Ocho tablas, tipos Arrow, lineage y detección de mutaciones de snapshot. |
| [test_embeddings.py](layer3/test_embeddings.py) | Cache, fingerprints, bundles, dimensiones y adaptador lazy mediante mocks. |
| [test_vector.py](layer3/test_vector.py) | Cosine exacto, ranking, persistencia e integridad del índice. |
| [test_graph.py](layer3/test_graph.py) | Aristas factuales, límites, identidad y bridges resolved_only. |
| [test_indicator_retrieval.py](layer3/test_indicator_retrieval.py) | Expansión factual con soporte semántico y candidatos de referencia. |
| [test_source_context.py](layer3/test_source_context.py) | Todas las secciones SOURCE, roles de campos y separación discovery/evidencia. |
| [test_evaluation.py](layer3/test_evaluation.py) | Métricas con ground truth explícito; ausencia de etiquetas no se presenta como PASS. |
| [test_provenance.py](layer3/test_provenance.py) | IDs/hashes y trazabilidad de recuperación. |
| [test_orchestration.py](layer3/test_orchestration.py) | Plan, calidad, publicación/rollback y despacho sin ejecución institucional. |
| [test_integration_pending.py](layer3/test_integration_pending.py) | Integración real opt-in sobre snapshots aprobados, modelo y artefactos. |
