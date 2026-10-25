# Cierre definitivo V2 — CAPA_4_COMPLETE

La ejecución autorizada y aceptada completó veinte proyectos y veintinueve pares:
2 SUPPORTED, 16 INSUFFICIENT_EVIDENCE, 11 NOT_SUPPORTED, cero inválidos y dos
proyectos con SUPPORTED. Codex CLI es el único motor; ASSESSMENT_V2 y la fórmula
100*(0.55*S+0.45*K) permanecen. Se mantienen dos candidatos y fallback desactivado.

Publicación única: `outputs/layer4/final/resultado_capa4.xlsx`, exactamente dos
hojas, 29 filas de indicadores y 13 territoriales. Hash SHA-256:
`fc6f876493ee327f140f5fbdbd234b93242eeaee15d86aa752388980f03332e1`.
Verificador oficial PASS; 316 pruebas de 4A PASS; 1.854 archivos protegidos íntegros.

Consumo de las veinte llamadas fuente de los resultados vigentes: 474,231 s de
inferencia, media 23,712 s/proyecto, mediana 22,488 s y 16,353 s/indicador estimado.
Tokens: 332.447 entrada + 19.553 salida = 352.000; 15.872 cacheados son subconjunto
de entrada. Las quince llamadas nuevas consumieron 303,345 s y 259.989 tokens.
Las versiones sustituidas y el fallback experimental se contabilizan aparte.

El usuario autorizó los textos de los quince proyectos, aceptó el piloto y
aceptó expresamente los veintinueve resultados finales para publicación con
acuerdo **global 5/5**. No son veintinueve calificaciones individuales independientes.
Las ocho opiniones históricas permanecen intactas; no se infirieron etiquetas
humanas ni métricas de clasificación. Constancias y verificación están en
`outputs/layer4/pruebas/piloto_v2/cierre_20/`. Procedimiento vigente:
[cierre de Capa 4](../methodology/layer4_closure_v2.md).

## Antecedente conservado: implementación inicial del 20 de octubre de 2026

Estado de aceptación: **BLOCKED**. No es un acta de CAPA_4_COMPLETE.
La implementación se extiende sobre el coordinador y adaptador Codex CLI existentes.
La autorización recibida en esta conversación cubre únicamente el piloto V2 de
cinco proyectos/ocho pares. No autoriza continuar con los otros quince proyectos.

## Entrega técnica

- ASSESSMENT_V2: criterios conceptuales fijos, evidencia por criterio, distinción
  de propuesta/ejecución/expectativa/resultado demostrado y citas verificadas.
- EVIDENCE_CONFIDENCE_V2 candidata: `100 × (0.55 × strength/4 + 0.45 × K)`;
  K es media de CLEAR=1, PARTIAL=0,5 y NOT_DEMONSTRATED=0. Todos los estados
  válidos reciben respaldo; los inválidos conservan NULL. No reclasifica por score.
- Cálculo comparativo V1/V2 sobre un mismo juicio V2, con proyección histórica
  explícita. Las evaluaciones V1 no se reutilizan como respuestas V2.
- Telemetría de tiempo, tokens observados, CPU/RSS del coordinador, reintentos,
  errores y procedencia de medidas; sin atribuir recursos remotos ni inventar costos.
- Exportación oficial única de dos hojas, condicionada a ejecución real completa,
  aprobación de fórmula/cap, revisión humana vinculada y QA de originales/identidades.
- Contrato del selector dinámico de Power BI; no se construye Power BI.

## Diagnóstico real preservado

La ejecución V1 posterior de 20 proyectos tiene 23 pares válidos, 21 indicadores
distintos: 2 SUPPORTED, 15 INSUFFICIENT_EVIDENCE y 6 NOT_SUPPORTED. Dos proyectos
tienen SUPPORTED; cero assessments inválidos. Sus dos puntuaciones son 94 y 100.
No hay evidencia de que un filtro de confianza haya reducido la clasificación.
El preliminar anterior de 20/31 y el piloto anterior de 5/8 son históricos separados.

Seis proyectos de la ejecución posterior recibieron un solo candidato pese a
disponer de más. Para esos mismos 20 proyectos hay 29/38/49 pares publicados con
caps 2/3/5. Capa 3 tiene 280 PROJECT con candidatos ASSESSMENT_READY, entre los
2.232 de la rama territorial. No se afirma recall ni pertinencia de nuevos pares
sin inferencia y revisión humana. No se reconstruye Capa 3 ni 4B.

## Pruebas y conservación

La batería final de 4A pasó 230 pruebas, incluida una publicación sintética real
en XLSX de dos hojas, verificación de aceptación guardada y detección de alteraciones.
Suites adicionales: Capa 1 70 PASS; Capa 2 51 PASS/12 SKIP; Capa 3 191 PASS/28 SKIP;
territorios 101 PASS; preparación 84 PASS/8 FAIL históricos por los ZIP ausentes.
La batería incluye los controles adicionales de proyecciones y schema nativo.
Total de casos distintos comprobados en las suites finales:
**727 PASS, 8 FAIL, 40 SKIP**.
Las integraciones omitidas requieren opt-in; no se presentan como revalidadas.

Los ocho fallos exigen `archives/layer4/pre_namespace_migration.zip` y
`archives/layer4/pre_layer1_unification.zip`, ya ausentes antes del cierre.
No se modificaron pruebas, hashes esperados ni archivos upstream para hacerlos pasar.
La comprobación inicial de 561 archivos protegidos conserva bytes de publicaciones,
código upstream, referencia, 4B e históricos. La verificación de la ejecución activa,
desde el contexto que puede leer también las auditorías históricas restringidas,
pasó sobre 1.854 archivos protegidos. Evidencia privada y JUnit en
`outputs/layer4/auditoria/cierre_v2/`.

## Ejecución y aceptación pendientes

La selección activa fija 20 PROJECT y 29 pares en
`outputs/layer4/pruebas/piloto_v2/preparacion_20/`. Configuración: `config/layer4_final.yaml`.
La preparación inicial anterior al ajuste visual de revisión se conservó sin
inferencias, junto con su código y configuración; no es otra ejecución procesada.

Un intento en el contexto sin red agotó 600 segundos sin respuesta ni uso
observable. El cambio de contexto se detuvo por fingerprint de features antes
de inferencia. Una preparación con red reveló un rechazo HTTP 400 de uniqueItems
en el schema nativo: dos solicitudes rechazadas, sin assessment ni tokens
reportados. Se preservaron intentos, código y configuración antes de corregir.
La restricción de unicidad sigue en el schema normativo y Python; solo se retiró
del transporte nativo. invalid_json_schema pasa a ser fatal sin reintento inútil.
Los registros de transición enlazan las ejecuciones y mantienen el mismo alcance
autorizado. No se presentan estos errores como evaluaciones NOT_SUPPORTED.

## Resultado del piloto V2 autorizado

Ejecución `6e916fb281f94e81ae727596a2805cd1`: cinco PROJECT, ocho assessments
válidos, dos SUPPORTED, cuatro INSUFFICIENT_EVIDENCE, dos NOT_SUPPORTED y cero
inválidos. Dos proyectos tienen al menos un SUPPORTED. Son los mismos ocho
pares del piloto V1 y no cambiaron sus decisiones. No se afirma mejora de calidad
ni falsos negativos corregidos sin revisión humana.

La proyección V1 sobre las mismas respuestas V2 da ASC-01 94 frente a V2 100 y
COL-01 100 frente a V2 100. Diferencia media numérica: tres puntos en dos casos
comparables. En los otros seis, V1 sigue NULL; V2 contiene respaldo parcial o cero.
La comparación y los 29/38/49 candidatos disponibles están en QA, sin inventar
relevancia, nuevos SUPPORTED ni costos de candidatos aún no evaluados.

Lote: 186,720 s de pared; CLI activa: 175,953 s; media por proyecto 35,191 s,
mediana 36,171 s y razón estimada por indicador 21,994 s. Tokens reportados:
86.246 entrada + 5.708 salida = 91.954; cacheados 0. CPU del coordinador 2,156 s
y pico muestreado 287,996 MiB. Modelo efectivo y costos monetarios no disponibles.
Los tres informes privados vigentes describen este piloto; el baseline V1 se
conserva por separado. El Markdown completa el contexto editorial desde los
manifests y logs preservados, sin cambiar métricas ni respuestas.

La revisión humana y la aprobación de V2 siguen pendientes. No se ejecutó continue.
Quedan quince proyectos/21 pares del presupuesto inicial preparados, sin
autorización de inferencia. No existe publicación oficial de Capa 5.

La autoridad sobre llamadas realmente terminadas y respuestas válidas son
`progress.json`, `records/` y `codex_runs/` de la ejecución activa. Un proceso en
curso, timeout o intento sin respuesta no equivale a un proyecto evaluado.
No se publicará `outputs/layer4/final/resultado_capa4.xlsx` antes de aceptación.

Los informes de desempeño incluyen una línea base V1 real, conservada en
`outputs/layer4/performance/historico_cierre/baseline_v1/`: 195,171 s activos, media 9,759 s
por proyecto, mediana 9,441 s y razón 8,486 s por par. Tokens: 300.006 de entrada,
4.844 de salida y 15.616 cacheados (subconjunto de entrada); total 304.850.
Modelo efectivo, CPU y RAM históricos no observados se dejan NOT_AVAILABLE.
Estas cifras no son resultados V2 ni una prueba de superioridad de la nueva fórmula.

La revisión humana permanece sin etiquetas. Faltan contraste real de fórmulas,
beneficio/costo de caps, revisión conceptual/temporal, autorización de continuación
y aceptación final. Procedimiento: [cierre V2](../methodology/layer4_closure_v2.md).
