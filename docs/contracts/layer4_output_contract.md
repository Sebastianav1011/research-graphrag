# Salida vigente del flujo autónomo

La plantilla y proyección vigentes están en [final_output_contract.md](final_output_contract.md).
Los contratos siguientes describen cierres históricos y no controlan la salida autónoma actual.

# Contrato de salida Capa 4

## Preparado: LAYER4_CONSUMER_V3_3_V1 (todavía no publicado)

Exactamente dos pestañas y columnas en el siguiente orden:

| Pestaña | Columnas |
|---|---|
| RESULTADO_INDICADORES | siap_id, indicador_id, parrafo_evidencia, fuente_evidencia, ubicacion_evidencia, confianza |
| TERRITORIOS | siap_id, territory_type, territory_code, code_system |

`estado_cumplimiento` no se exporta. SUPPORTED, INSUFFICIENT_EVIDENCE,
NOT_SUPPORTED e INVALID permanecen en los registros internos y en la auditoría.
Son elegibles únicamente pares priorizados por el discovery V3.3 vigente con
assessment VALID y SUPPORTED, identidad única, contrato ASSESSMENT_V3, citas y
ubicaciones verificables y confianza igual al cálculo determinista almacenado.
Las evidencias parciales pertinentes se conservan internamente; no equivalen a
cumplimiento demostrado ni se eliminan para mejorar estadísticas. No hay umbral
de confianza. Un assessment faltante/inválido de un priorizado bloquea el cierre.
Un proyecto con cero priorizados es analizado sin inventar filas.

La confianza permanece `100 × (0.55S + 0.45K)` y no es una probabilidad.
`siap_id` y códigos territoriales son texto; COUNTRY/000 es INTERNAL y las claves
DANE aceptadas se preservan. Evidencia, fuente y ubicación mantienen correspondencia
numerada, cita literal, section_id y coordenadas verificadas.

`src/layer4/indicators/consumer_v3_3.py` prepara una especificación de workbook y
una auditoría separada sin escribir Excel. El verificador de un bundle completo es:

```powershell
.\.venv\Scripts\python.exe -B scripts/prepare_layer4_consumer_v3_3.py --bundle RUTA_BUNDLE.json --check-only
```

El bundle explícito contiene `consumer_contract`, `projects` (los veinte), `rows`,
`profiles` (48), `rubrics`, `selections` (respuestas V3.3 por proyecto), `territories`
(dimensión y relaciones aceptadas) y `source_hashes` para verificar procedencia.
Debe consolidarse desde resultados válidos y reutilizaciones compatibles, sin
reescribir respuestas ni decisiones. No existe aún un bundle final aprobado.
El modo parcial de la función se reserva para diagnóstico/pruebas; no autoriza
publicación. El verificador no crea un Excel ni sustituye el gate de aceptación
ni la publicación atómica. La integración final de publicación exige completar
las entradas y aprobación expresa; no activar el exportador V2 de siete columnas
para publicar este contrato nuevo.

## Compatibilidad con la publicación vigente

`outputs/layer4/final/resultado_capa4.xlsx` sigue siendo V2 y conserva sus siete
columnas originales. Los consumidores actuales deben mantener esa lectura hasta
una migración explícita. Véase [Power BI](layer4_powerbi_contract.md).

## Referencia histórica V2/V1

El texto anterior se conserva como referencia de su versión, no como el contrato
futuro de seis columnas:

# Salida oficial de Capa 4 y contratos técnicos históricos

## Contrato activo de cierre V2

Única ruta consumible por Capa 5: `outputs/layer4/final/resultado_capa4.xlsx`.
Solo se publica tras completar veinte proyectos, validar los resultados efectivos
y aceptar explícitamente su calidad y confianza. No existe publicación parcial
oficial. Se usa `scripts/run_layer4_closure.py --settings config/layer4_closure_definitive.yaml finalize --approval ... --review ...`
y `scripts/run_layer4_closure.py --settings config/layer4_closure_definitive.yaml verify-final`, sin reconstruir capas anteriores.

El archivo contiene exactamente dos hojas, con encabezados en la primera fila:

| Hoja | Columnas |
|---|---|
| RESULTADO_INDICADORES | siap_id, indicador_id, estado_cumplimiento, parrafo_evidencia, fuente_evidencia, ubicacion_evidencia, confianza |
| TERRITORIOS | siap_id, territory_type, territory_code, code_system |

La primera conserva todas las evaluaciones válidas, sus estados independientes y
el respaldo calculado mediante EVIDENCE_CONFIDENCE_V2, sin umbral de exportación.
La segunda consume únicamente relaciones RESOLVED de 4B; sus códigos permanecen
como texto y COUNTRY/000 es INTERNAL. La clave de relación territorial es el triple
tipo+código+sistema, equivalente a la dimensión aceptada, sin nombres ni nuevos IDs.
Las dos hojas se relacionan por el SIAP institucional original.

El [contrato de consumo](layer4_powerbi_contract.md) especifica claves, evidencia,
selector dinámico, temporalidad y límites de interpretación. El [procedimiento
único](../methodology/layer4_closure_v2.md) establece autorización y aceptación.
Las métricas, prompts, manifests y auditorías permanecen privados; no son hojas
del archivo oficial. El reemplazo es atómico, con verificación y journal recuperable.

## Contrato técnico histórico V1 (se conserva sin reinterpretar)

Contrato técnico histórico. La publicación oficial de cierre V2 se rige por
el [procedimiento único](../methodology/layer4_closure_v2.md) y el
[contrato de consumo](layer4_powerbi_contract.md). No se reescriben estos históricos.

Los schemas nuevos están en `schemas/layer4_assessment/`. Este contrato técnico
prepara el preliminar; no genera filas reales ni reescribe la plantilla histórica
`data/templates/resultado_final_indicadores.xlsx` o su aceptación anterior (plantilla histórica).

## PROJECT_INDICATOR_V1

Una fila por PROJECT+INDICATOR evaluado con respuesta válida. Se conservan las
tres decisiones, no solo SUPPORTED. Clave única project_id + indicator_id.

Campos: project_id, indicator_id, indicator_name, indicator_category,
indicator_dimension, decision, support_strength, supported_key_elements,
evidence_source_fields, evidence_texts, evidence_explanation,
key_element_coverage, field_relevance_score, corroboration_score,
support_strength_score, confidence_raw_score, confidence_status,
confidence_version, assessment_engine, assessment_engine_status,
confidence_probability y confidence_level.

Los arrays evidence_source_fields/evidence_texts están alineados, sin concatenar
citas de campos distintos. Probability/level son NULL. No existe retrieval_score
ni un campo de similitud. Los Decimals se serializan como números en este límite;
Excel muestra el raw score con dos decimales. INVALID_ASSESSMENT puede describirse
técnicamente con score NULL, pero la exportación de consumo se bloquea hasta
resolver/reintentar la respuesta inválida; nunca se presenta como SUPPORTED válido.

## PROJECT_TERRITORY_CONSUMPTION_V1

Campos: project_id, territory_type, territory_code, territory_name,
department_code, department_name y code_system. La proyección copia el código
textual de dane_code sin convertirlo a número. No migra ni reescribe los Parquet
o el CSV territorial v1 ya publicados.

- MUNICIPALITY/DEPARTMENT: code_system=DANE; códigos de 5/2 dígitos y padre
  departamental coherente con el prefijo. Nombres tomados de la dimensión.
- COUNTRY/000/Colombia: code_system=INTERNAL; departamento NULL. `000` es una
  convención interna del proyecto, **no un código DANE oficial**.

Las reglas existentes se conservan: con subnacional RESOLVED solo se publica
subnacional; sin subnacional resuelto, una mención nacional válida puede publicar
000. Una mención subnacional AMBIGUOUS jamás se transforma en 000. Si además hay
mención nacional independiente, esta no reemplaza ni oculta la ambigüedad:
permanece el registro técnico con dane_code NULL y el conteo se expone en metadata.
Sin menciones no hay relación. ALCANCE_NACIONAL y las hojas DANE originales no se
modifican en esta preparación. El origen existente USER_DEFINED_COUNTRY equivale
explícitamente a code_system=INTERNAL en consumo.

`consumption_rows` realiza el JOIN con la dimensión, valida códigos/origen y
rechaza ambiguos, duplicados y COUNTRY combinado con subnacionales resueltos.
No infiere departamento padre como una segunda relación.

## Workbook previsto, todavía no ejecutado con datos reales

`export_workbook` recibe datos explícitos ya validados; no selecciona proyectos,
lee corpus ni invoca proveedores. Generará en la siguiente tarea
`resultado_preliminar_20_proyectos.xlsx` cuando esa tarea lo ejecute.
En esta preparación se llama únicamente desde tests con fixtures sintéticos.

| Hoja | Granularidad |
|---|---|
| PROYECTOS | Una fila por project_id, con sus seis campos separados. |
| INDICADORES | Una fila por PROJECT+INDICATOR evaluado y validado. |
| TERRITORIOS | Una fila por PROJECT+TERRITORY RESOLVED; nunca AMBIGUOUS. |
| METADATA | Versiones, hashes y estado real de ejecución. |

El generador verifica claves únicas, foreign keys, project_count, máximo dos
candidatos por proyecto, alineación de evidencia, citas y coincidencia del score
con el recálculo de RAW_CONFIDENCE_V1 usando el perfil explícito. No acepta scores
inyectados. Conserva el maestro PROJECT sin expandirlo por indicadores/territorios.
No sobrescribe un workbook existente. Usa Artifact Tool offline cuando está
disponible y openpyxl únicamente como fallback si ese runtime no existe.

## Metadata

Claves obligatorias: output_status, project_count, candidate_limit_per_project,
layer3_run, retrieval_indicator_version, assessment_indicator_version,
assessment_indicator_sha256, assessment_engine, assessment_engine_status,
confidence_version, confidence_is_probability, territory_version,
dane_reference_sha256, country_internal_code, country_internal_code_system y
generated_at. El hash de DANE identifica el XLSX autorizado; los manifests
técnicos conservan adicionalmente la identidad de su dimensión normalizada.

Se añaden planned_project_count y los conteos territory_ambiguous_mentions y
territory_ambiguous_projects para conservar visibilidad de los diagnósticos.
Durante preparación: output_status=PREPARED_NOT_EXECUTED, project_count=0,
planned_project_count=20, engine=UNCONFIGURED y status=NOT_EXECUTED. No hay IDs
seleccionados. confidence_is_probability=false, country_internal_code='000',
country_internal_code_system=INTERNAL. Los tests usan SYNTHETIC_TEST, nunca un
estado que aparente un resultado preliminar real.
