# Contrato definitivo territorial con códigos DANE

## Fuente principal y estructura

La autoridad para los códigos y las relaciones departamento–municipio es:

`data/layer1_sources/reference/Codigos Dane/Tabla_Codigos_Dane.xlsx`

SHA-256: `77ac1090c480457e8b1e95d9cb3a7d53483b9c56189e75fde9c44db78c5dbfef`.

El archivo se inspecciona mediante el normalizador existente `layer2_processing.preprocessing.dane_reference.inspect_catalog`, reutilizando la implementación que ya consumía este Excel. No se modifica el libro ni se requiere reconstruir las publicaciones históricas de referencia.

- `Sheet1`: 1.124 filas, cuatro columnas. Las filas 1–3 forman los encabezados. Hay 1.120 registros de nivel municipal y 33 códigos departamentales diferentes.
- A: código departamental **DD**, dos dígitos.
- B: nombre departamental.
- C: componente municipal **MMM**, tres dígitos.
- D: nombre municipal.
- El código municipal completo es **DD + MMM**, cinco dígitos, y se conserva únicamente para identidad y validación internas. El CSV exporta el componente **MMM**, de tres dígitos, de la columna C.
- `Sheet2` y `Sheet3`: vacías.
- `ALCANCE_NACIONAL`: extensión `COUNTRY` Colombia, código `000`; no se exporta como departamento ni municipio.

El lector valida todos los registros. No existe una tabla parcial de equivalencias por proyecto. Los nombres se comparan sin diferencias de acentos/puntuación y se mantienen códigos de texto.

La referencia pública local ya disponible en `resources/divipola` se usa únicamente como conocimiento secundario: variantes ortográficas, tipología y vínculos de centros poblados. Ningún código ni padre ausente del Excel puede incorporarse a la salida. La implementación funciona con el Excel sin esa referencia secundaria; las localidades que entonces no puedan verificarse quedan pendientes. No se descargó otro catálogo para esta corrección.

Se detectó una anomalía del Excel en D733: **CHACHAGsI**, en la fila A733=`52`, C733=`240`. La evidencia de 21736 escribe Chachagüí y la referencia oficial local ya existente confirma esa grafía para `52240`, con padre `52`. Se utiliza **Chachagüí** en la presentación, conservando en auditoría el texto original, la fila y la fuente de la normalización. También se restauran acentos verificables sin cambiar identidades ni códigos. No se altera el Excel.

## Conocimiento GraphRAG

`descriptores-limpio.csv` aporta los campos sustantivos de proyectos; `produccion-limpio.csv`, los de artículos. La geografía se encuentra en resumen, metodología, objetivos y demás secciones autorizadas, con su procedencia RAW.

Las capas de conocimiento preservan documentos, secciones, fragmentos y metadatos. El grafo factual actual contiene entidades PROJECT, ARTICLE, RESEARCHER, ORGANIZATION e INDICATOR y relaciones explícitas de participación de investigadores. No hay una relación territorial factual que permita deducir automáticamente el municipio desde una afiliación. Los embeddings permiten recuperar documentos; no prueban una ubicación.

La resolución territorial utiliza las citas literales vinculadas a criterios CLEAR/PARTIAL y consulta las secciones sustantivas del mismo SOURCE, sus identificadores de sección y `field_provenance`. El contexto puede desambiguar municipios homónimos o establecer el padre de una vereda/corregimiento. Se validan los resultados contra el Excel completo. Se distinguen declaraciones del ámbito de estudio de referencias, antecedentes y afiliaciones. El título no asigna territorios y un departamento no determina su capital.

## Salida permanente

El exportador común `src/layer4_evaluation/indicator_csv.py`, utilizado por el coordinador y la ejecución autónoma, genera este orden exacto:

```text
proyecto/articulo_siap_id;indicador_id;estado_cumplimiento;parrafo_evidencia;fuente_evidencia;ubicacion_evidencia;confianza;codigo_dane;departamento;codigo_municipio_dane;municipio
```

- `codigo_dane`: exclusivamente el código departamental de **dos dígitos**, o vacío si no se verifica uno.
- `departamento`: nombre correspondiente al código validado.
- `codigo_municipio_dane`: exclusivamente el componente municipal **MMM, de tres dígitos**, exactamente el valor normalizado de la columna C, o vacío. Las celdas numéricas se normalizan como texto: `1` → `001`, `10` → `010`, `240` → `240`. Se rechazan componentes de cinco dígitos; no se truncan códigos arbitrariamente.
- `municipio`: nombre del municipio validado, o vacío junto con su código.
- Una fila por evaluación fuente–indicador, sin modificar sus siete campos originales.
- CSV separado por punto y coma, UTF-8 con BOM. No se introducen fórmulas, apóstrofos ni conversiones numéricas en los identificadores.

Para múltiples municipios de un mismo departamento, el principal conserva el departamento común y deja vacíos los campos municipales escalares. Para múltiples departamentos, deja vacíos los cuatro campos geográficos escalares. En ambos casos, **todas** las relaciones verificadas permanecen en `indicadores_territorios_relaciones.csv`, con códigos departamentales y municipales en columnas separadas. No se mezclan códigos ni se introducen arrays dentro de las claves para cruces externos. El puente carece de medidas de evaluación que puedan duplicarse al agregarlas.

`territorios_auditoria.json` identifica los casos múltiples, los pendientes, las fuentes, las normalizaciones y el manifiesto del Excel. Si únicamente se verifica el departamento, conserva su código/nombre y deja vacío el municipio. Los centros poblados y veredas no se convierten en municipios sin un vínculo verificable.

Para Power BI/Excel, importar `codigo_dane`, `codigo_municipio_dane` y los identificadores como **Texto**, antes de la detección/conversión automática de tipos. El CSV conserva literalmente valores como `05` y `001`; no contiene metadatos de tipos que impidan la conversión automática del consumidor. En Excel: **Datos → Desde texto/CSV → Transformar datos**, seleccionar `codigo_municipio_dane` y asignar **Texto** antes de cargar, eliminando cualquier paso previo de conversión numérica. En Power BI: **Obtener datos → Texto/CSV → Transformar datos**, asignar **Texto** a ambas columnas de códigos antes de cualquier conversión automática. Para cruces municipales se utiliza el par `(codigo_dane, codigo_municipio_dane)`; el componente `001` por sí solo se repite entre departamentos.

## Archivo existente corregido

Se actualizó directamente:

`outputs/runs/local/run_20261116_094429_222507/resultados/indicadores_territorios.csv`

| Proyecto | codigo_dane | departamento | codigo_municipio_dane | municipio | Registros |
|---|---|---|---|---|---:|
| 21736 | 52 | Nariño | 240 | Chachagüí | 1 |
| 21750 | 11 | Bogotá, D.C. | 001 | Bogotá, D.C. | 14 |
| 21869 | 11 | Bogotá, D.C. | 001 | Bogotá, D.C. | 9 |

Se verificaron las ubicaciones contra las fuentes originales, los campos documentales de los planes GraphRAG y las evidencias persistidas. Matarredonda se vincula explícitamente con Chachagüí; los otros dos proyectos describen sus poblaciones/territorio piloto en Bogotá.

Los **24 registros** mantienen su orden, los siete campos de evaluación y los códigos departamentales del respaldo original de ocho columnas. La última corrección solo modifica `codigo_municipio_dane`: las otras diez columnas son idénticas al respaldo inmediato. Ninguno queda sin municipio.

Se conservan los respaldos anteriores y un nuevo respaldo inmediato `indicadores_territorios.csv.before-municipal-component-<hash>.bak`, así como el equivalente del puente. El recibo actual es `correccion_componente_municipal.receipt.json`: documenta los hashes y la conservación de las otras diez columnas. `correccion_territorial_dane_v2.receipt.json` y los anteriores recibos describen versiones históricas.

La reparación utilizó los resultados guardados y el verificador de planes/recibos; no ejecutó modelos, embeddings ni cálculos de confianza. El script de mantenimiento no forma parte de la generación habitual.

## Archivos implicados

- `src/layer4_evaluation/territories/catalog.py`: lectura directa del Excel, autoridad de códigos y padres, conocimiento secundario filtrado y normalizaciones auditadas. La proyección ahora devuelve exclusivamente el componente municipal de tres dígitos, manteniendo y contrastando la identidad completa interna.
- `src/layer2_processing/preprocessing/dane_reference.py`: opción explícita para rellenar con ceros componentes municipales numéricos al leer este catálogo. El comportamiento predeterminado del lector histórico y sus validaciones se conserva.
- `src/layer4_evaluation/territories/document_resolution.py`: resolución contextual y variantes de Bogotá compatibles con el Excel.
- `src/layer4_evaluation/indicator_csv.py`: once columnas definitivas, claves escalares y puente compatible.
- `scripts/pipeline_coordinator.py` y `src/autonomous_execution/final_output.py`: integraciones con el exportador común y su auditoría, conservadas.
- `scripts/repair_territorial_export.py`: migración histórica con respaldos y comparación literal.
- `tests/test_document_territories.py`, `tests/test_indicator_csv.py`, `tests/test_thesis_output.py` y `tests/test_prospective_v2.py`: formato, autoridades, cobertura nacional y las dos rutas de exportación.
- Este informe y `resources/divipola/README.md`: documentación de la autoridad principal y secundaria.
- El CSV solicitado, su puente, auditoría, respaldos y recibo V2 dentro de la ejecución indicada.

El libro DANE, los datos originales y los resultados semánticos permanecen intactos. No se incluyen en este trabajo los cambios preexistentes de otras funciones del repositorio.

## Pruebas

Se comprueba automáticamente la conservación de las 24 filas y sus códigos originales, la igualdad de los siete campos de evaluación, el esquema exacto de once columnas, el ancho textual de los códigos, los casos sin municipio, los homónimos, las localidades menores, múltiples territorios, las variantes y las fuentes documentales.

Una prueba exporta y valida las **1.153 entradas completas del Excel**. Otra comprueba la resolución explícita de todas las unidades clasificadas como municipio, con su departamento. También se rechazan códigos presentes únicamente en la referencia secundaria y se comprueba la operación sin ella. Las pruebas de integración verifican la salida automática del coordinador y de la ejecución autónoma.

La ejecución ampliada registrada en `.tmp/territorial-dane-v2.xml` produjo **191 pruebas aprobadas y un fallo histórico por un archivo ausente**: `tests/layer5_preparation/test_dane_unification.py::test_dane_reference_function_bodies_are_unchanged` necesita `archives/layer4/pre_layer1_unification.zip`, que no está instalado. No se modificó `dane_reference.py` ni se fabricó el archivo para satisfacer esa prueba. Las 63 pruebas específicas de territorio/formato pasaron; las comprobaciones adicionales de las dos rutas de exportación también pasaron después de añadir verificaciones explícitas de las columnas/códigos.

Comando ejecutado:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_document_territories.py tests/test_indicator_csv.py tests/layer5_territories/test_matching.py tests/layer5_territories/test_dane_reference.py tests/layer5_preparation/test_dane_unification.py tests/test_prospective_v2.py tests/test_thesis_output.py::test_valid_output_keeps_seven_numeric_columns_and_technical_states_only_in_audit -q --tb=short --junitxml=.tmp/territorial-dane-v2.xml
```

El Excel conserva el SHA-256 indicado al inicio y `git diff --check` no presenta errores.

### Validación de la representación municipal de tres dígitos

La última ejecución específica produjo **94 pruebas aprobadas**. Incluye la exportación del catálogo completo, la conservación literal de las otras diez columnas y los 24 registros, el valor `001` para Bogotá, `240` para Chachagüí, ausencia de componentes de cinco dígitos, campos vacíos para municipios no verificados y pruebas de columnas C numéricas (`1`, `10`, `240`) conservando las identidades completas internas.

No se modificó la extracción documental, el conocimiento territorial ni los nombres validados. La conversión de los CSV existentes consultó exclusivamente el Excel, y el exportador permanente utiliza la misma columna C validada.
