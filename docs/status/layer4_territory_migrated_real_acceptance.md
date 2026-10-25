# Aceptación real de Capa 4B después de la migración

**Estado:** `LAYER4B_MIGRATED_REAL_ACCEPTED`.

**Fecha de aceptación UTC:** `2026-10-18T00:29:11.388264+00:00`.

Esta acta resumida registra la validación del código migrado a
`src/layer4/territories/`, para los fingerprints y snapshots indicados.
No reemplaza la publicación vigente ni reescribe la
[aceptación territorial histórica](layer4_territory_v1_acceptance.md).
La arquitectura funcional continúa siendo `PROJECT_TERRITORY_V1`.

## Procedimiento y aislamiento

La validación utilizó copias independientes de código, configuración, catálogos
y publicaciones existentes en una ubicación temporal ignorada por Git.
No se utilizaron enlaces duros ni junctions. Se comprobó la ausencia de procesos
de producción y locks activos antes de ejecutar. No se abrieron fuentes RAW.
Se ejecutaron dos builds reales con el código migrado y las mismas entradas,
y se compararon con la publicación territorial histórica aceptada.

## Pruebas ejecutadas

| Suite final | PASS | FAIL/ERROR | SKIPPED |
|---|---:|---:|---:|
| Territorial completa, incluidos datos reales | 101 | 0 | 0 |
| Capa 4A: perfiles, assessment con fixtures/mocks, confidence y exportación | 261 | 0 | 0 |
| Capa 1 con datos sintéticos | 70 | 0 | 0 |
| Capas 2/3: unitarias y mocks | 242 | 0 | 0 |
| **Total distinto** | **674** | **0** | **0** |

Antes de los builds también pasó una ejecución adicional de las 101 pruebas
territoriales sobre la publicación histórica copiada. No se ejecutó la
integración de Capa 3 que reconstruye embeddings.

El primer intento de Capa 1 tuvo 1 fallo y 11 errores por fixtures sintéticos
y plantilla ausentes en la copia aislada. Se completaron sus copias y se repitió
la suite sin cambiar código ni aserciones: 70 PASS. El registro original se conserva.

Las suites se ejecutaron por procesos separados cuando lo exigen sus fixtures,
con `python -B -m pytest`, `-p no:cacheprovider` y directorios temporales aislados.
Se validaron los ocho schemas de Capa 4, los contratos de Capas 2/3, imports y
entrypoints. `git diff --check` pasó.

## Equivalencia de resultados

| Resultado | Histórico | Migrado |
|---|---:|---:|
| PROJECT procesados | 2232 | 2232 |
| PROJECT con territorio resuelto | 1366 | 1366 |
| Relaciones publicadas | 2654 | 2654 |
| MUNICIPALITY | 990 | 990 |
| DEPARTMENT | 1147 | 1147 |
| COUNTRY Colombia 000 | 517 | 517 |
| Evidencias | 7135 | 7135 |
| Menciones AMBIGUOUS | 757 | 757 |
| Menciones nacionales auditadas | 4718 | 4718 |

Los cuatro Parquet y el CSV territorial coinciden byte a byte con los históricos.
También coinciden schemas, orden y valores de todas las filas, IDs, offsets,
candidatos ambiguos y hashes lógicos. Las hojas RESUELTOS, AMBIGUOS y CATALOGO_DANE
del workbook coinciden celda a celda. No se detectaron diferencias de comportamiento.

Se conservaron códigos como strings, ceros iniciales, ambigüedades sin código
publicado y la distinción DANE/INTERNAL. `COUNTRY | 000 | Colombia` sigue siendo
una convención INTERNAL y no duplica territorios subnacionales resueltos.

## Idempotencia y diferencias operacionales

**Idempotencia: PASS.** Ambos builds migrados tienen el mismo código, inputs,
build ID y payloads. Los Parquet, CSV y resumen son idénticos entre ambos.
El primer build registra `FIRST_BUILD_OR_INPUT_CHANGE` frente a la copia histórica;
el segundo registra `PASS` con `same_inputs_and_code=true`.

Las diferencias frente al histórico son operacionales: rutas/fingerprint de código,
build ID y fecha. En METADATA del workbook solo cambian `build_id`, `code_hashes`
y `generated_at_utc`. El verificador nuevo validó `CURRENT_PUBLICATION_CODE`,
sin usar el ZIP histórico para aceptar el código migrado.

| Identidad | Valor |
|---|---|
| Build histórico | `8c0fbeb9729aaa884179a39eb2b196b522d2045150976f699c4d3d1756997c99` |
| Build migrado, repetido dos veces | `3923240587e4625b40de7be09a4d734c67d7262bff37dcc95715c236bb8e2e7e` |

## Fingerprints del código aceptado

Son hashes de los archivos efectivamente utilizados en los builds. Cambiar
contenido o rutas de estos archivos exige evaluar una identidad nueva; esta
aceptación no cubre automáticamente esos cambios.

| Archivo relativo al repositorio | SHA-256 |
|---|---|
| `scripts/render_territory_workbook.mjs` | `c4e5c76226d13956155337ee14bf70f40b4ff1ed7c5f33cb210fe42ef6dae715` |
| `scripts/run_territories.py` | `c4804c26dcb5ab6b76b86b71c00e2913559b152522a05543adfa59970d6eb0ec` |
| `src/layer1_territories/__init__.py` | `acd2d7bec2bb7ea7c4ac6ab7922ba7a63a47ed118bf7718d3b6e3e7278359334` |
| `src/layer1_territories/reference.py` | `acfc7a1b7370d774acdd842e57dd061b2b7b930a6fd82a3b9c43549a7e03c19a` |
| `src/layer4/__init__.py` | `ff8ef184b80a14ba1e85df5e2e8ba2d2e0fb947e1baf842241be5edad60c5518` |
| `src/layer4/territories/__init__.py` | `9bd0f92a3fd8c9f3bbc5cf78ca04769f65cb1d45f935e68e97aa9a552f0f1a8c` |
| `src/layer4/territories/contracts.py` | `e38b776ce723fd5489f720520709abfd0a0e2f713d15572e8e533b24bfcf7db8` |
| `src/layer4/territories/inputs.py` | `c40378e753c69877f02f0fe5e4361b6217ed5a1b6f8a583f2105ef31d032bac4` |
| `src/layer4/territories/matching.py` | `c9b8367a4812e309f74d84ef94eb6648eca39e2889a25a19700ef103b72b3dfb` |
| `src/layer4/territories/pipeline.py` | `f818de8bbce2db0561c03934f4d22b4eb1b04f201756f5c05094b44e3797d433` |
| `src/layer4/territories/workbook.py` | `dbececde56de96e045570fb15c35a09d8cab0859c1eb505039954dd96fc40e93` |

## Fingerprints de entradas y payloads

| Entrada | SHA-256 |
|---|---|
| Manifest publicado de Capa 2 | `b0ec6990c8dc9d38398c780af4d51ed9c16c80e5504d7d70abd548fbe62d472f` |
| source_documents | `f3b9a596bfbd41779455410dc05a831d3d15c5c0019751569281695b4eb8d116` |
| source_sections | `c40acdff8ec32c38b9b61e7533da394ac1923fe31ace1a8a0473957f3aa24f82` |
| XLSX DANE autorizado | `77ac1090c480457e8b1e95d9cb3a7d53483b9c56189e75fde9c44db78c5dbfef` |
| Catálogo de indicadores v2, verificación 4A | `1aeb1a376c24bca7bdd7acd228da527ef0043f0574541649589badb54e1cf88f` |

| Payload territorial | Hash lógico SHA-256 |
|---|---|
| `ambiguous` | `990ae2d6b355ca45bd4ce43232868e83f4ad5ea5ee9b5875d2719c1b271b9915` |
| `evidence` | `7ded824342d42301c735f0851ebd6eb734840f313ffb0aea3e0a5df5dcbd29af` |
| `national_mentions` | `0614576cdd45767498258dd0f668b4296f22245c5c4103287de26b6b9b97cab9` |
| `relationships` | `803db4c3e924212767334cf45152c1aa528b26ed409bf075853847b1f7b048e6` |
| `summary` | `9c846a79c5ff9f7f80b460c6750d9ac102cc43bc3337b064114b74e6a9db5521` |

## Capa 4A y alcance de esta aceptación

Los 48 perfiles publicados coinciden con la proyección determinística del XLSX v2.
Los 48 mappings siguen UNMAPPED y `preferred_evidence_fields=[]`.
`RAW_CONFIDENCE_V1` conserva su fórmula y reproduce 87.50 con
K=0.75, F=1.00, C=1.00 y S=0.75; probability/level permanecen NULL.
La preparación, selección, validación y exportación se comprobaron con las
pruebas correspondientes. No se ejecutó assessment LLM ni se otorga aquí
una aceptación final de Capa 4A.

## Integridad y evidencia

Los 2280 archivos originales del baseline y seis entradas adicionales de tests
conservan sus hashes. Capas 1/2/3, catálogos, configuraciones, contratos,
publicaciones, manifests y aceptaciones anteriores permanecen intactos.
El estado Git antes y después de la validación coincidió.

No se requieren correcciones de aplicación. No hubo LLM, API externa, nuevo
retrieval, recálculo de embeddings institucionales, commit ni push.

La evidencia detallada permanece local en
`.tmp/layer4-real-validation-20261017/`: acta JSON, hashes antes/después,
manifests de los dos builds, comparación y reportes JUnit. Se conserva sin
publicar porque contiene copias institucionales y rutas operacionales privadas.
Este resumen no incorpora filas de proyectos, títulos, citas, identificadores
personales, credenciales ni rutas personales absolutas.

SHA-256 del acta privada original: `a169755a3c083cdb7ddb091012998baf22551c98ca57898fc1c635575a2adcaf`.
