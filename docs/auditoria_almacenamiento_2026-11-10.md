# Auditoría de almacenamiento — 10 de noviembre de 2026

GraphRag se conserva como proyecto canónico. Se retiraron **1,416 GB lógicos y 38.512 archivos**, todos recuperables en la Papelera. **Espacio de contenido liberado físicamente: 0 bytes**; no se vació la Papelera. El trabajo académico, el historial Git y el entorno activo se conservan.

## Medición

| Alcance | Antes | Después | Archivos antes → después | Carpetas antes → después |
|---|---:|---:|---:|---:|
| Docs Tesis | 25,426 GB | 24,010 GB | 362.946 → 324.436 | 49.875 → 45.932 |
| GraphRag | 23,394 GB | 21,979 GB | 352.217 → 313.707 | 48.032 → 44.089 |

GB decimal; tamaños lógicos, que cuentan cada hardlink. Carpetas descendientes, sin contar la propia raíz de cada alcance. Se combinaron dos inventarios de lectura con distintos permisos para cubrir carpetas inicialmente denegadas. No quedaron errores de lectura en la unión. Se excluyeron **1.281 puntos de reanálisis** sin seguir sus destinos; no se afirma medir esos destinos ni almacenamiento externo. El cuadro recoge el cierre del inventario, incluidos informe y manifiesto. La preparación posterior añade unos pocos objetos internos de Git; su recuento actualizado está en el manifiesto final.

Antes, las carpetas principales de GraphRag ocupaban:

| Carpeta | Tamaño | Archivos | Carpetas, incluida la cabecera |
|---|---:|---:|---:|
| `outputs` | 9,490 GB | 222.345 | 25.188 |
| `.tmp` | 8,813 GB | 94.806 | 19.393 |
| `.venv` | 4,914 GB | 32.372 | 2.991 |
| `docs` | 0,067 GB | 171 | 12 |
| `data` | 0,063 GB | 19 | 12 |
| `archives` | 0,022 GB | 877 | 103 |
| `(root files)` | 0,013 GB | 13 | 0 |
| `tests` | 0,005 GB | 212 | 26 |
| `src` | 0,004 GB | 271 | 19 |
| `.git` | 0,003 GB | 972 | 271 |
| `scripts` | 0,001 GB | 74 | 3 |
| `config` | 0,000 GB | 26 | 1 |
| `schemas` | 0,000 GB | 46 | 8 |
| `__pycache__` | 0,000 GB | 1 | 1 |
| `.pytest_cache` | 0,000 GB | 5 | 3 |
| `requirements` | 0,000 GB | 7 | 1 |

El manifiesto local `auditoria_almacenamiento_2026-11-10.json` contiene los 30 directorios mayores, los 30 archivos mayores, los 30 directorios con más archivos, extensiones y estadísticas de la raíz. No sumar tamaños de directorios anidados. Las mayores extensiones eran DLL (9,06 GB), JSON (3,45 GB), NPY (3,06 GB), BIN (2,27 GB) y Parquet (1,82 GB). `outputs/runs` tenía 127.641 archivos y `outputs/layer3/cache`, 87.280: sus cachés de embeddings pueden evitar reconstrucciones y se conservaron.

## Copias y conservación académica

- **`GraphRag-confidence` — D/E, conservar.** Worktree registrado en `wip/layer4-confidence`, base `ab24d44`, con cinco grupos de archivos nuevos sin registrar. Comparación técnica por ruta: 45 archivos idénticos por SHA-256, 35 diferentes y 54 rutas ausentes en el mismo lugar del canónico. Tras buscar también contenido con otros nombres en código, documentación y archivos históricos del canónico, 49 candidatos siguen sin equivalencia comprobada. No se retiró ni fusionó. Integración futura: revisar específicamente `src/layer4_confidence`, sus tests y contrato contra la implementación actual, trasladando cambios mediante una rama revisada, sin sobrescribir namespaces o configuraciones.
- **`Pruebas/Prueba GraphRag` — D/E, conservar.** Implementación previa de Capas 1–2 en un repositorio independiente, con modificaciones, numerosas altas sin registrar y bajas históricas anteriores a esta sesión. Comparación técnica por ruta: 8 idénticos por SHA-256, 15 diferentes y 50 rutas ausentes; 49 candidatos siguen sin equivalencia comprobada tras buscar contenido en otras rutas. Se preservaron datos, scripts, historial y entorno. Integrar únicamente diferencias revisadas contra los paquetes actuales, conservando su versión experimental y sus manifests.
- **Copias internas — D/E, conservar.** `.tmp/publication-copy/.git` es un índice independiente con 380 archivos preparados y sin commit; no tiene HEAD. Los `index-clone-*`, backups de código, `archives/` y workspaces de migración son evidencia o contienen variantes. No se retiró ningún repositorio ni historial. En dos workspaces, los 20 archivos de `data/graphrag` son idénticos por SHA-256 a `outputs/layer3/publication` (951.896.453 bytes por copia); se conservaron sus rutas selladas y contexto de validación.
- **Prueba de 10 proyectos — D.** Sus carpetas históricas ya estaban ausentes del árbol de `Pruebas` al empezar. Se verificó la lectura de los **58 blobs** de `01_prueba_controlada_10_proyectos`, `02_aproximacion_plantilla_final` y `shared` en el commit `c2a97f2` (6.274.663 bytes): código, entradas, embeddings, grafo, resultados, README y plantilla histórica. Sus rutas, objetos y SHA-256 quedan en el manifiesto. Para recuperarlos sin sobrescribir, usar `git archive` de ese commit hacia un archivo externo a los árboles activos. No se reconstruyó el experimento ni se confunde la fixture vacía vigente con esta prueba. Su ejecución histórica requiere restauración aislada y dependencias por revisar.
- **Prueba de 60 proyectos — D.** Se conserva `Pruebas/Prueba LightRAG`: CSV con 60 filas, script, catálogo, README y resultados de 43 filas. El README advierte que no se completaron los 60 proyectos con todos los indicadores; no se certifica una ejecución completa. También se conservan las pruebas LLM y sus resultados (720 filas).
- **Fuentes, catálogos, prompts, confianza y plantilla — A/D.** Se comprobaron SHA-256 antes/después de 513 archivos de código/configuración/schemas/tests/datos originales y del worktree: ningún cambio. `DatosLimpios`, `2026`, documentos y handoffs permanecen intactos. La plantilla vigente `data/templates/plantilla_resultado_tesis.xlsx` contiene solo encabezados en dos hojas, sin filas de datos; se preserva junto a las anteriores y se habilita expresamente para Git.

## Retiradas y recuperación

| Ruta relativa a GraphRag | Clase | Acción y motivo |
|---|---|---|
| `.tmp/venv-install-validation/` | B | Papelera: entorno CPU de validación, 38.378 archivos, 1.151.782.220 bytes; 49 paquetes, 25.718 hashes de RECORD verificados, sin archivos propios ni paquetes modificados. Dependencias y evidencia de instalación permanecen. |
| `outputs/layer3/models/bge-m3/.../.cache/huggingface/download/*.incomplete` | B | Papelera: única descarga parcial de 262.144.000 bytes. Los pesos completos coinciden con el SHA-256 aprobado de `config/layer3.yaml`. Ruta literal y destino de recuperación en el manifiesto. |
| Diez `__pycache__/` en raíz y `src/` | B | Papelera: 133 archivos y 2.408.461 bytes. Cada archivo es bytecode Python válido y tiene su fuente existente. Ninguno estaba seguido por Git. Rutas exactas y listado completo en el manifiesto. |
| `.tmp/exact-sync-env/` | B/E | **Retirada revertida.** Compartía archivos con `.venv` mediante hardlinks. La Papelera cambió permisos compartidos y la validación aislada perdió acceso a dependencias; las importaciones del usuario con acceso ampliado seguían funcionando. Se restauró el directorio desde la Papelera y se confirmó nuevamente el acceso normal. Se conserva; sus 4.818.378.143 bytes lógicos no se cuentan como ahorro. |

El manifiesto se escribió antes de las operaciones, registra cada raíz retirada, tamaño, motivo, digest del inventario, destino nativo en Papelera y la reversión. Incluye la lista completa de archivos/carpetas retirados comprimida dentro del mismo JSON, con esquema y checksum; no se crearon miles de documentos. Las carpetas recicladas conservan sus RECORD. Para recuperar, usar **Restaurar** en la Papelera; si hubiera una colisión, conservar ambas versiones y detener la restauración automática. No borrar el entorno activo.

No hubo eliminaciones permanentes ni retirada de directorios vacíos por mero nombre: varios forman parte de contratos o fixtures. Antes de cualquier eventual vaciado, revisar el manifiesto. Los deltas de espacio libre del volumen incluyen actividad ajena y metadatos; no equivalen a espacio atribuible a esta tarea. El entorno CPU se puede reconstruir aisladamente con las versiones registradas; su torch CPU histórico no sustituye al entorno CUDA oficial, reproducible mediante `pyproject.toml` y `uv.lock`.

## Archivos pesados conservados

Modelo BGE-M3 de 2.271.145.830 bytes (SHA-256 `b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38`), `.venv` CUDA de 4,91 GB, índices/vectores de hasta 371,6 MB, embeddings de 185,8 MB, publicaciones Parquet, trazabilidad de hasta 271,2 MB, SQLite con sus WAL/SHM y todos los resultados de `runs`/`historico` permanecen. A/D para datos/resultados y B para dependencias reproducibles; el costo de regeneración, la reanudación y los manifests justifican conservarlos. `.tmp` contiene evidencia y scripts útiles: no es una carpeta descartable en bloque. `layer4.zip` (12,46 MB, 5.279 entradas) se conserva como archivo local privado, pendiente de comparar íntegramente antes de cualquier retirada.

## Git y reproducción

Se conservó el repositorio existente, rama `main`, HEAD `fee5b9d`, remoto `research-graphrag`. Había 448 archivos seguidos y el índice estaba vacío de cambios preparados. `.git` ocupaba unos 2,9 MB: no es el problema de almacenamiento. `fsck --connectivity-only` no detectó objetos faltantes; informó blobs sin referencias, que se conservaron. Sin inicialización, reescritura, limpieza del historial, commit o push.

Se prepara selectivamente `.gitignore`, `docs/README.md`, este informe y la plantilla vacía vigente. El manifiesto local queda ignorado por contener ubicaciones de Papelera y hashes/rutas privadas. También se excluye específicamente `/layer4.zip`; se mantienen exclusiones existentes de datos, outputs, entornos, credenciales y configuración local. La excepción para la nueva plantilla evita ocultar un recurso esencial; ninguna exclusión retira contenido ya seguido del historial.

Los **12 archivos modificados y nueve archivos nuevos de código/tests/schema/exportadores** previos a esta auditoría se preservan fuera de este staging, para revisar su conjunto funcional y el fallo de regresión antes de publicarlos. No se afirma que un clon contenga esos cambios todavía. El exportador auxiliar `.mjs` depende de Artifact Tool en el runtime local de Codex y no dispone de instalación Node portátil declarada; queda pendiente. No se considera un script sin referencias textuales como prueba de inutilidad: `export_verified_partial.py` es un entrypoint manual y se conserva.

Flujo documentado del equipo: clonar, `uv sync --locked`, abrir `uv run python run.py --help` y ejecutar pruebas sintéticas. El lock resolvió 96 paquetes en modo offline; el acceso directo global de uv falló en esta sesión y se usó el ejecutable conservado de `uv-bootstrap`. Un clon no contiene fuentes institucionales, catálogo operativo, pesos, perfiles o planes privados: deben distribuirse por canal autorizado. Las rutas personales se mantienen solo donde pertenecen a la configuración local/histórica; no se modificaron checkpoints sellados. No se detectaron rutas absolutas personales en los 173 módulos Python analizados. Pesos, embeddings y datasets privados corresponden a almacenamiento externo con manifests y hashes; no se migraron a Git LFS ni se subieron.

## Validación y pendientes

Sintaxis de 173 módulos correcta; 513 hashes protegidos sin cambios; cero archivos originales ausentes fuera de las retiradas previstas; dependencias instaladas y ayuda CLI desde otro directorio correctas. Red, importación de modelos e inferencias bloqueadas mediante guard temporal; sin regenerar datos ni llamar APIs. Escaneo de candidatos publicables sin claves detectadas, con el límite de que no certifica toda información institucional ni cada commit del historial. `git diff --check` correcto.

La misma selección ligera, antes y después de la restauración, dio **28 PASS y 1 FAIL**: `tests/test_indicator_csv.py::test_autonomous_export_integration`, cuyo mock no acepta `positive_only`. No se cambió el test ni se ejecutó el pipeline completo. La suite histórica completa conserva además los pendientes descritos en `docs/status/auditoria_final_repositorio.md`; no se declara verde.

Pendientes manuales: revisar e integrar trabajo único de los worktrees/experimentos; respaldar externamente `Pruebas/.git`, único custodio local de la prueba histórica de 10; restaurar esa prueba aisladamente si se desea ejecutarla; revisar el mock y el conjunto actual de código antes del commit; declarar las dependencias del exportador Node si el equipo lo requiere; decidir retención de snapshots, cachés de embeddings y runs con sus cierres/estados. Cualquier limpieza de ejecuciones deberá respetar `docs/ALMACENAMIENTO.md` y conservar checkpoints inciertos, resultados y SQLite asociados. No se hicieron descargas, reconstrucciones costosas, migraciones LFS ni publicaciones.
