## Capa 4: puntos de entrada actuales

- `run_layer4_pilot_discovery_v3_3.py verify --project PROJ_20456`: verifica sin
  inferencia el descubrimiento completado en `outputs/layer4/pruebas/validacion_v3_3/`.
- El mismo ejecutor mantiene PROJ_21299 preparado; `execute` requiere autorización
  independiente y permite una llamada sin retries ni assessments automáticos.
- `prepare_layer4_consumer_v3_3.py --bundle RUTA --check-only`: valida el futuro
  contrato de dos hojas (seis/cuatro columnas), sin crear ni publicar Excel.
- La reanudación vigente está en `outputs/layer4/auditoria/estado_reanudacion_v3_3.json`.
  No ejecutar helpers históricos para repetir proyectos ni activar propuestas pendientes.

# Scripts y operaciones

Cierre de Capa 4: usar únicamente `run_layer4_experiment.py` con
`config/layer4_final.yaml` para prepare, verify, execute-batch, compare, review,
performance, finalize y verify-final. `audit` diagnostica los históricos sin
inferencia; `performance --historical` genera la línea base real V1. El
[procedimiento único](../docs/methodology/layer4_closure_v2.md) define autorizaciones,
aceptación y bloqueo. `export_layer4_pilot.py` y `export_layer4_powerbi.py` son
exportadores históricos; no publican la salida oficial V2.

## Propósito

Ofrece entrypoints desde la raíz del repositorio. La lógica de negocio vive en
[src](../src/README.md). Los comandos no son equivalentes: algunos solo
comprueban, otros escriben informes y otros reemplazan publicaciones.

## Archivos principales

### Ejecutores y preparación

| Archivo | Función / capa | Tipo | Escritura |
|---|---|---|---|
| [run_layer1.py](run_layer1.py) | ETL de Capa 1; --config y --settings | Operativo | Staging, auditoría, runs y reemplazo de canonical |
| [run_layer2.py](run_layer2.py) | Profile/validate/publish de Capa 2 | Operativo | Profile escribe reportes; validate en memoria; publish reemplaza knowledge y conserva anterior |
| [run_layer3.py](run_layer3.py) | Plan/validate/build/query/evaluate/verify/compare/test/setup-model/approve | Operativo | Plan solo configuración; otros modos pueden escribir reportes, configuración o publicación |
| [prepare_layer4_inputs.py](prepare_layer4_inputs.py) | Verifica preparación de 4A, sin seleccionar muestra | Operativo de preparación | Metadata e inputs preparados; sin LLM/workbook real |
| [run_layer4_preliminary.py](run_layer4_preliminary.py) | Etapas --prepare, --execute, --finalize, --verify de 4A | Provisional | Prepare selecciona/escribe; execute llama Codex CLI; finalize exporta; verify no publica |
| [run_territories.py](run_territories.py) | Caracterización 4B de todos los PROJECT | Operativo | Reemplaza outputs/layer4/territorios/publicacion con archivo previo y rollback |

**Operaciones grandes:** run_layer3 --mode setup-model descarga pesos y calibra GPU;
--mode build puede generar embeddings, índices y candidatos. Run_layer1,
run_layer2 --mode publish y run_territories generan nuevas publicaciones.
No ejecutar estos comandos para comprobar enlaces o documentación.

### Constructores de contratos y referencias

| Archivo | Función / capa | Tipo | Escritura |
|---|---|---|---|
| [build_contracts.py](build_contracts.py) | Contratos de Capa 1 y plantilla histórica vacía | Mantenimiento | Reescribe schemas, diccionario CSV y plantilla; no tiene --check |
| [build_layer2_contracts.py](build_layer2_contracts.py) | Schemas de Capa 2 | Mantenimiento | Sin --check los escribe; con --check solo compara |
| [build_layer3_contracts.py](build_layer3_contracts.py) | Schemas activos de embeddings, consultas, manifest y SOURCE | Mantenimiento | Sin --check los escribe; con --check solo compara; no regenera la reserva indicator_profile |
| [build_layer4_contracts.py](build_layer4_contracts.py) | Schemas técnicos de assessment y preliminar | Mantenimiento | Sin --check escribe; con --check compara; no genera confidence |
| [build_dane_reference.py](build_dane_reference.py) | Referencia territorial de Capa 1; --source / --output | Operativo independiente | Dimensión/índices/manifest y snapshots versionados; requiere XLSX autorizado |
| [build_indicator_assessment_profiles.py](build_indicator_assessment_profiles.py) | Perfiles/reglas desde catálogo v2 de 4A | Operativo de preparación | Referencias procesadas y snapshot del catálogo; sin assessment |

### Verificadores

| Archivo | Función / capa | Tipo | Escritura |
|---|---|---|---|
| [verify_layer1.py](verify_layer1.py) | Aceptación de Capa 1; con --existing compara dos publicaciones existentes | Verificador | Escribe reportes; **sin --existing ejecuta ETL dos veces** |
| [verify_layer2.py](verify_layer2.py) | Contratos, upstream, privacidad e idempotencia de knowledge | Verificador histórico | Escribe acceptance.json; requiere baseline y dos publicaciones compatibles |
| [verify_territories.py](verify_territories.py) | Publicación 4B, calidad, workbook, idempotencia y baseline protegido | Verificador | Read-only; imprime informe |
| [territory_integrity.py](territory_integrity.py) | Fingerprint de publicaciones y archivos protegidos de Capas 1–3 | Auxiliar de aceptación | Read-only; imprime JSON; la redirección del usuario puede guardarlo |

También verifican sin invocar LLM: run_layer4_preliminary --verify y el
[verificador auxiliar de preparación](auxiliary/README.md). Run_layer3 --mode
verify/compare **sí escriben reportes**. Un verificador histórico no concede
aceptación al código migrado ni autoriza rebajar hashes.

### Exportadores

| Archivo | Función / capa | Tipo | Escritura |
|---|---|---|---|
| [export_layer4_powerbi.py](export_layer4_powerbi.py) | Proyección del preliminar verificado a consumo Power BI | Operativo específico | CSV/XLSX/spec/manifest en destino nuevo; --repair-territories modifica artefactos existentes bajo supuestos históricos |
| [render_layer4_powerbi.mjs](render_layer4_powerbi.mjs) | Render de una especificación de consumo ya validada | Auxiliar Node | XLSX y preview; requiere Artifact Tool externo, sin fallback propio |
| [render_layer4_workbook.mjs](render_layer4_workbook.mjs) | Render reusable de cuatro hojas, sin selección ni proveedor | Auxiliar Node | XLSX y previews; el llamador Python ofrece fallback openpyxl |
| [render_territory_workbook.mjs](render_territory_workbook.mjs) | Render territorial de hojas/datos preparados | Auxiliar Node | XLSX, QA y previews opcionales; el llamador Python ofrece fallback openpyxl |

Los renderizadores reciben argumentos posicionales: especificación JSON y destino
XLSX; el territorial admite además directorio de previews. Son auxiliares de
Python: no validan por sí solos la procedencia o aceptación de una publicación.
No requieren un proyecto npm en este repositorio.

### Herramientas auxiliares

[auxiliary](auxiliary/README.md) contiene auditorías de identidad, preparación de
revisión humana SOURCE-level y verificación histórica de preparación de Capa 4.
No forman parte de la secuencia operacional obligatoria.

## Funcionamiento

CLI → módulo de src → validación/gates → cálculo o publicación → resultado agregado.
Cada script resuelve la raíz desde su ubicación; auxiliary usa un nivel adicional.
Los scripts eliminados de la raíz no son entrypoints actuales.

## Entradas y salidas

Configuración YAML, fuentes autorizadas, snapshots con manifest y referencias
versionadas. Las salidas operativas están en data/outputs privados; los
constructores de contratos también pueden escribir archivos versionados.

## Relación con otras capas

Cada ejecutor llama a su capa. Territorios utiliza Capa 2 + DANE, sin Capa 3.
El preliminar usa candidatos congelados y el adaptador provisional; los
exportadores consumen resultados validados sin repetir assessment.

## Ejecución

Consultar [README principal](../README.md#ejecución-paso-a-paso) para orden,
aprobaciones y comandos completos. Ejecutar --help solo en scripts que lo
implementan; no asumir que todos tienen argparse o un modo de solo verificación.
