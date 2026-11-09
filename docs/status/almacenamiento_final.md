# Cierre de almacenamiento y publicación

Fecha: 2026-11-09. Reorganización focalizada: no se repitió la auditoría completa
ni se cambió GraphRAG, sus embeddings, indicadores o fórmula de confianza.

## Resultado operativo

| Operación | Resultado |
|---|---|
| Runs inspeccionados y migrados | **51** |
| Clasificados local/Ollama | **38** |
| Clasificados API/OpenAI | **0**; se creará el bucket al usarlo |
| Proveedor no identificable, anteriores | **13** |
| Entradas históricas conservadas y verificadas | **24**, locales |
| Runs eliminados | **0** |
| Espacio recuperado | **0 bytes**; no se descartó trabajo recuperable |
| Runs conservados en runs | **51** |
| Candidatos seguros del dry-run posterior | **0** |

Los cuatro runs de Ollama identificados en manifiestos heredados no se enviaron
a anteriores. Cada movimiento se hizo dentro del mismo almacenamiento, con journal
previo, inventario de archivos/tamaños y verificación de bytes de metadata. No se
sobrescribieron archivos. Se preservaron IDs, checkpoints y WAL/SHM asociados.
Los aliases mantienen los locadores antiguos sin reescribir manifiestos sellados.

Los journals y el detalle por ID quedan **privados** en
`outputs/runs/.storage-events/`, y los aliases en `.relocations.json`.
Los resultados históricos contienen archivos existentes, evidencias aceptadas,
performance y trazabilidad; no se ejecutaron evaluadores para generarlos.

## Por qué se retienen ejecuciones antiguas

Ningún run heredado tiene el recibo de cierre definitivo verificable que exige
la nueva política. Muchos contienen trabajo pendiente o reanudable. Un progreso
“COMPLETE”, una carpeta vieja o un worker “FINISHED” no prueban por sí solos que
sea seguro eliminar checkpoints.

Motivos observados por el dry-run (se conservan los detalles privados):

- `AGE_UNVERIFIABLE`: 49 runs (los motivos se solapan).
- `NOT_DEFINITIVELY_CLOSED`: 49 runs (los motivos se solapan).
- `NO_VERIFIED_ARCHIVE`: 49 runs (los motivos se solapan).
- `PENDING_STEPS`: 3 runs (los motivos se solapan).
- `PROVIDER_UNKNOWN`: 13 runs (los motivos se solapan).
- `RECOVERABLE_OR_UNCERTAIN_JOBS`: 22 runs (los motivos se solapan).
- `UNRESOLVED_DISPATCH`: 1 runs (los motivos se solapan).
- `UNVERIFIABLE_ValueError`: 2 runs (los motivos se solapan).

Las bases con WAL pendiente o estado no verificable se conservaron íntegramente.
Para moverlas en Windows se comprobó que no hubiera handles SQLite activos; no
se abrió su contenido para descartar o recomputar trabajo. No se atribuye una
edad por el nombre de carpeta o mtime. El histórico no está sujeto a retención.

## Estructura y comportamiento

`outputs/runs/local|api|anteriores/ID/` usa `estado/`, `manifiestos/`, `grafo/`,
`logs/`, `preprocess/`, `workspace/` y `resultados/`, conservando `autonomous/`
y archivos técnicos requeridos. Los buckets vacíos no se crean por decoración.
El ledger mantiene juntos sus archivos SQLite y sidecars.

`run_paths.py` centraliza el almacenamiento. La separación de archivos raíz se
aplica también a sus lectores/escritores y locks. Los flujos normal/autónomo y
ambos proveedores usan la misma resolución. Si se repite un ID entre proveedores,
se exige `--provider`; no se elige arbitrariamente.

Cada exportación escribe su snapshot bajo `outputs/historico/<grupo>/ID/` y una
metadata con hashes, proyectos/contrato, estado, conteos, fechas y consumo cuando
estén disponibles. Nuevas exportaciones van a revisiones inmutables; `latest.json`
señala la más reciente. Un parcial nunca se renombra como completo. Los snapshots
se verifican antes de marcar cerrado el run y antes de permitir cualquier borrado.

La limpieza exige más de 72 horas desde un cierre completo verificable, inactividad,
ausencia de trabajos o llamadas inciertas, y archivo íntegro vigente. No sigue
symlinks/junctions. Apply pide `ELIMINAR`; la política automática requiere opt-in
local y usa las mismas verificaciones. El resumen deja registro previo/posterior.
Solo se elimina dentro de runs; no se borran fuentes, contratos o histórico.

## Pruebas y compatibilidad

**67 pruebas focalizadas aprobadas en 21,83 s** con datos sintéticos y SDK falso:
rutas por proveedor y colisiones, migración/reinicio tras interrupción, reversión
de una migración intacta, bytes preservados, snapshot parcial inmutable, cierre,
retención/confirmación, protección de actividad/incertidumbre/archivo corrupto,
opt-in automático, reanudación de un checkpoint autorizado después de moverlo,
API con rutas nuevas, CSV/DANE, contratos y confirmación de toda la base.

Las pasadas intermedias se solapan con ese grupo; no sumar sus cifras. La prueba
del checkpoint migrado conservó los sellos y reanudó sin repetir sus dos llamadas
falsas. El test API usa el bucket api y comprueba stop/export/resume y presupuesto
agotado sin envíos. No se repitió la suite histórica, que requiere snapshots/ZIP
privados y conserva errores conocidos ajenos a estos cambios.

Una migración de rutas **no permite cambiar la versión de código autorizada**.
Los runs antiguos con fingerprints de otro código se conservan y `status` ofrece
diagnóstico explícitamente no verificado para inferencia. Para reproducirlos,
restaurar una migración intacta con `restore-run` y usar su código original. No se
relajaron verificaciones ni se actualizaron hashes para autorizar llamadas nuevas.

Se conserva el contrato de tesis byte por byte:

`3ff98a8d2e0f901ab1aff0b08f90f60b46d7b4aba002eea1d6b6e318b375ed21`

## Toda la base

**GO técnico**, después de que el usuario prepare recursos y autorice el trabajo.
Se muestran total, elegibles y bloqueados con motivo, modelo, rutas y advertencia
de tiempo/costo. La confirmación es obligatoria; CLI no interactiva requiere
`--confirm-all`. La prueba rechazó la confirmación sin crear un run y confirmó
solo un ETL sintético al aceptar. No se procesó la base real.

Se mantienen exclusión de evidencia no autorizada, estados parciales, checkpoints,
stop/Ctrl+C, exportación, archivo, reanudación sin repetir resultados válidos,
performance y presupuesto API. Las fuentes previamente comprobadas contienen
2.232 proyectos, de los que 1.863 disponen de texto autorizado; el resumen de una
ejecución recalcula esas cifras y no garantiza suficiencia semántica por indicador.

Pendiente externo antes de ejecutar: fuentes/catálogos operativos idénticos,
pesos BGE-M3 y CUDA, servicio/modelo Qwen o clave/acceso Terra, presupuesto y
revisión de las autorizaciones. No se validaron mediante una llamada real.

## Publicación

**GO para publicar el conjunto preparado**, después de revisar el diff y hacer
personalmente commit/push. El código y el contrato ya están en el índice de Git.
La copia exacta exportada de ese índice, sin fuentes privadas, pasó `uv sync
--locked --offline`, arranque de ambos encabezados/modelos, menús, ayuda, estado,
cleanup dry-run y **48 pruebas ligeras**. El contrato clonado conservó sus bytes.
Se reutilizó un entorno independiente ya instalado, sin una descarga nueva de
PyTorch. La protección final de reapertura se comprobó además con **20 pruebas**
de almacenamiento/integración; estos grupos se solapan con los anteriores.

El contrato `data/contratos/tesis_comparacion_30.v1.json` está expresamente autorizado
por el usuario. `.gitignore` permite solo ese JSON, y `.gitattributes` conserva sus
bytes entre equipos. El resto de data, outputs completo, claves, preferencias,
entornos, cachés, pesos y logs se mantienen excluidos.

Se prepara un conjunto explícito: run.py, paquetes actuales y compatibilidad,
adaptadores, gestor de contratos, run_paths/run_storage, schemas, configuración
pública, scripts, tests/fixtures sintéticos, uv/lock/Python, plantillas vacías,
documentación vigente y contrato. Los archivos obsoletos o informes no revisados
se retiran **solo del índice** cuando procede; no se borran del disco. No se hace
commit, push ni reescritura del historial.

El escáner del conjunto preparado no detectó claves conocidas. Se revisaron además
**363 blobs históricos** para patrones de credenciales y
rutas de payloads privados: sin hallazgos. Esto no es una certificación semántica
de cada texto histórico. Los archivos institucionales operativos siguen fuera de
Git y deben obtenerse por canal autorizado; el contrato no los distribuye.

La comprobación del conjunto exportado del índice y su arranque se registra
en el inventario de publicación. Solo Windows x64 se valida realmente; el entorno
uv reutilizado evita descargar de nuevo PyTorch. Ninguna prueba certifica Linux,
macOS ni inferencia real. El remoto solo tendrá estos archivos después del commit
y push que decida hacer el usuario.

## Comandos

```powershell
uv sync --locked
uv run python run.py
uv run python run.py cleanup --dry-run
uv run python run.py cleanup --apply
uv run python run.py status --run-id ID --provider ollama
uv run python run.py stop --run-id ID --provider ollama
uv run python run.py export --run-id ID --provider ollama --partial
uv run python run.py resume --run-id ID --provider ollama
```

Detalles: [almacenamiento](../ALMACENAMIENTO.md), [instalación](../instalacion.md)
y [API/contratos](../OPENAI_EXPERIMENTS.md). El inicio de toda la base o de un
contrato es una decisión posterior del usuario, no una prueba de instalación.

**No hubo inferencias Qwen/OpenAI, llamadas API, embeddings ni análisis GraphRAG
institucional. No se consumieron créditos ni se alteraron indicadores, confianza,
fuentes o contrato. No se borró ningún resultado/checkpoint original.**
