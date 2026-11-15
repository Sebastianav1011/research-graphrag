# Diagnóstico independiente: 0 `SUPPORTED` en `run_20261115_063255_909981`

**Alcance.** Este análisis usa solo los artefactos del run: `outputs/historico/local/run_20261115_063255_909981/` (exportados) y `outputs/runs/local/run_20261115_063255_909981/evaluation/` (prompts, respuestas crudas, validaciones, selección de contexto). Para interpretar la lógica de decisión leí `src/layer4_evaluation/indicators/assessment_v3.py` y `ollama_provider.py`, pero no audité el resto del repositorio. No ejecuté inferencias ni modifiqué código, BASE, Knowledge, rúbricas ni umbrales.

**Configuración del run:** `qwen3.5:4b-q4_K_M`, `PROSPECTIVE_V1`, `BASE_RETRIEVED_GRAPH_V1`, temperatura 0, `num_ctx` 16384 y presupuesto de entrada de 8000 tokens. Se evaluaron 5 proyectos × 48 indicadores.

---

## 1. Resumen ejecutivo

1. **Qwen nunca propuso `SUPPORTED`, y el código no lo eliminó después.** En las 328 respuestas crudas, contando los reintentos, `decision` vale siempre `INSUFFICIENT_EVIDENCE`. La decisión la emite el modelo, y Python solo valida si una propuesta de `SUPPORTED` es coherente. Ningún umbral de confianza convierte un caso en `SUPPORTED`, y ningún validador anuló uno.
2. **Ninguna evaluación quedó cerca de `SUPPORTED`.** `SUPPORTED` exige que todos los criterios REQUIRED sean `CLEAR`. A la evaluación más cercana todavía le faltan **3** criterios REQUIRED en `CLEAR`. De 1001 juicios de criterio, solo **30 son `CLEAR` (3 %)**, y 25 de ellos corresponden a criterios contextuales (`CONTEXT_ONLY`). En criterios sustantivos, que piden una acción, un producto o un resultado, hay **5 `CLEAR` de 616**.
3. **La mayoría de los rechazos son correctos.** Los cinco proyectos son investigaciones básicas o exploratorias: denuncia en contadores forenses, memoria biocultural, percepciones sobre genética, usos de IA en la escritura académica e IA predictiva de seguridad. Muchos de los 48 indicadores no corresponden a su tema o exigen hechos ocurridos.
4. **El sistema aun así casi no puede producir un `SUPPORTED`, y la muestra contiene al menos dos falsos negativos probables** (21869·TEC-04 y 21736·COL-01). Tres factores verificados en los artefactos se combinan:
   - **(a) Las rúbricas se contradicen con el modo prospectivo.** La derivación prospectiva relaja `temporal_requirement`, pero conserva textos `rationale` e `insufficient_evidence` que exigen ejecución. Por ejemplo, TEC-04·C01 tiene `PROPOSAL_OR_HIGHER` con el texto *"El uso de tecnología debe haberse ejecutado; una previsión de uso no satisface el indicador"*. Esto ocurre en unos 59 criterios esenciales de unos 36 indicadores.
   - **(b) Qwen tiende a responder `PARTIAL` con cobertura 2.** El 79 % de sus `PARTIAL` tienen `coverage=2`, y casi nunca usa `CLEAR` en criterios sustantivos.
   - **(c) La puerta de decisión es conjuntiva.** Hay 4–6 criterios REQUIRED por indicador, sin alternativas, y todos deben ser `CLEAR`.
5. **La "confianza" no indica cercanía a `SUPPORTED`.** Las confianzas más altas del run corresponden a rechazos correctos con criterios contextuales mal marcados como `CLEAR`:
   - 75,1: TEC-04 en un estudio que no usa tecnología.
   - 60,6: SAL-05 ("medicina tradicional") en el estudio de contadores, donde Qwen afirma que los contadores forenses "corresponden a la medicina occidental" y también "a la tradicional".
6. **La recuperación limita el contexto, pero no explica el resultado.** En 192 de 240 solicitudes se omitieron unidades por presupuesto, y en dos proyectos cada prompt recibe solo un 35–41 % del descriptor observado. Sin embargo, el proyecto con descriptor completo (21844) tiene la confianza media más baja.

**Conclusión breve:** el 0 % de `SUPPORTED` mezcla dos cosas. Por un lado, los documentos realmente no respaldan la mayoría de los indicadores. Por otro, el instrumento es demasiado estricto de forma estructural: contradicciones en las rúbricas, un modelo 4B que evita `CLEAR` y una puerta conjuntiva. Por eso el cero **no debe reportarse como un hallazgo sobre los proyectos**: el sistema, tal como está, no distingue un proyecto con contribución prevista bien documentada de uno sin ella. La sección 7 detalla la conclusión.

---

## 2. Distribución de resultados (análisis ligero)

| Métrica | Valor |
|---|---|
| Evaluaciones planificadas | 240 (5 × 48) |
| `VALID` exportadas | 197; todas `INSUFFICIENT_EVIDENCE` |
| `BLOCKED_ERROR` | 43 (17,9 %), no exportadas |
| Respuestas crudas de Qwen con `SUPPORTED` | **0 de 328** |
| `support_strength` máximo emitido | 2 (`SUPPORTED` exige 3–4) |
| Confianza = 0 | 109 (55 %): todos los criterios `NOT_DEMONSTRATED` |
| Confianza ≥ 50 / ≥ 60 / ≥ 70 | 23 / 5 / 3 |
| Juicios de criterio | 1001: ND 751 (75 %), PARTIAL 220 (22 %), CLEAR 30 (3 %) |
| `CLEAR` en criterios `CONTEXT_ONLY` / sustantivos | 25 / **5** |
| `coverage` dentro de `PARTIAL` | 1 → 43 · **2 → 174** · 3 → 3 |
| Criterios REQUIRED que faltan en `CLEAR` (mínimo) | **3**; distribución: 3 (10), 4 (75), 5 (91), 6 (18), 7 (3) |

**Rúbricas efectivas** (extraídas del `INPUT_JSON` de los prompts):

- 48 indicadores, 246 criterios: **233 REQUIRED**, 13 COMPLEMENTARY y **0 ALTERNATIVE**.
- Temporalidad de los REQUIRED: 94 `PROPOSAL_OR_HIGHER`, 78 `CONTEXT_ONLY` y 61 `EXPECTED_OR_DEMONSTRATED`.

**Por proyecto (confianza media / evaluaciones con confianza > 0):**

| Proyecto | Confianza media | Con confianza > 0 |
|---|---|---|
| 21736 | 24,7 | 22/38 |
| 21750 | 22,4 | 21/39 |
| 21869 | 18,0 | 16/40 |
| 22022 | 15,0 | 15/38 |
| 21844 | 14,5 | 14/42 |

**Por dimensión:** las medias más altas son Sociedad (33,5) y Medio ambiente (31,0). Las más bajas son Cultura (4,6), Salud (8,5) y Política pública (9,9), que coinciden con lo que cabe esperar de la temática de estos proyectos.

**Patrones de rechazo:**

- Las explicaciones de 297 de los 616 criterios sustantivos no `CLEAR` (48 %) usan vocabulario de ejecución o futuro ("ejecutad", "realizad", "efectivamente", "previst", "propuest", "futur"…). Es una cota superior léxica: parte de esos usos son descriptivos y correctos.
- En 6 evaluaciones, todos los criterios salieron `PARTIAL` con cobertura 2, un patrón uniforme compatible con evasión del juicio.

**Correcciones dirigidas:**

- De 55 criterios marcados en el primer intento como `NOT_DEMONSTRATED` con citas (`UNSUPPORTED_CANNOT_CLAIM_EVIDENCE`), 42 se resolvieron como ND sin citas, **0 pasaron a `PARTIAL`** y 13 terminaron en evaluaciones bloqueadas.
- La reparación siempre resolvió hacia abajo. Aun así, esto no afecta `SUPPORTED`, porque un `PARTIAL` tampoco lo habría alcanzado.

**Bloqueos (43):** se deben a incoherencias S/K (`SK_ZERO_SUPPORT…`, `ZERO_ANCHOR_MISMATCH`, referencias de fuerza no verificables), no a propuestas de `SUPPORTED`. Afectan sobre todo a SAL-01, TEC-06, ECO-07 y SAL-03.

---

## 3. Casos seleccionados

Revisé en detalle 12 evaluaciones. Las ocho siguientes cubren los distintos tipos de caso:

| # | Proyecto · Indicador | Confianza | Criterios REQUIRED que bloquean | Motivo de Qwen | Valoración independiente |
|---|---|---|---|---|---|
| 1 | 21869 · TEC-04 (IA predictiva de seguridad; "usa tecnología para maximizar impacto") | 53,4 | C01, C03, C04, C05 = PARTIAL(2); C02 = PARTIAL(2) | "IA, GAN y NLP es conceptual"; "no se demuestra cómo genera beneficio" | **Falso negativo probable.** |
| 2 | 21736 · COL-01 (enfoque inter/transdisciplinario) | 62,5 | C01, C02, C03 = PARTIAL(2) | C02: "se describen como 'propuestos' o 'se emplearán'. No hay evidencia de análisis ejecutados" | **Falso negativo probable**, rechazado por razones temporales. |
| 3 | 21869 · SOC-03 (enfrentar desigualdad o exclusión) | 56,9 | C01–C05 = PARTIAL(2) | "no hay evidencia de que estas acciones hayan sido ejecutadas" | **Ambiguo.** C03 debería ser `CLEAR` prospectivo, pero la brecha de C04 es legítima. `INSUFFICIENT` defendible. |
| 4 | 21736 · AMB-01 (soluciones ambientales) | 51,2 | C01, C04 = ND | "proponer lineamientos… es una intención futura" | **Ambiguo.** Decisión defendible por falta de concreción, pero con un razonamiento temporal incorrecto en modo prospectivo. |
| 5 | 21736 · POL-07 (documentos de política entregados a gobierno) | 73,1 | C01 = ND, C04 = PARTIAL | "no hay constancia de entrega" | **Rechazo correcto.** No existe documento de política previsto. La confianza está inflada por `CLEAR` contextuales erróneos. |
| 6 | 21844 · TEC-04 (estudio de denuncia en contadores) | **75,1** (máximo del run) | C01 = ND | "no menciona ninguna herramienta tecnológica" | **Rechazo correcto.** La confianza más alta del run es un artefacto. |
| 7 | 21844 · SAL-05 (medicina occidental ↔ tradicional) | 60,6 | C04, C05 = ND | C01–C03 `CLEAR`: "forensic accountants… corresponde al rol de la medicina occidental / tradicional" | **Decisión correcta y razonamiento alucinado.** Debería ser *no aplicable*. |
| 8 | 21869 · ASC-02 (la comunidad usa o sostiene la solución) | 0 | C01–C04 = ND | "no define la solución… no identifica beneficiario" | **Decisión correcta para un indicador ex post**, pero C01 y C02 se descartan con una evidencia que Qwen sí reconoce en TEC-04. Es inconsistente. |

**Otros rechazos correctos revisados:**

- 22022·TEC-04: el estudio trata *sobre* la IA y no la usa como medio. Qwen lo distingue bien en C01, aunque concede `PARTIAL` a C03–C05 citando literatura.
- 21750·COL-03: los "actores" son sujetos muestrales, no copartícipes.
- 21750·DIV-01: el proyecto solo "identificará estrategias"; los módulos educativos son una consecuencia posible, no un entregable.
- 21844·SOC-01: no existe ningún mecanismo de mejora del bienestar.

### Detalle de los casos clave

**Caso 1: 21869·TEC-04 (falso negativo probable).** Los fragmentos recuperados contienen todos los elementos prospectivos que piden los criterios:

- **Tecnología concreta:** "IA… GAN y NLP", "NLP y Computer Vision", plataforma en "Leaflet, Mapbox o Google Maps".
- **Destinatarios:** "Herramienta digital… para uso de instituciones y ciudadanía"; "comunidad piloto".
- **Función:** "La IA interviene clasificando, validando y priorizando los aportes ciudadanos… y generando análisis automatizados que alimentan el mapa".
- **Beneficio esperado:** "priorizar intervenciones", "anticipar riesgos", "seguridad urbana preventiva, inclusiva".
- **Mecanismo:** despliegue con "retroalimentación para los usuarios… útil para la toma de decisiones".

Qwen asigna `PARTIAL` con cobertura 2 a los cinco criterios. En C01 incluso reconoce que el criterio admite tecnología "prevista de manera concreta", pero luego califica la IA de "conceptual". La rúbrica empuja en contra de su propia temporalidad efectiva:

- C01: *"debe haberse ejecutado; una previsión de uso no satisface"*.
- C03: *"vinculada a uso real"*.
- C05: *"uso ejecutado"*.
- `insufficient_evidence`: *"Tecnología prevista pero no usada"*.

**Caso 2: 21736·COL-01 (falso negativo probable).** Los fragmentos documentan la integración en el problema, los métodos y los conceptos:

- "enfoque analítico-descriptivo e inter y transdisciplinario, que articula saberes científicos y prácticos de actores sociales".
- "interacciones entre factores biofísicos, sociales y culturales".
- Herramientas etnográficas y de cartografía social, más el índice cuantitativo de la Estructura Agroecológica Principal.
- "diálogo de saberes".

Qwen da `CLEAR` a C04 y razona explícitamente que "cumple con la exigencia prospectiva". En C02 rechaza el mismo tipo de evidencia porque los métodos "se emplearán". Esa decisión sigue al pie de la letra la `rationale` de C02 (*"El diseño aporta evidencia parcial, pero no acredita su aplicación efectiva"*) y el `insufficient_evidence` del indicador (*"Una metodología propuesta solo respalda diseño, no métodos ya utilizados"*).

**Caso 6: 21844·TEC-04 (confianza alta en un rechazo correcto).** El proyecto es un diseño factorial 2×2 sobre intención de denuncia, sin ninguna tecnología, y Qwen lo reconoce en C01. Aun así:

- Marca `CLEAR` en C02 (los contadores como "destinatarios") y en C04 (reducir el miedo a represalias como "impacto").
- La corrección conserva del primer intento una `strength_rubric` (3, 3, 4, 4), por diseño de `TARGETED_REFERENCE_CORRECTION_V3_CRITERION_MERGE`.

El resultado es S = 0,875 y K = 0,60, es decir, una **confianza de 75,1 para un indicador que el proyecto no toca**.

**Caso 7: 21844·SAL-05 (pertinencia).** El indicador no tiene ninguna relación con el proyecto. Como el esquema solo ofrece `SUPPORTED` o `INSUFFICIENT_EVIDENCE`, el modelo "rellena" los criterios contextuales con la única población disponible. El validador lo acepta porque `CONTEXT_ONLY` admite cualquier `stage`: basta con que exista una cita.

---

## 4. Causas probables, con su respaldo

### 4.1 Hallazgos comprobados en los artefactos o el código

**C1. Contradicción entre la temporalidad prospectiva y los textos de la rúbrica (verificado en los prompts).**

- `prospective_rubric()` (`assessment_v3.py:196`) solo reescribe `temporal_requirement`. `rationale`, `criterion`, `insufficient_evidence` y `descripcion_ampliada` pasan sin cambios.
- En la rúbrica efectiva, unos 59 criterios **esenciales** de unos 36 de 48 indicadores tienen `PROPOSAL_OR_HIGHER` o `EXPECTED_OR_DEMONSTRATED` junto con una `rationale` que exige ejecución o un logro alcanzado. Lo conté por patrón léxico, revisado a mano y excluyendo 6 coincidencias falsas. Ejemplos:
  - POL-01·C02: "La participación activa debe haberse realizado".
  - SAL-06·C01: "La estrategia debe estar implementada".
  - SOC-01·C03: "La mejoría debe haber ocurrido… el beneficio esperado no basta".
- El prompt pide al modelo "interpretar las exclusiones… según la temporalidad efectiva adjunta". Esa instrucción meta exige que un modelo 4B resuelva un conflicto entre dos textos del mismo criterio, y las explicaciones muestran que suele resolverlo a favor de la `rationale`.

**C2. Qwen casi no usa `CLEAR` en criterios sustantivos y tiende a `PARTIAL` 2 (verificado en los datos).**

- Hay 5 `CLEAR` sustantivos de 616 juicios, y 174 de 220 `PARTIAL` tienen cobertura 2.
- Con 4–6 REQUIRED por indicador y ninguna alternativa, el producto conjunto hace que `SUPPORTED` sea prácticamente inalcanzable aunque la evidencia sea buena (caso 1).

**C3. La confianza no mide el respaldo al indicador (verificado en los datos y el código).**

- K promedia todos los REQUIRED, incluidos los `CONTEXT_ONLY`.
- S valora la claridad de los fragmentos citados, aunque solo respalden el contexto.
- Por eso las confianzas más altas corresponden a rechazos correctos (casos 5–7), y la confianza no sirve para ordenar "casi `SUPPORTED`".
- Además, `TEMPORAL['CONTEXT_ONLY'] = set(STAGES)`: un `CLEAR` contextual solo requiere una cita, y ningún control comprueba que la cita trate del objeto del indicador.

**C4. No existe la opción "no aplicable" (verificado en el código).**

- `SK_STATE_INSTRUCTIONS` solo define `SUPPORTED` e `INSUFFICIENT_EVIDENCE`. El `NOT_APPLICABLE` de `confidence.py` es un estado de la confianza, no de la decisión.
- Indicadores ajenos al proyecto, como CUL-02 o SAL-05 en el estudio contable, quedan mezclados con indicadores pertinentes que tienen evidencia parcial.

**C5. Algunos indicadores son intrínsecamente ex post (verificado en las rúbricas).**

- ASC-02 ("es usada, adaptada…, sostenida"), SOC-01 ("mejora… debe haber ocurrido"), ECO-06 ("crecimiento reportado como alcanzado"), SAL-01 y SOC-04 ("beneficio efectivamente recibido") definen su **objeto** como un hecho ocurrido.
- La derivación prospectiva no puede convertirlos en "contribución prevista" sin cambiar el indicador. Evaluarlos en `PROSPECTIVE_V1` produce `INSUFFICIENT_EVIDENCE` por construcción.

**C6. La recuperación es incompleta, pero no es la causa dominante (verificado en `context_selection.json`).**

- En 192 de 240 solicitudes se omitieron unidades de menor rango por presupuesto (`LOWER_RANKED_UNITS_OMITTED_BY_BUDGET`), y `expected_results` se omitió 114 veces.
- Cobertura por prompt respecto de la unión de fragmentos observados del proyecto:

  | Proyecto | Cobertura por prompt |
  |---|---|
  | 21750 | ≈ 35 % |
  | 21869 | ≈ 41 % |
  | 22022 | ≈ 67 % |
  | 21736 | ≈ 87 % |
  | 21844 | 100 % |

- La confianza media no sigue esa cobertura: 21844 tiene el descriptor completo y la media más baja. En los dos falsos negativos probables, la evidencia necesaria **sí estaba en el prompt**.

**C7. La reparación no es causa del cero (verificado).** No hubo ningún `SUPPORTED` que reparar. Su asimetría a la baja (0 de 42 casos pasaron a `PARTIAL`) existe, pero es marginal para esta pregunta.

### 4.2 Hipótesis que requieren verificación (no comprobadas)

- **H1. Peso causal de C1.** Que las `rationale` contradictorias *causen* el rechazo de los casos 1–2 es la explicación más coherente con el texto de las explicaciones, pero solo se demuestra con un A/B: los mismos prompts con rúbricas prospectivas armonizadas. Esto requiere nuevas inferencias, que quedaron fuera de este análisis.
- **H2. Capacidad del modelo.** La tendencia a `PARTIAL` 2 y las alucinaciones contextuales (caso 7) apuntan a un límite de un modelo 4B Q4 frente a un prompt de unos 26 KB, con instrucciones superpuestas e incluso notas históricas ("esa nota histórica ya NO calcula S"). Habría que contrastarlo con un modelo mayor o con un prompt simplificado sobre una muestra etiquetada.
- **H3. Efecto de la recuperación en casos concretos.** No comparé contra el descriptor completo de la BASE. Es posible que, para 21750 y 21869, algunos indicadores perdieran fragmentos decisivos. Para verificarlo, compara `selected` y `omitted` de `context_selection.json` con el descriptor fuente en los pares candidatos.
- **H4. Los 43 bloqueados.** No sé si alguno habría acabado siendo un caso fuerte. La ausencia de `SUPPORTED` en sus respuestas crudas sugiere que no, pero están excluidos de cualquier conclusión sobre la tasa de respaldo.

---

## 5. Evaluación de la clasificación

**`SUPPORTED` / `INSUFFICIENT_EVIDENCE`.** Esta distinción es metodológicamente adecuada y conviene mantenerla. `INSUFFICIENT_EVIDENCE` ya distingue internamente entre "sin respaldo" (fuerza 0) y "respaldo parcial" (fuerza 1–2). No hace falta un estado nuevo para eso; basta con reportarlo por separado.

**Falta una tercera categoría: `NOT_APPLICABLE`.** Es necesaria. Mezclar "el indicador no corresponde a la naturaleza del proyecto" (SAL-05 o CUL-02 en un estudio contable) con "corresponde, pero la evidencia es insuficiente" sesga cualquier tasa de cumplimiento y genera confianzas espurias (caso 7). Para que no se convierta en una vía de escape, debería:

- decidirse en un paso de pertinencia previo al análisis por criterio, con una justificación citable;
- aplicarse solo cuando el **objeto** del indicador (tecnología, medicina, patrimonio, documento de política…) esté ausente del alcance del proyecto, no cuando falte un detalle;
- excluirse del denominador del cumplimiento y reportarse aparte.

**No recomiendo un estado nuevo para los indicadores ex post (C5).** "No evaluable ex ante" es una propiedad del par **indicador × modo**, no del proyecto. Debe resolverse en el catálogo: marcar esos indicadores como fuera del alcance de `PROSPECTIVE_V1`, no evaluarlos y declararlo en el informe. Así se evita un estado redundante y no se confunde con `NOT_APPLICABLE`.

**Sugiero no añadir `PARTIALLY_SUPPORTED` como decisión.** Rebajaría el estándar de `SUPPORTED`. El respaldo parcial ya está representado por la fuerza 1–2 y por los criterios `PARTIAL`.

---

## 6. Recomendaciones mínimas, por prioridad

Ninguna rebaja umbrales ni la exigencia de `CLEAR`. Todas buscan que el instrumento mida lo que declara medir.

1. **Armonizar las rúbricas con el modo prospectivo (C1, máxima prioridad).**
   - Revisar los ~59 criterios esenciales y los textos `insufficient_evidence` que exigen ejecución bajo una temporalidad prospectiva.
   - Para cada uno, redactar una variante prospectiva: "actividad o producto concreto previsto por este proyecto, con destinatario y mecanismo", conservando las exclusiones de concreción, pertinencia y destinatarios.
   - Debe hacerse como una revisión humana versionada del catálogo, sin parchear el prompt. Es un cambio de rúbrica, así que lo dejo como recomendación.
2. **Separar del modo prospectivo los indicadores intrínsecamente ex post (C5).** Hay que decidir a nivel de catálogo qué indicadores se evalúan en `PROSPECTIVE_V1`. Candidatos: ASC-02, SOC-01, SOC-04, SAL-01, ECO-06 y los criterios de conteo de productos "efectivamente" realizados en DIV-03 y POL-02/03/05.
3. **Introducir `NOT_APPLICABLE` con un paso de pertinencia explícito y justificado (C4)**, reportado fuera del denominador.
4. **No usar la confianza actual como indicador de cercanía a `SUPPORTED` (C3).** En los informes, reporta junto a ella la cobertura de los criterios sustantivos, es decir, los no `CONTEXT_ONLY`. Valora además exigir que un `CLEAR` contextual cite un fragmento que mencione el objeto del indicador.
5. **Antes de la nueva campaña, hacer una calibración con un patrón humano.**
   - Etiquetar a mano unos 20–30 pares proyecto × indicador: los 8 casos de este informe, los otros 10 con confianza ≥ 50 y una muestra de los de confianza 0.
   - Medir la tasa de falsos negativos con la rúbrica actual y con la armonizada.
   - Sin esa medición, ningún cambio permite saber si el sistema mejoró o solo se volvió más permisivo.
6. **Simplificar el prompt, con prioridad media.** Elimina notas históricas y reglas duplicadas o superpuestas (los bloques V1/SK/V3 conviven en el texto) para reducir la carga sobre un modelo 4B. Conviene probarlo junto con la recomendación 5.
7. **Recuperación, con prioridad baja y condicionada a H3.** En el modo prospectivo, asegúrate de que `objectives` y `expected_results` entren siempre en el presupuesto antes que `methodology` de menor rango. Solo vale la pena si la verificación de H3 muestra pérdidas reales.

---

## 7. Conclusión explícita

**¿Pierde el sistema resultados legítimos por una evaluación excesivamente estricta, o los documentos realmente no ofrecen suficiente evidencia?**

**Las dos cosas, pero en proporciones distintas y con implicaciones distintas:**

- **La mayoría de los 197 rechazos están justificados.** Los proyectos son investigaciones en fase de propuesta, y muchos indicadores no corresponden a su tema o exigen hechos ocurridos. Incluso con un evaluador ideal, la tasa de `SUPPORTED` sería baja.
- **El sistema sí pierde resultados legítimos, y su resultado de cero no es informativo.**
  - En una muestra de 12 casos revisados encontré **2 falsos negativos probables** (21869·TEC-04 y 21736·COL-01) y 2 casos ambiguos rechazados con un razonamiento temporal incorrecto.
  - La causa no es la recuperación ni un error del código de decisión. Es la combinación verificada de **(i)** rúbricas que siguen exigiendo ejecución en el modo prospectivo, **(ii)** un modelo que casi nunca concede `CLEAR` a un criterio sustantivo y **(iii)** una puerta conjuntiva de 4–6 REQUIRED.
  - Con 5 `CLEAR` sustantivos en 616 juicios, el instrumento no puede distinguir un proyecto con una contribución prevista bien documentada de uno sin ella.
- **Mi estimación, con baja precisión:** en este run, unos pocos pares (del orden de 3 a 10 de 197) merecerían `SUPPORTED` en un modo prospectivo coherente. Esta cifra debe confirmarse con la calibración de la recomendación 5.

**Antes de la nueva campaña, corregiría primero C1 (rúbricas), C5 (alcance de los indicadores ex post) y C4 (`NOT_APPLICABLE`), y validaría el resultado contra un patrón humano.** Cambiar umbrales o cambiar de modelo antes de eso no permitiría atribuir la mejora a ninguna causa.

---

### Anexo: cómo se obtuvieron las cifras

- **Distribuciones:** `evaluaciones_validas.json` y `estado_indicadores.json` del histórico.
- **Decisiones crudas y errores de validación:** `*/calls/*/assessment_*/assessment/ollama_runs/*/attempt_*/{response.raw.txt, validation.json}`, 328 intentos.
- **Rúbricas efectivas y fragmentos:** `INPUT_JSON` de `prompt.txt` del primer intento de cada una de las 240 evaluaciones.
- **Omisiones de contexto:** `evaluation/batch_*/context_selection.json`.
- **Conteo de `rationale` contradictorias:** patrón léxico (`ejecutad|haberse|realizad|efectivamente|implementad|alcanzad|ocurrid|uso real…`) sobre criterios no complementarios con temporalidad prospectiva, revisado a mano. Excluí ASC-01·C02, COL-01·C01, TEC-04·C04, SAL-03·C03, DIV-02·C05 y DIV-05·C05 por ser permisivos o no temporales.
