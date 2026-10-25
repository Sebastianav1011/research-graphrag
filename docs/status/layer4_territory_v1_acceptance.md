# Aceptación de Capa 4B territorial v1

Estado: **LAYER4_TERRITORY_V1_READY**, 2026-10-16.

Esta extensión es posterior a las aceptaciones históricas de Capas 1–3 y no las
reescribe. La arquitectura vigente está en [Capa 4](../architecture/layer4.md).
Capa 4A indicator assessment permanece IN PROGRESS / PENDING_GROUP_REVIEW.

## Referencia autorizada

`data/reference/Codigos Dane/Tabla_Codigos_Dane.xlsx`, Sheet1, encabezados 1–3:
33 unidades departamentales según el catálogo y 1.120 municipios. Sheet2/Sheet3
vacías; fila 611 vacía. No hay códigos duplicados ni nulos en filas de datos.
El almacenamiento mixto numérico/texto se valida como DD/MMM; la dimensión
publica strings DD y DDMMM. Hay 68 grupos municipales de nombres repetidos y
nueve colisiones entre niveles DANE, además de Colombia tras su extensión.

La hoja autorizada ALCANCE_NACIONAL añade COUNTRY/000/Colombia como
USER_DEFINED_COUNTRY. No es un código DANE departamental o municipal y no
reemplaza al municipio Colombia (Huila). Las partes XML originales de las hojas,
sus valores, estilos y datos permanecen idénticos; el original se conserva
byte-for-byte en la versión previa de referencia.

SHA256 del XLSX utilizado:
`77ac1090c480457e8b1e95d9cb3a7d53483b9c56189e75fde9c44db78c5dbfef`.
Referencia normalizada independiente:
`fc894f850caa32b24d714ac89d0ef0c9238f562558257c2c068e67b4bcdf7d51`.

## Extracción real

| Métrica | Resultado |
|---|---:|
| PROJECT considerados | 2.232 |
| Proyectos con territorio resuelto | 1.366 |
| Proyectos sin territorio resuelto | 866 |
| Relaciones RESOLVED | 2.654 |
| Relaciones MUNICIPALITY | 990 |
| Relaciones DEPARTMENT | 1.147 |
| Relaciones COUNTRY/000 | 517 |
| Menciones resueltas publicadas | 7.135 |
| Menciones AMBIGUOUS | 757 |
| Proyectos con AMBIGUOUS | 298 |
| Proyectos con múltiples territorios | 469 |
| Códigos territoriales distintos utilizados | 365 |
| Menciones nacionales suprimidas por territorio específico | 2.912 |

La tasa resuelta principal es 90,4080% y AMBIGUOUS 9,5920%, sobre 7.892
menciones publicadas resueltas + ambiguas. Incluyendo las menciones nacionales
suprimidas, son 10.804 menciones: 92,9933% resueltas y 7,0067% ambiguas.
Estas tasas no miden precisión ni recall contra ground truth humano.

Los principales nombres ambiguos son Bogotá (200), Nariño (129), Boyacá (105),
San Andrés (34), Candelaria (23) y Jericó (22). Un candidato único también puede
quedar ambiguo por nivel explícito incompatible: el catálogo distingue BOGOTA
departamental de BOGOTA, D.C. municipal, sin introducir aliases nuevos.

## Validación

Dos builds finales con el mismo código, referencia y snapshot de Capa 2
produjeron los mismos payloads, relaciones, offsets, candidatos y métricas.
Build ID:
`8c0fbeb9729aaa884179a39eb2b196b522d2045150976f699c4d3d1756997c99`.
Snapshot Capa 2: `run_20261005T204120_837354Z`, manifest SHA256
`b0ec6990c8dc9d38398c780af4d51ed9c16c80e5504d7d70abd548fbe62d472f`.

- Territorial: **101 PASS**, incluida integración real, duplicados reales del
  catálogo, múltiples campos, COUNTRY, idempotencia e integridad protegida.
- Regresiones aisladas de Capa 1: **70 PASS**; Capa 2: **51 PASS**; Capa 3:
  **191 PASS**. Sin fallos, errores ni skips en estas cuatro suites.
- Total final: **413 PASS**. No se ejecutó integración de Capa 3 ni modelos.
- Quality, hashes, roundtrip, catálogo, offsets y workbook: **PASS**.
- El CSV coincide exactamente con la bridge resuelta; ningún ambiguo publica
  dane_code. Todos los códigos y ceros iniciales se preservan como texto.
- 80 archivos protegidos de canonical, knowledge, código/contratos/tests y
  publicación activa de Capa 3 conservan sus SHA256 anteriores.

Se revisaron muestras reales de 10 municipios resueltos, 10 departamentos,
10 ambiguos, 10 menciones nacionales y cinco proyectos con múltiples territorios.
Las revisiones motivaron guardias generales para vocabulario común, apellidos,
instituciones, citas, rasgos naturales/listas de subdivisiones y contexto lejano.
Se verificaron visualmente las cuatro hojas y las vistas detalladas del workbook.
Esta revisión acotada no constituye un benchmark de precisión/recall.

## Evidencia privada y alcance

La publicación se encuentra en `outputs/layer4/territorios/publicacion/`. La referencia,
sus manifests, auditoría, índices y versiones están en `data/reference/processed/`.
La evidencia de aceptación, muestras y JUnit reside en
`outputs/layer4/territorios/aceptacion/`; el acta formal es `final_acceptance.json`.
Los builds previos permanecen en `outputs/layer4/territorios/versiones/`.

No se modificaron RAW, canonical L1, publicación L2, código/publicación L3 o
embeddings. No hubo LLM, fuzzy matching, API externa, geocoding, commit ni push.
La tasa de ambigüedad es material para revisión posterior. La fase LLM futura
no está implementada y requiere una decisión separada después de esa revisión.
