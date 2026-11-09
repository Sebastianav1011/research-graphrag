# Salida final de indicadores

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
