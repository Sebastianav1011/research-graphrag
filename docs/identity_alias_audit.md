# Auditoría de aliases de identidad — 2026-10-05

La revisión reconstruyó los candidatos exclusivamente desde la procedencia del canonical
oficial y reprodujo exactamente sus asignaciones researcher_id y estados.
No se modificó el resolver, la normalización ni la configuración; no se republicó canonical.

## Significado confirmado

- id_empleado ≡ id_investigador: nombres del mismo atributo institucional personal,
  representado como institutional_id en el contrato vigente.
- cedula_empleado ≡ cedula_investigador: nombres del mismo documento personal,
  representado como document_number cuando esté configurado en una fuente.
- researcher_id: llave técnica canónica generada por el pipeline, distinta del identificador
  institucional de origen. No se renombran archivos, datasets ni columnas canónicas.

## Comportamiento encontrado

No existen namespaces separados para id_empleado e id_investigador. normalize_record
deduplica sus valores normalizados en un único conjunto de evidencia institutional_id.
El resolver usa tokens (institutional_id, valor), sin el nombre de la columna original.
Mismo valor en ambas columnas o en filas distintas produce una identidad resuelta única.
Coexistir con valores iguales no produce conflicto. Si ambas copias contienen valores
distintos, la política vigente conserva una contradicción del mismo atributo, deja el
institutional_id escalar NULL en esa ocurrencia y bloquea la fusión del componente.
No se considera que esas copias discrepantes representen dos personas confirmadas.

Los nombres cedula_empleado y cedula_investigador no aparecen en las fuentes de las
ocurrencias publicadas. Se comprobó con datos sintéticos que ambos pueden mapearse al
mismo document_number. Las fuentes actuales siguen usando documento y cedula según config.

## Evidencia actual de miembros

| Presencia de aliases | Ocurrencias |
| --- | ---: |
| Ambos iguales tras normalización | 1990 |
| Ambos distintos tras normalización | 5447 |
| Solo id_empleado | 213 |
| Solo id_investigador | 4250 |
| Ninguno | 126 |

La equivalencia semántica declarada no se cumple materialmente en 5447 filas del archivo
actual: las dos columnas contienen valores diferentes incluso tras retirar el artefacto
de comillas. La auditoría no determina qué transformación introdujo esos valores.

## Causa de las ambigüedades

- 21637 ocurrencias: componentes conectados por coincidencias exactas que contienen
  valores contradictorios de institutional_id/document_number y, en algunos casos, document_type.
- 31 ocurrencias: nombres repetidos sin corroboración suficiente.

Un único componente contiene 21348 ocurrencias, 2670 valores institucionales,
2637 documentos y 6 tipos documentales. Los valores discrepantes actúan como puentes;
la política conservadora vigente bloquea el componente completo, propagando el estado
ambiguous a sus ocurrencias. Los otros 25 componentes contradictorios reúnen 289 ocurrencias.

Como diagnóstico en memoria, ignorar completamente id_investigador reproduce 3271 resolved,
1422 ambiguous y 3089 unresolved. Esto demuestra el impacto de la evidencia añadida;
no demuestra que descartar ese alias sea correcto, pues también elimina las 4250
ocurrencias donde es el único identificador institucional. No se publicó ese contrafactual.

## Resultado

Conforme a la instrucción de conservar identidad si no se encontraron IDs independientes,
se mantienen 574 resolved, 21668 ambiguous y 95 unresolved. No se eligió arbitrariamente
una copia discrepante ni se intentó reducir los ambiguos.
30 tests existentes de identidad/dominio aprobados, además de comprobaciones sintéticas
de coexistencia, alias único y aliases documentales en el script de auditoría.
SHA-256 de fuentes, catálogo y todos los archivos de canonical iguales antes/después.

Evidencia privada agregada: outputs/layer1/reports/identity_alias_audit.json.
Reproducción: uv run python scripts/audit_identity_aliases.py. El script solo escribe su informe.
