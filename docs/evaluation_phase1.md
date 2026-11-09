# Corrección del motor de evaluación: fase 1

Esta entrega implementa coherencia de contratos, síntesis mediante referencias verificables, presupuestos por fase y reparación dirigida. No cambia GraphRAG, BGE-M3, Qwen, los 48 indicadores, sus rúbricas ni la fórmula de confianza. El run `run_20261102_004408_677016` se conserva como observación histórica; no se autoriza ni ejecuta ninguna inferencia en esta entrega.

## Cambios y motivos

| Problema comprobado | Corrección |
|---|---|
| Un shard podía aceptar CLEAR con una etapa que la evaluación final rechazaba | `assessment_v3._criterion_contract` comparte las reglas entre `validate_criteria` y `validate`. El gate V2 valida schema, cobertura exacta del subconjunto, literalidad/campo, referencias y compatibilidad temporal antes de aceptar cada shard |
| Errores temporales poco específicos para reparar | Diagnósticos por ruta, ID de criterio, índices, requisito temporal y etapas observadas. El feedback no contiene respuestas ni textos institucionales completos |
| La síntesis volvía a enviar todas las explicaciones y citas duplicadas | `phase1.synthesis` construye un registro de intervalos originales: unión de todos los textos enviados a los shards, sin eliminar contenido. Las citas se representan por intervalo y etapa; los juicios por ID, soporte e índices. Las explicaciones completas siguen en los shards y en el bundle final |
| Evidencia repetida entre shards | Deduplicación determinista exclusivamente por `(field, text, stage)` y remapeo de índices. Etapas distintas siguen siendo evidencias distintas |
| La mayor ventana no daba más entrada | La política V2 exige entrada estrictamente creciente y separa la reserva de salida de síntesis |
| Reintentos idénticos con temperatura/seed fijos | Tras INVALID_ASSESSMENT, feedback de regla/ruta/IDs. Se conserva el contexto si cabe; se amplía únicamente cuando lo requiere el presupuesto. Las respuestas incompletas siguen escalando de forma acotada |
| Explicaciones largas y repetitivas | Instrucción de una frase completa de aproximadamente 80–120 caracteres por criterio, límites de 200 por criterio y 400 para el indicador. No se recortan respuestas después de generarlas ni se limitan artificialmente las citas |
| Coste después del último rechazo | V2 no aplica cooldown después del último intento. Mantiene pausas entre intentos y los límites de recuperación |
| IDs omitidos en una respuesta completa | Schema V2 con número exacto de criterios y enum de IDs. La unicidad y cobertura siguen verificándose semánticamente |

No se asignan decisiones semánticas desde Python. La construcción del registro, la unión de intervalos, el remapeo, el ensamblaje y el cálculo de confianza son deterministas. Una respuesta completa válida no necesita síntesis. Cuando se necesitan shards, Qwen sigue decidiendo el indicador y su fuerza: los juicios negativos no se convierten automáticamente en NOT_SUPPORTED y los errores no producen una evaluación aceptada.

La validación de PARTIAL conserva las reglas existentes; no se amplían las etapas que permiten CLEAR. Los requisitos de decisión y de roles REQUIRED/ALTERNATIVE se aplican sobre el conjunto completo, no prematuramente sobre un subconjunto. La evaluación final y el cálculo de confianza conservan las barreras originales.

## Presupuestos V2

El techo de contexto continúa en 8192; margen 768, un worker, dos intentos por paso. No hay límite global de tokens/llamadas. El suelo de RAM permanece en 1536 MiB. Las políticas de espera de recursos existentes continúan aplicándose al modo autónomo normal.

| num_ctx | num_predict normal | Entrada normal | num_predict síntesis | Entrada síntesis |
|---:|---:|---:|---:|---:|
| 4096 | 1024 | 2304 | 512 | 2816 |
| 6144 | 1536 | 3840 | 512 | 4864 |
| 8192 | 2048 | 5376 | 512 | 6912 |

La selección inicial V2 estima salida mediante `384 + 128 × criterios`; la elección definitiva incluye instrucciones, datos, schema y feedback. No se modifica el estimador UTF-8/3 para hacer que las solicitudes pasen. Se mantienen el margen y los guardas posteriores basados en tokens medidos por Ollama.

El registro de síntesis conserva todos los intervalos enviados a cualquier shard. Intervalos solapados se unen a partir del campo original, sin parafrasear. Cada cita incluye campo, etapa, referencia al intervalo y límites Unicode `[start,end)`; el `synthesis_provenance` registra coordenadas originales y hashes. Los textos literales permanecen en `source_spans` y en las evidencias del resultado; no se reemplazan por un resumen generado.

Esta representación es la estrategia verificable para evitar acumular citas y explicaciones repetidas. Si incluso esa representación íntegra supera el techo finito, se registra `SYNTHESIS_CONTEXT_TOO_LONG` y un diagnóstico con todos los presupuestos; no se despacha ese intento ni se eliminan fuentes para forzarlo. No se implementa una jerarquía semántica arbitraria para fuentes ilimitadas: es una limitación explícita pendiente, que no afecta a los ocho casos reproducidos.

## Resultado offline de los ocho casos

Estos números corresponden a reconstrucciones con juicios históricos, **no a respuestas nuevas ni a tokens medidos por Qwen**. Los datos están en `outputs/experiments/evaluation_phase1/phase1_20_v1/offline_synthesis.json`, con recibos de los artefactos utilizados.

| Proyecto / indicador | Entrada estimada anterior | Entrada estimada V2 |
|---|---:|---:|
| 4836 / DIV-04 | 3489 | 2885 |
| 5501 / ECO-04 | 3348 | 3061 |
| 5501 / ECO-07 | 3360 | 3073 |
| 5501 / POL-08 | 3511 | 3154 |
| 5501 / SAL-06 | 3356 | 3073 |
| 5501 / TEC-03 | 3959 | 3207 |
| 5501 / TEC-04 | 3609 | 3155 |
| 5501 / TEC-06 | 3471 | 3104 |
| Total | 28103 | 24712 |

Reducción estimada conjunta de entrada de síntesis: **12,1 %**. Las ocho caben en el nivel de 6144/512, con 4864 tokens disponibles para entrada. No se aumenta el contexto respecto del primer intento completo histórico de esos casos. La reserva de salida de síntesis baja de 1536–4096 a 512; es una reserva, no un ahorro de tokens generados ya demostrado.

TEC-03 conserva cuatro incompatibilidades temporales en sus shards históricos. El nuevo motor las rechaza antes de sintetizar. No se usa el hecho de que el prompt ahora quepa para aceptar esos juicios. Una reparación real requiere otra salida de Qwen que supere las mismas reglas.

## Panel comparativo preparado

Directorio: `outputs/experiments/evaluation_phase1/phase1_20_v1/`.

- Ocho casos reales bloqueados identificados en la auditoría.
- Ocho PASS reales: 4636/AMB-01, COL-01 y TEC-01; 4836/SAL-01, SOC-01 y ASC-01; 5501/TEC-01 y ECO-01.
- Cuatro controles sintéticos separados: diálogo establecido, diálogo propuesto, ingresos realizados y negativo explícito. Sus objetivos de diseño incluyen SUPPORTED, INSUFFICIENT_EVIDENCE y NOT_SUPPORTED; esos objetivos **no son etiquetas de referencia**.
- Los veinte casos tienen `reference.status=PENDING_HUMAN_REVIEW`, sin decisión de referencia.
- Los controles usan textos identificados como sintéticos y contexto fijo de prueba. No prueban la recuperación vectorial ni se mezclan con publicaciones institucionales.

El brazo `baseline` usa la política V1 congelada y la rama histórica del motor; `corrected` usa V2. Comparten el código refactorizado de las reglas V3, cuya aceptación final no cambia. Por tanto, baseline reproduce el comportamiento V1, **no un checkout binario de todo el repositorio histórico**. Las pruebas revalidan los 136 PASS y sus puntuaciones sin cambios. Para medir tiempo, ambos brazos deben ejecutarse sobre el mismo panel; los tiempos del run histórico no sustituyen una medición A/B bajo condiciones comparables.

El manifiesto fija los veinte pares, los textos, origen sintético/institucional, las políticas de ambos brazos, modelo/proveedor local y runtime esperado, rúbricas, prompts y fingerprints de código/schemas. También fija hashes de los inputs originales, archivo fuente e índice candidato y verifica `graph.binding.json`. Se reutiliza la recuperación persistida: no se reconstruye el grafo ni se calculan embeddings.

Preparar no contacta con Ollama. Al ejecutar, el proveedor comprueba identidad de modelo, digest, servidor y configuración como en el motor normal. Una diferencia requiere otro experimento revisado, no actualizar el manifiesto autorizado. El runner no llama al pipeline completo.

## Procedimiento exacto

El panel `phase1_20_v1` ya está preparado y **no autorizado**. Revisar `manifest.json`, ambos manifiestos de brazo, `assets/cases.json` y `assets/synthetic_sources.json` antes de autorizar.

SHA-256 del manifiesto:

```text
d079bfcb65336741cf777866df8501178508fb2ac56600abdfbb0b74d86ef87e
```

Para preparar otra copia nueva, sin sobrescribir la anterior:

```powershell
uv run python scripts/compare_evaluation.py prepare --name phase1_20_v2
```

Para autorizar el panel entregado, tras revisarlo:

```powershell
uv run python scripts/compare_evaluation.py authorize --name phase1_20_v1 --manifest-sha256 d079bfcb65336741cf777866df8501178508fb2ac56600abdfbb0b74d86ef87e
```

Los comandos siguientes **sí ejecutarán Qwen**. No se han ejecutado en esta entrega. Cada brazo evalúa veinte casos; completar ambos implica hasta cuarenta evaluaciones, más los reintentos acotados que correspondan:

```powershell
uv run python scripts/compare_evaluation.py run --name phase1_20_v1 --arm baseline
uv run python scripts/compare_evaluation.py run --name phase1_20_v1 --arm corrected
uv run python scripts/compare_evaluation.py metrics --name phase1_20_v1
```

El mismo comando `run --arm ...` reanuda ese brazo: revalida los PASS y no repite sus inferencias. Un transporte completado se recupera mediante sus recibos; una llamada despachada sin resultado comprobable queda incierta y no se repite ciegamente. Los bloqueos semánticos no se reintentan indefinidamente. Ante falta de recursos o drift de runtime, el experimento detiene ese brazo y conserva los resultados. Este runner de comparación no sustituye al scheduler de espera automática del modo autónomo normal; revisar un bloqueo y preparar un experimento nuevo si hace falta cambiar política o alcance.

Para adjudicar referencias, copiar `references.pending.csv` a `references.reviewed.csv`. Un revisor humano completa `decision`, `reviewer` y `reviewed_at`, y cambia únicamente los casos revisados a `APPROVED_HUMAN_REVIEW`. Conservar el resto pendiente. Las etiquetas están separadas del alcance autorizado de inferencia y su SHA se registra al calcular métricas:

```powershell
uv run python scripts/compare_evaluation.py metrics --name phase1_20_v1 --references outputs/experiments/evaluation_phase1/phase1_20_v1/references.reviewed.csv
```

No se autoriza ni se inicia nada por el hecho de calcular métricas. No se acepta `--yes`. Si cambia código, fuente o política, la comprobación falla antes de otra inferencia: preparar un nuevo nombre y autorizar su hash.

Para ejecuciones institucionales nuevas sigue disponible `uv run python run.py prepare --autonomous`, con el menú existente y las cuatro modalidades de selección. Se prepara y autoriza un manifiesto nuevo con V2. **No usar esta entrega para reautorizar o migrar el run histórico**: sus fingerprints corresponden a otra versión y se rechaza su ejecución con código cambiado. Conservarlo para comparación y conservar la versión de código anterior si se necesita reproducirlo literalmente.

## Métricas y criterios de comparación

`metrics.json` y `metrics.csv` muestran por brazo y caso:

- Matriz de confusión y exactitud por categoría solo para referencias humanas aprobadas; fallos técnicos terminales cuentan como fallo frente a una referencia. Los casos aún pendientes/running no se califican como decisiones erróneas. Sin referencias, la exactitud queda sin calcular.
- Llamadas, tokens reales de entrada/salida, tiempo HTTP, generación y carga nativas cuando están disponibles.
- Tiempo activo por evaluación y tiempo de las sesiones completas del brazo, incluida su verificación. Una interrupción no añade el tiempo apagado al tiempo activo.
- Errores de contexto, rechazos de validación y shards aceptados que contradicen el contrato común. Estos últimos permiten medir el problema del baseline independientemente de que una síntesis llegue a enviarse.
- RSS máximo observado del coordinador y RAM disponible mínima del host, muestreados cada segundo y en los extremos de cada caso. No se acumula una serie ilimitada en memoria.

Los picos de memoria del proceso Ollama y VRAM se dejan **null / NOT MEASURED**: los muestreos del host y del coordinador no permiten atribuirlos. Los tiempos de preparación/GraphRAG del run previo no se inventan como coste del experimento. El A/B mide el motor de evaluación sobre recuperación congelada. Comparar arranques fríos/calientes, orden y caché de forma explícita; una segunda copia con orden invertido permite detectar ese efecto sin reutilizar resultados del primer panel.

No se declara éxito por producir más positivos ni por consumir menos tokens. Requiere cero citas inventadas aceptadas, todos los criterios conservados, cero incompatibilidades temporales aceptadas en shards, ausencia de errores técnicos convertidos en decisiones y calidad al menos equivalente a la adjudicación humana. El ahorro de generación y tiempo permanece por medir: las comprobaciones offline no lo demuestran.

## Archivos y validación realizada

Archivos de producción modificados:

- `config/autonomous.json`.
- `src/autonomous_execution/engine.py`, `policy.py`, `packing.py`, `lifecycle.py`.
- `src/layer4_evaluation/indicators/assessment_v3.py`, `validation_diagnostics.py`.

Archivos añadidos:

- `src/autonomous_execution/phase1.py`, `comparison.py`.
- `scripts/compare_evaluation.py`.
- `tests/test_phase1_evaluation.py` y este documento.

Se actualizó `tests/test_autonomous_execution.py` para verificar los prompts V2 y la conservación de la rúbrica completa. La publicación de perfiles, las rúbricas y el cálculo de confianza no se modificaron.

Validación: **233 pruebas satisfactorias** en la suite seleccionada, más **una prueba adicional satisfactoria** de presupuesto irreducible sin dispatch. Incluye contratos positivos/parciales/negativos; temporalidad/campo/cita/índices/cobertura; reproducción de los ocho contextos; remapeo sin pérdida; reparación dirigida; ausencia de síntesis tras shard inválido; exportación con citas; simulación de veinte casos; autorización, drift, reinicio y no repetición de PASS; espera de RAM; menú; preparación e integridad. Todos los clientes y respuestas de inferencia de las pruebas son simulados.

Comando principal ejecutado, con directorio de temporales nuevo:

```powershell
uv run python -B -m pytest -q tests/test_phase1_evaluation.py tests/test_autonomous_execution.py tests/test_assessment_recovery.py tests/test_context_budget.py tests/test_ollama_provider.py tests/test_resource_wait.py tests/test_autonomous_prepare_menu.py tests/test_preparation_integrity.py tests/layer5_experiment/test_assessment_v3.py --basetemp=outputs/test-phase1-final-01 --disable-warnings --maxfail=2
```

La prueba adicional fue `test_irreducible_synthesis_budget_fails_closed_with_receipt`, con temporales propios. Para repetir las pruebas, utilizar otro directorio temporal nuevo: pytest limpia el `basetemp` que se le proporciona.

Se verifican los 136 bundles y sus puntuaciones, y los SHA-256 de los 3283 archivos originales registrados por la auditoría. No se modifican manifiestos, autorizaciones, checkpoints, logs, Excel ni resultados históricos. No hubo commit, push, reconstrucción de embeddings/grafo ni ejecución real del panel de veinte casos.

## Limitaciones pendientes

La calidad semántica —incluido el probable falso negativo contextual— requiere revisión y A/B reales. Las rúbricas conservan su estado histórico de revisión pendiente. El estimador sigue siendo aproximado; no se prometen tokens medidos para prompts nunca enviados. La interpretación por Qwen de referencias estructuradas y la brevedad de sus explicaciones deben contrastarse en el panel. La recuperación y el grafo quedan fuera de esta fase. No se implementó una síntesis jerárquica arbitraria para entradas que superen incluso el registro íntegro y el techo autorizado, ni medición individual de memoria de Ollama/VRAM.
