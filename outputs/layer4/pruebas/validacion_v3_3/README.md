# Validaciones y piloto V3.3

Esta carpeta conserva un único conjunto trazable de respuestas, autorizaciones,
planes, prompts, hashes, métricas, errores y continuaciones. No es la publicación
oficial. Los manifiestos conservan versiones y rutas originales; la resolución de
rutas se documenta en `../../auditoria/rutas.json`.

## Pruebas conservadas y resultados

| Artefacto | Finalidad y resultado |
|---|---|
| `continuacion_prompt_v3_1/` y `records/` | Ejecuciones V3 recuperadas de cuatro proyectos: 20 assessments VALID, 2 SUPPORTED y 18 INSUFFICIENT_EVIDENCE. |
| `pilot_five.*` | Consolidación del piloto de cinco proyectos, configuraciones exactas y procedencia. No atribuye assessments V3 a V3.3. |
| `prueba_controlada_v3_3_PROJ_22027/` | Control de rechazo: cero seleccionados, 48 descartados. Sus dos assessments V3 se conservan solo como historia. |
| `control_positivo_v3_3_PROJ_20022.*` | Control positivo: conserva ASC-01; seis priorizados, nueve en backlog y 33 descartados. El backlog no son evaluaciones nuevas. |
| `cierre_piloto_v3_3_PROJ_20899.*` | Quinto proyecto: discovery V3.3 válido, cero seleccionados; sin assessments nuevos. Intento fallido previo y continuación exitosa preservados. |
| `cierre_homogeneo_v3_3/PROJ_20456/` | Discovery V3.3 válido: seis priorizados, 42 descartados. Una llamada, 55.930 tokens y 120,438876 s. |
| `cierre_homogeneo_v3_3/PROJ_21299/` | Plan preparado; discovery V3.3 pendiente y sin autorización consumida. |
| `preparacion_cierre_v3_3.*` | Consumo observado, presupuestos, lotes y optimizaciones propuestas no activadas. |
| `auditoria_rubricas_v3_4.*` | Propuestas COL-01/CUL-01 sin aprobar, no activadas. |

## Reanudación

Consultar primero `../../auditoria/estado_reanudacion_v3_3.json`. PROJ_20456 no debe
volver a descubrirse: su `verification.json` y `reuse_comparison.json` conservan
COL-01, ASC-01, COL-02, COL-03 y CUL-02 reutilizables bajo comprobación de proyecto,
indicador, contenido/versión de rúbrica, contrato, entrada semántica, citas, hashes
nativos y ejecución. **SOC-02 está pendiente de assessment**. ECO-04 permanece
histórico y no seleccionado por V3.3. Seis selecciones no son seis assessments.

La reutilización registra la nueva procedencia de discovery y conserva la
respuesta de assessment original. No basta con coincidir en indicador. El
coordinador controlado no ejecuta el assessment SOC-02: necesita una autorización
y preparación específica posterior, sin relanzar descubrimiento.

Para verificar la ejecución completada, desde la raíz:

```powershell
.\.venv\Scripts\python.exe -B scripts/run_layer4_pilot_discovery_v3_3.py verify --project PROJ_20456
```

PROJ_21299 requiere autorización independiente ligada a su plan/request antes de
cualquier `execute`. No retirar claims ni borrar intentos para habilitar otra
llamada. Ante un resultado incierto, error o métricas ausentes, detener e inspeccionar.
El control no continúa automáticamente a assessments ni a otro proyecto.

Los veinte proyectos aún no forman un cierre homogéneo V3.3: quedan 16
 descubrimientos (PROJ_21299 y los quince fuera del piloto), además de assessments
justificados por la selección y compatibilidad. No se ejecutaron aquí.

## Límites y verificación

La selección V3.3 examina 48 perfiles y admite cero candidatos. El contrato actual
es ASSESSMENT_V3, confianza `100 × (0.55S + 0.45K)`. Las rúbricas congeladas están
en `continuacion_prompt_v3_1/rubrics.json`. No se activaron propuestas V3.4 ni
compactación. Los nombres antiguos de helpers/estados describen su ejecución
histórica: no ejecutarlos automáticamente para regenerar resultados.
La verificación reproducible sin inferencia usa las pruebas locales del README
general y el subcomando `verify`; repetir una inferencia no garantiza la misma
respuesta y requiere autorización nueva.
