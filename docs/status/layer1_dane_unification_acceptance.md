# Aceptación de la unificación DANE y revalidación territorial

**Estado:** `LAYER1_DANE_UNIFICATION_AND_TERRITORY_REVALIDATED`.

**Fecha UTC:** `2026-10-18T02:00:50.294696+00:00`.

Aceptación limitada al código y snapshots indicados. La publicación activa y
las actas anteriores no se sustituyeron. Esta validación es posterior a la
[migración territorial de Capa 4](layer4_territory_migrated_real_acceptance.md).

## Cambios y aislamiento

- Cuatro scripts auxiliares trasladados, dos herramientas obsoletas retiradas.
- DANE se importa desde `layer1_data.dane_reference`, sin paquete territorial paralelo.
- El módulo DANE conserva exactamente sus bytes y funciones originales.
- Los diez archivos canonical preexistentes no cambiaron. No se modificó su snapshot.
- La dimensión DANE mantiene dataset, rutas y versiones independientes.
- No se reorganizaron Capas 2/3/4; solo se ajustaron consumidores y fingerprints necesarios.
- Pruebas reales sobre copias independientes, sin hardlinks ni publicación productiva.

## Pruebas

| Etapa | PASS | FAIL/ERROR | SKIPPED |
|---|---:|---:|---:|
| Baseline completo anterior | 674 | 0 | 0 |
| Fase 1: suite de Capa 4A tras mover scripts | 261 | 0 | 0 |
| Final Capa 1 | 70 | 0 | 0 |
| Final Capa 2/3, unitarias y mocks | 242 | 0 | 0 |
| Final Capa 4A y tres pruebas nuevas de unificación | 264 | 0 | 0 |
| Final territorio completo, incluidas integraciones reales | 101 | 0 | 0 |
| **Total final distinto** | **677** | **0** | **0** |

No se ejecutó la integración que reconstruye embeddings de Capa 3. Se conservaron
las aserciones anteriores, sin nuevos skips. Los contratos, imports y ayudas CLI
aplicables pasaron. El verificador histórico de preparación funciona desde
`scripts/auxiliary/verify_layer4_preparation.py`, con sus criterios originales.

## Referencia DANE

Dos builds independientes en un output de prueba produjeron manifests y archivos
idénticos. Las 1154 filas, schema y Parquet coinciden con la dimensión vigente:
33 departamentos, 1120 municipios y una extensión COUNTRY. Se mantienen códigos
string, ceros iniciales, provenance, índice de ambigüedad y COUNTRY000 INTERNAL.
Solo cambia la identidad del constructor/versión de prueba; no se publicó esa versión.

| Identidad | Valor |
|---|---|
| Referencia vigente conservada | `fc894f850caa32b24d714ac89d0ef0c9238f562558257c2c068e67b4bcdf7d51` |
| Referencia de prueba con constructor integrado | `efda829536d98e4f392269bf93718102e47764cf749fd29a340bc8cdc928faef` |
| Payload lógico | `f584d3c1545fd6848f1829d82c2ea89eedf7b2f07e24794dbf9d66cfd3e8e181` |
| XLSX autorizado | `77ac1090c480457e8b1e95d9cb3a7d53483b9c56189e75fde9c44db78c5dbfef` |

| Constructor: archivo | SHA-256 |
|---|---|
| `scripts/build_dane_reference.py` | `3dcbeddd465828d7ca91955056734ef18dfa586cac9bab793afce1bfbb559e5c` |
| `src/layer1_data/__init__.py` | `42be3b60e65bbf9528ec1633299d582f76d6a53521ad94f67c8e177a511ff42d` |
| `src/layer1_data/dane_reference.py` | `acfc7a1b7370d774acdd842e57dd061b2b7b930a6fd82a3b9c43549a7e03c19a` |

## Capa 4B

Dos builds con el código consumidor nuevo usaron la referencia vigente, sin
reemplazarla por la referencia de prueba. Coinciden los hashes lógicos y físicos
de los cuatro Parquet, CSV y resumen entre builds y frente a la publicación
histórica. También coinciden con la migración territorial previamente aceptada.
Las tres hojas de datos del workbook coinciden celda a celda.

| Resultado | Histórico y nuevo |
|---|---:|
| Proyectos considerados | 2232 |
| Relaciones | 2654 |
| Municipales / departamentales / COUNTRY | 990 / 1147 / 517 |
| Evidencias / AMBIGUOUS | 7135 / 757 |

**Idempotencia: PASS.** Mismo build ID y payloads en ambos builds nuevos.
No hay diferencias de comportamiento. Solo cambian hashes/rutas de código,
build ID y fecha. El verificador nuevo valida `CURRENT_PUBLICATION_CODE`;
los verificadores históricos siguen exigiendo sus hashes originales.

| Build | ID |
|---|---|
| Histórico productivo, conservado | `8c0fbeb9729aaa884179a39eb2b196b522d2045150976f699c4d3d1756997c99` |
| Migración anterior, conservada | `3923240587e4625b40de7be09a4d734c67d7262bff37dcc95715c236bb8e2e7e` |
| Integración DANE nueva, aislada | `ea1c7d93b6e4388d3a4efeb7f9e1e5470091cc86e911fe3834a346ff83abda8c` |

| Código territorial aceptado | SHA-256 |
|---|---|
| `scripts/render_territory_workbook.mjs` | `c4e5c76226d13956155337ee14bf70f40b4ff1ed7c5f33cb210fe42ef6dae715` |
| `scripts/run_territories.py` | `c4804c26dcb5ab6b76b86b71c00e2913559b152522a05543adfa59970d6eb0ec` |
| `src/layer1_data/__init__.py` | `42be3b60e65bbf9528ec1633299d582f76d6a53521ad94f67c8e177a511ff42d` |
| `src/layer1_data/dane_reference.py` | `acfc7a1b7370d774acdd842e57dd061b2b7b930a6fd82a3b9c43549a7e03c19a` |
| `src/layer4/__init__.py` | `ff8ef184b80a14ba1e85df5e2e8ba2d2e0fb947e1baf842241be5edad60c5518` |
| `src/layer4/territories/__init__.py` | `9bd0f92a3fd8c9f3bbc5cf78ca04769f65cb1d45f935e68e97aa9a552f0f1a8c` |
| `src/layer4/territories/contracts.py` | `e38b776ce723fd5489f720520709abfd0a0e2f713d15572e8e533b24bfcf7db8` |
| `src/layer4/territories/inputs.py` | `c40378e753c69877f02f0fe5e4361b6217ed5a1b6f8a583f2105ef31d032bac4` |
| `src/layer4/territories/matching.py` | `5d785440eb3e5f99c02ce1878b742de8cb50abe3a6b28bb63a1003d3688bf210` |
| `src/layer4/territories/pipeline.py` | `2e03352152808088e2fe00eaca1f429f0dfac1d0422adbe3142edbb1e5dbfed4` |
| `src/layer4/territories/workbook.py` | `dbececde56de96e045570fb15c35a09d8cab0859c1eb505039954dd96fc40e93` |

## Integridad y alcance

Canonical, DANE publicado, knowledge, GraphRAG, resultados territoriales,
manifests, schemas, configuraciones, workbooks y actas anteriores permanecen
intactos. Los cambios de código autorizados se registran con hashes nuevos,
sin rebasar registros históricos. Los ZIP históricos de Capa 4 no están
incluidos en este árbol; los hashes de aceptación y las verificaciones del
código actual permanecen documentados.

Capa 4A conserva perfiles v2, validación, RAW_CONFIDENCE_V1, preparación y
exportación. Esta aceptación no declara finalizado un assessment LLM.
No hubo LLM, nuevo retrieval, embeddings institucionales, commit ni push.

La evidencia privada queda en `.tmp/final-cleanup-20261017/`: baseline, copias,
JUnit, dos builds DANE, dos builds territoriales, comparaciones y acta nueva.
No se publican datos institucionales, textos, identificadores personales ni rutas absolutas.
