# Salida final de indicadores

## Contrato vigente: THESIS_ALL_INDICATORS_V1

Desde la corrección del 2026-11-13, el contrato predeterminado incluye una fila por
cada combinación seleccionada de proyecto e indicador, incluso en proyectos incompletos.
Mantiene exactamente las hojas y ocho columnas de la plantilla descritas abajo.
Esquema: `schemas/thesis_all_indicators.v1.schema.json`.

Las decisiones válidas SUPPORTED, INSUFFICIENT_EVIDENCE y NOT_SUPPORTED conservan
su significado y confianza numérica almacenada, incluido cero. Los estados técnicos
y pendientes conservan su nombre original, con confianza NULL y sin evidencia inventada.
Las explicaciones provienen del registro original; solamente las citas verificadas
aportan fuente y ubicación. No se recalcula `100 * (0.55*S + 0.45*K)`.
No se fabrican artículos, relaciones territoriales ni códigos DANE.

El coordinador y el exportador autónomo usan este contrato por defecto. Las nuevas
ejecuciones producen `resultados/resultado_indicadores.xlsx` e `indicadores.csv`
con cobertura completa. La cobertura del archivo no convierte una evaluación PARTIAL
en COMPLETE. Los IDs se guardan como texto; confianza como número o celda vacía.
Power Query debe tipar los IDs como Texto y confianza como Número decimal, conservando
las celdas vacías como null, sin reemplazarlas por cero.

Recuperación offline sin inferencia, evaluación, scoring ni procesamiento:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -B -m layer4_evaluation.thesis_output --run outputs/runs/local/RUN_ID
```

También disponible mediante `scripts.pipeline_coordinator.export(root, run, offline=True)`.
Se verifican planes sellados, catálogo embebido, selección, recibos, hashes de artefactos,
identidades, ausencia de duplicados y coincidencia exacta con las evaluaciones originales.
La recuperación reutiliza los escritores de plantilla y CSV del exportador existente.
Genera `resultado_indicadores_completo.xlsx`, `indicadores_completos.csv` y un recibo nuevo
con hashes de todos los archivos originales; rechaza sobrescribir estos destinos.
No modifica manifiestos, checkpoints, evaluaciones, auditorías ni archivos archivados.

## Contrato histórico: THESIS_POSITIVE_OUTPUT_V1

Su significado y esquema permanecen intactos. Puede solicitarse explícitamente con
`output_contract='THESIS_POSITIVE_OUTPUT_V1'` en los exportadores. La descripción
siguiente documenta exclusivamente esa política histórica; no rige las nuevas ejecuciones.

La instrucción explícita de salida del usuario reemplaza las proyecciones históricas
descritas más abajo. La plantilla versionada es
`data/templates/plantilla_resultado_tesis.xlsx`; las anteriores se conservan intactas.
El esquema es `schemas/thesis_output.v1.schema.json`.

Exactamente dos hojas, `Proyectos` y `Artículos`, ambas con estas columnas en orden:

1. `proyecto/articulo_siap_id`
2. `indicador_id`
3. `estado_cumplimiento`
4. `parrafo_evidencia`
5. `fuente_evidencia`
6. `ubicacion_evidencia`
7. `territorio_region`
8. `confianza`

Una fila por fuente e indicador SUPPORTED con evaluación VALID, citas y ubicaciones
verificadas y confianza calculada original. No se multiplican filas por investigador
ni por territorio. El párrafo conserva la explicación del evaluador y las citas
literales que la sustentan. La fuente contiene nombres de columnas originales;
la ubicación incluye archivo, hoja/fila, columna y coordenadas verificables.
Solo se proyectan territorios verificados en las citas del cumplimiento; en otro caso
la celda queda vacía. La fórmula de confianza no cambia.

Negativos, parciales, bloqueos y pendientes permanecen en diagnósticos separados.
Artículos conserva los ocho encabezados sin filas mientras no haya evaluaciones
ARTICLE verificadas. Cero positivos produce ambas hojas con solo encabezados,
sin cambiar el estado PARTIAL de una ejecución incompleta.

El coordinador usado por menú/CLI y el exportador autónomo comparten
`src/layer4_evaluation/thesis_output.py`. El Excel de diagnóstico no sustituye esta
salida final. Los planes, manifiestos y libros históricos no se migran automáticamente.

## Referencia histórica: INDICADORES / TERRITORIOS

La descripción siguiente corresponde a la versión anterior y no controla nuevas salidas.

La plantilla oficial es `data/templates/plantilla_resultado_final_indicadores_territorios.xlsx`.
Se proporciona manualmente y nunca se regenera ni sobrescribe al construir contratos.
El exportador la localiza desde la raíz del repositorio, independientemente del directorio actual.

Hojas y columnas, en orden:

- `INDICADORES`: `id_proyecto`, `id_articulo`, `id_investigador`, `id_indicador`,
  `estado_cumplimiento`, `confianza`, `parrafo_evidencia`, `fuente_evidencia`, `ubicacion_evidencia`.
- `TERRITORIOS`: `id_proyecto`, `id_articulo`, `tipo_territorio_id`, `codigo_dane`,
  `fuente_evidencia`, `ubicacion_evidencia`.

La proyección autónoma actual procesa proyectos: `id_articulo` queda vacío.
Mantiene SUPPORTED, INSUFFICIENT_EVIDENCE y NOT_SUPPORTED validados. Los casos pendientes
figuran como REVIEW_REQUIRED, con explicación provisional y sin confianza inventada.
Las decisiones, la fórmula de confianza, las relaciones institucionales y las citas no cambian.
La explicación breve proviene del evaluador; fuente y ubicación conservan columna, archivo y hoja/fila.
No se publican JSON ni identificadores de chunks en las celdas.

Se mantienen ambas hojas incluso sin filas territoriales. Este exportador no incorpora un
puente territorial nuevo: no infiere territorios ni convierte el tema de un proyecto en una ubicación.
El reconocimiento territorial existente permanece separado e intacto.

`run.py export --autonomous --run-id ID` verifica las autorizaciones, datos, resultados y scores
persistidos y escribe `outputs/runs/<run_id>/resultado_final_indicadores.xlsx`. No ejecuta inferencias
ni reescribe manifiestos o checkpoints. La plantilla y su SHA-256 se registran en el comprobante del Excel.
Los libros históricos no se migran automáticamente al formato nuevo.

`data/templates/resultado_final_indicadores.xlsx` conserva únicamente bytes de la plantilla anterior
para referencias históricas; no es una alternativa de exportación. El resolvedor mantiene los localizadores
antiguos sin cambiar sus hashes.
