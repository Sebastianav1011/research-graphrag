# Diagnóstico de publicación de Knowledge

Fecha: 2026-11-15. Run investigado: `run_20261115_184156_741664`.

## 1. Diagnóstico y evidencia

**Defecto comprobado:** dentro de `verified_execution`, `verify()` retenía un
`ReadLease` sobre los archivos de staging. En Windows, `CreateFileW` se abre con
`FILE_SHARE_READ` (sin compartir eliminación/renombrado). Luego `_publish_staged()`
intentaba mover el directorio con esos manejadores abiertos. Se liberaban recién
al salir de la ejecución, demasiado tarde para publicar.

Una prueba nueva con un checkpoint sintético, dentro de `verified_execution`, falló
antes de la corrección con **el mismo `PermissionError: [WinError 5]` en
`os.replace(builder, target)`**. Después de la corrección pasa en Windows. Las
pruebas anteriores de publicación no cubrían esa sesión de verificación envolvente.

**Diagnóstico histórico más probable:** bloqueo provocado por el propio proceso.
El traceback de `outputs/runs/local/run_20261115_184156_741664/logs/terminal.log`
confirma `verified_execution → execute_pipeline → register_built_knowledge →
register → _publish_staged → os.replace`; `estado/failure.json` registra
`PermissionError` en la etapa `graphrag` con origen y destino coincidentes.

Inspección de solo lectura: staging `build-ec7068b4b170468c8ab5da469abecca2` sigue
presente y tiene recibo `.promotion.json`, creado a las `19:14:31 UTC`. Este recibo
identifica `d778bfa52b4c1c69-c23a16f9`. El directorio de esa versión existe, pero
está vacío: no hay `artifacts` ni `manifest.json`. Esto concuerda con la creación
del padre seguida del fallo del renombrado. `active.json` conserva la versión
anterior `78420dc8b249600b-9558d0f0`.

| Posible causa | Conclusión |
| --- | --- |
| Destino existente | No hay evidencia de `artifacts` existente; el padre vacío es normal antes de mover. El estado actual no prueba por sí solo el estado histórico. |
| Archivos bloqueados | Bloqueo propio reproducido y comprobado; no existe captura histórica de manejadores que descarte además procesos externos. |
| Permisos de Windows | `WinError 5` por sí solo no demuestra un problema de ACL. No se cambiaron permisos. |
| Operación de movimiento | Falló exactamente el renombrado de staging. No se detectó necesidad de copiar artefactos ni cambiar de volumen. |
| Publicación parcial | Quedaron intención persistida y padre vacío; no una versión registrada o activada a medias. |
| Carrera | No hay evidencia de otra publicación simultánea en ese run. Sí había comprobación de existencia seguida de movimiento sin exclusión mutua y temporales JSON con nombre compartido: riesgos demostrables en el código. |

## 2. Archivos y funciones

- `src/knowledge_store.py`: `verify`, `_publish_staged`, `register`, `_atomic_write`,
  `_publication_lock`; revisión de `compatible`, `describe`, `identity` y activación.
- `src/knowledge_verification.py`: `ReadLease`, `verified_execution` (revisados,
  sin cambios).
- `scripts/pipeline_coordinator.py`: `execute_pipeline`, `register_built_knowledge`
  y `validated_graph` (revisados, sin cambios).
- `src/layer2_processing/pipeline.py` y `checkpoints.py`: validación de integridad
  y fingerprints (revisados, sin cambios).
- `run.py`: `confirm_action`. Pruebas en `tests/test_knowledge_store.py` y
  `tests/test_selection_console.py`.

## 3. Correcciones

- Staging recibe verificación profunda sin conservar leases. Tras moverlo se
  verifica nuevamente en destino; los artefactos definitivos conservan sus leases
  e inmutabilidad durante la ejecución. Una validación fallida sigue abortando.
- Exclusión mutua de publicaciones mediante bloqueo del sistema operativo,
  no bloqueante y liberado ante salida del proceso. El archivo `.publication.lock`
  permanece deliberadamente; su existencia no significa que esté bloqueado.
- `os.rename` evita reemplazar destinos en Windows. Se rechazan también versiones
  ya registradas antes de mover en un reintento; no se reemplazan checkpoints
  existentes. Se conserva la política previa de rechazo de un constructor distinto
  que produce el mismo identificador.
- JSON atómico con temporal exclusivo, cierre antes del reemplazo, `fsync` y
  limpieza exclusivamente del temporal creado por esa llamada. El recibo de
  promoción sigue permitiendo reintentos idempotentes, con validación completa.
- Los errores del renombrado conservan tipo y traceback y añaden registro y nota
  con operación, rutas, recibo, `errno`, `winerror` y existencia de origen/destino.
  No hay reintentos automáticos que oculten bloqueos externos.
- Ante `Fingerprint mismatch`, se muestra la advertencia solicitada. Solo cambia
  el texto: se mantienen aceptación de `si`/`sí`, rechazo por defecto, EOF y modo
  no interactivo. La etiqueta `(s/N)` se reproduce literalmente según lo pedido.
- No se cambian fingerprints, criterios de compatibilidad ni selección de BASE.
  Cambios de interfaz/publicación no fuerzan una reconstrucción de Knowledge:
  esos módulos están fuera de `KNOWLEDGE_CODE`. Las verificaciones de integridad
  continúan rechazando cualquier incompatibilidad real.

No se eliminaron ni limpiaron publicaciones históricas o incompletas: se conserva
la evidencia y se evita destruir artefactos que pudieran estar referenciados.

## 4. Pruebas y resultados

Comando final, sin sincronizar dependencias ni ejecutar `run.py`:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/test_knowledge_store.py tests/test_selection_console.py -q
```

**79 pruebas aprobadas en 16,26 s, sin omisiones**, con carpetas temporales del
sistema y validadores pesados simulados. Cubren publicación dentro de la sesión
real de verificación, destino existente, permisos denegados simulados
(`winerror` 5 y 32), archivo realmente bloqueado con un lease de Windows,
interrupción antes del movimiento y antes del manifiesto, reintentos seguros,
rechazo de corrupción posterior al movimiento, protección de versiones/punteros
anteriores, exclusión de un segundo publicador y liberación del bloqueo tras
excepción y terminación abrupta de un subproceso sintético. También cubren
fingerprints exactos compatibles/incompatibles con el validador real, reutilización
compatible y texto/comportamiento de la advertencia. `git diff --check` sin errores.

No se cargaron modelos, generaron embeddings ni ejecutaron reconstrucciones o
campañas reales. El run afectado no se recuperó ni reanudó.

## 5. Riesgos residuales

Antivirus, indexadores, otros lectores sin compartir renombrado, ACL, falta de
espacio y fallos del disco pueden seguir impidiendo publicar. Se aborta conservando
el recibo y los artefactos; no se garantiza éxito frente a esas condiciones.
El bloqueo coordina publicadores que usan este código, no modificaciones manuales.
La activación y su historial siguen siendo operaciones separadas de la publicación;
no se garantiza orden transaccional del historial entre activaciones concurrentes.
Una caída eléctrica no equivale a las interrupciones simuladas. Las pruebas no
certifican un build completo ni el estado profundo de los artefactos históricos.

## 6. Antes de la siguiente ejecución

1. Usar este código actualizado y comenzar una ejecución nueva; conservar el run
   fallido y sus directorios sin moverlos ni borrarlos.
2. Ejecutar una sola campaña/publicación a la vez; evitar herramientas que mantengan
   abiertos los archivos de `outputs/shared/base`. Confirmar espacio libre y acceso
   normal de escritura con el usuario habitual, sin elevar privilegios por defecto.
3. Elegir reutilización cuando exista una versión realmente compatible. Si aparece
   la advertencia de fingerprint, decidir explícitamente la reconstrucción; no
   editar manifiestos o hashes para forzar compatibilidad.
4. La siguiente ejecución completa de `uv run python run.py` queda a cargo del
   usuario. Ante otro fallo, conservar `terminal.log`, `failure.json` y el recibo
   de promoción, ahora con diagnóstico adicional del renombrado.
