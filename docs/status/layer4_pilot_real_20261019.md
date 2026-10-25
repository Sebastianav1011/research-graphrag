# Piloto real integrado de Capa 4 — 2026-10-19

La infraestructura de 4A está implementada. El piloto está ejecutado y sus ocho
respuestas superan validación automática. La revisión humana, el benchmark, la
calibración y la aceptación final de 4A permanecen pendientes. La publicación
territorial de 4B conserva su aceptación previa y no se ejecutó de nuevo.

## Alcance y ejecución

Se conservaron byte por byte el manifest de selección de 50 proyectos y 77
candidatos y el piloto original de cinco proyectos/ocho pares. Solo se procesaron
esos cinco: 20022, 22027, 21410, 22037 y 21457. No se procesaron los otros 45
proyectos ni los 69 pares restantes. Hay cinco llamadas, cero reintentos y cero
assessments inválidos. Se verificó una reanudación posterior: reutilizó las ocho
respuestas y el conteo permaneció en cinco llamadas.

El primer arranque se detuvo antes de inferencia por un fingerprint de features
distinto entre el entorno restringido y el autorizado. La única diferencia
observada fue `daemon_auto_start`: true frente a false. Versión y binario fueron
idénticos. No se modificó el manifest original para forzar su aceptación.

Se fijó una preparación independiente en `outputs/layer4/pruebas/piloto_v2/original_5`,
con `config/layer4_pilot.local.yaml`, conservando 50/77 y la misma selección
SHA256 `c0f35cbed13d0681e561f01aae528ec14e03447137429a7176a6f05b845fdc78`.
La configuración solo cambia el directorio de salida. Debe usarse para continuar
posteriormente y aprovechar las respuestas reales guardadas. La preparación
anterior permanece en `experiment_50`, como constancia de preparación previa.

Los fingerprints y el diagnóstico del cambio de contexto están en
`outputs/layer4/auditoria/historicos/diagnostico_runtime/context_transition.json`. Las auditorías
del nuevo run se fijaron desde el mismo entorno autorizado utilizado al ejecutar.
La verificación de algunos archivos históricos requiere ese contexto de acceso;
un error de permisos en el entorno restringido no autoriza omitir hashes.

## Autorización registrada

La constancia utilizada fue la declaración del usuario «si sin problema» en esta
conversación, en respuesta a la pregunta específica sobre la autorización
institucional de los textos para el proveedor de Codex CLI. Se registró como
confirmación del usuario, distinta de la aprobación general del flujo.

No se recibió un documento institucional formal ni se verificó documentalmente
el rol o representación del declarante. La auditoría registra esa limitación y
no inventa un número de resolución, responsable institucional o fecha de concesión.
La fecha del archivo corresponde al registro de la declaración. Su scope es
exclusivamente pilot, cinco proyectos/ocho pares; no autoriza los 69 restantes.
Constancia privada: `outputs/layer4/auditoria/historicos/experimento_50/authorization.pilot.user_attestation.json`.

## Resultados

| SIAP | Indicador | Decisión propuesta | Strength | K | F | C | S | Raw |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 20022 | ASC-01 | SUPPORTED | 4 | 1 | 1 | 1 | 1 | 100 |
| 22027 | SAL-01 | NOT_SUPPORTED | 0 | — | — | — | — | NULL |
| 22027 | SAL-02 | NOT_SUPPORTED | 0 | — | — | — | — | NULL |
| 21410 | DIV-01 | INSUFFICIENT_EVIDENCE | 2 | — | — | — | — | NULL |
| 21410 | DIV-02 | INSUFFICIENT_EVIDENCE | 2 | — | — | — | — | NULL |
| 22037 | COL-01 | SUPPORTED | 4 | 1 | 1 | 0.70 | 1 | 94 |
| 21457 | ECO-07 | INSUFFICIENT_EVIDENCE | 2 | — | — | — | — | NULL |
| 21457 | SOC-02 | INSUFFICIENT_EVIDENCE | 2 | — | — | — | — | NULL |

Son dos SUPPORTED, cuatro INSUFFICIENT_EVIDENCE y dos NOT_SUPPORTED. Dos scores
son computables: mínimo 94, media 97 y máximo 100. Las otras seis celdas son NULL,
no cero. La fórmula continúa siendo 100 × (0.35K + 0.30F + 0.20C + 0.15S), con
Decimal y ROUND_HALF_UP según el contrato congelado. Los scores altos reflejan
elementos declarados y evidencia estructurada; no prueban validez semántica ni
100 % de acierto. La pertenencia de elementos y las citas literales se verifican
determinísticamente; su implicación semántica requiere revisión independiente.

Tres relaciones RESOLVED cubren tres proyectos: DEPARTMENT/11/BOGOTA para 20022
y 22037; MUNICIPALITY/05001/MEDELLIN para 21410, con metadatos del departamento
ANTIOQUIA/05. No hay COUNTRY en esta muestra y no se añade como fallback. 22027 y
21457 no tienen territorio resuelto. Hay ocho menciones de evidencia territorial
y cero menciones AMBIGUOUS para estos cinco proyectos. No se confunden menciones,
relaciones y proyectos, ni se convierte un departamento contextual de la dimensión
en una relación adicional no publicada.

## Tecnología y consumo observable

Se usó exclusivamente el adaptador Codex CLI existente, versión 0.163.0, con la
interfaz no interactiva, schema, cwd aislado, sandbox read-only, configuración
personal/rules ignorada y herramientas restringidas. El código de inferencia,
los perfiles, prompts y reglas de confianza preparados no se modificaron.

La CLI no reportó un identificador verificable de modelo en los eventos ni en
stderr. Se conserva modelo solicitado NULL y modelo efectivo no observado; no se
deduce a partir del agente de desarrollo o de configuración personal ignorada.

Los cinco eventos turn.completed informaron, en conjunto, 79.839 input_tokens y
1.695 output_tokens. Los valores se conservan por llamada, sin atribuirlos a cada
indicador ni estimar costos monetarios. Los campos de cache y reasoning informados
fueron cero. No son estimaciones ni consumo de Capas 1–3.

Se conservaron dos avisos de arranque por llamada: feature experimental
skip_host_skill_discovery y Code Mode inhabilitado por code_mode_host=false.
No se habilitaron herramientas para silenciarlos. Los cinco procesos terminaron
con retorno cero, respuesta estructurada válida y sin uso operativo de herramientas.

## Entrega y evidencia privada

La carpeta `outputs/layer4/auditoria/historicos/entrega_piloto_5` tiene exactamente tres archivos:

- `resultado_capa4.xlsx`: dos hojas, ocho decisiones válidas y tres territorios;
- `resumen_resultados.md`: conteos, confianza, ejemplos reales y límites;
- `README.md`: interpretación, arquitectura y reproducción breve.

Para esta entrega, conforme a la última solicitud, parrafo_evidencia combina la
explicación original de la LLM y sus citas literales intactas; fuente_evidencia
identifica los campos y ubicacion_evidencia declara campo, offsets y sistema de
coordenadas en lenguaje legible. El ID técnico de sección queda en la auditoría
privada. No se cambia el assessment original ni su contrato de evidencia.
La proyección técnica histórica de Power BI permanece sin reescribir. La nueva
proyección de presentación está versionada como LAYER4_PILOT_INTEGRATED_DELIVERY_V1.

Los nombres y el orden de las siete columnas de cada hoja son exactamente los
solicitados. No se añaden PII, tablas de investigadores, prompts completos,
probabilidades ni factores técnicos al Excel de consumo. La trazabilidad y las
menciones ambiguas se mantienen fuera de la carpeta de entrega.

Los directorios privados `experiment_50_pilot/records`, `codex_runs`, `exports`
y `pilot_delivery` contienen respuestas originales, prompts, eventos, hashes,
validaciones, workbook de revisión humana y manifests. El archivo
`pilot_delivery/latest_manifest.json` identifica la entrega vigente y sus hashes;
`pilot_delivery/acceptance_verification.json` registra las comprobaciones finales.

## Reproducción y controles

Desde la raíz, usando el contexto de acceso que puede leer todos los artefactos
históricos protegidos:

```powershell
.\.venv\Scripts\python.exe -B scripts/run_layer4_experiment.py --config config/layer4_pilot.local.yaml verify
.\.venv\Scripts\python.exe -B scripts/export_layer4_pilot.py
.\.venv\Scripts\python.exe -B scripts/verify_layer4_pilot_delivery.py
```

Estos comandos no infieren. La reanudación autorizada del mismo piloto usa
execute-batch --stage pilot con su constancia y recupera las respuestas compatibles.
No crear aprobación de continuación ni lanzar stage continue antes de revisar el
piloto. La aprobación deberá vincular el hash de resultados del piloto, disponible
en progress.json. Los libros de revisión mantienen etiquetas humanas vacías.

Se ejecutaron siete pruebas sintéticas del exportador, incluida conservación de
citas, explicaciones, offsets, NULL, territorios independientes de inferencia,
selección fija y tipos string del workbook. Se revalidaron las seis pruebas de
lógica tras la última mejora de presentación. Los ocho checks históricos siguen
bloqueados por los ZIP pre_namespace_migration.zip y pre_layer1_unification.zip
ausentes; no se modifican para hacerlos pasar.

Las publicaciones y código de Capas 1–3 y 4B, referencias, perfiles y el preliminar
de 20 proyectos se verifican mediante los baselines fijados. No hubo commit ni
push. La recomendación técnica es que la infraestructura permite continuar, pero
primero deben revisarse los ocho casos, especialmente los dos SUPPORTED con raw
alto, y aprobarse expresamente el siguiente alcance. No se afirma aceptación final.
