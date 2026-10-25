# Auditoría de Capa 4

`inventory_before.json` e `inventory_restricted.json` inventarían 1.725 archivos
originales. `duplicate_groups.json`, `cleanup_dry_run.json` y
`relocation_dry_run.json` documentan la simulación anterior a los movimientos.
`deleted_files.json` registra **11 duplicados idénticos** eliminados (409.233
bytes), con ruta original, hash, motivo y copia canónica retenida.
`deleted_directory_aliases.json` registra 56 alias de directorio pytest eliminados;
no son 56 archivos de resultados. Sus destinos se preservaron.

`rutas.json` resuelve rutas históricas sin reescribir manifiestos ni fingerprints.
`codigo_original/` conserva una vez los bytes anteriores de los archivos editados
para migración/documentación y los vincula con hashes actuales. No es un respaldo
duplicado de los resultados. `estado_reanudacion_v3_3.json` es el índice operativo
actual; los estados antiguos quedan como evidencia de sus respectivas ejecuciones.

## Material histórico necesario

- `cierre_v2/`: manifiestos y procedencia de la publicación protegida.
- `revision_humana/`: revisiones conservadas sin reinterpretar decisiones.
- `qa/`: informes históricos de pruebas; no equivalen a una ejecución actual.
- `historicos/`: entregas iniciales, preparaciones, diagnósticos y experimentos
  anteriores conservados porque sus archivos son entradas o evidencia de
  manifiestos/fingerprints congelados. Incluye `entrega_20`, `entrega_piloto_5`,
  `preparacion_inicial`, `preliminar_20`, `powerbi_preliminar_20`,
  `diagnostico_pre_refactor`, `diagnostico_runtime`, `experimento_50`,
  `cierre20_previo`, `cierre20_red`, `final20_previo` y `cierre_v2_20`.
- `pendiente_revision/`: 287 archivos de fixtures de pruebas con restricciones de
  acceso o dependencias inciertas. No se eliminaron por nombre ni antigüedad.
  `restricted_review.json` documenta la revisión pendiente.

Los duplicados restantes con procedencia/fingerprints distintos no se eliminaron
automáticamente. Las respuestas originales y errores son evidencia; no se borran
para mejorar estadísticas. Una revisión futura puede retirar material adicional
solo tras demostrar que no tiene dependencias activas.

## Cierre de la recuperación

`integrity_sandbox.json` e `integrity_native.json` registran las comprobaciones
complementarias de permisos. Su unión cubre las 1.725 entradas originales,
incluidas las once resueltas hacia duplicados canónicos y la documentación cuyo
original se conserva en snapshot. `recovery_completion.json` registra cobertura,
pruebas ejecutadas, protección de V2/4B y trabajo pendiente. No se consumió
inferencia durante esta recuperación.
