# Decisión determinista de PROSPECTIVE_V2

Revisión preparada: **VALIDATED_CRITERIA_DECISION_V1**, prompt
**PROSPECTIVE_V2_CRITERIA_DECISION_V1**, contrato `ASSESSMENT_PROSPECTIVE_V2`.
`python run.py` utiliza **PROSPECTIVE_V2** y **VALIDATED_CRITERIA_DECISION_V1**
por defecto para runs nuevos, tanto de BASE como de Incoming. No requiere flags
ni seleccionar la metodología en el menú. Conserva la selección habitual de fuentes,
proyectos, conocimiento y autorización. La política y su hash quedan en el plan. No reanudar
un plan anterior esperando que cambie de metodología: los planes sellados se conservan.
No se ejecutaron inferencias ni campañas para esta corrección.

## Integración predeterminada en `python run.py`

El comando sin argumentos abre el flujo habitual de selección y autorización.
`main -> menu -> dispatch -> dispatch_pipeline -> execute_with_console ->
pipeline_coordinator.execute_pipeline` resuelve la política de los runs nuevos
con `assessment_v3.evaluation_policy`. BASE ya seleccionaba V2; Incoming ahora
también la selecciona por defecto y no pide elegir metodología ni contexto.
Se conserva el contexto recuperado de GraphRAG propio de cada fuente.

El coordinador conserva la política completa (metodología, prompt, política de
decisión, versión de confianza y hash) en `execution.json`, la configuración de
`run.json` y `model.binding.json`. `prepare_evaluation` la lleva a `plan.json` y
a las solicitudes de los 48 indicadores; el manifiesto del lote sella su hash.
`evaluate -> live_execution -> ollama_provider` aplica el resolver determinista
a los componentes validados. Las exportaciones y `runtime.manifest.json`
conservan la política del run. Los checkpoints históricos conservan su política.

Validación de esta integración: **128 pruebas deterministas aprobadas**:

```text
.venv/Scripts/python.exe -B -m pytest tests/test_run_prospective_defaults.py tests/test_selection_console.py tests/test_prospective_v2.py tests/test_prospective_v2_decisions.py tests/test_prospective_v2_closure.py tests/test_prospective_v2_pilot.py tests/test_calibrated_context.py -q
```

Incluyen entrada sin argumentos, ambas fuentes, metadatos, planificador real
con datos sintéticos, 48 solicitudes, tres decisiones semánticas, errores técnicos,
fórmula de confianza, transporte simulado y exportación prospectiva JSON/CSV/Excel.
Sin inferencias, campañas, embeddings nuevos ni cambios en datos históricos.

La revisión ampliada detectó además 22 fallos en pruebas antiguas de exportación
(`test_indicator_csv.py` y `test_thesis_output.py`): esperan el contrato histórico,
confianza en H y errores técnicos entre las filas exportadas. Los mismos 22
fallos se reprodujeron restaurando en memoria el comportamiento predeterminado
anterior de `evaluation_policy`, sin modificar archivos del sistema. No proceden
de esta integración; los exportadores y sus contratos se conservaron.

## Regla general, independiente del indicador

Qwen conserva la evaluación individual, evidencia, etapas, cobertura, fuerza y
aplicabilidad. Su `decision` pasa a ser una recomendación auditable.

1. Se verifica el esquema, los IDs exactos y completos, las citas literales del
   contexto enviado, su temporalidad, cobertura/soporte, relación con el proyecto,
   referencias de fuerza, anclas de fuerza y documentación de aplicabilidad.
   Solo se difieren las validaciones dependientes de la decisión original.
2. Si los componentes son inválidos, se produce `INVALID_ASSESSMENT`. No se obtiene
   una decisión semántica ni confianza artificial y no se corrigen puntuaciones.
3. Con componentes válidos, Python deriva:

| Aplicabilidad y criterios | Decisión candidata |
|---|---|
| NOT_APPLICABLE con alcance/exclusión documentados, citas y contrato de respaldo cero | NOT_APPLICABLE |
| APPLICABLE, todos REQUIRED CLEAR y una alternativa CLEAR por grupo, con condiciones especiales existentes satisfechas | SUPPORTED |
| Respaldo esencial incompleto o aplicabilidad UNDETERMINED | INSUFFICIENT_EVIDENCE |

4. Se aplica **toda la validación final existente**, incluida la fuerza 3/4 para
   SUPPORTED, fuerza 0/1/2 para insuficiencia y las limitaciones de registros externos
   ya vigentes. Una contradicción entre fuerza y componentes sigue siendo un error;
   no se altera la fuerza para obtener una decisión aceptable. COMPLEMENTARY no bloquea.

No se usa confianza para seleccionar estados. Su fórmula, definiciones de S/K y
redondeo permanecen `C = 100 × (0,55 × S + 0,45 × K)`. NA conserva confianza N/A;
errores técnicos, sin valor. No cambian los 48 indicadores, rúbricas ni recuperación.

## Integración y trazabilidad

- `prospective_v2.resolve_decision`: deriva el estado sobre componentes validados,
  copia el assessment sin cambiar juicios, evidencia, cobertura ni fuerza y somete
  el resultado a las validaciones finales. La explicación final es determinista.
- `assessment_v3.validate(..., components_only=True)`: reutiliza los controles
  independientes de la decisión. La proyección a la validación histórica usa un
  sobre interno compatible con la fuerza; no altera la entrada. Las llamadas
  normales de validación, filas y confianza siguen validando el resultado completo.
- `context_budget.make_request`: activa la política solo para la nueva revisión.
  Se mantienen las revisiones anteriores y el esquema de decodificación V3.
- `ollama_provider`: materializa referencias, llama al resolver, guarda
  `decision.json` y valida el assessment final. `response.raw.txt` y `selection.json`
  mantienen la respuesta original; `decision.json` conserva decisión/explicación
  originales, decisión derivada, bloqueadores y versión.
- `live_execution.resolve_wrapper/materialize_output`: usa el mismo resolver para
  ejecución y verificación offline. La auditoría reconstruye el resultado desde
  la selección original y exige coincidencia del recibo. Los hashes cubren las trazas.
- Las filas y exportaciones consumen la decisión derivada ya validada; se conserva
  el contrato JSON/CSV/Excel y no se añaden columnas obligatorias.

## Comprobación offline con el piloto existente

Se conservaron los archivos originales, verificando sus SHA-256 antes/después.
Los resultados reinterpretados están separados en
`outputs/pilotos/prospective_v2_tec04/consistencia_determinista/`. No son una nueva
respuesta de Qwen ni una modificación del resultado histórico del piloto.

| Traza almacenada | Resultado de la nueva política |
|---|---|
| 21869 R2, intento 1 | SUPPORTED, cinco esenciales CLEAR, confianza 100,00 |
| 21844 R2, intento 2 | INSUFFICIENT_EVIDENCE, confianza 73,00; C01/C03/C05 sin CLEAR; aplicabilidad UNDETERMINED |
| 21844 cierre, intento 1 | INVALID_ASSESSMENT: ND con citas y referencias de fuerza inválidas |
| 21844 cierre, intento 2 | INVALID_ASSESSMENT: fuerza cero incompatible con dimensiones y criterios positivos |

En el segundo caso, la decisión original era NOT_APPLICABLE pese a una aplicabilidad
UNDETERMINED. Los componentes sí satisfacen el contrato independiente de decisión;
Python resuelve la contradicción sin cambiar sus valores. No se ha reclasificado
automáticamente ninguno de los dos intentos posteriores inválidos.

**89 pruebas deterministas aprobadas (10,61 s)**: tres estados, alternativas y
complementarios, criterios incompletos/duplicados, citas/etapas/cobertura/fuerza
inválidas, NA sin prueba documental, confianza alta con esencial incompleto,
fórmula exacta, revisiones anteriores, exportaciones, transporte simulado con
decisión contradictoria y reconstrucción de recibos. No hay regresiones conocidas
en estas comprobaciones. `git diff --check` sin errores de formato.

## Alcance de la preparación

La consistencia entre criterios válidos y estado final queda resuelta de forma
general, sin condiciones específicas para TEC-04. La revisión está preparada para
la ejecución manual posterior. No se garantiza que todas las respuestas futuras
de Qwen tengan componentes válidos: errores de citas, cobertura, fuerza o
aplicabilidad seguirán bloqueándose y separándose de las decisiones semánticas.

La validación estructural tampoco certifica por sí sola la pertinencia de cada
cita si el modelo declara una relación equivocada. En 21844, el CLEAR de C04 y las
dimensiones máximas siguen mereciendo revisión humana; no cambian el rechazo de
SUPPORTED porque faltan tres esenciales. La reproducción offline comprueba la
política y la integración, no la tasa futura de errores del modelo. Se detiene aquí
el trabajo, sin nuevas inferencias ni optimizaciones adicionales.
