# Herramientas auxiliares

## Propósito

Agrupa auditorías y revisión histórica fuera de los entrypoints operativos.
Su uso requiere los datos y fingerprints que espera cada herramienta.

## Archivos principales

| Archivo | Responsabilidad | Capa / efecto |
|---|---|---|
| [audit_identity_aliases.py](audit_identity_aliases.py) | Audita interpretación de aliases a partir de provenance y compara resolución | Capa 1; escribe reportes privados, no publica canonical |
| [audit_identity_alias_forensics.py](audit_identity_alias_forensics.py) | Reproduce parsing/identidad en memoria y explica discrepancias de aliases | Capa 1; lee fuentes autorizadas y escribe reportes forenses privados |
| [create_source_level_review_workbook.py](create_source_level_review_workbook.py) | Prepara revisión humana PROJECT+INDICATOR con candidatos históricos y catálogo v2; deja decisiones humanas vacías | Capas 3/4; escribe workbook y previews, sin assessment |
| [verify_layer4_preparation.py](verify_layer4_preparation.py) | Reconcilia acta de preparación, referencias, integración de confidence, JUnit y contratos | Capa 4; read-only respecto a publicaciones; invoca contract checks |

## Funcionamiento

Las auditorías cargan mapping/provenance y producen diagnóstico sin sustituir
tablas canónicas. El workbook cruza candidatos R8, campos de Capa 2 y catálogo
v2. Conserva su guard estricto de code_hashes R8: el código reorganizado puede
bloquear su ejecución; no debilitarlo ni modificar manifests históricos.

El verificador de preparación comprueba el cierre histórico aceptado y sus
originales archivados; no exige que un preliminar posterior deje de existir.
No representa aceptación nueva del código actual.

## Entradas y salidas

Fuentes o canonical para auditorías; snapshots Capa 2/3 y catálogo para revisión;
actas/baselines/JUnit locales para preparación. Outputs privados bajo outputs.
No subir los reportes: pueden contener información institucional.

## Relación con otras capas

Ayudan a diagnosticar Capa 1 y revisar evidencias de Capas 3/4. No sustituyen el ETL,
retrieval, assessment, benchmark final ni pipeline territorial.

## Ejecución

Verificación histórica, sin llamar a un proveedor:

```powershell
python scripts/auxiliary/verify_layer4_preparation.py
```

Para el workbook, inspeccionar primero
`python scripts/auxiliary/create_source_level_review_workbook.py --help`.
Admite --output, --preview-dir y --replace-unreviewed; este último solo reemplaza
un generado sin decisiones humanas. Puede necesitar Node y Artifact Tool externo;
ARTIFACT_TOOL_NODE_MODULES configura los módulos y REVIEW_WORKBOOK_NODE el ejecutable.
No ejecutarlo automáticamente como paso de instalación.
