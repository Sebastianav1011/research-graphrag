# Clonar y ejecutar — Windows / PowerShell

Para el cierre actual de Capa 4, seguir el [procedimiento único V2](methodology/layer4_closure_v2.md).
Define prepare/verify, autorización, piloto/lotes, comparación, revisión, desempeño
y finalize/verify-final. Los procedimientos de preliminares o pilotos V1 conservados
en este documento son históricos y no publican el único workbook oficial V2.

La raíz es el directorio del clon, sin rutas específicas del usuario.
El gestor oficial es uv; véase [instalación](instalacion.md) y el Inicio rápido
del [README](../README.md). Las secciones metodológicas posteriores conservan
los procedimientos históricos y sus prerrequisitos; no son una instalación nueva.

## 1. Clon, Python y entorno

```powershell
git clone https://github.com/Sebastianav1011/research-graphrag.git
cd research-graphrag
uv sync
uv run python run.py
```

Python 3.14.0 queda fijado en `.python-version`. `uv.lock` fija el runtime,
pruebas y grupos opcionales para las plataformas declaradas; no se necesita
activar `.venv`. No instalar manualmente las dependencias transitivas.
Los locks y requirements anteriores se conservan por compatibilidad.
Para una instalación existente usar `uv sync --inexact` si se desea conservar
paquetes adicionales ajenos al proyecto. No se eliminan entornos ni datos.

## 2. Datos que no vienen con Git

Obtén del grupo los archivos autorizados, sin crear sustitutos institucionales:

- data/raw/proyectos/descriptores-limpio.csv
- data/raw/articulos/produccion-limpio.csv
- data/raw/investigadores/miembros-doc-limpio.csv
- data/reference/indicadores/catalogo_indicadores.xlsx (hoja Catalogo_Indicadores)

Esas son las rutas por defecto de sources.example. Si usarás otras rutas,
edita únicamente config/sources.yaml (local, ignorado por Git). La plantilla
vacía data/templates/plantilla_resultado_final_indicadores_territorios.xlsx sí está permitida en Git.

```powershell
$inputs = @('data/raw/proyectos/descriptores-limpio.csv','data/raw/articulos/produccion-limpio.csv','data/raw/investigadores/miembros-doc-limpio.csv','data/reference/indicadores/catalogo_indicadores.xlsx')
$inputs | ForEach-Object { if (-not (Test-Path -LiteralPath $_)) { throw "Falta input autorizado: $_" } }
```

Para reproducir solo Capa 3, pide el snapshot completo data/knowledge y su
_manifest.json, sin copiar RAW/STAGING. Sus ocho Parquet son source_documents,
source_sections, source_chunks, reference_documents, reference_sections,
reference_chunks, entities y relations. No mezcles tablas de runs diferentes.
Puedes omitir las operaciones de Capas 1–2 de la siguiente sección si consumes
ese snapshot aprobado. Para regresiones de Capa 2 también se necesita canonical
oficial; la integración valida su lineage, no modifica esos datos.

## 3. Capas 1–2 desde inputs autorizados

Esta ruta crea nuevas publicaciones upstream. No la ejecutes para reemplazar
un snapshot ya congelado si tu objetivo es solo trabajar Capa 3.

```powershell
uv run python scripts/run_layer1.py --config config/sources.yaml --settings config/layer1.yaml
uv run python scripts/run_layer1.py --config config/sources.yaml --settings config/layer1.yaml
uv run python scripts/verify_layer1.py --existing
uv run python -B -m pytest tests/layer1 -q -p no:cacheprovider
Get-Content data/canonical/_manifest.json | ConvertFrom-Json | Select-Object run_id,status
```

Antes de Capa 2 verifica SUCCESS del manifest canonical y acepta explícitamente
su hash en el gate existente. Este comando actualiza solo ese campo de config:

```powershell
$canonicalHash = (Get-FileHash data/canonical/_manifest.json -Algorithm SHA256).Hash.ToLowerInvariant()
$env:APPROVED_LAYER1_SHA256 = $canonicalHash
python -c "import os,yaml; from pathlib import Path; p=Path('config/layer2.yaml'); c=yaml.safe_load(p.read_text(encoding='utf-8-sig')); c['readiness']['approved_layer1_manifest_sha256']=os.environ['APPROVED_LAYER1_SHA256']; p.write_text(yaml.safe_dump(c,sort_keys=False),encoding='utf-8')"
uv run python scripts/run_layer2.py --mode profile
uv run python scripts/run_layer2.py --mode validate
uv run python scripts/run_layer2.py --mode publish
uv run python scripts/run_layer2.py --mode publish
$env:LAYER2_REAL_INTEGRATION='1'
$env:LAYER2_VERIFY_PUBLICATION='1'
uv run python -B -m pytest tests/layer2 -q -p no:cacheprovider
Get-Content data/knowledge/_manifest.json | ConvertFrom-Json | Select-Object layer2_run_id,status
```

El gate no aprueba una publicación fallida ni omite validaciones de outputs,
schemas, hashes, privacidad o chunking. No cambies contratos o 220/340/20 para
hacer pasar un snapshot incompatible. Los manifests upstream deben decir SUCCESS.

## 4. Aprobar y validar Capa 3

```powershell
$knowledgeFiles = @('_manifest.json','source_documents.parquet','source_sections.parquet','source_chunks.parquet','reference_documents.parquet','reference_sections.parquet','reference_chunks.parquet','entities.parquet','relations.parquet')
$knowledgeFiles | ForEach-Object { if (-not (Test-Path -LiteralPath "data/knowledge/$_")) { throw "Falta tabla publicada: $_" } }
$knowledgeHash = (Get-FileHash data/knowledge/_manifest.json -Algorithm SHA256).Hash.ToLowerInvariant()
uv run python scripts/run_layer3.py --mode approve --manifest-sha256 $knowledgeHash
uv run python scripts/run_layer3.py --mode validate
```

approve valida físicamente todos los archivos/schema/lineage antes de escribir
el hash en config/layer3.yaml. No elimina gates. validate no genera embeddings.
Si existe .publish.lock o publication_pending.json, resuelve la publicación
interrumpida con su journal antes de iniciar otro writer; nunca borres a ciegas
el lock de un proceso vivo o previous_graphrag requerido para rollback.

## 5. Modelo local y construcción

Pesos/config/tokenizer se ubican en outputs/layer3/models/bge-m3/
5617a9f61b028005a4858fdac845db406aefb181. No vienen con Git. Puedes recibir una
copia verificada del grupo o ejecutar la preparación explícita siguiente:

```powershell
uv run python scripts/run_layer3.py --mode setup-model
uv run python scripts/run_layer3.py --mode build
uv run python scripts/run_layer3.py --mode verify
```

setup-model descarga el modelo público fijado, verifica el SHA de los pesos,
registra hardware, tokeniza TODOS los chunks sin truncación y calibra batch con
el chunk más largo. No envía textos institucionales a una API. Es una operación
explícita y grande (~2,3 GB de pesos), para GPU CUDA en el camino principal.
No hace falta repetirla al reconstruir retrieval si el modelo/config son válidos.

Cada build conserva el snapshot exacto de config, usa candidate → validación →
roundtrip → hashes → swap/journal/rollback, y reutiliza bundles/cache compatibles.
No redivide textos, no genera embeddings de documentos completos y no ejecuta LLM.

## 6. Dos builds e idempotencia

```powershell
uv run python scripts/run_layer3.py --mode build
uv run python scripts/run_layer3.py --mode compare
uv run python scripts/run_layer3.py --mode verify
uv run python scripts/run_layer3.py --mode query --query "restauración ambiental y biodiversidad" --retrieval-mode hybrid
uv run python scripts/run_layer3.py --mode test --real-integration
uv run python scripts/build_layer3_contracts.py --check
```

compare requiere dos builds con mismo manifest/model/config; compara candidatos,
discovery mappings, contextos, ranks, grafo y embeddings (atol=1e-6, rtol=0).
Run IDs, timestamps y tiempos operacionales pueden cambiar. Las queries guardan
su paquete privado en outputs/layer3/reports y stdout muestra IDs/conteos.
GRAPH-only exige seeds explícitos mediante --seed-entity; no uses labels como seeds.

Comprueba la publicación activa y los reportes:

```powershell
Get-Content data/graphrag/_manifest.json | ConvertFrom-Json | Select-Object layer3_run_id,status,candidate_architecture,candidate_count,context_package_count
Get-Content outputs/layer3/reports/source_publication_verification.json | ConvertFrom-Json | Select-Object status,layer3_run_id
Get-Content outputs/layer3/reports/idempotence.json | ConvertFrom-Json | Select-Object status,builds
Get-ChildItem outputs/layer3/reports/*source_regression.xml
```

La aceptación final combina verify PASS, tests sin FAIL/SKIP relevantes,
idempotencia PASS, inputs upstream intactos, privacidad, limpieza y docs. SUCCESS
es publicación validada; FINAL_PROJECT_LAYER_3_SOURCE_LEVEL_READY es el cierre
técnico registrado en el reporte final local, no una predicción de indicadores.

## 7. Git y pendientes

```powershell
# La herramienta histórica de inventario se retiró; consultar CODE_MAP para recuperación desde Git.
git status --short
git diff --check
git check-ignore data/graphrag/_manifest.json config/sources.yaml
```

No añadas con -f datos privados, outputs, pesos, caches, logs o configuración
local. El lock completo se conserva; pytest es dev/test, sentence-transformers
y torch son runtime Capa 3. Módulos upstream permanecen sin cambios.
Los perfiles siguen [PENDING_GROUP_REVIEW](pending/indicator_profiles.md).
No hay benchmark final vigente de indicadores, selección LLM ni Capa 4A final.

El inventario registra función y consumidores por archivo: ejecutar
La herramienta de inventario anterior se conserva en el historial Git y no representa la estructura vigente. Los fixtures estáticos
de tests están en data/samples/synthetic; no son datasets institucionales.
## 8. Rama territorial independiente de Capa 4B

Esta ruta consume todos los PROJECT de `data/knowledge` y la referencia territorial
autorizada, sin repetir Capas 1–3 ni leer RAW. El XLSX de referencia debe conservar
su estructura DANE inspeccionada y la hoja adicional autorizada `ALCANCE_NACIONAL`
con encabezados `code,name,type` y fila textual `000,Colombia,COUNTRY`.

En una nueva sesión de aceptación, registra primero la integridad protegida.
No sobrescribas un baseline de una aceptación que aún estés verificando.

```powershell
New-Item -ItemType Directory -Force outputs/layer4/territorios/aceptacion | Out-Null
uv run python -B scripts/territory_integrity.py | Out-File -Encoding utf8 outputs/layer4/territorios/aceptacion/integrity_before.json
uv run python -B scripts/build_dane_reference.py
uv run python -B scripts/run_territories.py
uv run python -B scripts/run_territories.py
uv run python -B scripts/verify_territories.py
uv run python -B -m pytest tests/territories -q --basetemp=outputs/layer4/territorios/aceptacion/tests-temp
```

`build_dane_reference` crea versiones inmutables y su manifest independiente en
`data/reference/processed`, sin alterar canonical. La publicación territorial
se encuentra en `outputs/layer4/territorios/publicacion`; las anteriores se archivan en
`outputs/layer4/territorios/versiones`. `verify_territories` comprueba hashes físicos y
lógicos, catálogo, todas las fuentes, offsets, workbook, CSV, idempotencia y
baseline protegido. Las pruebas reales requieren los snapshots privados existentes;
sin ellos se omiten explícitamente y no acreditan aceptación real.

El exportador del workbook usa Artifact Tool local cuando está instalado.
`TERRITORY_ARTIFACT_RUNTIME` puede apuntar al directorio padre de su node_modules;
si Node o Artifact Tool no existen, el exportador usa openpyxl ya instalado.
No instala paquetes ni llama a servicios. Las vistas `qa/` se generan con Artifact
Tool; el fallback mantiene los mismos datos y hojas sin previews renderizadas.

En Power BI importa `project_territories_powerbi.csv` y
`data/reference/processed/dane_territories.parquet`. Define los códigos como texto,
incluido `000`, y relaciona PROJECT 1:N PROJECT_TERRITORY N:1 TERRITORY.
No expandas filas de la tabla maestra ni incluyas AMBIGUOUS como relaciones.

## 9. Cierre de preparación de Capa 4, sin muestra ni engines

RAW_CONFIDENCE_V1 ya está integrado en el repositorio principal. Su configuración
versionada es `config/layer4_confidence.yaml`; no necesita instalar un proveedor.
La preparación usa el XLSX v2 autorizado de indicadores y los manifests/outputs
históricos existentes. No reconstruyas capas upstream ni ejecutes retrieval.

```powershell
uv run python -B scripts/build_layer4_contracts.py --check
uv run python -B scripts/build_indicator_assessment_profiles.py
uv run python -B scripts/prepare_layer4_inputs.py
uv run python -B -m pytest tests/layer4_confidence tests/territories tests/layer4_preparation -q -p no:cacheprovider --basetemp=outputs/layer4/auditoria/historicos/preparacion_inicial/integrated-test-temp --junitxml=outputs/layer4/auditoria/historicos/preparacion_inicial/integrated-tests.xml
uv run python -B scripts/build_layer2_contracts.py --check
uv run python -B scripts/build_layer3_contracts.py --check
uv run python -B scripts/auxiliary/verify_layer4_preparation.py
```

`layer4_preliminary.yaml` conserva tres flags de ejecución en false y engine
UNCONFIGURED/NOT_EXECUTED. La metadata preparada registra project_count=0 y
planned_project_count=20. El verificador del cierre actual consume el baseline
previo a integración de `outputs/layer4/auditoria/historicos/preparacion_inicial/integrity_before.json`; nunca
lo sobrescribas para hacer pasar una diferencia. Ese baseline y el registro de
integración de confidence son evidencia local, no un permiso para modificar upstream.

Los perfiles y reglas se publican independientemente bajo data/reference/processed,
con versiones inmutables. Los 48 fuentes_relevantes narrativos quedan UNMAPPED y
preferred_evidence_fields=[], sin mappings semánticos. Las 12 reglas son RULE_TEXT,
no lógica declarada implementada. Consulta los contratos layer4_assessment,
layer4_indicator_profiles y layer4_output en docs/contracts.

El generador de cuatro hojas está en layer4.indicators.export; las pruebas solo
exportan un fixture sintético a test-temp. No hay provider implementado ni comando
para assessment real. No ejecutar Codex CLI, seleccionar proyectos o crear
resultado_preliminar_20_proyectos.xlsx en esta fase. El siguiente paso autorizado
por separado será PRELIMINARY_LAYER4_20_PROJECTS.

El entorno, outputs y datos reales permanecen privados. Las carpetas generadas
se crean en runtime y no necesitan placeholders vacíos en Git.


## Código actual de Capa 4 y verificación histórica

Los imports activos son `layer4.indicators` y `layer4.territories`; las rutas de
scripts, schemas, configuración y outputs se conservan. Confidence se importa
desde `layer4.indicators.confidence`; el protocolo está en
`layer4.indicators.assessment`. No se necesita el worktree confidence para
ejecutar el código migrado ni para comprobar su copia histórica archivada.

`uv run python -B scripts/auxiliary/verify_layer4_preparation.py` verifica la preparación histórica,
sin reabrir su cierre ni exigir que el preliminar posterior no exista.
`uv run python -B scripts/verify_territories.py` verifica la publicación existente sin
reescribir su acta. `uv run python -B scripts/run_layer4_preliminary.py --verify`
verifica el preliminar persistido sin ejecutar el proveedor. Estas verificaciones
pueden leer datos reales y no sustituyen una nueva aceptación del código actual.

Los originales esperados en `archives/layer4/` no están incluidos en este árbol.
Las verificaciones que comparan fingerprints históricos requieren obtenerlos
por un canal autorizado; no forman parte de la instalación ni se añaden a
PYTHONPATH.

Un futuro build de perfiles o territorios y una futura ejecución preliminar
registrarán rutas/hashes nuevos. Para aceptar territorialmente ese nuevo código
habrá que ejecutar, con autorización separada, las integraciones reales, dos
builds territoriales idénticos y su QA/idempotencia en una publicación nueva;
no sobrescribir el cierre histórico. Esta migración no ejecuta esos pasos.


## Referencia DANE integrada en Capa 1

El código está en `layer1_data.dane_reference`; no se añade al ETL canonical.
El comando `scripts/build_dane_reference.py` y la ubicación de sus outputs no cambian.
La unificación se validó en aislamiento, sin sustituir la referencia vigente.
Consultar [aceptación](status/layer1_dane_unification_acceptance.md) para código,
datos, tests y alcance. No repetir builds sobre una publicación aceptada para
"ajustar" sus fingerprints.

Las auditorías trasladadas se ejecutan mediante `scripts/auxiliary/`.
`verify_layer4_preparation.py` reproduce el cierre histórico en lectura;
`create_source_level_review_workbook.py --help` conserva sus argumentos, pero
generar el workbook exige el checkout/snapshot R8 exacto que validan sus guardias.
Las dos auditorías de identidad se reservan para reproducción metodológica
con inputs privados autorizados; no ejecutarlas para instalar el proyecto.

Pruebas conjuntas: ejecutar `tests/layer1` por separado. En otro proceso usar
`tests/layer2/test_unit.py tests/layer3 tests/layer4_confidence tests/layer4_preliminary
tests/layer4_preparation tests/layer4_powerbi tests/territories`, excluyendo
`tests/layer3/test_integration_pending.py` para no reconstruir embeddings.
Usar `-B`, `-p no:cacheprovider`, basetemp y JUnit en una carpeta nueva de `.tmp/`.
La suite territorial completa incluye datos reales; ejecutar contra una copia
de snapshots si se están comprobando publicaciones nuevas.
