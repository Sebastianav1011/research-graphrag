# Auditoría final del repositorio GraphRAG

Fecha: 2026-11-08. **Estado general: NO LISTO para publicar el repositorio completo ni dar por aceptadas las pruebas reales.** El runtime actual supera las verificaciones focalizadas sin inferencia; quedan condiciones de publicación, recursos privados y regresiones históricas pendientes. No equivale a afirmar que el evaluador actual esté bloqueado.

## 1. Componentes revisados

| Componente | Estado | Evidencia y alcance |
|---|---|---|
| Conjunto actual de Git | FAIL | `run.py`, archivos uv y paquetes actuales siguen sin seguimiento. Hay eliminaciones de namespaces anteriores aún pendientes de publicar. Publicar solo lo ya seguido no reproduce este workspace. |
| Exclusiones y secretos | PASS / WARNING | Revisión de `git status`, `ls-files`, `check-ignore`, patrones de secretos y plantillas. Sin credenciales detectadas en candidatos existentes. Esta búsqueda no certifica privacidad de textos institucionales. |
| Documentación histórica | WARNING | Más de cien informes de estado/migración requieren revisión antes de compartirse: contienen referencias, IDs o evidencias de ejecuciones anteriores. No autorizar su publicación mediante un agregado masivo. |
| uv / Python Windows x64 | PASS | Python 3.14.0, uv 0.13.7, lock de 96 paquetes. Sincronización exacta bloqueada en entorno independiente; ver límites de la comprobación en §5. |
| Linux / macOS | WARNING | Resolución declarada en el lock; no se instalaron ni ejecutaron esos sistemas. macOS no está habilitado para el pipeline CUDA completo. |
| Imports / rutas | PASS / WARNING | AST de 167 módulos de producción/scripts, imports principales y arranque desde subdirectorio correctos. Sin rutas absolutas del computador en esos módulos. No se importaron backends reales de embeddings. |
| Menú / CLI normal | PASS | Encabezado de proveedor, cambio de modelo, selección cantidad/todos/contratos y cancelación; sin opción status en el menú principal. CLI y menú comparten coordinador y selector. |
| Ciclo autónomo | PASS | Mocks de autorización, recursos, checkpoints, interrupción, incertidumbre, recuperación y exportación. Requiere recursos privados para ejecuciones reales. |
| Contratos | PASS | IDs únicos y ordenados, semilla reproducible, versiones sin sobrescritura, hashes y ampliación excluyendo obligatorios. No se creó contrato institucional alguno. |
| Relaciones / selección | PASS | Tests sintéticos del ETL y de identidad compartida: no amplían proyectos ni inventan producción por compartir investigador. Se mantienen las relaciones institucionales verificadas. |
| Ollama | PASS / WARNING | Transporte, validadores y recuperación con mocks. Nombre publicado verificado; instalación, digest, RAM/VRAM y calidad real pendientes. |
| OpenAI Responses | PASS / WARNING | SDK oficial, esquema estricto y validación semántica existente; SDK falso en pruebas. Identificador publicado verificado; acceso de cada cuenta y respuesta real no verificados. |
| Claves | PASS / WARNING | Entrada oculta, almacén del usuario, reemplazo y reutilización; ningún test facturable. Fallback explícito en texto plano ignorado; permisos de cuenta/ACL y almacén real deben prepararse en cada equipo. |
| Presupuesto | PASS / WARNING | Reservas SQLite, límites, concurrencia, errores, reintentos 429, costos y agotamiento con mocks. Protección preventiva, sin consulta de saldo y sin garantía de sobrecosto cero. |
| Stop / export / resume | PASS | Stop cooperativo, Ctrl+C, exportación sin inferencia y recuperación conservando resultados válidos. Pruebas API incluyen detención, reanudación y presupuesto agotado. |
| CSV / territorios / performance | PASS | CSV principal, territorial con solo `codigo_dane` adicional y carpeta performance. Ceros iniciales preservados al leer como texto. Hardware remoto no disponible, sin valores inventados. |
| Suite histórica completa | FAIL | Línea base: 1460 pasan, 91 fallan, 55 errores de preparación. No se declara verde ni se reescribieron snapshots para evitar los fallos. |
| Recursos privados en clon | WARNING | El menú funciona sin ellos; procesar proyectos exige paquete autorizado de fuentes, catálogo, perfiles/rúbricas/planes, DANE y pesos BGE-M3. |

## 2. Errores encontrados y corregidos

- Se restauró el punto de sustitución `OllamaClient` del flujo local en `live_execution` y preparación autónoma. Los mocks existentes no interceptaban la nueva fábrica genérica; el guard de auditoría bloqueó el intento de transporte antes de conectar.
- Checkpoints JSON: nombres temporales únicos, escritura durable y reemplazo atómico. La prueba concurrente descubrió `WinError 5` en Windows; ahora se reintenta brevemente solo el reemplazo para errores de compartición transitorios, nunca una inferencia.
- SDK inyectado: evita leer credenciales reales cuando se prueba con un cliente falso; mensajes del SDK permanecen fuera de errores persistidos.
- Performance API: suma el tiempo remoto de todos los intentos, excluyendo la espera de backoff; el ledger cuenta envíos reales, incluidos 429, separados de solicitudes lógicas. Se conserva la reserva en resultados inciertos y se migra el esquema anterior sin perder reservas. Los detalles de razonamiento/caché no reportados permanecen nulos, con cobertura de observaciones, en lugar de atribuirles cero.
- Ctrl+C devuelve el estado interrumpido con su exportación parcial; la CLI evita exportarla dos veces.
- La selección del menú recibe raíz y configuración elegidas. La detección de un run autónomo usa el directorio configurado del coordinador. `stop` devuelve código de salida exitoso al registrar la solicitud.
- Pruebas de interrupción actualizadas al contrato de finalización segura, sin retirar las comprobaciones de resultados conservados y ausencia de duplicados. Relojes simulados quedaron limitados a resource_wait: antes alteraban el reloj global y producían fechas ZIP anteriores a 1980 durante la exportación.
- Mocks de la CLI actualizados para incluir la consulta de configuración/directorio usada por la validación del binding.
- `.gitignore` permite únicamente las tres plantillas Excel vacías conocidas, en lugar de cualquier Excel que se coloque en templates.
- README principal simplificado, con requisitos privados explícitos; configuración documentada con las rutas actuales. Guía OpenAI e índice documental enlazan esta auditoría y advierten que preparar un run puede construir embeddings.

No se cambiaron indicadores, fórmulas de confianza, fuentes originales ni resultados existentes. Los cambios de código sí afectan los hashes de ejecuciones autorizadas: no se alteraron sus manifiestos para hacerlas compatibles artificialmente.

Archivos creados por esta auditoría: este informe, `docs/status/auditoria_archivos_publicacion.json`, `tests/test_final_audit_regressions.py` y `tests/test_api_lifecycle_integration.py`.

Archivos modificados por esta auditoría:

- `.gitignore`, `run.py`, `README.md`, `config/README.md`, `docs/README.md`, `docs/OPENAI_EXPERIMENTS.md`.
- `src/layer4_evaluation/live_execution.py`, `src/layer4_evaluation/indicators/openai_provider.py`.
- `src/autonomous_execution/lifecycle.py`, `src/autonomous_execution/cli.py`, `src/autonomous_execution/store.py`.
- `tests/test_autonomous_execution.py`, `tests/test_resource_wait.py`, `tests/test_phase11_evaluation.py`, `tests/test_phase12_evaluation.py`, `tests/test_python_runner.py`.

Los demás cambios que aparecen en Git eran anteriores. Los auxiliares y evidencias temporales de la auditoría quedan ignorados en `.tmp/`.

## 3. Pendientes que afectan la aceptación

1. **Preparar el conjunto de Git.** El inventario técnico adjunto enumera los candidatos y los esenciales sin seguimiento. Revisar altas y bajas del refactor conjuntamente; no publicar el índice actual como si contuviera el runtime probado.
2. **Autorizar la privacidad documental.** Revisar informes antiguos, README secundarios con evidencias y cualquier contrato antes de añadirlos. El escáner de claves no detecta toda información personal/institucional. No se encontraron bases existentes entre los archivos de `data/` seguidos por Git; las tres plantillas candidatas se inspeccionaron y contienen encabezados, sin filas de datos.
3. **Distribuir el paquete privado reproducible.** El runtime aún obtiene las definiciones semánticas desde el plan de cierre aprobado y sus perfiles/rúbricas. Un clon sin esos artefactos no puede crear un contrato institucional ni evaluar proyectos. No se sustituyeron con definiciones inventadas.
4. **Regresiones históricas pendientes.** Persisten familias de pruebas de snapshots con fingerprints antiguos, archivos ZIP ausentes, flujos Codex bloqueados intencionalmente y comparaciones semánticas selladas. Otras pruebas todavía entregan JSON o Excel sin hoja `Proyectos`, incompatibles con el contrato vigente de entrada. También hay aserciones antiguas de estructura de carpetas, frontera performance/ETL y estados de cuarentena. No todos estos fallos se han demostrado inocuos: necesitan triage del equipo y fixtures actualizados antes de exigir una suite completa verde.
5. **Checkpoints anteriores.** Los sellados con otro código o raíz pueden rechazar resume/export en el runtime actual. Conservarlos y sus resultados; usar su versión original para reproducirlos. Las pruebas verdes de reanudación corresponden a runs nuevos preparados con la misma versión, proveedor y modelo.
6. **Validación externa deliberadamente pendiente.** Acceso a Terra por cuenta, cuotas efectivas, costo facturado, latencia, truncamiento/calidad de salida y rendimiento real de ambos equipos. `max_output_tokens` incluye razonamiento; los límites iniciales compartidos necesitan observación en las pruebas que iniciará el equipo.
7. **Plataformas y hardware.** Solo Windows x64 fue probado. OpenAI no requiere Ollama, pero la recuperación local conserva BGE-M3/CUDA. No se verificó ejecución completa en CPU, macOS o Linux.

No se bajaron gates de integridad ni se reactivó Codex histórico para lograr resultados verdes. No se eliminaron ni reorganizaron datos.

## 4. Archivos imprescindibles para Git

Consultar [inventario técnico de publicación](auditoria_archivos_publicacion.json): lista rutas, SHA-256, condición seguida/no seguida y exclusiones de alcance. Es una propuesta técnica, **no autorización de publicación de datos o textos**. Los recuentos corresponden al momento del inventario; el informe y su inventario también son nuevos.

Debe incluirse, tras revisión:

- `run.py`, `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, `setup.ps1` y `pytest.ini`.
- `scripts/__init__.py`, `scripts/pipeline_coordinator.py`, comprobadores y scripts que consumen los módulos vigentes.
- Los paquetes actuales `src/layer2_processing/`, `src/layer3_graphrag/`, `src/layer4_evaluation/`, `src/autonomous_execution/`, utilidades raíz de src y compatibilidad de namespaces.
- `src/model_access.py`, `src/experiment_runtime.py`, `src/evaluation_contracts.py`, `src/run_control.py`, `src/project_menu.py` y el adaptador `openai_provider.py`.
- Configuración pública, incluidos `config/pipeline_manual.json`, `config/openai.json`, políticas, relocations y schemas.
- Las tres plantillas vacías conocidas de `data/templates/`, tests y fixtures sintéticos autorizados, documentación vigente y este informe.

Al elaborar el inventario inicial había 539 candidatos existentes, 371 sin seguimiento, 246 archivos técnicos sin seguimiento y 133 rutas seguidas ausentes por el refactor. Los recuentos exactos actualizados están en el JSON. **No se hizo staging en el repositorio original.**

`.venv`, `.tmp`, secretos, preferencias locales, modelos, outputs y contratos permanecen excluidos. `.gitignore` no elimina un archivo ya seguido: la revisión del índice y del historial sigue siendo necesaria antes de publicar. No se auditó exhaustivamente cada commit histórico para certificar ausencia de secretos revocados.

## 5. Pruebas y validaciones realizadas

### Seguridad de la ejecución de auditoría

Se instaló un guard temporal heredado por pytest y sus subprocesos: bloquea conexiones socket, imports reales de transformers/sentence_transformers y escrituras Python en los `data/` y `outputs/` originales. Las opt-in de integración real quedaron desactivadas; se excluyeron dos módulos de integración real de la suite general. Las pruebas históricas pueden leer snapshots anteriores; no se lanzó un pipeline sobre proyectos institucionales.

### Resultados

| Verificación | Resultado |
|---|---|
| Suite general inicial, 1606 casos | 1460 PASS, 91 FAIL, 55 ERROR; 774 s. |
| Recuperación/autonomía/resource_wait/fases 11–12/CLI, después de corregir | 142 PASS; 91 s. |
| Modelos/contexto/contratos/selección/entorno/performance/CSV | 125 PASS y 1 fallo concurrente descubierto; se corrigió y se volvió a probar ese caso. |
| Regresiones nuevas + API simulada + CSV, tras corrección Windows | 30 PASS; 1,32 s. |
| Última comprobación CLI + regresiones/API/CSV | 66 PASS; 14,28 s. |
| Ciclo de vida API con SDK falso | 3 PASS; 7,67 s. Incluye presupuesto agotado sin envío y stop/export/resume sin duplicados. |
| Última validación API/CSV/regresiones/ciclo de vida, incluidos detalles de tokens desconocidos | 33 PASS; 8,46 s. |
| Sintaxis e imports | AST de 167 módulos; imports principales, OpenAI SDK, keyring, pandas, pyarrow y openpyxl correctos. |
| Git diff | `git diff --check` correcto; avisos de normalización LF/CRLF en archivos previos. |
| Secretos | Escaneo de candidatos de Git sin hallazgos de claves OpenAI, tokens GitHub/AWS ni claves privadas PEM conocidas. Sin imprimir coincidencias ni credenciales. |

Los grupos de pruebas se solapan: no sumar sus cifras como casos únicos. No se volvió a ejecutar toda la suite de 12 minutos después de las correcciones; su estado global sigue pendiente. Los JUnit y el guard están en `.tmp/` y no forman parte de los datos publicables.

### uv y copia limpia equivalente

`uv sync --locked --offline` completó una sincronización exacta en `.tmp/exact-sync-env`, entorno independiente sin tocar `.venv`. Para evitar descargar/copiar otra vez PyTorch se reutilizaron archivos de paquetes instalados mediante hardlinks y se verificó que los RECORD no apuntaran fuera del entorno temporal. Resultado: lock válido de 96 paquetes y comprobación de 66 paquetes instalados. No fue una instalación desde red en un computador nuevo ni certifica disponibilidad futura de todos los índices.

Se creó una copia del conjunto técnico propuesto para publicación, con índice Git temporal independiente y sin commit. Sin bases, outputs, credenciales ni pesos, usando el entorno independiente y bloqueo de red, pasaron:

- Menú local y encabezado OpenAI, salir sin ejecutar.
- Menú de modelos, contratos y navegación de proyectos base con cancelación.
- Ayuda CLI e inventario `status` vacío.
- Imports principales y ayuda desde `src/` mediante `../run.py`.
- Las 30 pruebas rápidas documentadas, también sin las fuentes o snapshots privados del workspace original.

Esa copia incluye archivos actuales aún no seguidos en el repositorio original. **Demuestra el conjunto propuesto si se publica; no que el estado Git actual produzca ya un clon funcional.**

Versiones: Python 3.14.0; OpenAI 2.54.0; keyring 25.7.0; pytest 9.1.1; torch 2.11.0+cu128 Windows/Linux. Desarrollo separado en grupo dev; PDF y observabilidad opcionales. Ollama se usa por HTTP estándar y no requiere su SDK Python.

Los identificadores se verificaron únicamente en documentación pública: [GPT-6.1 Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra), [Responses estructuradas](https://developers.openai.com/api/docs/guides/structured-outputs) y [Ollama Qwen](https://ollama.com/library/qwen3.5:4b-q4_K_M). Esto no comprueba permisos de una cuenta, disponibilidad instalada o equivalencia de calidad. Las tarifas US$1/US$5 por millón son referencias configurables del experimento fechadas 2026-11-08, no una consulta de facturación o saldo.

## 6. Instalación y comandos definitivos

Después de publicar el conjunto revisado:

```powershell
winget install --id astral-sh.uv --exact
git clone https://github.com/Sebastianav1011/research-graphrag.git
cd research-graphrag
uv sync --locked
uv run python run.py
```

Reabrir terminal tras instalar uv si no aparece en PATH. En Linux/macOS, instalar uv con el procedimiento oficial enlazado en [instalación](../instalacion.md); esas plataformas no fueron verificadas aquí. No activar venv manualmente. En este equipo se utilizó un bootstrap temporal de uv: no se instaló globalmente ni se cambió PATH.

Desde la raíz, comprobaciones ligeras:

```powershell
uv run python run.py --help
uv run python scripts/check_environment.py --skip-external
uv run python -m pytest tests/test_api_contract_integration.py tests/test_final_audit_regressions.py tests/test_indicator_csv.py -q
```

Desde `src/`, usar `uv run python ../run.py --help`: uv descubre el proyecto padre, mientras Python necesita la ruta real del script. El código resuelve sus recursos desde la raíz del repositorio, no desde una ruta del computador original.

Configurar modelo y clave propia, sin prueba de conexión:

```powershell
uv run python run.py model --provider ollama
uv run python run.py model --provider openai
uv run python run.py contracts
```

La clave se solicita oculta, con reutilización o reemplazo en keyring. Fallback `.env.openai.local` solo con aceptación expresa de sus limitaciones. No introducir claves en argumentos, código o historial. Ollama no necesita clave OpenAI. Los contratos deben crearse después de provisionar las fuentes/catálogos y compartirse solo con autorización; no se creó el definitivo de 30 proyectos.

Los siguientes comandos **sí son para ejecuciones reales futuras**, después de revisar recursos, contrato y permisos:

```powershell
uv run python run.py run --provider ollama --contract data/contratos/CONTRATO.v1.json --run-id local_01
uv run python run.py run --provider openai --budget-usd 15 --contract data/contratos/CONTRATO.v1.json --run-id terra_01
uv run python run.py status --run-id terra_01
uv run python run.py stop --run-id terra_01
uv run python run.py export --run-id terra_01 --partial
uv run python run.py resume --run-id terra_01
```

Conservar revisiones y autorizaciones indicadas por consola. Una API sin presupuesto explícito lo solicita en terminal; recomendado US$15, sin presumir saldo real. Para reproducir adicionales en otra ejecución usar `--selection-run ID_PREVIO`, con el mismo contrato y fuentes, sin copiar respuestas.

Autónomo, preparación y autorización separadas; la primera orden puede construir embeddings y no es un smoke test:

```powershell
uv run python run.py prepare --autonomous --provider openai --budget-usd 15 --contract data/contratos/CONTRATO.v1.json --run-id terra_auto_01
uv run python run.py authorize --autonomous --run-id terra_auto_01 --manifest-sha256 HASH_REVISADO
uv run python run.py start --autonomous --run-id terra_auto_01
uv run python run.py resume --autonomous --run-id terra_auto_01
```

`stop`, `status` y `export` reconocen el run desde otra terminal. Stop es cooperativo: una solicitud en curso puede tardar hasta su timeout y puede quedar incierta. El reintento de una solicitud incierta exige revisión; no se repite automáticamente una llamada pagada con resultado válido persistido.

## 7. Salidas y trazabilidad

En cada run, la exportación informa la ubicación de `resultados/indicadores.csv`, `resultados/indicadores_territorios.csv` y `resultados/performance/`. Conservar íntegra la carpeta `outputs/runs/ID/`, sus bindings, manifiestos y checkpoints. El archivo territorial agrega únicamente `codigo_dane`; debe importarse como texto en herramientas externas.

La API conserva tokens reportados, detalles de razonamiento/caché cuando llegan, costo estimado por proyecto, reservas, configuración y recibos privados. Razonamiento ya está incluido en output_tokens y no se cobra dos veces en la estimación. El tiempo remoto se separa del consumo local; no se asigna CPU/GPU/RAM de servidores OpenAI. Las métricas locales ausentes se conservan como no disponibles.

El contrato permanece inmutable; adicionales y su orden quedan en el manifiesto del run. Se distinguen completos, parciales, bloqueados y pendientes. Cambios de fuentes o catálogo bloquean el contrato; cambios de modelo exigen runs independientes.

## 8. Confirmación de alcance

**No se hicieron llamadas reales a OpenAI ni Ollama, inferencias, embeddings, descargas de pesos ni ejecuciones de proyectos institucionales.** No se creó el contrato definitivo ni se consultó saldo de cuentas. Solo se consultaron páginas públicas de documentación y se ejecutaron pruebas/imports locales, con transportes simulados y guard de red.

No se hizo commit ni push. El repositorio original no se añadió al índice ni se alteraron sus credenciales/configuración de Git global. La aceptación final queda pendiente de preparar el conjunto de publicación, revisar privacidad, distribuir recursos autorizados y resolver/clasificar las regresiones históricas restantes.
