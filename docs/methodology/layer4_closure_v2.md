# Procedimiento único de cierre de Capa 4 V2

Estado vigente: **CAPA_4_COMPLETE**, veinte proyectos, veintinueve pares válidos,
aceptación explícita global 5/5 y publicación oficial verificada. Constancias:
`pruebas/cierre_v2_20_definitivo/final_acceptance_decision.json`,
`official_verification.json` y `closure_status.json`. La declaración global no
representa veintinueve calificaciones independientes ni etiquetas humanas.

## Configuración definitiva

Usar `scripts/run_layer4_closure.py` con **`--settings config/layer4_closure_definitive.yaml`**.
Es la configuración operativa: ASSESSMENT_V2, SEMANTIC_POLICY_V2_1,
EVIDENCE_CONFIDENCE_V2, hasta dos candidatos iniciales y fallback desactivado por
defecto. Su implementación experimental permanece disponible, sin participar
en la ejecución final.

`config/layer4_closure.yaml` y `pruebas/cierre_v2_20` están congelados porque sus
bytes forman parte de los fingerprints del piloto. No ejecutar el cierre actual
sin --settings ni cambiar sus hashes. La ejecución definitiva usa
`outputs/layer4/pruebas/piloto_v2/cierre_20/`: el mismo coordinador y requests
pendientes, con reutilización trazable de ocho pares. No es otro experimento.

## Entradas e interpretación

Capa 1 aporta identidad institucional y dimensión territorial; Capa 2, textos
canónicos, secciones y procedencia; Capa 3, candidatos PROJECT+INDICATOR publicados.
4A recibe title, keywords, summary, methodology, objectives y expected_results
completos, perfil operacional, definición y rúbrica. No reconstruye retrieval.

Codex CLI es el único motor semántico. Python prepara, coordina, valida citas y
calcula confianza. Una evidencia sustantiva puede bastar; title/keywords solo
contextualizan. Se distinguen mecanismos existentes, actividades ejecutadas,
resultados esperados e impactos demostrados según el significado del indicador.
No se inventan hechos ni se usa retrieval_score como prueba de cumplimiento.

SUPPORTED corresponde a strength 3–4; INSUFFICIENT_EVIDENCE, 1–2; NOT_SUPPORTED, 0.
El score no transforma una clasificación en otra.

## Confianza

`EVIDENCE_CONFIDENCE_V2 = 100 * (0.55*S + 0.45*K)`.
S=strength/4. K se calcula con los pesos de criterios y CLEAR=1, PARTIAL=0,5,
NOT_DEMONSTRATED=0. Cada valoración conserva evidencia y explicación auditables.
Python calcula; Codex no entrega un número arbitrario de confianza.
No hay penalizaciones por cantidad de campos, citas, longitud o corroboración.
Los válidos tienen score 0–100, los inválidos NULL. No es una probabilidad
estadística calibrada. RAW_CONFIDENCE_V1 permanece histórica.

## Fallback y aceptación del piloto

El fallback real exploró trece perfiles en tres proyectos, seleccionó cero y
consumió 39.553 tokens y 37,22 s sin aumentar cobertura. El usuario decidió
desactivarlo para el cierre. Esto no demuestra ausencia de otros indicadores
relevantes ni exhaustividad del catálogo. No se eliminó su implementación.

La validación automática, las opiniones humanas y la aceptación son distintas.
ECO-07=INSUFFICIENT_EVIDENCE/54,50 y SOC-02=INSUFFICIENT_EVIDENCE/50,00 son las
versiones vigentes; sus antecesoras no cambian. Las ocho opiniones históricas se
conservan sin convertir sus notas en etiquetas. El usuario aceptó expresamente
las ocho decisiones, incluidos SAL-02 y DIV-01, manteniendo sus observaciones.
Constancia única: `pruebas/piloto_v2_5/aceptacion_piloto_consolidada.json`.
No se afirma revisión independiente. Esta aceptación no acepta resultados nuevos.

## Preparación y tres lotes

La congelación local reproducible está en `outputs/layer4/auditoria/cierre_v2/prepare_definitive.py`.
Verifica fuentes y piloto, registra la autorización expresa y conserva procedencia
por assessment. No invoca la LLM; si existe el plan, solo lo verifica.
Hay veinte proyectos y veintinueve pares: ocho reutilizados y veintiuno pendientes
en quince proyectos. Las respuestas reutilizadas no consumen inferencia nueva.

```powershell
.\.venv\Scripts\python.exe -B scripts/run_layer4_closure.py --settings config/layer4_closure_definitive.yaml verify
```

Ejecutar este comando tres veces, verificando cada lote de cinco:

```powershell
.\.venv\Scripts\python.exe -B scripts/run_layer4_closure.py --settings config/layer4_closure_definitive.yaml execute-remaining --authorization outputs/layer4/pruebas/piloto_v2/cierre_20/authorization.remaining.json --pilot-approval outputs/layer4/pruebas/piloto_v2/aceptado_5/pilot_approval.definitive.json --batch-size 5
```

El control comprueba plan, autorización, aceptación del piloto, runtime y hashes.
La reanudación omite completados; una invocación posterior debe hacer cero llamadas.
No borrar resultados inciertos ni repetir llamadas para forzar éxito. Con el plan
enabled=false no hay exploración ni assessments complementarios.

`verify` conserva los diagnósticos del origen histórico y de preparación del
coordinador congelado. El estado de aceptación y publicación actual se consulta
con **verify-final**, que devuelve CAPA_4_COMPLETE, y closure_status.json; los
estados históricos no se reescriben para aparentar otra ejecución.

## Desempeño privado

`outputs/layer4/performance/` contiene metricas_desempeno_capa4.csv,
reporte_desempeno_capa4.xlsx e informe_desempeno_capa4.md. Las estadísticas finales
usan veinte proyectos y veintinueve pares efectivos, contando cada llamada fuente
una vez. Las evaluaciones sustituidas y el fallback experimental se informan aparte.

Se registran inferencia, preparación/validación disponibles, tokens de entrada,
salida y caché, modelo observado, CPU/RSS del coordinador, errores y reintentos.
MEASURED es medición, ESTIMATED identifica repartos/proyecciones y NOT_AVAILABLE
conserva lo inaccesible. Caché es subconjunto de entrada. No se suman solapamientos,
pausas o picos de RAM como consumo acumulado. CPU/RAM locales no son recursos remotos.

## Aceptación y publicación única

La revisión vigente cubre los veintinueve pares efectivos y sus textos fuente.
Campos humanos permanecen vacíos hasta respuesta explícita. No inventar notas,
etiquetas, independencia o aceptación. El exportador exige veinte proyectos
completos, pares válidos únicos, citas y confianza verificables y aceptación
ligada al plan y hash exacto de resultados.

```powershell
.\.venv\Scripts\python.exe -B scripts/run_layer4_closure.py --settings config/layer4_closure_definitive.yaml finalize --approval outputs/layer4/pruebas/piloto_v2/cierre_20/final_approval.json --review outputs/layer4/pruebas/piloto_v2/cierre_20/human_review.json
.\.venv\Scripts\python.exe -B scripts/run_layer4_closure.py --settings config/layer4_closure_definitive.yaml verify-final
```

La aprobación incluye supplemental_output_directory para enlazar el cierre
definitivo. Se publica un candidato verificado mediante journal recuperable y
reemplazo atómico. Un journal interrumpido bloquea hasta recuperar por sus hashes.

Único archivo para Capa 5: **outputs/layer4/final/resultado_capa4.xlsx**.
Exactamente dos hojas:

- RESULTADO_INDICADORES: siap_id, indicador_id, estado_cumplimiento,
  parrafo_evidencia, fuente_evidencia, ubicacion_evidencia, confianza.
- TERRITORIOS: siap_id, territory_type, territory_code, code_system.

Todos los estados válidos se conservan sin umbral de confianza. Los territorios
provienen solo de RESOLVED de 4B aceptada, filtrados a estos proyectos. La clave
(territory_type, territory_code, code_system) enlaza la dimensión aceptada.
Códigos como texto; COUNTRY/000 es INTERNAL. No hay nombres, reclasificación de
AMBIGUOUS, nuevo matching ni reconstrucción DANE.

Power BI implementará su selector 0–100 sin modificar datos. La vista principal
parte de SUPPORTED; un umbral nunca convierte insuficiencia en cumplimiento.

## QA y límites históricos

Verificar veinte identidades, todos los candidatos, citas, confianza, procedencia,
idempotencia, territorios, desempeño y dos hojas exactas. Conservar capas 1–3 y
4B byte a byte. Los ZIP antiguos de migración ausentes solo limitan verificadores
históricos que los necesitan y no bloquean esta aceptación si no son sus entradas.
No inventarlos ni alterar hashes. COMPLETE exige ejecución, aceptación y
publicación verificada; de faltar una condición, BLOCKED con causa específica.
