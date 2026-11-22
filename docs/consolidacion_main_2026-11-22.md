# Consolidación de main — 22 de noviembre de 2026

## Alcance e historial

Se conserva el historial mediante integración normal, sin force push, reset,
eliminación de ramas ni descarte de archivos locales. La consolidación no cambia
fórmulas, modelos, criterios de evaluación ni algoritmos del pipeline.

Estado inicial, contrastado con `git fetch origin`:

| Referencia | Commit inicial | Tratamiento |
| --- | --- | --- |
| `main`, `origin/main`, `dev` | `abd7f9a` | Base de integración; `dev` no aporta commits adicionales. |
| `origin/dev` | `d3e78a8` | Ya contenido en la base. |
| `v5-openai-articulos-decision-v2` | `55ad264` | Integra `6c73078`, `efd75bf` y `55ad264`, más los cambios locales revisados. |
| `origin/v5-openai-articulos-decision-v2` | `efd75bf` | Contenido en la rama V5 local. |
| `respaldo-main-pre-claude` | `fee5b9d` | Ancestro conservado; sin commits exclusivos. |
| `wip/layer4-confidence` | `ab24d44` | Ancestro conservado; su worktree permanece intacto. |

Antes de intervenir había modificaciones sin confirmar en `run.py`,
`tests/test_contract_startup.py` y `tests/test_v5_articles_optimization.py`.
Se conservan: selección explícita de proyectos o proyectos y artículos por ID,
resolución de EID/DOI y pruebas asociadas. Se ajustó la secuencia de entrada
simulada de la prueba manual para elegir reconstrucción en su entorno temporal,
que no dispone de Knowledge BASE activo.

El worktree antiguo de confianza contiene archivos sin seguimiento. Su configuración
y sus tres schemas son idénticos a los actuales. Sus funciones tienen equivalentes
en `src/layer4_evaluation/indicators/confidence.py` (13 de 14 cuerpos idénticos),
y sus 51 funciones de prueba son idénticas a las de
`tests/layer5_confidence/test_confidence.py`. La documentación vigente conserva
la histórica y añade su condición de versión anterior. No se copian namespaces
antiguos ni se modifica ese worktree.

## Implementación conservada

- Procesamiento, identidades, Knowledge, embeddings BGE-M3 y GraphRAG.
- Evaluación local/API, artículos, decisión V2 y recuperación por fuente.
- Identificación territorial y referencia pública DIVIPOLA.
- Exportaciones Excel/CSV, almacenamiento, reanudación y resultados históricos.
- Configuraciones, schemas, lock de dependencias, pruebas sintéticas y suites
  experimentales históricas. Los scripts de ejecución real siguen disponibles,
  pero no se ejecutaron como validación de esta consolidación.

El README enlaza la arquitectura vigente y describe la selección actual por ID.
`.env.example` aclara la configuración local de credenciales sin incluir claves.

## Seguridad y archivos locales

Se revisaron `.gitignore`, archivos seguidos, archivos sin seguimiento,
plantillas Excel y patrones de claves privadas, tokens OpenAI/GitHub, claves AWS
y credenciales en URL. La única coincidencia fue una URL ficticia `user:pass`
en una prueba que rechaza endpoints inseguros. Esta comprobación por patrones
no constituye una certificación completa de privacidad documental.

No hay archivos seguidos por Git que coincidan con las exclusiones vigentes.
No fue necesario ampliar `.gitignore`. Permanecen excluidos:

- `.env`, `.env.*` excepto el ejemplo, credenciales, claves y configuración local.
- Datos institucionales, entradas privadas y contratos no autorizados.
- `outputs/`, resultados, archivos de recuperación y auditorías locales privadas.
- `.venv/`, cachés, temporales, logs, pesos de modelos y payloads vectoriales.

Se mantienen las excepciones explícitas existentes para plantillas con encabezados,
fixtures sintéticos y `data/contratos/tesis_comparacion_30.v1.json`, cuya autorización
ya estaba documentada. No se añadieron bases privadas ni resultados locales.
No se eliminaron datos o resultados por estar ignorados. Las evidencias técnicas
de esta revisión permanecen en `.tmp/consolidation-*`, fuera de Git.

## Validación

- `uv lock --check --offline`: correcto, 96 paquetes; no se actualizaron dependencias.
- `scripts/check_environment.py --skip-external`: `READY`, Python 3.14.0.
- Dependencias instaladas contrastadas con `pyproject.toml`: sin incumplimientos.
- Análisis sintáctico de todos los Python versionados: sin errores.
- Imports de procesamiento, Knowledge, GraphRAG, evaluación, territorios,
  proveedores, coordinador y `run`: correctos.
- `run.py --help` y `git diff --check`: correctos.
- Suites V5, artículos, decisión V2 y territorios: **86 pasan**.
- Entorno, auditoría, almacenamiento, contrato API y CSV: **52 pasan**.
- Capas de procesamiento, Knowledge, GraphRAG e intake: **361 pasan, 40 omitidas,
  1 falla**. La falla exige que `data/` solo contenga `layer1_sources` y `templates`,
  ignorando el directorio de contratos que ya existía antes de consolidar.

No se hicieron llamadas facturables ni inferencias reales. Las pruebas reales
opt-in se omitieron. Estas verificaciones no certifican calidad metodológica
ni una ejecución completa con fuentes institucionales privadas.

## Regresiones y límites pendientes

La suite histórica no está completamente verde. La auditoría anterior del
8 de noviembre ya documentaba fallos y errores de preparación; no se presenta
ese resultado antiguo como si fuera el de esta revisión.

Se intentó ejecutar la suite completa (2740 pruebas recogidas). La suite de consola
`test_contract_startup.py` queda en bucle cuando se agotan sus respuestas simuladas.
El primer bloqueo se reprodujo tanto con el `run.py` actual como con el de
`55ad264`, cargado en memoria sin modificar el árbol de trabajo. Una protección
diagnóstica temporal permitió observar `StopIteration`. Esa protección no se
incorpora al repositorio ni se cuenta como prueba aprobada.

Un segundo intento sin `test_contract_startup.py` alcanzó al menos el 74 % antes
de interrumpirse por falta prolongada de progreso visible. Se intentó aislar el
tramo restante con salida detallada; también se interrumpió, sin resultado global,
durante la familia `test_minimal_evaluation.py`, que depende de ejecuciones
históricas privadas. No se atribuye una causa técnica definitiva a esa lentitud.
Los logs parciales no se cuentan como una suite completada. Las verificaciones
focalizadas terminadas suman **499 aprobadas y 40 omitidas**; aparte constan las
fallas de intake y de selección manual descritas aquí. No son el total de fallas
de los intentos amplios.

La prueba manual por ID, con las opciones de documento y Knowledge actuales,
termina pero falla al esperar una llamada al evaluador simulado que no ocurre.
No se debilita esa aserción. Requiere revisar el fixture de ejecución V5; el
flujo completo de esa prueba no se declara validado.

También se reprodujo un fallo en recuperación de cierre V3.3: un manifiesto
histórico exige el fingerprint de `src/layer4/indicators/global_discovery.py`
anterior a la implementación vigente. No se cambiaron hashes ni resultados
sellados para forzar compatibilidad. El código de ese fallo no fue modificado
por la consolidación.

La integración de Git puede completarse conservando la versión más reciente,
pero la aceptación integral del sistema requiere clasificar las regresiones
históricas y validar los recursos privados y ejecuciones reales por separado.
