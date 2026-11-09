# Schemas técnicos de assessment y exportación

## Propósito

Define las formas de 4A entre proveedor, validador, perfiles y resultados
reutilizables. La proyección territorial de consumo no cambia la bridge 4B.

## Archivos principales

| Archivo | Qué valida |
|---|---|
| [assessment.schema.json](assessment.schema.json) | Respuesta cerrada del proveedor: decisión, strength, elementos, citas y explicación; sin score generado por LLM. |
| [indicator_profile.schema.json](indicator_profile.schema.json) | Perfil INDICATOR_ASSESSMENT_PROFILE_V2 con originales, elementos, criterios, preferencias explícitas y procedencia de catálogo. |
| [project_indicator.schema.json](project_indicator.schema.json) | Fila técnica PROJECT_INDICATOR con decisión, evidencia alineada, engine y confianza calculada. |
| [project_territory.schema.json](project_territory.schema.json) | Proyección de consumo: código/nombre territorial, departamento y code_system DANE/INTERNAL. |
| [metadata.schema.json](metadata.schema.json) | Estado/engine, versiones de retrieval/assessment/confidence/territorio y generación. |
| [workbook_data.schema.json](workbook_data.schema.json) | Contenedor projects/indicators/territories/metadata usado por el exportador reusable. |

## Funcionamiento

[contracts.py](../../src/layer4/indicators/contracts.py) genera las definiciones.
[assessment.py](../../src/layer4/indicators/assessment.py) complementa schemas con
validación semántica determinística y confidence. El exportador exige formas
consistentes antes de crear las cuatro hojas.

## Entradas y salidas

Datos de transporte y filas técnicas → datos válidos o errores, sin ejecutar
proveedores. Las citas y los IDs se conservan; no se infieren preferencias de
prosa ambigua ni se implementan automáticamente las reglas RULE_TEXT.

## Relación con otras capas

Consume candidatos de Capa 3 y campos de Capa 2; exporta indicadores y la
proyección resuelta de 4B. Los diagnósticos de assessments inválidos pertenecen al
contrato [preliminar](../layer4_preliminary/README.md), no a filas finales válidas.

## Ejecución

Desde la raíz: `uv run python scripts/build_layer4_contracts.py --check`.
Sin --check escribe las definiciones exportables; no realiza assessment.
