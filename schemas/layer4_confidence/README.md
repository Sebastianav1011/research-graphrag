# Schemas de confianza RAW_CONFIDENCE_V1

## Propósito

Describe el intercambio mínimo para validar evidencia y calcular un raw score
determinístico independiente de cualquier proveedor.

## Archivos principales

| Archivo | Qué valida |
|---|---|
| [assessment.schema.json](assessment.schema.json) | Decisión, strength, elementos, citas y explicación antes de calcular confianza; permite metadata ignorada. |
| [indicator_profile.schema.json](indicator_profile.schema.json) | Elementos clave y nombres de campos preferidos explícitos; no es el perfil operacional v2 completo. |
| [confidence_result.schema.json](confidence_result.schema.json) | Versión, cuatro estados, K/F/C/S, score 0–100 y errores; probability/level deben ser NULL. |

## Funcionamiento

El schema describe tipos y valores. [confidence.py](../../src/layer4/indicators/confidence.py)
es la autoridad de hard gates: verifica cita literal NFC/whitespace, pertenencia
al catálogo, strength entero y campo sustantivo antes de calcular con Decimal.
Validar solo JSON Schema no comprueba que la evidencia exista.

## Entradas y salidas

Assessment, perfil y campos PROJECT reales → resultado COMPUTED, NOT_APPLICABLE,
NOT_COMPUTABLE o INVALID_ASSESSMENT. La API interna conserva Decimal; el intercambio
JSON representa números y la presentación debe conservar dos decimales.

## Relación con otras capas

Pertenece exclusivamente a 4A. Retrieval nunca entra en la fórmula.
[assessment](../layer4_assessment/README.md) añade identidad/provenance y contratos
de exportación al resultado; no sustituye estos gates.

## Ejecución

No tiene CLI generador propio. Se comprueba mediante
`python -B -m pytest tests/layer4_confidence -q -p no:cacheprovider`.
La configuración es [layer4_confidence.yaml](../../config/layer4_confidence.yaml).
