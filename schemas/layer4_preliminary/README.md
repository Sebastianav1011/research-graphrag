# Schemas del preliminar técnico

## Propósito

Mantiene separado el transporte por proyecto de las filas diagnósticas de un
assessment provisional, incluidas respuestas inválidas que no son asignaciones.

## Archivos principales

| Archivo | Qué valida |
|---|---|
| [assessment_batch.schema.json](assessment_batch.schema.json) | Envoltorio project_id + assessments y formas de respuesta exigidas al adaptador provisional. |
| [project_indicator_preliminary.schema.json](project_indicator_preliminary.schema.json) | Fila técnica con assessment_validation_status y validation_errors, además de decisión, evidencia, engine y confianza. |

## Funcionamiento

El runner prepara requests → el adaptador devuelve un batch → los validadores
contrastan IDs, citas y gates → preliminary_output produce filas/diagnósticos.
Un INVALID_ASSESSMENT conserva errores y raw score NULL; no se rescata como
asignación bajando el score.

## Entradas y salidas

JSON estructurado y filas del preliminar → validación de transporte/exportación.
Los archivos persisted del run viven en outputs/layer4/preliminary_20, privados;
estos JSON son contratos versionados, no respuestas de proyectos reales.

## Relación con otras capas

Extiende las formas de [assessment](../layer4_assessment/README.md) para revisión
técnica. No modifica SOURCE_INDICATOR_V1 ni implica evaluación final/calibración.

## Ejecución

`python scripts/build_layer4_contracts.py --check` comprueba las formas generadas.
El runner usa etapas separadas descritas en
[indicadores](../../src/layer4/indicators/README.md).
