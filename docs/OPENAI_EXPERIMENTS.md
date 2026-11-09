# Comparación Ollama / OpenAI en el pipeline existente

Rutas y publicación actualizadas: [almacenamiento](ALMACENAMIENTO.md). El contrato de tesis está expresamente autorizado para Git; los demás contratos y todos los outputs siguen privados. Los informes anteriores describen su fecha.

Integración inicial preparada el 2026-11-08, sin ejecutar proyectos, embeddings,
modelos ni comprobaciones de conexión. El contrato definitivo de 30 evaluables se
creó el 2026-11-09, sin inferencias; consultar la sección Contratos.
Los comandos siguientes son instrucciones para ejecutar personalmente más adelante.

Estado de integración y limitaciones: [auditoría final](status/auditoria_final_repositorio.md).
`prepare --autonomous` puede construir embeddings locales: no usarlo como prueba
de instalación. La auditoría solo ejecutó mocks, nunca esos comandos sobre fuentes reales.

## Archivos de esta integración

Nuevos (nueve):

- `config/openai.json`
- `src/model_access.py`
- `src/experiment_runtime.py`
- `src/evaluation_contracts.py`
- `src/run_control.py`
- `src/layer4_evaluation/indicators/openai_provider.py`
- `scripts/check_shareable_secrets.py`
- `tests/test_api_contract_integration.py`
- `docs/OPENAI_EXPERIMENTS.md`

Integración modificada (dieciséis; se conservaron los demás cambios previos del workspace):

- `.gitignore`, `requirements.txt`, `run.py`, `scripts/pipeline_coordinator.py`
- `src/project_menu.py`, `src/layer4_evaluation/live_execution.py`
- `src/layer4_evaluation/indicators/ollama_provider.py`, `src/layer4_evaluation/indicators/performance.py`
- `src/autonomous_execution/engine.py`, `src/autonomous_execution/lifecycle.py`
- `src/autonomous_execution/minimal.py`, `src/autonomous_execution/final_output.py`
- `src/autonomous_execution/store.py`, `src/autonomous_execution/prepare_menu.py`
- `src/autonomous_execution/preparation_integrity.py`, `src/autonomous_execution/resource_wait.py`

## Preparación por computador

Instalar uv siguiendo el Inicio rápido de `README.md`. Desde la raíz del clon:

```powershell
uv sync --locked
uv run python run.py
```

Ollama solo es necesario al elegir el proveedor local; OpenAI no requiere instalarlo.
Conservar BGE-M3 y los demás recursos descritos en
`docs/RUNBOOK.md`. No se descargan pesos desde este adaptador. Cada computador
necesita las mismas fuentes institucionales y los recursos aprobados del catálogo,
distribuidos por un canal privado autorizado. Un clon público no incluye esas bases,
los pesos ni las publicaciones privadas del catálogo. En particular, los mecanismos
existentes de catálogo todavía verifican `closure.plan.json`, su manifiesto,
`outputs/layer4/indicator_profiles/` y las rúbricas aprobadas referidas por ese plan;
no deben publicarse esos artefactos sin revisar su contenido y autorización.

Los contratos verifican bytes SHA-256 de fuentes, población, mapeos de selección,
perfiles, rúbricas y reglas. Las diferencias bloquean el uso del contrato. Las
relaciones continúan pasando por el ETL y el resolvedor de identidad existentes.
No se exige que los dos computadores tengan la misma ruta absoluta: se crea una
ejecución independiente en cada uno. Un checkpoint autorizado sí pertenece a su
raíz y a su versión de código; no se traslada como sustituto de una ejecución nueva.

## Menú y preferencias

El menú conserva ejecutar pipeline, ejecutar etapa, reanudar y verificar fuentes.
La opción 5 es **Cambiar modelo**; el estado se consulta desde otra terminal con
`status`. El encabezado muestra `MODELO ACTUAL: LOCAL | ...` u
`OPENAI API | gpt-6.1-terra`.

Cambiar modelo ofrece Ollama y OpenAI. La preferencia se conserva en
`config/model.local.json`, ignorado por Git, y se aplica a ejecuciones nuevas.
`--provider ollama` y `--provider openai` permiten elegirlo por comando. Cambiar
la preferencia no cambia el proveedor de una ejecución ya preparada. La configuración
y presupuesto se congelan en `outputs/runs/<grupo>/<ID>/manifiestos/model.binding.json` y se incorporan
a los manifiestos/revisiones. No se mezclan respuestas entre modelos.

```powershell
uv run python run.py model --provider ollama
uv run python run.py model --provider openai
```

El submenú de selección de proyectos base conserva cantidad/todos y añade
**Contratos de evaluación → Crear contrato / Utilizar contrato existente / Volver**.
También está disponible sin preparar ni ejecutar un proyecto:

```powershell
uv run python run.py contracts
```

## Clave API

`model --provider openai` pregunta **Utilizar API existente** o **Configurar nueva
API** cuando encuentra credenciales; si no hay, ofrece configurarlas. La entrada
usa `getpass` y rechaza terminales que no puedan ocultarla. No se admiten claves
como argumentos. Guardarla no prueba la API ni genera consumo.

Se prefiere `keyring` con el almacén del usuario (Windows Credential Manager en
Windows). Servicio: `GraphRAG.OpenAI`, cuenta: `api-key`. Si no está disponible,
se solicita aceptación explícita de `.env.openai.local`: texto plano excluido de
Git, legible por otros procesos con acceso a la cuenta/directorio y por copias de
seguridad. En Windows el modo POSIX 0600 no sustituye una ACL. Preferir el almacén
seguro. La opción de configurar una nueva reemplaza la anterior. Un reemplazo
aceptado en archivo tiene precedencia sobre un almacén antiguo que no pudo
actualizarse; volver a guardar en el almacén elimina ese archivo.

También se reconoce `OPENAI_API_KEY` ya provisionada por el entorno del usuario.
No introducir claves con comandos que queden en el historial. Cada integrante
configura su propia credencial. Ollama no necesita clave ni importa el SDK al usar
su transporte local. La disponibilidad se comprueba antes de iniciar evaluación API,
sin consultar saldo ni hacer una llamada de prueba.

## Contratos

**Contrato definitivo de tesis creado (2026-11-09):**
`data/contratos/tesis_comparacion_30.v1.json` contiene 30 IDs únicos y reproducibles,
semilla 42, elegidos entre 1.863 proyectos con texto sustantivo autorizado. Se
excluyeron 369 proyectos sin ese texto antes de aplicar el mismo muestreo
estratificado; no se modificaron fuentes. La regla `AUTHORIZED_SUBSTANTIVE_TEXT_V1`
y el hash de la población elegible se verifican al cargarlo y al ampliar la muestra.
Esto permite intentar una evaluación, sin garantizar evidencia suficiente para
cada indicador. Ver [validación y comandos](status/validacion_contrato_tesis30.md).
Cargar desde **Ejecutar pipeline completo →
base → Contratos de evaluación → Utilizar contrato existente**; N conserva los 30,
S exige una cantidad adicional finita. Los IDs originales no se reemplazan.

Crear desde el menú pregunta nombre, cantidad obligatoria y semilla (42 por
defecto). Los nombres admiten letras ASCII, números, `_` y `-`. El muestreo es el
estratificado existente; los proyectos son únicos y el orden queda fijado.
Crear el mismo nombre produce `.v2.json`, `.v3.json`, etc.; no sobrescribe versiones.
El menú pregunta si se exige texto sustantivo autorizado (S por defecto).
En CLI, `contract-create --require-evaluable` fija esa regla en contratos nuevos;
sin la opción se conserva el comportamiento anterior de toda la población.
Los contratos antiguos se siguen leyendo sin aplicarles un filtro nuevo.

Ejemplo de comando de creación **para ejecutar después**, con tres proyectos de
ejemplo, no el contrato definitivo:

```powershell
uv run python run.py contract-create --contract-name piloto_compartido --count 3 --seed 42
```

Se guarda `data/contratos/piloto_compartido.v1.json`, con ID, versión, IDs ordenados,
cantidad, semilla, método, hashes de fuentes/catálogo/mapeos y hash del contrato.
No contiene textos, personas ni respuestas, pero los IDs también requieren
autorización de compartición. Estos archivos permanecen ignorados por defecto.
Compartir exactamente el mismo JSON por canal autorizado o, **solo después de
autorizar su contenido**, añadir ese archivo específico a Git:

```powershell
git add -f -- data/contratos/piloto_compartido.v1.json
```

Seleccionar un contrato pregunta `¿Desea procesar proyectos adicionales? (S/N)`.
N conserva exclusivamente los obligatorios. S exige una cantidad positiva finita;
se seleccionan adicionales excluyendo los obligatorios. El manifiesto registra
ambos grupos y su orden. La cola atiende el orden del contrato; con varios workers
las últimas solicitudes de un proyecto pueden seguir en curso al reclamar el
siguiente. Para orden estrictamente secuencial conservar un worker (predeterminado).
Seleccionar o crear no autoriza llamadas: siguen vigentes las revisiones y
confirmaciones del flujo normal o la autorización por hash del flujo autónomo.

## Ejecutar personalmente

Flujo normal, sobre el mismo contrato, en ejecuciones distintas:

```powershell
uv run python run.py run --provider ollama --contract data/contratos/piloto_compartido.v1.json --run-id local_01
uv run python run.py run --provider openai --budget-usd 15 --contract data/contratos/piloto_compartido.v1.json --run-id terra_01
```

Los permisos existentes de construcción local y revisión de textos permanecen
activos. Si se deja una revisión pendiente, continuar como indique la consola:

```powershell
uv run python run.py resume --run-id terra_01 --approve-build --authorize-llm
```

`--authorize-llm` ahora autoriza el proveedor congelado del run; se usa únicamente
después de revisar sus textos. No cambia de proveedor ni activa lotes experimentales.

Flujo autónomo (preparación local, revisión, autorización y ejecución separadas):

```powershell
uv run python run.py prepare --autonomous --provider openai --budget-usd 15 --contract data/contratos/piloto_compartido.v1.json --run-id terra_auto_01 --non-interactive
Get-Content outputs/runs/api/terra_auto_01/autonomous/main/manifest.json
```

Usar el SHA-256 que devuelve `prepare`, después de revisarlo:

```powershell
$manifestHash = (Get-FileHash outputs/runs/api/terra_auto_01/autonomous/main/manifest.json -Algorithm SHA256).Hash.ToLowerInvariant()
uv run python run.py authorize --autonomous --run-id terra_auto_01 --manifest-sha256 $manifestHash
uv run python run.py start --autonomous --run-id terra_auto_01
```

`--background` sigue disponible en `start`/`resume` autónomos. La preparación puede
usar las operaciones locales de conocimiento/descubrimiento del flujo existente;
no autoriza por sí sola evaluación API. La evaluación individual sigue por defecto;
API rechaza `--batch-size 2/3`.

Ampliar una ejecución nueva con un límite explícito, y repetir luego **los mismos
obligatorios y adicionales** con Ollama, sin copiar respuestas:

```powershell
uv run python run.py run --provider openai --budget-usd 15 --contract data/contratos/piloto_compartido.v1.json --additional-count 2 --run-id terra_ampliado
uv run python run.py run --provider ollama --selection-run terra_ampliado --run-id local_ampliado
```

`--selection-run` requiere el contrato original y revalida fuentes, catálogo e IDs.
En el otro computador pueden utilizar el mismo contrato y el mismo
`--additional-count 2`, que reconstruye idénticos IDs y orden si los hashes coinciden.
El mecanismo existente `--reuse-run` conserva proveedor y respuestas: no sirve
para comparar un modelo distinto. `--selection-manifest` mantiene su función previa.

## Presupuesto, errores y recuperación

`config/openai.json` configura razonamiento (`low` inicialmente), concurrencia,
reintentos de 429, espera, margen preventivo y tarifas. Referencia suministrada
para este experimento, fecha 2026-11-08: entrada USD 1/millón, salida USD 5/millón.
Verificar las tarifas antes de una ejecución; no son una consulta de precio o saldo
de la cuenta. El timeout y los límites de contexto/salida reutilizan la configuración
del pipeline y los niveles de `config/autonomous.json`.

Presupuesto operativo recomendado: USD 15; reservar otros USD 5 de un saldo
previsto de USD 20 es una decisión externa, no una comprobación del sistema.
Se exige `--budget-usd` en terminal no interactiva; en una terminal interactiva se
pregunta si falta. La configuración se conserva al reanudar. No se eleva el límite
silenciosamente ni se consulta el saldo real.

Antes de enviar se reserva un margen conservador de entrada y salida en SQLite
con transacción inmediata, incluyendo las llamadas concurrentes. `output_tokens`
ya incluye razonamiento: se registra su desglose sin cobrarlo dos veces. La caché
se registra y se valora conservadoramente a tarifa de entrada estándar. Se
contabiliza también una respuesta recibida que falle la validación semántica.
Al agotarse la reserva preventiva se detienen envíos y se exportan parciales.
Es una protección preventiva; no garantiza impedir cualquier sobrecosto.

Errores distinguibles: `API_AUTHENTICATION`, `API_BALANCE`, `API_PERMISSIONS`,
`API_RATE_LIMIT`, `API_SERVER_UNCERTAIN` y `API_OUTCOME_UNCERTAIN`. No se conservan
mensajes arbitrarios del SDK que pudieran contener credenciales. El SDK se inicia
con `max_retries=0`; solo se reintentan 429 de tasa de forma acotada. Los 5xx y
fallos de transporte se conservan como inciertos y **no se repiten automáticamente**,
porque podrían haber producido consumo. No se adivina su costo: se conserva la
reserva. Hay recibos de despacho, respuesta, IDs y uso en los directorios privados.
Un proceso terminado abruptamente puede dejar `IN_FLIGHT`; no borrar esos recibos.

Los resultados válidos persistidos se adoptan y revalidan sin otra llamada.
Los mecanismos previos de `retry-pending --acknowledge-uncertain` no convierten una
llamada pagada incierta en una llamada segura: primero comprobar el desenlace;
la recuperación puede continuar bloqueada por el recibo incierto. La resolución
de cobros inciertos requiere revisión humana, no un reenvío especulativo.
El nombre `gpt-6.1-terra` es el solicitado; se registra también el modelo devuelto
cuando existe. No se promete que un alias remoto fije pesos inmutables.

## Detener, exportar, reanudar

Desde otra terminal, en la misma raíz y entorno:

```powershell
uv run python run.py status --run-id terra_01
uv run python run.py stop --run-id terra_01
uv run python run.py status --run-id terra_01
uv run python run.py export --run-id terra_01 --partial
uv run python run.py resume --run-id terra_01
```

Para el autónomo:

```powershell
uv run python run.py stop --run-id terra_auto_01
uv run python run.py export --run-id terra_auto_01 --partial
uv run python run.py resume --autonomous --run-id terra_auto_01
```

`stop` escribe una solicitud cooperativa; no mata el proceso. El worker deja de
enviar, espera las llamadas en curso o registra su incertidumbre, conserva válidos
y exporta parciales. Esperar a que `status` muestre detenido antes de `export`;
el bloqueo de ejecución impide exportar a la vez que se escribe. Ctrl+C intenta
la misma finalización; un segundo interruptor, cierre forzado o corte de energía
puede impedirla. Reanudar limpia la solicitud anterior dentro del bloqueo y
conserva proveedor, modelo, contrato, versiones y presupuesto. Los resultados
inciertos continúan bloqueados. `export` no inicia inferencias, también con código
posterior cuando el exportador existente admite resultados archivados.

## Salidas y auditoría

Por ejecución, bajo `outputs/runs/<grupo>/<ID>/` (metadata en `estado/` y `manifiestos/`):

- `resultados/indicadores.csv`.
- `resultados/indicadores_territorios.csv`: solo `codigo_dane` adicional.
- `resultados/performance/`: métricas existentes más `provider.json` y, con API,
  `openai_usage.json` (tokens, razonamiento/caché, costo, reserva y disponible por run/proyecto).
- `manifiestos/runtime.manifest.json`: proveedor, modelo, contrato y proyectos completos,
  parciales, bloqueados o pendientes; `estado/project_states.json` suplementa el autónomo.
- `api-ledger.sqlite`: reservas y consumos API; no contiene claves.

Los tiempos del pipeline y recursos CPU/GPU/RAM/VRAM son observaciones locales.
Los recibos de API y `provider.json` separan respuesta remota; no se informa uso
de hardware de OpenAI. Se conservan además los exportadores Excel existentes.
La salida parcial representa pendientes como lo establece cada exportador previo,
sin convertirlos en decisiones de cumplimiento calculadas por Python.

## Validación mínima y GitHub

Se ejecutaron pruebas focalizadas con SDK falso e IDs sintéticos, y pruebas del
contrato CSV: 25 casos pasaron en 3,75 segundos; tras ajustar la integración se
repitieron solo los 12 casos nuevos, que pasaron en 0,90 segundos. El análisis
estático de sintaxis pasó y el escáner revisó 533 candidatos Git sin hallazgos.
No se ejecutaron proyectos institucionales ni se validaron conexiones de pago. La migración posterior a uv sincroniza
los paquetes Python ausentes sin ejecutar inferencias; véase `docs/instalacion.md`. Para repetirlas:

```powershell
uv run python -m pytest tests/test_api_contract_integration.py tests/test_indicator_csv.py -q
uv run python scripts/check_shareable_secrets.py
```

El escáner no imprime valores; detecta claves OpenAI reconocibles y rutas sensibles
entre candidatos Git. Es una revisión preventiva, no prueba que todos los datos
estén autorizados para publicarse. `.gitignore` excluye venv, credenciales, preferencias,
bases, contratos por defecto, salidas, pesos y cachés. No se hizo commit ni push;
hay cambios previos del workspace ajenos a esta integración que deben revisarse
antes de preparar un commit. No subir bases, artefactos con personas o contratos
sin autorización. Cada integrante configura su credencial y aporta recursos privados.

La integración de transporte sigue la documentación oficial de
[Responses y el modelo solicitado](https://developers.openai.com/api/docs/models/gpt-6.1-terra)
y de [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
La aceptación efectiva del modelo, los permisos de cuenta, límites y latencia solo
se podrán comprobar durante las ejecuciones que inicien los integrantes.
