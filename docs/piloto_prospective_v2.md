# Piloto mínimo PROSPECTIVE_V2

## Revisión final: decisión determinista

La versión actual de nuevos planes `prospective-v2` utiliza el prompt
`PROSPECTIVE_V2_CRITERIA_DECISION_V1` y la política `VALIDATED_CRITERIA_DECISION_V1`.
Python valida componentes, deriva el estado y aplica todas las validaciones finales.
El positivo almacenado sigue SUPPORTED; una traza negativa R2 válida en sus
componentes queda INSUFFICIENT_EVIDENCE por reproducción offline. Los intentos con
referencias/fuerza inválidas siguen bloqueados. Pasaron 89 pruebas; no hubo nuevas
inferencias. Véase [la documentación de la corrección](decision_determinista_prospective_v2.md)
y el inicio del informe `outputs/pilotos/prospective_v2_tec04/comparacion.md`.
Los planes y resultados anteriores no se migran ni se resellan. Las secciones
siguientes son antecedentes de la preparación y de los cierres anteriores.

## Cierre definitivo

El cierre del 2026-11-15 conserva 21869/TEC-04 como SUPPORTED y registra un bloqueo
residual en 21844/TEC-04 tras las dos llamadas adicionales autorizadas. Se detuvo
el trabajo al alcanzar ese límite. El informe definitivo es
`outputs/pilotos/prospective_v2_tec04/comparacion.md`; no se da por validado el sistema
para iniciar la campaña completa.

La versión final preparada es PROSPECTIVE_V2 con prompt
`PROSPECTIVE_V2_APPLICABILITY_V3` y protocolo `APPLICABILITY_DECISION_SCHEMA_V1`.
El esquema restringe combinaciones de aplicabilidad/decisión sin modificar rúbricas
ni validadores. Se conservan las revisiones previas y no se migran planes existentes.
El resto del documento describe etapas anteriores; sus comandos no constituyen
una indicación de volver a ejecutar el piloto. Los resultados de cierre están en
`outputs/pilotos/prospective_v2_tec04_cierre/` (solo 21844, dos llamadas).

## Ejecución y revisión de instrucciones (2026-11-15)

El piloto original ya se ejecutó por autorización explícita del usuario. Conserva sus
cuatro respuestas nativas en `outputs/pilotos/prospective_v2_tec04/`: 21869 produjo
`SUPPORTED` tras corregir una etiqueta temporal; 21844 agotó el reintento con
`INVALID_ASSESSMENT`. Este último es un bloqueo técnico, no un rechazo semántico.

La revisión `PROSPECTIVE_V2_APPLICABILITY_V2` aclara requisitos ya existentes:
referencias vacías en criterios `NOT_DEMONSTRATED`, incompatibilidad entre respaldo
positivo y evidencia ajena, diferencia entre falta de evidencia y exclusión
documentada, y etapas apropiadas para resultados esperados. Conserva las rúbricas,
validadores, modelo y confianza. La revisión anterior sigue disponible mediante
`prospective_v2.instructions_for(PROMPT_V1)` y `make_request(...,
prompt_version='PROSPECTIVE_V2_APPLICABILITY_V1')`. Los nuevos planes V2 seleccionan
la revisión V2; los planes existentes no se migran ni se resellan.

La repetición de los mismos dos pares utiliza una carpeta distinta:
`outputs/pilotos/prospective_v2_tec04_r2/`. Su `comparacion.md` y el informe de la
carpeta original documentan los resultados. La repetición también quedó PARTIAL:
21869 fue válido sin reintento, pero 21844 volvió a producir una decisión incompatible
con su aplicabilidad. Fueron siete llamadas entre ambas ejecuciones y 55 pruebas
deterministas aprobadas. No se recomienda todavía iniciar la campaña completa.
No volver a ejecutar el plan original
con código modificado: el control de hashes lo impide deliberadamente. Las fuentes
originales afectadas se conservaron en `codigo_revision_original/` dentro del primer
piloto. El resto de este documento describe el protocolo de preparación original.

Preparación sin inferencias. La ejecución manual evalúa exclusivamente **21869/TEC-04** y **21844/TEC-04**. No procesa los cinco proyectos ni el resto del catálogo.

Desde PowerShell:

```powershell
Set-Location -LiteralPath 'C:\Users\sebas\Workspace\Docs Tesis\GraphRag'
& .\.venv\Scripts\python.exe -B scripts\pilot_prospective_v2.py execute
```

Este es el único comando que inicia las inferencias. Ollama debe estar disponible en el endpoint ya configurado. El script no inicia servidores ni descarga modelos. La preparación no ha comprobado la disponibilidad del servidor.

Salida aislada: `outputs/pilotos/prospective_v2_tec04/`.

- `preparacion.json`: alcance preparado y constancia de que no se ejecutó.
- `evaluation/batch_pilot_tec04/review.txt`: configuración y presupuestos para revisión antes de ejecutar.
- `evaluation/batch_pilot_tec04/plan.json`: dos proyectos, solo TEC-04 y el catálogo V2 sellado. Conservar 48 perfiles en el plan es un requisito de validación, no implica evaluarlos.
- `comparacion.md` y `comparacion.json`: se generan con resultados al terminar, incluso si quedan bloqueos técnicos. Antes de ejecutar, el Markdown solo indica que no hay resultados nuevos.
- `resultados/`: evaluaciones válidas, estados técnicos, CSV y Excel del contrato prospectivo existente.
- `evaluation/batch_pilot_tec04/calls/`: prompts, respuestas originales de Qwen, respuestas nativas, validaciones y reintentos.

## Qué se mantiene fijo

Modelo `qwen3.5:4b-q4_K_M`, configuración general del run de referencia, `PROSPECTIVE_V2`, contrato `ASSESSMENT_PROSPECTIVE_V2`, prompt `PROSPECTIVE_V2_APPLICABILITY_V1`, contexto `BASE_RETRIEVED_GRAPH_V1` y Knowledge `78420dc8b249600b-9558d0f0`.

Para aislar el efecto de las instrucciones y rúbricas V2 se reutilizan **exactamente los fragmentos y relaciones ya recuperados y sellados** para esos dos pares en `run_20261115_063255_909981`. Se conservan IDs, texto, orden, campos, límites y procedencia. No se ejecuta otra búsqueda, no se generan consultas BGE-M3 y no se reconstruye ningún artefacto. Esto prueba la interpretación de evidencia fija, no la calidad de una nueva recuperación.

La preparación deriva las rúbricas mediante la función V2 existente y verifica las etapas efectivas; no modifica las rúbricas de producción ni las históricas. No reutiliza las respuestas anteriores como respuestas nuevas o ejemplos dentro del prompt. Las respuestas nuevas se obtienen mediante `live_execution.execute`, su proveedor real de Ollama, sus validaciones y su cálculo de confianza. Los manifiestos del Knowledge y del grafo se verifican por hash; no se realiza una nueva auditoría profunda de vectores o BASE.

El límite del piloto es una llamada inicial más un reintento por par: **máximo cuatro llamadas nativas**. El reintento puede usarse para corrección o límite de salida según el proveedor existente. No cambia temperatura, semilla, ventana, modelo, pesos ni reglas de aceptación. Los errores técnicos permanecen separados de las decisiones semánticas.

## Interpretación de la comparación

Por par se conservan estado y confianza anteriores/nuevos, CLEAR/PARTIAL/NONE, requisitos esenciales sin CLEAR, aplicabilidad, justificaciones y citas con etapas. NONE corresponde a `NOT_DEMONSTRATED`. El informe enlaza las respuestas originales y registra errores y reintentos.

“Mismos juicios y decisión” describe el resultado observado; no prueba por sí solo que siga una interpretación restrictiva. “Cambio de juicio o decisión” tampoco prueba que el cambio sea correcto. Revisar si las citas describen tecnología instrumental, destinatarios, función, mecanismo y beneficio esperado, sin confundir una población o un mecanismo social con tecnología ni exigir ejecución. La corrección documental permanece `PENDING_HUMAN_REVIEW`.

La fórmula sigue siendo `100 × (0,55 S + 0,45 K)`. `INSUFFICIENT_EVIDENCE` conserva la confianza calculada; `NOT_APPLICABLE` requiere justificación verificable y muestra N/A; los errores no reciben puntuaciones artificiales.

Para regenerar solo el informe, sin inferencias:

```powershell
& .\.venv\Scripts\python.exe -B scripts\pilot_prospective_v2.py report
```

Un plan preparado nunca se sobrescribe. Si cambia el código congelado, la ejecución se detiene; para preparar una revisión aparte se necesita otra subcarpeta mediante `prepare --output outputs/pilotos/<nombre>` y el mismo `--output` en el comando manual. Los comandos no activan Knowledge ni modifican el run de referencia.
