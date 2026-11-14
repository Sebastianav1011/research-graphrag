# Monitoreo y lotes de indicadores

**Estado al cierre del 8 de noviembre de 2026:** pruebas reales suspendidas por
instrucción del usuario. No iniciar ni reanudar GraphRAG, embeddings o inferencias
sin una nueva autorización explícita. Una autorización antigua guardada en disco
no sustituye esa autorización. Los comandos de ejecución de este documento son
solo referencia para una futura ejecución personal del usuario.

Los lotes siguen siendo experimentales: la comparación histórica muestra
discrepancias semánticas que requieren revisión humana. No se certifica todavía
la conservación de calidad ni se recomienda ejecutar los 100 proyectos con lotes.
Véase el [informe de revisión estática](status/optimization_static_review_20261108.md).

`status` autónomo consulta SQLite en modo de solo lectura y conserva el avance
aunque haya cambiado el código. No abre una cola nueva, autoriza, reencola,
valida vectores ni llama al modelo. La verificación completa sigue siendo
obligatoria antes de ejecutar o reanudar.

```powershell
uv run python run.py status --autonomous --run-id RUN_ID
uv run python run.py status --autonomous --run-id RUN_ID --json
```

El porcentaje es PASS dividido por trabajos proyecto–indicador declarados.
Los resultados parciales y los errores no representan proyectos completos.
Los proyectos sin trabajos LLM se informan aparte: el descubrimiento puede no
admitir candidatos, o puede faltar texto. No se presentan como evaluados por Qwen.
Un PID solo se considera activo cuando coincide también su identidad de creación.
Un checkpoint RUNNING abandonado se muestra interrumpido. El ETA solo aparece
con un worker activo, muestra suficiente y sin errores pendientes; es orientativo.
Las métricas ausentes no se sustituyen por cero. Durante una espera de RAM se
muestran la observación disponible, el umbral y el siguiente intervalo de revisión.

## Ejecuciones nuevas

`prepare --autonomous` conserva el adaptador individual por defecto.
`--batch-size 2` o `3` activa lotes explícitamente; `1` mantiene la evaluación
individual anterior. El lote, los prompts,
las fuentes y el código quedan sellados en el manifiesto. Se requieren permisos
explícitos del manifiesto antes de la inferencia, como en el flujo anterior.

- Se agrupan indicadores del mismo proyecto con fragmentos recuperados comunes.
- Se deduplican fragmentos idénticos, no sus asociaciones con cada indicador.
- Cada indicador conserva íntegros su catálogo, rúbrica, criterios, temporalidad,
  referencias permitidas y validación de evidencia/confianza.
- El esquema JSON comparte definiciones repetidas mediante `$defs`; se valida
  además cada respuesta contra el contrato individual más estricto.
- El contexto permanece estable en el mayor nivel autorizado de hasta 6144.
  Entrada real tokenizada, salida reservada y margen deben caber juntos. El
  esquema se registra como gramática externa de decodificación, sin contarlo
  otra vez como texto del prompt. No se elimina
  evidencia para admitir un lote. Si no cabe, se usa un lote menor o evaluación
  individual; si tampoco cabe, se registra el bloqueo y nunca un falso negativo.
- Los miembros válidos se guardan por separado antes del siguiente trabajo.
  Solo los inválidos reciben una aclaración individual pertinente, reutilizando
  su primera respuesta. No se repite el análisis inicial ni se vuelve a agrupar
  el miembro inválido. Los casos que no admiten agrupación usan el adaptador
  individual. Una llamada incierta conserva
  el plan y bloquea sus miembros; no se repite automáticamente al reanudar.
- Los fragmentos y candidatos parseados se reutilizan dentro del proyecto.
  La selección de fuentes sigue comprobándose; los embeddings válidos siguen
  usando las cachés del pipeline existente.
- Se cuenta una llamada física y sus tokens una sola vez por proyecto. En la
  cola, el indicador propietario recibe el 100% del uso compartido y los demás
  cero uso adicional. `batch_receipts/`, `batch_plans/` y `shared_call` en los
  resultados explican los miembros y la atribución. Los tres entregables no
  cambian su esquema.

Los lotes requieren un worker para impedir carreras de reserva. El modo anterior
con dos workers permanece disponible con `--batch-size 1`. El perfil opcional
`config/autonomous_optimized.json` revisa la RAM cada 30–60 segundos, manteniendo
el umbral de seguridad y las dos muestras estables. No reduce el requisito de RAM
ni cambia pesos, modelo, catálogo o confianza.

## Checkpoints

Para los lotes es necesario preparar también el tokenizador fijado, usando las
dependencias existentes. No descarga pesos ni ejecuta inferencia:

```powershell
uv run python scripts/prepare_qwen_tokenizer.py
```

Su revisión, SHA-256 y compatibilidad con el digest y la plantilla local están
en `config/qwen_tokenizer.json`. Se contrastó sin inferencias con 798 solicitudes
históricas: tokenizador más 12 tokens de plantilla coincide con todos los conteos
de entrada observados. El margen reservado es de 300 tokens, además de esos 12,
y la salida se adapta al número de criterios y al espacio disponible. El servidor
sigue verificándose antes/después de cada llamada y los conteos reales se
comprueban al recibirla; no hay truncamiento ni cambio automático de modelo.
La calibración corresponde a este digest/plantilla, no a cualquier instalación
de Qwen. Si cambian, la ejecución exige revisar la calibración.

Ollama recibe el esquema mediante `format`, separado de `messages`; véanse
[salidas estructuradas](https://ollama.com/blog/structured-outputs) y el
[contrato HTTP oficial](https://github.com/ollama/ollama/blob/main/docs/api.md).

Los resultados y transportes completos se adoptan sin volver a inferir. Ctrl+C
conserva resultados, planes, recibos y cola. Una respuesta cortada o incierta no
se transforma en una evaluación negativa. Tras comprobar que ya terminó la
llamada incierta, la recuperación explícita sigue disponible mediante
`retry-pending --acknowledge-uncertain`; puede implicar repetir una llamada cuyo
resultado nunca se recibió. Los bloqueos semánticos requieren revisión.

```powershell
uv run python run.py resume --autonomous --run-id RUN_ID
```

Los manifiestos históricos fijan el código anterior. **Se pueden monitorear con
esta versión, pero su reanudación requiere su versión autorizada**. No se actualizan
sus hashes ni se convierten silenciosamente a lotes. Reutilizar el manifiesto de
selección en un run nuevo conserva la muestra; no importa automáticamente sus
resultados de inferencia. La comparación pequeña exige inferir nuevamente el
proyecto elegido para medir la estrategia nueva.

## Preparar posteriormente los 100 seleccionados

Estos comandos son para ejecución posterior del usuario; no forman parte de la
prueba pequeña. Utilizar un `run_id` que aún no exista:

La corrida de referencia fue compactada el 11 de noviembre. Extraer primero su
evidencia a un destino nuevo; no es una reanudación del workspace retirado:

```powershell
uv run python scripts/manage_run_retention.py --archive outputs/historico/compactados/evidencias_runs_2026-11-11.zip --extract-run local/run_20261108_154514_059252 --destination archives/evidencias100
```

```powershell
$runId = 'muestra100_lotes_20261108_v1'
uv run python scripts/prepare_qwen_tokenizer.py
uv run python run.py prepare --autonomous --selection-manifest archives/evidencias100/preprocess/selection_manifest.json --policy config/autonomous_optimized.json --batch-size 2 --run-id $runId
$manifestPath = "outputs/runs/$runId/autonomous/main/manifest.json"
# Revisar el manifiesto antes de autorizar:
$manifestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant()
uv run python run.py authorize --autonomous --run-id $runId --manifest-sha256 $manifestHash
uv run python run.py start --autonomous --run-id $runId
```

Desde otra terminal, usar los comandos `status` y `resume` anteriores con el
mismo ID. La terminal principal informa periódicamente el avance sin volcar IDs
masivos, evidencia ni respuestas completas.

## Diagnóstico histórico reproducible

```powershell
uv run python scripts/analyze_run_performance.py archives/evidencias100 --output docs/status/optimization_baseline_20261108.json
```

El script escribe fuera del run fuente y no ejecuta inferencias. Incluye llamadas
y tokens por solicitud, proyecto e indicador; errores, contextos, tiempos Ollama,
esperas de RAM, huecos entre solicitudes y performance original. Los tiempos de
Ollama forman parte de la inferencia y no deben sumarse otra vez al total.

## Revisión Qwen/Ollama sin inferencias — 13 de noviembre de 2026

Alcance exclusivo: construcción de solicitudes, transporte y reintentos. No se
modificaron fórmula, componentes S/K, estados de cumplimiento, validadores de
evidencia, BGE-M3 ni proveedor. No se ejecutaron proyectos, endpoints, modelos,
descargas o benchmarks. Los históricos se leyeron sin reescribirlos; el ZIP
compactado se inspeccionó por `index.json` y sus objetos, sin extraerlo.

### Configuración encontrada y conservada

Modelo: `qwen3.5:4b-q4_K_M`, Ollama local. DEFAULTS de `ollama_provider.py` y
`config/pipeline_manual.json` coinciden:

| Parámetro | Manual / proveedor actual | Autónomo |
|---|---|---|
| num_ctx / num_predict | 8192 / 4096 | Niveles 4096/1024, 6144/1536, 8192/2048, 32768/4096 |
| timeout_seconds | 600 | 600 |
| keep_alive | 5m | 5m |
| temperature / seed | 0 / 0 | 0 / 0 heredados del LLM |
| Margen de contexto | 512 | 768; lotes con tokenizador fijado usan el margen existente 300 |
| Reintentos por salida | Hasta 2, habilitados explícitamente por plan; max_predict=6144 | Proveedor interno sin retries; hasta 2 intentos de paso según política |
| Correctivos | Hasta 2 por plan | Adaptador compacto: una evaluación y como máximo una aclaración dirigida |
| maximum_calls | 48 × proyectos × 3; 4320 para 30 proyectos | Sin cuota global en la política; límites finitos por paso y recuperación |
| batch_size | Una evaluación de indicador por llamada; agrupar proyectos en un plan no los fusiona en una inferencia | 1 por defecto; 2 o 3 indicadores solo si se solicita; un worker y techo de contexto existente 6144 para lotes |

Los valores 4096/1024/600 siguen en manifiestos históricos y en el primer nivel
autónomo. No describen el default manual actual. `retries` genérico del proveedor
es 0; los retries de salida y de corrección comparten un máximo de dos adicionales,
no se suman como cuatro. Los metadatos autónomos permiten tres consultas acotadas
y tres fallos de servicio consecutivos detienen el worker. No se cambió ninguno
de estos parámetros ni sus archivos de configuración.

El código anterior ya permitía ampliar salida dentro de max_predict y del contexto
reservado cuando el plan lo habilita. Esta revisión conserva ese techo y solo evita
reintentos cuando no hay espacio adicional. Tampoco amplía los niveles autónomos.
Cambiar num_ctx puede aumentar reservas/KV cache y presión RAM/VRAM; aumentar salida
puede prolongar generación y, con contexto fijo, reducir el espacio de entrada. Los
registros disponibles no justifican una ampliación adicional ni permiten cuantificar
su rendimiento. Se conserva la configuración en lugar de estimar nuevos valores.

### Hallazgos históricos: hechos e hipótesis

Dos ejecuciones locales contienen 30 proyectos cada una, en 15 planes por ejecución:

| Run | Llamadas conservadas | Válidas | INVALID_ASSESSMENT | Solicitudes idénticas repetidas que fallaron ambas veces |
|---|---:|---:|---:|---:|
| run_20261109_165418_908891 | 229 | 190 | 39 | 11 |
| run_20261109_201419_941189 | 70 | 66 | 4 | 1 |

Son conteos de recibos de llamada, no proyectos completados ni garantía de cobertura
de los 30. No se suman como una muestra independiente. Ambos planes fijaron
8192/4096/600, temperature=0, seed=0, keep_alive=5m, dos correctivos y dos retries
por salida. El límite total era 4320 por ejecución. Las repeticiones se identificaron
por hashes de prompt/esquema y opciones de generación iguales.

Los 39 errores del primero son 36 `V3_POSITIVE_STRENGTH:REQUIRES_EVIDENCE` y tres
`V3_CRITERION:UNSUPPORTED_CANNOT_CLAIM_EVIDENCE`; los cuatro del segundo son de
fuerza positiva sin evidencia. Los nativos terminaron en `done=true, stop`, con
JSON completo: no son prueba de timeout ni salida truncada. Los rangos observados
de entrada/salida fueron 1118–1910 / 495–971 y 1726–1925 / 575–827 tokens. Por eso
no se atribuyen esos errores a falta de salida 4096. Son incoherencias de la respuesta
semántica; aumentar tokens no demuestra que las resuelva. Sus estados/validadores
ya se trataron en la etapa anterior y se conservan.

En el ZIP `outputs/historico/compactados/evidencias_runs_2026-11-11.zip` se comprobaron:

- `local/run_20261109_095941_728900`, PROJ_20035, assessment_5, y
  `local/validacion_integral_3_20261108`, PROJ_21227, assessment_5: ambos tienen
  `INCOMPLETE_RESPONSE` histórico, `done_reason=length`, 1024 tokens de salida y
  JSON no parseable. Sus entradas nativas son 1324 y 1299 tokens. La causa confirmada
  es el límite de salida 1024, no un timeout de 600 segundos. El proveedor actual ya
  distingue estos casos como TOKEN_LIMIT; se verificó mediante mocks.
- Hay 48 artefactos STATIC_CONTEXT_TOO_LONG y 82 CONTEXT_TOO_LONG preventivos;
  no equivalen a 130 llamadas rechazadas por Ollama. Por ejemplo, el presupuesto de
  AMB-01 en `validacion_lotes_1_20261108_v2` estima 8694 tokens (7461 prompt y 1233
  esquema) frente a 3840 disponibles en 6144/1536/768. Es un bloqueo previo al envío.
  Su estimador bytes/3 es aproximado: esto no prueba una tokenización real concreta.
  La variante con tokenizador fijado ya separa plantilla y gramática externa; no se
  cambió la política del estimador aproximado sin evidencia adicional.

`outputs/layer4/auditoria/demo_30.*` pertenece a Codex CLI: su timeout/red y drift de
CLI no se atribuyen a Qwen. No se confirmó timeout de Ollama en las dos muestras de
30 proyectos revisadas. Inferencias sobre límites RAM/VRAM, velocidad, calidad
semántica o un timeout óptimo permanecen como hipótesis, no resultados de esta etapa.

### Correcciones implementadas

1. `OllamaAssessmentProvider.evaluate` ya no repite TOKEN_LIMIT si max_predict o el
   espacio de entrada/margen impiden ampliar la salida. Conserva el error y uso real.
2. No repite una corrección local fallida si prompt y salida quedan idénticos. Si el
   diagnóstico cambia y produce otra corrección dirigida, puede usar el intento
   restante del límite existente. Errores internos, contexto y timeout no se convierten
   en correctivos. Una respuesta inválida nunca se acepta por agotar los intentos.
3. `Worker._step` impide repetir una solicitud de Ollama idéntica en el último nivel
   tras un límite de tokens/contexto. Se conserva el retry finito de un servicio
   transitoriamente ocupado. Recuperar recibos existentes sigue siendo offline.
   Además, `Worker.evaluate` reconoce TOKEN_LIMIT como activador de la recuperación
   por criterios/síntesis que ya existía: antes solo reconocía INCOMPLETE_RESPONSE,
   aunque el transporte había separado ese código de la salida cortada por longitud.
   No se crea otro protocolo de recuperación ni se cambia el adaptador compacto.
4. `live_execution.verify_run` no vuelve a marcar automáticamente como reintentable
   un indicador local que ya agotó su evaluación/correcciones. Resume conserva el
   bloqueo y avanza con los demás indicadores; no reinicia el presupuesto del mismo
   fallo. Una revisión de fuentes/parámetros requiere otro plan compatible y revisado,
   nunca modificar hashes históricos. No cambia el comportamiento de otro proveedor.
5. En nuevos prompts SK por fragmentos se omite `key_elements` únicamente si coincide
   exactamente, en contenido y orden, con las etiquetas completas de la rúbrica.
   Permanecen criterios, roles, etapas, definición, fragmentos e IDs; perfiles completos
   y hashes siguen en el plan. Cualquier diferencia impide esa deduplicación. Las
   solicitudes de contratos históricos mantienen su serialización anterior.

Los constructores existentes ya deduplicaban evidencia compartida en lotes y evitaban
repetir citas largas mediante IDs F/E. No se eliminaron evidencias para hacer caber
solicitudes, ni se simplificaron requisitos institucionales. No se modificó el parser
estricto de JSON, la detección de `length`, la validación semántica, el registro de
tokens nativos o la conservación de resultados inciertos.

Se ajustaron fixtures antiguas que suponían default 4096 o esperaban el mensaje
genérico «detenida» donde ya se registra UNCERTAIN_OUTCOME. Las pruebas de cambios
de contexto ahora cambian realmente su configuración sintética; no cambian defaults
de producción para satisfacer expectativas antiguas.

Archivos editados en esta etapa: `ollama_provider.py`, `context_budget.py`,
`live_execution.py`, `autonomous_execution/engine.py`, `tests/test_token_limit_recovery.py`,
`tests/test_ollama_provider.py`, `tests/test_context_budget.py`,
`tests/test_evidence_references.py` y este documento. No se crean módulos, servicios,
scripts o configuraciones nuevas. Se conservan los cambios preexistentes del usuario.

### Pruebas y pendientes

Verificación final: **273 passed, 2 deselected**, con clientes Ollama simulados,
respuestas sintéticas y temporales fuera de outputs. Se ejercitaron respuestas
completas, JSON incompleto, `length`/techo de salida, contexto preventivo sin envío,
rechazo de contexto del servidor, timeout, servicio ocupado recuperable, correcciones
distintas, correctivos idénticos, techo de salida/espacio disponible, último nivel,
reanudación sin repetir límites, división por criterios/síntesis y contabilidad de
tokens de todos los intentos. También pasan las regresiones de estados, confianza,
evidencias y formato de tesis existentes. `git diff --check` pasó.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_token_limit_recovery.py tests/test_ollama_provider.py tests/test_context_budget.py tests/test_evidence_references.py tests/layer5_experiment/test_assessment_v3.py tests/test_assessment_recovery.py tests/test_autonomous_execution.py tests/test_batching_monitor.py tests/test_thesis_output.py --deselect='tests/test_autonomous_execution.py::test_projection_resources_are_pinned_before_authorization[template]' --deselect=tests/test_autonomous_execution.py::test_partial_export_separates_verified_pass_and_unvalidated_pending -q
```

Las dos exclusiones esperan la plantilla anterior
`plantilla_resultado_final_indicadores_territorios.xlsx` y las hojas INDICADORES /
TERRITORIOS, frente al formato vigente Proyectos / Artículos. Se detectaron al
ejecutar la suite ampliada y se dejan pendientes fuera del alcance de inferencia;
no se modifica la exportación ni se presenta toda la suite del repositorio como verde.
Los nueve fallos de fixtures de configuración/timeout observados al inicio de esta
revisión sí quedaron corregidos, sin cambiar parámetros de producción.

Continúan pendientes la calidad de interpretación semántica y la cuantificación de
RAM/VRAM/rendimiento con cada presupuesto: esta revisión no realiza esas mediciones.
Tampoco demuestra que todo CONTEXT_TOO_LONG aproximado sea un exceso real del
tokenizador. Los checkpoints con código fijado no se migran automáticamente y no
pueden reanudarse saltándose sus verificaciones. Ningún histórico fue modificado.

## Auditoría de checkpoints y resume — 13 de noviembre de 2026

Esta revisión se limita a persistencia, recuperación e integridad. No ejecuta
`run.py resume` sobre runs reales, inferencia, embeddings o recálculo de resultados
reales. No modifica confianza, S/K, decisiones de cumplimiento, prompts ni la
política de reintentos de la etapa anterior. Se reutilizan JSON, SQLite, recibos,
manifiestos y escritores existentes; no se crea otro sistema de persistencia.

### Arquitectura y auditoría histórica

- El coordinador verifica el run y reutiliza preprocessing en PREPROCESSED/PREPARED,
  knowledge en PREPARED y GraphRAG si su publicación existe y supera su validación.
  La selección/alcance se conservan, sin remuestrear. STAGE_REUSED no es otra ejecución.
- En el flujo manual, cada llamada guarda plan, autorización usada, claim, transporte,
  registro, filas y verification. PASS requiere métricas, límites y validación del
  resultado. El progreso se reconstruye desde esos recibos, no desde texto de consola.
- El autónomo utiliza queue.sqlite con claves únicas proyecto–indicador y
  paso–intento, WAL y synchronous=FULL. Guarda el resultado antes de marcar el job
  PASS. Un RUNNING abandonado vuelve a planificación; el paso adopta su transporte
  terminado o mantiene UNCERTAIN si no hay prueba de finalización. Las filas PASS
  no se reclaman otra vez. `usage` usa una clave única: releer no suma otra llamada.
- `Worker.adopt` ya validaba manifiesto, resultados, evidencias y hashes antes de
  adoptar un JSON duradero que quedó sin commit de cola. Los lotes ya conservaban
  resultados individuales y recibos compartidos. No se reemplazan esos mecanismos.

Se inspeccionaron en modo de lectura los dos runs locales de 30 proyectos citados
en la revisión anterior. El primero conserva 201 llamadas externas, 229 intentos
nativos y 190 evaluaciones válidas; el segundo, 67 llamadas, 70 intentos y 66 válidas.
Las 11 y una ausencias de assessment.rows.json corresponden a registros fallidos;
no son evidencia de pérdida de filas PASS. No se encontraron checkpoints externos
sin registro/verification en esas dos muestras, ni solicitudes PASS repetidas con
prompt, esquema y generación idénticos. Las 12 repeticiones encontradas fueron
INVALID_ASSESSMENT en ambos intentos y pertenecen al problema de reintentos ya tratado.

CALL_STARTED aparece 201 y 67 veces, respectivamente, consistente con las llamadas
externas. Ver nuevamente IDs de proyecto, progreso o RESUMED no demuestra inferencia
repetida. Las pruebas sintéticas distinguen tres eventos RESUMED de dos llamadas y
dos resultados PASS. La auditoría no demuestra que jamás haya existido repetición
en otras ejecuciones; solo describe los recibos conservados que se contrastaron.

Al comenzar esta revisión, los hashes distintos de los planes de esas muestras
correspondían a código modificado desde su preparación (210 y 180 referencias
repetidas entre los 15 planes de cada run). Esos rechazos son correctos y no deben
eliminarse. No se usa esta observación como certificación de todos los datos del
repositorio ni de objetos grandes que no se volvieron a hashear en ese muestreo.

### Defectos demostrados y correcciones

1. Una interrupción manual después del transporte válido y antes del registro,
   filas o verification dejaba un claim permanentemente incierto, aunque existieran
   todos los recibos necesarios para validar el resultado. Tres pruebas fallaron
   antes de la corrección. Ahora `verify_run` puede reconstruir una vista sin escribir;
   `execute`, bajo el lock existente, completa solo los archivos de checkpoint ausentes.
   Se verifican plan, autorización/claim, runtime, schema, prompts, JSON nativo,
   respuesta materializada, métricas, evidencias, contrato y filas. El commit de
   verification sigue siendo el último. No se vuelve a llamar al proveedor.
2. No se adoptan transportes sin call.json terminado, con `length`, JSON distinto,
   métricas alteradas o autorización inválida. Un archivo existente incompatible
   causa rechazo, nunca reparación por sobrescritura. Los errores y límites conocidos
   conservan la política anterior; los claims realmente inciertos no se adivinan.
3. El escritor manual usaba un `.pending` fijo y carecía de fsync. Ahora delega en
   `autonomous_execution.store.write`, ya existente: temporal único, flush/fsync,
   reemplazo atómico y retry exclusivamente de la operación de archivo en Windows.
   Una falla de serialización conserva los bytes anteriores. Esto no convierte JSON
   y SQLite en una transacción distribuida: la recuperación idempotente cubre su intervalo.
4. La adopción autónoma y la verificación superficial de PASS no contrastaban
   explícitamente assessment_version/confidence_version/conceptual_coverage_version
   con el contrato del manifiesto. Una prueba aceptaba indebidamente PASS V3 bajo un
   manifiesto SK. Ambas rutas ahora comparten `check_result_contract` y rechazan
   RESULT_CONTRACT_INCOMPATIBLE antes de reutilizar o recalcular la fila.
5. `verify_expected` reutilizaba la variable `name` al revisar related_sha256. Si
   cambiaba el módulo principal, podía informar el último archivo relacionado, aunque
   este estuviera intacto. Se corrigió ese diagnóstico; incluye hash esperado y actual.
   Las comparaciones exactas, snapshots y bindings revisados siguen siendo obligatorios.
6. El contador de llamadas de verification podía diferir de los recibos y alterar
   el progreso sin ser rechazado. Se contrastan calls, retries, tokens y duración
   contra la misma función usada al crear el checkpoint. status.json se actualiza
   únicamente si su contenido difiere del estado verificado, incluso tras recuperación.
7. Preparar un run con binding ya disponible construía un cliente que no necesitaba.
   Ahora se reutiliza primero ese binding, manteniendo las comprobaciones de alcance;
   las pruebas pueden prohibir cualquier cliente sin impedir la recuperación local.

### Compatibilidad y confianza

Se conserva `100*(0.55*S+0.45*K)`, con los contratos ya definidos. V3 usa
EVIDENCE_CONFIDENCE_V2 / CONCEPTUAL_UNITS_V3_REQUIRED_ALTERNATIVE; SK usa
EVIDENCE_CONFIDENCE_SK_V1 / CRITERIA_COVERAGE_SK_V1_REQUIRED_GATE. Compartir pesos
no hace intercambiables los juicios S/K de ambas versiones.

Para recalcular offline de forma segura haría falta verificar los originales,
hashes, rúbrica y versión; reconstruir el assessment completo de sus recibos y
aplicar la función pura `assessment_v3.confidence` del contrato correspondiente.
Si ya contiene strength_rubric con sus cuatro dimensiones, coverage por criterio,
roles/grupos, referencias y justificaciones, permite comprobar S/K SK sin una LLM.
Cualquier derivación con otra versión debería guardarse en un artefacto/run nuevo,
con el vínculo al original y revisión explícita; esta etapa no realiza esa migración.

Un V3 antiguo con solo support_strength y CLEAR/PARTIAL/NOT_DEMONSTRATED no contiene
las cuatro dimensiones de S ni los grados coverage de SK. No se pueden inventar,
inferir o convertir automáticamente. Se conserva su incompatibilidad explícita.
Las comprobaciones ordinarias de un resultado del mismo contrato pueden reproducir
su score para verificar igualdad; no reemplazan ni actualizan el score persistido.

Un cambio real de código/configuración/contrato/datos continúa bloqueando el resume
si contradice sus fingerprints. Restaurar la versión autorizada o preparar un run
nuevo mediante los mecanismos existentes son opciones distintas de sobrescribir
hashes. No se migra ni reautoriza ningún histórico. Los archivos compactados como
HISTORICAL_NON_RESUMABLE siguen siendo evidencia de lectura, no checkpoints activos.

Si el proceso se interrumpe después del envío pero antes de guardar un recibo completo,
no existe prueba para garantizar exactamente una inferencia: se conserva UNCERTAIN.
Un operador puede revisar ese caso mediante las herramientas existentes; no se
repite automáticamente una operación cuyo resultado se desconoce.

### Archivos de esta etapa

- `src/layer4_evaluation/live_execution.py`
- `src/autonomous_execution/engine.py`
- `src/autonomous_execution/lifecycle.py`
- `src/layer2_processing/checkpoints.py`
- `tests/test_resume_blocked_indicators.py`
- `tests/test_autonomous_execution.py`
- `tests/test_sad_source_migration.py`
- `tests/test_unified_runner.py`
- `docs/optimizacion.md`

Se preservan todos los cambios anteriores del usuario. Las pruebas antiguas que
esperaban reiniciar correctivos agotados se ajustaron a la política aprobada en la
etapa anterior, sin modificarla en producción.

### Verificación de esta etapa

Resultado final: **333 passed, 10 deselected** en una selección enfocada. Solo mocks
y checkpoints temporales sintéticos; también pasan las regresiones de confianza,
estados, transporte y formato de tesis seleccionadas. `git diff --check` pasó.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_resume_blocked_indicators.py tests/test_assessment_recovery.py tests/test_token_limit_recovery.py tests/test_evidence_references.py tests/test_context_budget.py tests/test_ollama_provider.py tests/test_autonomous_execution.py tests/test_batching_monitor.py tests/test_run_storage.py tests/layer5_experiment/test_assessment_v3.py tests/test_thesis_output.py tests/test_preparation_integrity.py tests/test_unified_runner.py::test_resume_reuses_completed_stages_and_pass_without_export_side_effects tests/test_unified_runner.py::test_resume_integrity_hashes_only_selected_original_files tests/test_sad_source_migration.py::test_fingerprint_reports_changed_main_module_not_unchanged_related_file tests/test_sad_source_migration.py::test_split_checkpoint_binding_rejects_a_changed_extracted_implementation --deselect='tests/test_autonomous_execution.py::test_projection_resources_are_pinned_before_authorization[template]' --deselect=tests/test_autonomous_execution.py::test_partial_export_separates_verified_pass_and_unvalidated_pending -k 'not test_reuse_autonomous_run and not test_reuse_rejects_modified and not test_reuse_leaves_incompatible and not test_reuse_never_requeues and not test_interactive_prepare' -q --tb=short
```

Se simularon cortes antes de registro, filas y verification en V3 y SK por referencias;
recibo terminado frente a claim incierto; autorización/JSON/métricas alterados;
repetición de resume; preservación byte a byte de PASS y artefactos; claves únicas y
conteo de uso; etapas completadas sin repetir preprocessing/knowledge/GraphRAG;
cambios de código, datos, catálogo, esquema, fórmula/versiones y componente K;
fallo de escritura sin sustituir el checkpoint anterior. Las seis pruebas iniciales
de defectos concretos (tres cortes, contrato, fingerprint y contador) fallaron antes
de sus correcciones y pasaron después.

Las diez exclusiones son siete casos cuya fixture reutiliza una muestra institucional
(se evita para mantener esta validación sintética), uno del menú interactivo que
espera una firma anterior del callback de confirmación y los dos de plantilla Excel
antigua ya descritos. Una exploración inicial del módulo completo de unified_runner
encontró además ocho pruebas de exportación con mocks anteriores sin `selected`;
no se cambió la exportación para satisfacerlos. Se añadió una prueba independiente
de resume hasta evaluación, sin efectos de exportación. No se declara toda la suite
general del repositorio aprobada.

## Tolerancia a fallos individuales (2026-11-13)

La finalización del procesamiento se informa por separado de la completitud de las
evaluaciones. Un proyecto está procesado cuando todas sus evaluaciones seleccionadas
tienen resultado validado o bloqueo identificado; con trabajo sin visitar permanece
pendiente. Solo queda completamente evaluado si todas sus evaluaciones son válidas.
Una ejecución con bloqueos o pendientes conserva `PARTIAL` y sus resultados disponibles.
Los fallos de integridad compartida (fuentes, contratos, fingerprints, runtime o
checkpoints alterados) siguen impidiendo continuar. No se normalizan errores como
ausencia de evidencia ni se les asigna confianza cero.

Cambios sobre funciones existentes:

- `live_execution.verify_run/summary`: un error aislado ya no convierte el lote en
  `BLOCKED`; se conservan errores, bloqueos por indicador, pendientes de scheduling y
  límites de reintentos. Se agregan contadores de procesamiento, decisiones y cobertura.
- `pipeline_coordinator.export/execute_pipeline` y `run.py`: distinguen seleccionados,
  procesados y completamente evaluados; contabilizan válidas, SUPPORTED, insuficientes,
  bloqueadas, pendientes y filas; explican el Excel vacío. Terminar solo la etapa de
  evaluación con bloqueos tampoco devuelve `COMPLETE` artificialmente.
- `autonomous_execution.batching/minimal`: un miembro ausente o estructuralmente
  inválido de un transporte terminado no descarta respuestas válidas de sus hermanos.
  Solo el miembro fallido pasa a la ruta individual acotada, conservando los recibos.
- `engine`, `store`, `monitor`: errores de validación conocidos se bloquean por pareja;
  se informa procesamiento separado de completitud sin cambiar el esquema SQLite.
- `final_output` y `preparation_integrity`: proyección y reutilización validan cada
  resultado y sus huellas; los miembros correctos no dependen del esquema de un hermano
  fallido. Exclusiones de evidencia/procedencia en exportación quedan auditadas por pareja.

Se mantiene `THESIS_POSITIVE_OUTPUT_V1`: mismas ocho columnas y hojas, exclusivamente
positivos validados con evidencia verificable. `INSUFFICIENT_EVIDENCE` sigue siendo
una evaluación válida bajo SK, incluso con confianza cero. No se modificaron Qwen,
`num_ctx=16384`, BGE-M3, embeddings, catálogo, rúbrica S/K ni
`100 * (0.55*S + 0.45*K)`.

### Diagnóstico histórico de solo lectura

Run: `outputs/runs/local/run_20261113_102233_307253`.
Antes de modificar el código se verificaron los tres lotes con sus fingerprints,
autorizaciones, recibos, métricas, validaciones semánticas y filas/confianzas originales:

| Proyecto | Válidas | SUPPORTED | INSUFFICIENT_EVIDENCE | Bloqueadas |
| --- | ---: | ---: | ---: | ---: |
| 21844 | 46 | 0 | 46 | 2 |
| 22022 | 47 | 0 | 47 | 1 |
| 21869 | 47 | 0 | 47 | 1 |
| 21750 | 48 | 0 | 48 | 0 |
| 21736 | 47 | 0 | 47 | 1 |
| Total | 235 | 0 | 235 | 5 |

Las 235 tienen `assessment_validation_status=VALID`, confianza 0.0 y ninguna cita.
No existían positivos verificables descartados por los bloqueos: las cero filas del
Excel eran correctas para este contrato. La exportación ya recorría las filas válidas
de proyectos incompletos; el defecto adicional estaba en estados y contadores, y en
el descarte conjunto de miembros estructuralmente inválidos del adaptador por lotes.

Las 235 se conservan aprovechables como resultados insuficientes en
`resultados/evaluaciones_validas.json`, junto a `estado_indicadores.json` y los recibos.
No hay positivos que recuperar para Excel. Los cinco bloqueos agotaron sus correctivos
Ollama y no son reintentables mediante un simple resume. Las huellas antiguas rechazan
el código cambiado, como corresponde; no se modificaron manifiestos ni autorizaciones
para evitarlo. Cualquier reanudación exige compatibilidad real con el código autorizado;
esta corrección no crea un mecanismo para forzar una migración histórica. No se ejecutó
resume, inferencia, embeddings ni una exportación sobre el run original. Su Excel
conserva el SHA-256 registrado en `manifiestos/export.json`.

### Archivos de esta corrección

Producción: `run.py`, `scripts/pipeline_coordinator.py`,
`src/layer4_evaluation/live_execution.py`,
`src/autonomous_execution/batching.py`, `src/autonomous_execution/engine.py`,
`src/autonomous_execution/minimal.py`, `src/autonomous_execution/store.py`,
`src/autonomous_execution/monitor.py`, `src/autonomous_execution/final_output.py`,
`src/autonomous_execution/preparation_integrity.py`.

Regresiones dentro de los tests existentes: `tests/test_manual_pipeline.py`,
`tests/test_autonomous_execution.py`, `tests/test_batching_monitor.py`,
`tests/test_resume_blocked_indicators.py`, `tests/test_unified_runner.py`,
`tests/test_selection_console.py`. Documentación: `docs/optimizacion.md`.

La exploración ampliada de `test_minimal_evaluation.py` encontró una dependencia de
fixture ausente (`outputs/runs/phase1_20_v1/metrics.csv`); no se creó ni modificó
ese histórico para satisfacer la prueba. La selección enfocada omite ese experimento
antiguo y el caso de plantilla anterior `test_projection_resources[template]`, y
mantiene pruebas reales de la plantilla actual y de los gates del contrato de tesis.

Resultado de esta corrección: **286 passed, 1 deselected** (165.43 s), más la
reverificación final de tres casos tras el último ajuste (5 positivos + 40 insuficientes
+ 3 bloqueados; excepciones locales de schema y semántica): **3 passed**.
Compilación Python y `git diff --check` correctos. No se declara aprobada toda la suite.

La selección ejecutada comprende `test_resume_blocked_indicators.py`,
`test_batching_monitor.py`, `test_thesis_output.py`, las dos pruebas de exportación
parcial de `test_manual_pipeline.py`, `test_autonomous_execution.py` (excepto la
expectativa antigua de plantilla indicada), `test_assessment_recovery.py`,
`test_evidence_references.py`, `test_context_budget.py`, `test_token_limit_recovery.py`,
`layer5_experiment/test_assessment_v3.py`, la nueva prueba de resumen de consola y las
pruebas de resume sin exportación y de cinco proyectos procesados de
`test_unified_runner.py`. Se usaron transportes simulados y checkpoints temporales.

### Aceptación principal: 47 válidas y un bloqueo

Se reforzaron las pruebas existentes con dos casos de integración en
`tests/test_resume_blocked_indicators.py::test_47_persisted_valid_results_survive_one_error_export_and_resume`.
Solo se simula HTTP: se ejecutan el planificador real, los gates SK por referencias,
la persistencia de llamadas y filas, el exportador, la lectura del Excel y resume.
Los documentos, rúbricas y checkpoints son sintéticos y temporales.

| Válidas conservadas | SUPPORTED | INSUFFICIENT_EVIDENCE | Bloqueadas | Filas Excel | Estado |
| ---: | ---: | ---: | ---: | ---: | --- |
| 47 | 3 | 44 | 1 | 3 | PARTIAL |
| 47 | 0 | 47 | 1 | 0 | PARTIAL |

En ambos casos se comprueba un proyecto procesado y cero completamente evaluados.
Las tres filas positivas conservan la evidencia literal y su localización verificada.
El Excel vacío registra ausencia de SUPPORTED en `export.json`, sin exclusiones de
exportación; el archivo existe y su SHA-256 se comprueba en la regresión de exportación.
El indicador técnicamente inválido no aparece entre las 47 evaluaciones válidas ni
se contabiliza como insuficiente. Las pruebas de excepciones de schema/semántica
verifican además `confidence is None` para los bloqueados en el recibo de auditoría.

Tras exportar se ejecutan dos resumes: no se consulta el modelo, no aumenta el número
de llamadas, cada uno de los 47 indicadores válidos tiene exactamente una solicitud
y todos los archivos del checkpoint original permanecen idénticos byte a byte.
El bloqueo permanece individual, agotado y visible. Se conserva el caso con 34
indicadores pendientes y estado PARTIAL, además de la recuperación de recibos
interrumpidos y evaluaciones pendientes sin duplicar llamadas.

Verificación adicional de aceptación: **13 passed** (casos exactos de 48 indicadores,
exportación, errores con confianza nula, cinco proyectos y consola) y **10 passed**
(interrupciones V3/SK, resume y errores de miembros compartidos). `git diff --check`
correcto. En esta comprobación solo se ampliaron dos archivos de pruebas existentes
y este registro; no se ejecutaron modelos ni proyectos reales.
