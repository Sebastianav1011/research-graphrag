# Contrato definitivo: 30 proyectos evaluables

Rutas y publicación actualizadas: [almacenamiento](../ALMACENAMIENTO.md). El contrato de tesis está expresamente autorizado para Git; los demás contratos y todos los outputs siguen privados. Los informes anteriores describen su fecha.

Fecha: 2026-11-09. El usuario confirmó **30 evaluables**: se aplicó un criterio
explícito de elegibilidad antes del muestreo. Esta validación reemplaza el NO GO
de la muestra sin filtro; la [auditoría histórica](auditoria_final_repositorio.md)
conserva el estado y alcance de su fecha. No se repitió la auditoría completa.

| Decisión | Estado | Alcance |
|---|---|---|
| Crear el contrato | **GO — creado** | 30 proyectos con texto sustantivo autorizado, IDs únicos y reproducibles. |
| Iniciar ejecuciones reales | **GO técnico** | Selección, contrato y simulaciones correctos; el equipo debe configurar claves/servicios/hardware y revisar las autorizaciones antes de ejecutarlas. No se validaron modelos reales. |
| Compartir el conjunto preparado en GitHub | **GO** | El usuario autorizó el contrato; runtime y documentación están preparados en el índice. Fuentes y outputs excluidos; commit/push pendientes del usuario. |

## Contrato guardado

- Ruta relativa exacta: `data/contratos/tesis_comparacion_30.v1.json`.
- Nombre `tesis_comparacion_30`, versión **1**, esquema `EVALUATION_CONTRACT_V1`.
- **30 IDs únicos y ordenados**, semilla **42**, método existente `STRATIFIED_PROJECTS_V1`.
- Regla adicional persistida: `AUTHORIZED_SUBSTANTIVE_TEXT_V1`.
- Población original: **2232** proyectos. Población elegible:
  **1863**. Excluidos por falta de texto autorizado: **369**.
- Hash de la población elegible: `5eff01fe27f3477ba57c4579cff468b2642c254859c5fed1fb115229c748a063`.
- Hash semántico del catálogo: `d4e587d079bac67782c994f720130920bf34d27b831c60800376694d815c24f5`.
- Hash contractual canónico (`sha256` dentro del JSON): `7f14fc111b4db0483caa3c5826c4aeb9cfe0febb1e4fb8d7eb38d39e6f5e1177`.
- SHA-256 de los bytes del archivo: `3ff98a8d2e0f901ab1aff0b08f90f60b46d7b4aba002eea1d6b6e318b375ed21`.

El contrato se guardó con `evaluation_contracts.create(..., require_evaluable=True)`,
el gestor existente. No había v1 ni otras versiones de ese nombre. Se abrió en
modo exclusivo; no se sobrescribió ningún contrato. Luego se releyó con `load`
y se verificó con `resolve`. No contiene proveedor, modelo ni presupuesto.

## Selección, elegibilidad y relaciones

Se reutilizan la clasificación y autorización de columnas del adaptador nativo
(`knowledge_fields.analyze_columns`, `select_text_columns` y su política de
`prepare_files`). Un proyecto es elegible si tiene contenido en resumen,
metodología, objetivos, resultados esperados o columnas adicionales ya autorizadas.
Títulos y palabras clave por sí solos no lo hacen elegible. No se autorizan
columnas sensibles nuevas, no se inventa evidencia y no se modifican las fuentes.

Después del filtro se aplica el mismo muestreo estratificado por área,
periodo/convocatoria, estado y completitud narrativa, con asignación proporcional
por mayores restos y desempate SHA-256 con semilla. **No se reemplazaron solamente
ocho IDs de la muestra anterior**: se recalculó toda la selección sobre la población
elegible. El orden de entrada invertido produce los mismos 30 IDs y la muestra no
coincide con los primeros 30 proyectos elegibles de las fuentes.

El contrato conserva hashes de la población original, fuentes y configuración,
además de regla, tamaño y hash de la población elegible. Al cargarlo se reconstruye
esa población y se comprueba que los obligatorios coincidan con el muestreo de la
semilla guardada. Un cambio de fuentes, mapeos, catálogo o elegibilidad bloquea la
carga. Los contratos antiguos sin regla de elegibilidad mantienen su comportamiento.

Se usó `source_scope.plan_scope` para recuperar relaciones en memoria, sin construir
ETL ni GraphRAG institucionales. Se recuperaron **30 registros
de proyectos, 176 registros de investigadores y
6 registros de artículos**. Son registros, no necesariamente
personas o publicaciones únicas. Los 30 tienen integrantes y texto autorizado.
Se revisó además la ausencia de títulos contradictorios bajo el mismo ID seleccionado.

29 proyectos no tienen grupos de artículos
enlazados por autoría corroborada. Eso no impide evaluar sus textos propios. La
autoría no demuestra que una publicación sea resultado de un proyecto: no se crea
esa relación ni se incorporan asociaciones no verificadas. Las cuarentenas del ETL
siguen activas. El flujo con contrato ahora registra también `project_selection`
y pasa por la validación nativa de selección, sin alterar las reglas de identidad.

**Evaluable significa que dispone de entrada textual autorizada para intentar la
evaluación. No garantiza evidencia suficiente, cumplimiento, confianza elevada ni
descubrimiento de indicadores.** Esos resultados los determinará el experimento.

## Fuentes y catálogo verificados

SHA-256 recalculados antes de guardar; rutas relativas, sin datos de las celdas:

| Recurso | SHA-256 |
|---|---|
| `data/layer1_sources/base/descriptores-limpio.csv` | `2f8b067e1420a3c5d3f89656ce458230b15e8bb41dab57992b4fe117e2709194` |
| `data/layer1_sources/base/miembros-doc-limpio.csv` | `9479f00739c90047491f57a6e85435d437fffc199ac8b265ea38145a4787ea1d` |
| `data/layer1_sources/base/produccion-limpio.csv` | `01c23f47cf186766ee9d95fc465f0b34cc0d8292f1aab76e56f6b3be615cce23` |
| `data/layer1_sources/reference/indicadores/catalogo_indicadores_v2.xlsx` | `1aeb1a376c24bca7bdd7acd228da527ef0043f0574541649589badb54e1cf88f` |

La publicación aprobada de perfiles/rúbricas/reglas pasó sus
**9** verificaciones de artefactos y contiene 48 indicadores.
La configuración semántica del flujo normal pasó sus **13**
verificaciones de recursos. No se relajaron fingerprints históricos ni se
modificaron fórmulas de confianza o indicadores.

## Simulaciones y pruebas

- **39 pruebas focalizadas aprobadas, 14,97 s**, con contratos elegibles, compatibilidad
  anterior, insuficiencia de población, cambios de elegibilidad, validación nativa
  de selección, API simulada, presupuesto agotado, stop/export/resume, CSV y CLI.
- Pasadas preparatorias: 35 y 26 pruebas aprobadas; se solapan con las finales y
  no deben sumarse como casos únicos. No se repitió la suite completa histórica.
- El JSON definitivo se cargó mediante el parser y `dispatch` reales para Qwen y
  Terra, sustituyendo exclusivamente el coordinador de ejecución por un registrador
  falso. **Ambos reciben los mismos 30 IDs en el mismo orden**.
- La simulación de Terra con cinco adicionales mantiene los 30 obligatorios al
  principio, genera cinco IDs elegibles distintos y guarda la ampliación en un
  manifiesto simulado separado. El contrato quedó idéntico en bytes.
- Se comprobó también `--selection-run` en una raíz temporal: Qwen puede repetir
  exactamente los obligatorios y adicionales del run Terra sin copiar sus respuestas.
- Cada proveedor conserva directorios, bindings y manifiestos propios. Los recibos
  simulados están únicamente en `.tmp/`, no en los outputs reales.
- Se reutiliza la evidencia previa de performance/checkpoints y se repitieron
  los casos de ciclo API con SDK falso. Persisten tests históricos que necesitan
  snapshots o ZIP privados; no se declara verde toda la suite. La configuración
  actual de catálogo y selección necesaria para esta comparación sí se verificó.

Python **3.14.0** y `uv run --locked --offline` correctos; no se actualizaron
dependencias ni se descargaron pesos. Sockets y backends reales de embeddings
estuvieron bloqueados. Para la creación se permitió únicamente el JSON definitivo
y su carpeta, manteniendo protegidas las fuentes y los outputs originales.

## Instalación, menú y ejecución posterior

```powershell
uv sync --locked
uv run python run.py
```

Los dos equipos necesitan el mismo código, contrato y paquete privado autorizado
de fuentes, catálogo/perfiles/rúbricas/planes, DANE y BGE-M3. OpenAI no requiere
Ollama, pero la recuperación local mantiene sus requisitos CUDA/BGE-M3. Consultar
[instalación](../instalacion.md); solo Windows x64 se verificó en estas tareas.

Menú: **Ejecutar pipeline completo → fuente base → Contratos de evaluación →
Utilizar contrato existente → tesis_comparacion_30.v1.json → N**. Completar los
prompts de run ID y revisar las autorizaciones de construcción/textos que presente.
N conserva exclusivamente los 30; S exige un límite positivo de adicionales.

Comandos definitivos, comprobados **sin ejecutar el pipeline**:

```powershell
uv run python run.py run --provider ollama --contract data/contratos/tesis_comparacion_30.v1.json --run-id qwen_30
uv run python run.py run --provider openai --budget-usd 15 --contract data/contratos/tesis_comparacion_30.v1.json --run-id terra_30
```

Para incluir cinco adicionales elegibles en una ejecución nueva:

```powershell
uv run python run.py run --provider openai --budget-usd 15 --contract data/contratos/tesis_comparacion_30.v1.json --additional-count 5 --run-id terra_30_mas5
uv run python run.py run --provider ollama --selection-run terra_30_mas5 --run-id qwen_30_mas5
```

El alcance de un run existente queda congelado: no se amplía con resume. Si se
decide ampliar después de terminar los primeros 30, usar un run nuevo y conservar
los originales. La ampliación no cambia el contrato ni copia respuestas de otro modelo.

Desde otra terminal:

```powershell
uv run python run.py status --run-id terra_30
uv run python run.py stop --run-id terra_30
uv run python run.py export --run-id terra_30 --partial
uv run python run.py resume --run-id terra_30
```

Los resultados se conservan dentro de `outputs/runs/local/ID/` o `outputs/runs/api/ID/`, con
`resultados/indicadores.csv`, `resultados/indicadores_territorios.csv` y
`resultados/performance/`. DANE debe importarse como texto. Configurar personalmente
la clave con `uv run python run.py model --provider openai`; guardarla no hace
una prueba de pago. Ver [guía experimental](../OPENAI_EXPERIMENTS.md).

Antes de iniciar: preparar servicio/pesos Qwen o clave/acceso Terra, recursos
locales idénticos y hardware. No se comprobaron cuenta, saldo ni inferencia real.
US$15 es una protección preventiva, no garantía de costo máximo facturado.

Para futuros contratos con el mismo criterio, el gestor ofrece
`contract-create --require-evaluable`. No volver a crear la v1: usar la existente;
cualquier cambio de proyectos requiere una versión nueva.

## GitHub y archivos

El JSON contiene solo IDs de proyecto y metadatos/hashes, sin nombres de personas,
documentos personales, narrativas, credenciales, modelos ni rutas absolutas del
computador. **El usuario autorizó expresamente compartir este contrato**.
`.gitignore` permite específicamente ese JSON y conserva privados los otros.
El seguimiento específico se prepara con:

```powershell
git add -- data/contratos/tesis_comparacion_30.v1.json
```

El contrato está preparado en el índice; no se habilitó `data/` completo y no se subió nada.
Se mantienen excluidos bases, credenciales, preferencias locales, cachés, modelos,
resultados y evidencias temporales. El inventario
`docs/status/auditoria_archivos_publicacion.json` identifica el runtime previsto;
`run.py` y sus módulos están incluidos y no omitidos por `.gitignore`.

El conjunto preparado incluye `run.py`, archivos uv, configuración pública,
paquetes actuales, gestor de contratos, almacenamiento y pruebas. Revisar el diff
del índice antes del commit. Los informes antiguos no revisados permanecen locales.
Un clon necesita además los recursos privados por canal autorizado; el contrato
no publica esas fuentes.

Cambios de esta ampliación: `src/evaluation_contracts.py`, `run.py`,
`scripts/pipeline_coordinator.py`, `tests/test_evaluable_contracts.py`, README,
guía OpenAI, este informe, inventario técnico y el contrato privado. No se creó un
segundo muestreador ni un segundo GraphRAG. Los cambios de código pueden invalidar
checkpoints históricos sellados: se preservan y deben reproducirse con su versión
original; preparar runs nuevos para la tesis.

**No se ejecutaron inferencias reales, embeddings, llamadas OpenAI/Ollama ni análisis
GraphRAG de proyectos institucionales. No se consumieron créditos. No hubo commit,
push ni borrado de resultados/checkpoints anteriores. El staging autorizado se completó durante la reorganización posterior.**
