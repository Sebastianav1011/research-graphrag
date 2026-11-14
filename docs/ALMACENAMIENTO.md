# Runs, histórico y limpieza

El almacenamiento usa el coordinador y los exportadores existentes. No cambia
indicadores, confianza, recuperación ni adaptadores de modelos.

```text
outputs/runs/local/<id>/       Ollama: activo, reciente o recuperable
outputs/runs/api/<id>/         OpenAI API: activo, reciente o recuperable
outputs/runs/anteriores/<id>/  Proveedor heredado no identificable
outputs/historico/local/<id>/  Resultados permanentes de Ollama
outputs/historico/api/<id>/    Resultados permanentes de OpenAI
outputs/historico/anteriores/  Resultados sin proveedor identificable
```

Se crean carpetas cuando contienen información, no buckets vacíos. Cada run nuevo
organiza execution/progress/stop/lock en `estado/`, run/raw/prepared/binding en
`manifiestos/`, resultados del grafo en `grafo/`, mensajes de descubrimiento en
`logs/` y las salidas en `resultados/`. Se conservan `preprocess/`, `workspace/` y
`autonomous/` con los checkpoints técnicos que requieren sus implementaciones.
El ledger API permanece con sus archivos SQLite asociados; no se separan WAL/SHM.

Las rutas se resuelven en `run_paths.py`. Los lectores aceptan locadores anteriores
mediante aliases registrados en `outputs/runs/.relocations.json`. La migración
conserva bytes y hashes: no reescribe manifiestos sellados. Un ID presente en dos
proveedores exige `--provider`; no se elige uno por preferencia arbitraria.

## Histórico

Cada exportación copia los CSV, Excel existente, performance, evidencias aceptadas
y manifiestos de trazabilidad a `outputs/historico/<proveedor>/<id>/`. Incluye
`metadata.json` con proveedor/modelo, estado real, contrato, proyectos, conteos,
fechas disponibles, consumo disponible y hashes de cada archivo. Los valores que
no están disponibles quedan desconocidos; no se presume que una selección completa
equivale a evaluación completa.

Los snapshots son inmutables. Si cambia la exportación, se conserva como
`revisiones/<hash>/` bajo el histórico del mismo run. `latest.json` indica la
revisión más reciente y la consola devuelve su ruta. El primer snapshot puede ser
parcial: su metadata conserva ese estado aun cuando otra revisión posterior termine.
No se sobrescribe la primera exportación ni se caduca el histórico.

El histórico no sustituye los checkpoints para reanudar. Los runs incompletos,
parciales o con solicitudes inciertas permanecen en `runs`. Si el archivo falla,
la exportación indica `RETAINED_UNARCHIVED`: conservar el run y repetir `export`;
esa ejecución no podrá limpiarse automáticamente.

## Retención de 72 horas

```powershell
uv run python run.py cleanup --dry-run
uv run python run.py cleanup --apply
```

El dry-run muestra run, proveedor, tamaño en bytes, decisión y motivos. Apply
vuelve a verificar y pide escribir `ELIMINAR` antes de borrar candidatos.

Solo es candidato un run cerrado por el runtime actual, completo, con más de
72 horas según `estado/closed.json`, sin proceso/lock activo, trabajos pendientes,
llamadas inciertas, archivos pendientes, links o junctions, y con snapshot íntegro
que coincida con todos sus resultados exportables actuales. El recibo se genera
después de exportar resultados completos, no al terminar solo ETL o al aparecer
un mensaje de progreso “COMPLETE”. Una fecha de carpeta o nombre de run no basta.

Los formatos anteriores sin prueba de cierre o edad fiable se conservan. Se
revisan identidad PID/creación, locks y bases SQLite; si no pueden comprobarse,
se retiene el run con el motivo. La limpieza no accede a fuentes, contratos o
histórico, ni elimina checkpoints únicos de trabajos recuperables.

Resumen y decisiones quedan en `outputs/runs/.storage-events/`, con bytes
recuperados y registro previo/posterior a cada borrado. La cifra cuenta bytes de
archivos eliminados, no garantiza bloques físicos liberados cuando hay hardlinks
o compresión del sistema de archivos.

Para habilitar limpieza segura al abrir el menú, crear **localmente**
`config/storage.local.json` con `{"automatic_cleanup": true}`. Está excluido de Git.
Por defecto está deshabilitada. Usa exactamente la misma verificación; no elimina
por mera antigüedad. El menú no ejecuta inferencias al arrancar.

## Migración y recuperación

```powershell
uv run python run.py migrate-runs
uv run python run.py restore-run --run-id ID --provider ollama
```

La primera orden clasifica por manifiestos/bindings/configuración, comprueba
inactividad y mueve dentro de `outputs/runs` sin sobrescribir. En Windows comprueba
que SQLite no tenga handles de otros procesos; no descarta sus WAL. En sistemas
donde un WAL no puede verificarse se conserva el run. Los journals permiten repetir
la orden si se interrumpe. Archiva los resultados existentes sin recalcularlos.
Un proveedor conocido pero incompatible o metadatos contradictorios se retienen
para revisión; no se etiquetan arbitrariamente como anteriores.

Restore revierte una migración **intacta**, sin cambiar datos ni borrar su histórico,
para volver a usar la versión original de código. Si el run cambió o hay colisiones,
se rechaza y se preservan sus archivos. Las rutas nuevas no anulan las verificaciones
de código de checkpoints antiguos. `status` presenta un diagnóstico conservador si
el formato o código no permiten verificarlo; no autoriza inferencia ni declara una
integridad que no comprobó. Los runs nuevos requieren su versión congelada al reanudar.

## Ejecutar y recuperar

```powershell
uv run python run.py run --provider ollama --contract data/contratos/tesis_comparacion_30.v1.json --run-id qwen_30
uv run python run.py run --provider openai --budget-usd 15 --contract data/contratos/tesis_comparacion_30.v1.json --run-id terra_30
uv run python run.py status --run-id terra_30 --provider openai
uv run python run.py stop --run-id terra_30 --provider openai
uv run python run.py export --run-id terra_30 --provider openai --partial
uv run python run.py resume --run-id terra_30 --provider openai
```

Stop es cooperativo: impide nuevos envíos y conserva los resultados en curso o
inciertos. Ctrl+C intenta la misma exportación segura. Export no inicia inferencias.
Las salidas son `resultados/indicadores.csv`, `indicadores_territorios.csv` (DANE
como texto) y `performance/` dentro del run y sus snapshots históricos.

## Toda la base

Elegir “Procesar todos los proyectos” en el submenú de proyectos muestra modelo,
cantidad total, elegibles, bloqueados, motivo, rutas y advertencia de tiempo/costo.
Se exige confirmación. Para CLI no interactiva, el equivalente explícito es:

```powershell
uv run python run.py run --provider ollama --all --confirm-all
uv run python run.py run --provider openai --budget-usd 15 --all --confirm-all
```

Estas órdenes **sí iniciarían trabajo**: no son pruebas de instalación. Conservan
además las autorizaciones de construcción y textos. Sin confirmación devuelve
revisión pendiente antes de crear ETL/GraphRAG. Los no evaluables quedan bloqueados
con motivo, sin cumplimiento ni confianza inventados; la cobertura queda parcial.
Se mantienen checkpoints, presupuesto, exportación parcial, archivo y reanudación.
Los resultados válidos persistidos no se repiten al reanudar el mismo alcance.

`outputs/` completo es privado y está excluido de Git. Se comparte exclusivamente
el código, configuración pública, documentación y el contrato expresamente autorizado;
fuentes, catálogo operativo y pesos se obtienen por canal privado.

## Retiro explícito de históricos y caché de documentos

La regla de 72 horas anterior sigue siendo la del runtime. Para cerrar
deliberadamente ensayos históricos reemplazados, usar el gestor administrativo
separado: **simula por defecto**, preserva evidencia antes de reciclar y no cambia
los sellos ni declara que una evaluación parcial haya terminado. No se importa
desde el pipeline, para conservar sus fingerprints y mecanismo de reanudación.

```powershell
uv run python scripts/manage_run_retention.py
uv run python scripts/manage_run_retention.py --policy config/retention.local.json
```

Copiar `config/retention.example.json` a una política local para futuros ensayos.
`keep_recent` protege los más recientes por timestamp explícito; `pinned` acepta
`local/ID` o `api/ID`; `keep_per_family` configura representantes por familia
etiquetada y perfil (`academic`/`temporary`). Las referencias oficiales de Layers 1–3,
los orígenes reutilizados por runs retenidos, procesos/locks activos, SQLite abierto,
hardlinks y solicitudes API inciertas se protegen. Los límites proponen retención;
no autorizan retirar contenido solo por edad o cantidad. Un run sin revisión se
conserva. Los perfiles son etiquetas explícitas, no se deducen de nombres.

Para autorizar el retiro de un ensayo ya revisado, su entrada en `reviewed` debe
identificar `family`, `profile`, `reason` y `closed_for_retention: true`. Esto
significa **no se pretende reanudar**, no significa evaluación completa. La política
local de la limpieza del 11 de noviembre registra sus decisiones individuales;
no se debe reutilizar a ciegas para runs nuevos.

```powershell
uv run python scripts/manage_run_retention.py --policy config/retention.local.json --apply --archive outputs/historico/compactados/NUEVO.zip --journal outputs/runs/.storage-events/NUEVO.json
```

Apply toma el lock del coordinador, vuelve a comprobar actividad/inventario,
crea un ZIP sin sobrescribir, deduplica contenido por SHA-256, verifica todos los
objetos y sus rutas y registra un journal durable antes de reciclar. Conserva
configuraciones, respuestas, evaluaciones, errores, métricas, manifiestos y toda
información única. No hay fallback de eliminación permanente. Modelos, publicaciones,
fuentes y archivos fuera de `runs` no forman parte de este comando.

La limpieza específica del 11 de noviembre añade omisiones revisadas por hash:
cachés de documentos cuyos vectores ya están publicados e índices SQLite de búsqueda
reconstruibles desde las tablas congeladas. No omite queues, ledgers ni sus WAL/SHM,
respuestas o query caches. El ZIP y su índice conservan los manifiestos históricos
originales **como evidencia**, con estado `HISTORICAL_NON_RESUMABLE` y un registro de
omisiones; no afirman que esas rutas sigan disponibles para ejecución. Las 13
referencias retenidas mantienen íntegros sus archivos y dependencias.

```powershell
uv run python scripts/manage_run_retention.py --verify --archive outputs/historico/compactados/evidencias_runs_2026-11-11.zip
uv run python scripts/manage_run_retention.py --archive outputs/historico/compactados/evidencias_runs_2026-11-11.zip --extract-run local/run_20261108_154514_059252 --destination archives/evidencias100
```

La extracción exige un destino nuevo, fuera de runs. Sirve para inspección y análisis
histórico, no autoriza reanudar. Para recuperar exactamente un workspace retirado,
restaurar **toda su carpeta desde la Papelera** a la ruta indicada en el manifiesto
de limpieza, sin sobrescribir una carpeta existente. Restaurar también sus orígenes
reutilizados indicados en `reuse.json` cuando corresponda; no reescribir sus sellos.
No vaciar la Papelera sin
verificar primero que ya no se necesitan esas reanudaciones.

La caché opcional global de documentos tiene límites configurables de bytes y número
de archivos. Puede revisarse periódicamente o después de un experimento cerrado:

```powershell
uv run python scripts/manage_run_retention.py --prune-document-cache
uv run python scripts/manage_run_retention.py --prune-document-cache --apply --journal outputs/runs/.storage-events/CACHE-NUEVO.json
```

Por defecto solo simula. El retiro requiere verificar hashes de pares JSON/NPY,
payload numérico, dimensiones y cobertura en bundles publicados íntegros. Conserva
todo el grupo si hay contenido desconocido, un vector único, un proceso activo o
una publicación en curso. No considera `query_cache`: su falta puede impedir evaluar.
Evita volver a materializar cachés opcionales si no se va a construir otra publicación.
Para datasets/modelos, usar los mecanismos de reutilización verificada del pipeline;
no crear hardlinks o mover pesos manualmente: sus rutas y hashes forman parte de los sellos.
