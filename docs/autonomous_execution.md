# Ejecución autónoma de GraphRag

El modo autónomo es optativo. Mantiene Qwen3.5-4B, BGE-M3, los contratos V3,
los validadores de evidencia, las rúbricas y la fórmula de confianza existentes.
Los comandos históricos siguen disponibles para runs sin manifiesto autónomo.
No se reescriben autorizaciones, llamadas ni checkpoints históricos.

## Evaluador simplificado integrado

Los nuevos manifiestos preparados desde `run.py` usan el adaptador mínimo ya probado.
Qwen decide criterios, temporalidad, fuerza y conclusión; Python verifica referencias,
ensambla el contrato V3 y calcula la confianza existente solo tras validación completa.
Los manifiestos históricos sin evaluator conservan su motor original; requieren el
código exacto autorizado para reproducirse. No se migran ni reescriben sus resultados.

Una llamada por evaluación y, excepcionalmente, una aclaración acotada.
NOT_SUPPORTED / fuerza 0 expresa ausencia de soporte pertinente; no es el nombre
genérico de todo indicador no demostrado. INSUFFICIENT_EVIDENCE / fuerza 1 o 2
conserva respaldo débil o parcial sin afirmar cumplimiento global, incluso cuando
algunos criterios sean CLEAR. SUPPORTED / fuerza 3 o 4 mantiene los requisitos
de aceptación completos. La elección sigue siendo semántica y corresponde a Qwen.

La aclaración existente explica esa distinción cuando hay una contradicción entre
conclusión y criterios, y pide revisar tanto la categoría como el fundamento de los
juicios afectados. Python no reclasifica ni inventa una fuerza. Si persiste el error,
queda BLOCKED / CLARIFICATION_UNRESOLVED, sin tercera llamada ni confianza.
Los originales, fuentes y diagnósticos permanecen en autonomous/main/attempts.
El validador V3 sigue rechazando CLEAR basado solo en títulos y las demás
inconsistencias documentales. Otros indicadores continúan.

El Excel `resultado_final.xlsx` usa exclusivamente la plantilla oficial de
`data/templates/plantilla_resultado_final_indicadores_territorios.xlsx`, con las
hojas INDICADORES y TERRITORIOS. La confianza queda vacía para pendientes de
revisión. Los diagnósticos técnicos permanecen en el run. El reconocimiento
territorial usa solamente sus fuentes seleccionadas y la referencia DANE sellada.

Para la prueba institucional de nueve evaluaciones, ejecute uv run python run.py prepare
--autonomous en una sola línea. Seleccione Archivo específico, navegue a
prueba_3_proyectos/10_Proyectos_Objetivos.xlsx, elija determinados proyectos e
introduzca 5501,4636,4836. No se seleccionan indicadores en el menú normal.
La preparación construye GraphRAG local y compara cada proyecto con los 48
perfiles y sus criterios usando BGE-M3, sin Qwen. Un mismo fragmento sustantivo
original debe superar los umbrales de perfil, criterio y consulta contextualizada.
Los umbrales de `retrieval.candidate_admission` en `config/layer3.yaml` son
PROVISIONALES: no son probabilidades ni una calibración validada de pertinencia.
No existe una cuota ni un top-k de indicadores. `discovery.json` conserva las
comparaciones de los 48 indicadores por proyecto, fragmentos, puntuaciones,
exclusiones y sensibilidad a umbrales; una exclusión no es NOT_SUPPORTED.
La selección y los recursos territoriales se fijan en el manifiesto antes de
autorizar inferencias. Sin relaciones verificables del grafo se usa la señal
vectorial y se registra contribución relacional cero. La preselección no decide
cumplimiento ni exige que se hayan alcanzado impactos. `--indicators` queda
reservado a depuración y regresiones; omitirlo en el uso normal.
Revise el manifiesto y
pulse Enter para dejarlo pendiente, o escriba AUTORIZAR solo cuando decida iniciar.

La misma preparación para scripts usa los selectores existentes, sin
`--indicators`. La selección automática queda congelada en el manifiesto;
no se aceptan cambios al iniciar o reanudar. No se presupone ninguna etiqueta humana.

## Preparar desde el menú

Con una terminal interactiva, para una ejecución nueva:

```powershell
uv run python run.py prepare --autonomous
```

El menú ofrece **Base institucional completa**, **Archivo específico** y
**Entrega completa**. La primera opción selecciona únicamente `base`. Para un
archivo, se abre directamente `data/layer1_sources/incoming/`: se navega por
carpetas y archivos compatibles mediante números, con opciones para subir de
carpeta y cancelar. Las entregas son las carpetas directamente contenidas en
`incoming`; se incluyen todos sus archivos y subcarpetas. Las rutas redirigidas,
archivos ocultos y temporales no se ofrecen en el navegador.

Después se muestran los identificadores disponibles: puede elegir todos o
escribir determinados IDs separados por comas. Los IDs inexistentes, duplicados
o vacíos se notifican y se vuelven a solicitar. Se conservan los ceros iniciales.
El descubrimiento usa los adaptadores, mappings y normalización existentes; el
alcance se vuelve a comprobar contra las identidades canónicas antes de crear el
manifiesto. En base/archivo, un subconjunto también utiliza el acotamiento ETL
existente. Para una entrega, se prepara su contenido completo y se limita la
evaluación a los proyectos elegidos, manteniendo el contrato histórico de entrega.

Python prepara los datos locales y genera el manifiesto con la configuración
vigente: GraphRAG, BGE-M3, Qwen mediante Ollama local, los 48 indicadores y la
política autónoma existente. El menú no pide parámetros técnicos ni editar JSON.
La preparación construye o recupera embeddings BGE-M3 locales y el grafo para
fijar los candidatos antes de la autorización. No ejecuta inferencias de Qwen;
consulta sus metadatos locales como ya lo hace `prepare`. El proceso de BGE
termina antes de revisar el manifiesto o iniciar el worker de Qwen.

La consola y `autonomous/main/review_summary.txt` presentan los archivos y hashes,
proyectos, evaluaciones previstas, catálogo, modelo, política y ubicación de
resultados. Después de revisar el resumen, escriba **AUTORIZAR** para autorizar
ese SHA-256 e iniciar el worker existente en segundo plano hasta la exportación.
Es una sola autorización; no vuelve a preguntarse por proyecto o reintento.
Enter, cualquier otra respuesta o EOF dejan el manifiesto sin autorizar. Si el
manifiesto cambia durante la revisión, la autorización se rechaza.

Ejemplo para toda la base:

```text
uv run python run.py prepare --autonomous
Fuente documental
1. Base institucional completa
2. Archivo especifico
3. Entrega completa
0. Cancelar
Opcion: 1

Proyectos a procesar
1. Todos los proyectos disponibles
2. Determinados proyectos (IDs separados por comas)
0. Cancelar
Opcion: 1

[Python prepara los datos y muestra el manifiesto y su resumen]
Autorizar este manifiesto e iniciar en segundo plano [AUTORIZAR/Enter para dejar pendiente]: AUTORIZAR
```

Anote el Run ID mostrado. Puede consultar y reanudar posteriormente:

```powershell
uv run python run.py status --autonomous --run-id <RUN_ID>
uv run python run.py resume --autonomous --run-id <RUN_ID> --non-interactive --through export --background
```

Los comandos explícitos (`--projects`, `--file`, `--file --projects`, `--delivery`),
`--non-interactive` y las operaciones sobre un `--run-id` conservan su flujo
anterior. El menú se abre únicamente con `prepare --autonomous` en una terminal,
sin un Run ID ni selectores explícitos. No cambia los parámetros administrables
mediante los mecanismos internos existentes.

La adaptación está en `src/autonomous_execution/prepare_menu.py`, registrada por
`scripts/__init__.py`. Este registro aditivo conserva byte por byte `run.py`, el
coordinador y el despachador autónomo, cuyos hashes ya están fijados por runs
históricos. Las operaciones existentes delegan al despachador original; las
preparaciones nuevas fijan también el hash del nuevo módulo en sus manifiestos.

## Arquitectura y alcance de autorización

La preparación produce `outputs/runs/<run>/autonomous/main/manifest.json`.
En runs nuevos, `autonomous/catalog_releases/` registra por separado los datos
aprobados del catálogo y los fingerprints actuales del ejecutor y los esquemas.
Se comprueban los perfiles publicados, su catálogo fuente y snapshot, las reglas
y las rúbricas aprobadas, sin exigir los hashes de ejecutables de un antiguo
experimento. No se regeneran rúbricas ni se modifican criterios. El manifiesto
fija tanto los recibos de datos como el código actual; una modificación posterior
se rechaza con ruta, regla, hashes esperado/calculado y origen. Un checkpoint de
datos preparado con código realmente diferente exige restaurar ese código o
crear un run nuevo; sus hashes no se actualizan para hacerlo pasar.

Si la preparación de datos ya está `PREPARED` y la creación del manifiesto falló,
puede completarse con `uv run python run.py prepare --autonomous --run-id <RUN_ID>`.
Se validan y reutilizan sus checkpoints, sin repetir el procesamiento de datos.
Este comando muestra el SHA-256 para los comandos existentes `authorize` y
`start`; el menú de selección se reserva para ejecuciones nuevas. Los manifiestos
históricos y las evaluaciones existentes mantienen su verificador y sus bytes.

Incluye las fuentes y sus hashes, selección de proyectos/archivo/entrega,
instantáneas autorizadas por proyecto, catálogo y rúbricas, proveedor local,
modelo/digest/versiones, configuración de embeddings, versiones y plantillas de
prompts, esquemas, política de selección de contexto, reintentos, subdivisión y
recuperación diferida. Los módulos del ejecutor también quedan fingerprintados.

La autorización por comando exige el SHA-256 exacto del manifiesto revisado; el
menú vincula la aprobación explícita al mismo hash que acaba de mostrar. No hay
`--yes`, autorizaciones por defecto ni preguntas `si/NO` en este modo. La política
aprobada cubre la generación posterior de prompts por indicador, reintentos,
subevaluaciones y síntesis local. Un cambio de fuentes, alcance, código aprobado,
modelo, proveedor o política impide continuar con esa autorización. El transporte
solo admite Ollama HTTP en localhost; no utiliza proxies, redirecciones, cloud,
herramientas, descargas ni fallback de proveedor.

La selección se delega al coordinador existente, conservando `--projects`,
`--file`, `--file --projects` y `--delivery`. La preparación solo ejecuta
preprocesamiento/conocimiento cuando faltan; no genera embeddings ni inferencias.
Para un run nuevo consulta metadatos de Ollama para fijar el modelo. Para un run
histórico con proveedor verificado reutiliza sus metadatos, sin llamar al servidor.

GraphRAG se construye después de autorizar, solo si falta la publicación. Usa el
constructor original en un proceso local separado que termina antes de evaluar
con Qwen: la salida del proceso libera los recursos de BGE, incluida su reserva
GPU. Los modelos no se descargan. Una publicación existente se valida por hashes,
snapshot de conocimiento y fingerprint de BGE sin cargar pesos ni vectores completos
en memoria. El índice de candidatos se deriva en disco y se comprueba también por
proyecto; no crea fuentes ni cambia el ranking de GraphRAG.

## Presupuestos y recursos

### Espera automática por RAM

Las preparaciones nuevas de un solo worker incluyen `resource_wait` en el
manifiesto revisado. Si la RAM física disponible es menor que el mínimo aprobado,
no se inicia la inferencia. El indicador pasa a `WAITING_RESOURCES`, se registra
la medición en MiB, su umbral y fecha, y se intenta liberar basura de Python y
caché de SQLite sin descartar datos activos. Una limpieza opcional fallida no
convierte el indicador en un error semántico.

Las comprobaciones esperan 60, 120, 240 y después 300 segundos como máximo. La
recuperación exige dos mediciones estables con 256 MiB de margen adicional sobre
el piso de RAM. No se cambia el mínimo de 1536 MiB ni se consumen intentos del
LLM o rondas de recuperación por esperar. `keep_alive=5m` se conserva: durante la
espera no se renueva mediante inferencias ni se envían peticiones de descarga.
Ollama puede liberar naturalmente el modelo al vencer ese plazo.

La política de espera se administra en `config/autonomous_resources.json`, que
extiende `config/autonomous.json` sin duplicar los presupuestos del evaluador.
Los valores efectivos quedan congelados en el manifiesto. `max_wait_seconds=0`
permite esperar indefinidamente a ritmo limitado. Si se configura un plazo
positivo, al agotarlo termina el worker conservando `WAITING_RESOURCES`; una
reanudación explícita abre otra ventana de espera y conserva el tiempo total
registrado desde la primera detección.

`status` incluye `waiting_resources` y `resources`. La última observación y la
primera detección se guardan también en `autonomous/main/resource_wait/<pid>/<iid>.json`.
La tabla SQLite `resource_samples` conserva las mediciones y sus fechas. Las
evaluaciones en espera cuentan como pendientes, sin convertirse en `BLOCKED` ni
`NOT_SUPPORTED`. Después de un reinicio, `resume` reencola las esperas y los
bloqueos anteriores `RESOURCE_RAM_FLOOR`; no reintenta automáticamente evidencia
inválida, resultados inciertos ni errores de memoria ocurridos tras despachar.

Para incorporar este comportamiento a un run **ya autorizado** con la política
anterior se requiere una ampliación explícita, conservando su manifiesto,
autorización, PASS y exportación anteriores:

```powershell
uv run python run.py prepare --autonomous --run-id <RUN_ID> --policy config/autonomous_resources.json --non-interactive
uv run python run.py authorize --run-id <RUN_ID> --manifest-sha256 <SHA256_DE_LA_AMPLIACION>
uv run python run.py resume --autonomous --run-id <RUN_ID> --non-interactive --through export --background
```

La ampliación está en `autonomous/resource_recovery/manifest.json`; vincula el
manifiesto y la autorización originales, los nuevos fingerprints de código y la
política de espera. Solo la inicialización de la consola cambia entre los
archivos previamente fijados; sus bytes anteriores se conservan en un snapshot
verificado. Los demás fingerprints originales, fuentes, evidencias y resultados
siguen verificándose. El SHA-256 de la ampliación exige su propia aprobación;
un cambio posterior de código la invalida. Antes de aprobarla, el estado indica
`REVIEW_REQUIRED_RESOURCE_POLICY` y no se inicia el worker. El Excel parcial
anterior se conserva además en `resource_recovery/preserved_exports/` para que
una exportación posterior no lo pierda.

La política se configura en `config/autonomous.json` **antes** de preparar y
autorizar. No existen cuotas acumuladas de tokens, llamadas, proyectos o duración
del run. Sí hay límites finitos para cada solicitud y cada recuperación:

| Nivel | `num_ctx` | `num_predict` | Margen | Entrada disponible |
|---|---:|---:|---:|---:|
| 1 | 4096 | 1536 | 768 | 1792 |
| 2 | 6144 | 2048 | 768 | 3328 |
| 3 | 8192 | 4096 | 768 | 3328 |

Se propone inicialmente una salida según el número de criterios
(`512 + 180 × criterios`) y se usa el nivel menor donde el prompt, esquema,
margen y evidencia realmente caben. El preflight que no cabe no consume una
inferencia. Se mantiene un techo de contexto de 8192 por defecto, configurable
hasta 16384 mediante una nueva revisión; nunca se crece indefinidamente.

El presupuesto usa el estimador existente de UTF-8/3, explícitamente aproximado,
incluyendo el esquema de la fase. Los conteos nativos de Ollama se verifican después
de cada llamada. `truncate=false` y `shift=false` se conservan. No se reduce
silenciosamente una cita para encajar; solo pueden seleccionarse fragmentos
originales o ventanas de oraciones completas, y cada omisión queda auditada.

Para `PROJ_4636 / DIV-04` se verificó offline: siete criterios, los tres fragmentos
seleccionados y estimación de entrada 2644 sobre 3328 disponibles en el nivel
6144/2048. El límite anterior de salida era 1024. Esto no sustituye la prueba real
del modelo ni garantiza que todas las respuestas sean válidas.

Hay dos intentos como máximo por fase; tres intentos de metadatos idempotentes
ante indisponibilidad temporal; espera de cinco segundos entre intentos; una
ronda diferida de recuperación explícita. Las evaluaciones complejas se dividen
en grupos de tres criterios, con IDs exactos, citas e índices propios. Después se
combinan sus referencias y **Qwen** toma la decisión sobre la rúbrica completa.
Python no decide el soporte ni infiere decisiones desde porcentajes. El resultado
fusionado pasa la validación V3 completa antes de calcular confianza. Si la síntesis
completa tampoco cabe en el techo aprobado, el indicador queda bloqueado.

Los límites de explicaciones son 240 caracteres por criterio y 600 por evaluación,
configurables. Son restricciones del esquema y de generación, no cortes del texto
recibido. Las citas no se recortan para ajustarse a esos límites.

Por defecto hay **un worker**, con máximo configurable de dos. Se comprueba un
mínimo de 1536 MiB de RAM libre y 1024 MiB de disco libre antes de cada inferencia.
Ante OOM se pausa; no se intenta resolverlo subiendo el contexto. La capacidad de
contexto declarada por el modelo se comprueba en el preflight. Estos controles no
son una medición exacta de VRAM: el techo aprobado y el rechazo por OOM siguen
siendo necesarios. El consumo de tiempo y tokens, errores y recursos previos
queda registrado por evaluación y fase.

El servidor Ollama administra sus propios slots. Para una máquina dedicada y
conservadora, usar `OLLAMA_NUM_PARALLEL=1` y `OLLAMA_MAX_LOADED_MODELS=1` en el
entorno del servidor, sin iniciar otra instancia desde este pipeline. La memoria
necesaria aumenta con contexto y paralelismo; `keep_alive` permite reutilizar el
modelo y liberar su reserva tras inactividad. Véase la [FAQ oficial de Ollama](https://docs.ollama.com/faq).
El ejecutor no modifica las variables del servidor ni reinicia Ollama.

## Preparar, revisar y autorizar

Ejemplos alternativos de preparación, desde la raíz del repositorio:

```powershell
uv run python run.py prepare --run-id institucional_01 --projects 4636,5501 --non-interactive
uv run python run.py prepare --run-id archivo_01 --file incoming/entrega/proyectos.xlsx --non-interactive
uv run python run.py prepare --run-id archivo_filtrado_01 --file incoming/entrega/proyectos.xlsx --projects 4636 --non-interactive
uv run python run.py prepare --run-id entrega_01 --delivery entrega --non-interactive
```

No ejecutar los cuatro ejemplos para la misma selección: representan modalidades
alternativas. Se puede seleccionar otra política con `--policy ruta/politica.json`.
La configuración queda congelada en el manifiesto y no se cambia durante start/resume.

Revisar `outputs/runs/<run>/autonomous/main/manifest.json` y los archivos locales
que identifica. La preparación devuelve su SHA-256 y estado `REVIEW_REQUIRED`.
Después de revisarlo:

```powershell
uv run python run.py authorize --run-id institucional_01 --manifest-sha256 <SHA256_REVISADO>
```

La autorización no inicia modelos. Los flags históricos `--authorize-llm` y
`--approve-build` se rechazan en el modo autónomo; no sustituyen este consentimiento.

## Iniciar, consultar y reanudar

En primer plano, sin preguntas:

```powershell
uv run python run.py start --autonomous --run-id institucional_01 --non-interactive --through export
```

Para dejarlo independiente de la ventana de PowerShell:

```powershell
uv run python run.py start --autonomous --run-id institucional_01 --non-interactive --through export --background
```

El arranque devuelve PID y rutas de logs. En Windows se usa un proceso sin ventana
y separado de la consola, con stdin cerrado; no se ejecuta una shell intermedia.
El modelo permanece en el servidor Ollama existente. El equipo debe permanecer
encendido; después de un reinicio se reanuda con el comando siguiente, sin otra
autorización si el alcance sigue intacto:

```powershell
uv run python run.py status --autonomous --run-id institucional_01
uv run python run.py resume --autonomous --run-id institucional_01 --non-interactive --through export --background
```

El modo autónomo activo también se reconoce en `status` y `resume` sin flag. Los
comandos históricos `run/stage` sobre ese mismo run se bloquean para no alterar sus
entradas. Para comprobar exhaustivamente fuentes, GraphRAG y resultados:

```powershell
uv run python run.py verify --autonomous --run-id institucional_01
```

`status` es una consulta ligera: manifiesto, código del ejecutor, metadatos del
inventario y contadores SQLite. No relee todos los vectores y resultados por cada
consulta; lo identifica como comprobación de metadatos. La verificación completa
se hace antes de ejecutar/reanudar y con `verify`. El estado incluye proyectos
totales/completados, PASS, pendientes, bloqueados, inciertos, recuperados, llamadas,
tokens conocidos y métricas faltantes, tiempo, etapa, última actividad, causas,
pasos diagnósticos, exportación y proceso. PID más identidad de creación permiten
detectar checkpoints RUNNING abandonados tras un reinicio.

## Persistencia y errores

La cola `queue.sqlite` usa WAL, transacciones y `synchronous=FULL`. La unidad de
checkpoint es PROJECT+INDICATOR; las fases y subevaluaciones también conservan sus
recibos. Cada PASS tiene un resultado escrito con flush/fsync y reemplazo atómico,
su hash, respuesta, evidencia, confianza y auditoría. El procesamiento mantiene en
memoria un proyecto/indicador por worker; usa lecturas Parquet por lotes e índices
SQLite para no acumular respuestas o contextos de todo el corpus.

| Situación | Acción |
|---|---|
| JSON/esquema/semántica/cita inválidos | Reintentos finitos y, cuando procede, subdivisión; nunca aceptar una cita falsa |
| Respuesta completa de transporte, salida cortada por tokens | Reintento con salida/contexto conjuntos dentro del techo |
| Metadatos temporalmente no disponibles | Reintentos idempotentes; si persiste, pausa con trabajos pendientes |
| HTTP ocupado/error conocido | Reintento acotado; circuito de fallos evita consumir todo el lote contra un servidor averiado |
| OOM/RAM/disco insuficientes | Pausa conservadora, registro explícito, sin aumentar contexto |
| Interrupción/timeout con resultado incierto | `UNCERTAIN`, conservar claim, no duplicar automáticamente esa llamada |
| Indicador irrecuperable | `BLOCKED`, continuar los demás si no hay dependencia crítica |
| Fuente/código/proveedor/resultado incompatible | Detener; no enviar información fuera del alcance autorizado |
| PASS antes de cerrar el proceso | Verificar recibo y reutilizar; no repetir inferencia |
| Respuesta validada persistida antes del checkpoint de job | Reconstruir el recibo offline y adoptar sin repetir |

Tres fallos de servicio consecutivos pausan el procesamiento. Los errores nunca
se convierten en `NOT_SUPPORTED`. Las respuestas incompletas, criterios parciales
de un shard y decisiones que contradigan sus criterios nunca se publican como PASS.

Para reencolar fallos dentro de la ronda diferida autorizada:

```powershell
uv run python run.py retry-pending --autonomous --run-id institucional_01
uv run python run.py resume --autonomous --run-id institucional_01 --non-interactive --background
```

Los PASS no se reencolan. Los bloqueos de fuentes/cuarentena/proveedor/código no
se resuelven con un reintento técnico. Para resultados inciertos, comprobar primero
que la llamada anterior ya terminó y después usar explícitamente:

```powershell
uv run python run.py retry-pending --autonomous --run-id institucional_01 --acknowledge-uncertain
```

Este reconocimiento no acepta la respuesta incierta ni inventa evidencia: permite
una nueva evaluación dentro de la única ronda diferida prevista. Los presupuestos
son vitalicios por fase/ronda; reiniciar no los pone a cero. Agotar esa ronda deja
el indicador bloqueado y exige revisar una nueva ejecución/política para continuar;
no existe un bucle infinito de recuperación. Un cambio de alcance o política
requiere otra preparación/autorización, conservando el run anterior.

## Resultados parciales

Se puede exportar mientras el worker continúa; se toma un snapshot consistente de
los PASS en SQLite, sin invocar modelos. También pueden exportarse los PASS
históricos importados antes de autorizar nuevas inferencias:

```powershell
uv run python run.py export --autonomous --run-id institucional_01 --partial
```

Produce `resultado_indicadores.autonomous.partial.xlsx`, con `INCOMPLETE_PARTIAL`
en COBERTURA y hojas de evaluaciones y pendientes/causas. Solo conserva decisiones,
citas, ubicaciones originales y confianza que pasaron los validadores. El resultado
final tiene nombre distinto: `resultado_indicadores.autonomous.final.xlsx`; se
rechaza su generación si la cobertura no es íntegra. No se sobrescribe el Excel
histórico. No se truncan textos para que quepan en Excel ni se interpretan como
fórmulas los textos provenientes de fuentes.

Al finalizar un ciclo start/resume se exporta el resultado final o el parcial,
según cobertura. `--through evaluation` omite ese paso. Una pausa o un resultado
parcial devuelve código de salida 3; autorización, arranque background y final
completo devuelven 0. El proceso en segundo plano conserva su resultado en logs.

## Recuperar `run_20261031_220138_059059`

La preparación autónoma importa las 13 evaluaciones válidas sin cambiar sus
decisiones, evidencia, confianza ni autorizaciones anteriores. Conserva el fallo
de `DIV-04` y el consumo histórico; este indicador queda pendiente en la cola nueva.
No modifica `run.json`, `execution.json` ni los lotes históricos. La autorización
anterior no cubría la nueva política y por eso se requiere revisar y autorizar
este manifiesto una sola vez.

```powershell
uv run python run.py prepare --run-id run_20261031_220138_059059 --non-interactive
```

Revisar `outputs/runs/run_20261031_220138_059059/autonomous/main/manifest.json`.
Después, con el hash devuelto por prepare:

```powershell
uv run python run.py authorize --run-id run_20261031_220138_059059 --manifest-sha256 <SHA256_REVISADO>
uv run python run.py start --autonomous --run-id run_20261031_220138_059059 --non-interactive --through export --background
```

```powershell
uv run python run.py status --autonomous --run-id run_20261031_220138_059059
uv run python run.py export --autonomous --run-id run_20261031_220138_059059 --partial
uv run python run.py resume --autonomous --run-id run_20261031_220138_059059 --non-interactive --through export --background
```

La preparación del run y su comprobación offline se documentan en
`docs/status/autonomous_20261101.md`. La ejecución real de Qwen y cualquier nueva
construcción de embeddings quedan a cargo del usuario.
