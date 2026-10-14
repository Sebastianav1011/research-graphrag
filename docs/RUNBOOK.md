# Clonar y ejecutar — Windows / PowerShell

La raíz es el directorio del clon, sin requisito de nombre de usuario. No hay
remote Git configurado todavía en la copia local: utiliza la URL que publique
el grupo. No se ha hecho commit/push durante el refactor.

## 1. Clon, Python y entorno

```powershell
$repoUrl = Read-Host 'URL Git del repositorio del grupo'
git clone $repoUrl GraphRag
Set-Location GraphRag
py -3.14 --version
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install -r requirements/layer3-windows-cuda.lock.txt
python -m pip check
Copy-Item config/sources.example.yaml config/sources.yaml
```

Camino verificado: Python 3.14 x64 y CUDA 12.8, GPU NVIDIA de 8 GiB. El lock
completo fija el runtime comprobado, incluidas dependencias transitivas y tests.
`requirements.txt` fija las dependencias directas de Capas 1–2. Para solo esas
capas, instala `python -m pip install -r requirements-dev.txt`.
`requirements/layer3.txt` fija los componentes directos de embeddings para
otro entorno; ese entorno requiere su propia validación/calibración. No
desinstales transitivas del lock porque no aparezcan como imports del proyecto.

## 2. Datos que no vienen con Git

Obtén del grupo los archivos autorizados, sin crear sustitutos institucionales:

- data/raw/proyectos/descriptores-limpio.csv
- data/raw/articulos/produccion-limpio.csv
- data/raw/investigadores/miembros-doc-limpio.csv
- data/reference/indicadores/catalogo_indicadores.xlsx (hoja Catalogo_Indicadores)

Esas son las rutas por defecto de sources.example. Si usarás otras rutas,
edita únicamente config/sources.yaml (local, ignorado por Git). La plantilla
vacía templates/resultado_final_indicadores.xlsx sí está permitida en Git.

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
python scripts/run_layer1.py --config config/sources.yaml --settings config/layer1.yaml
python scripts/run_layer1.py --config config/sources.yaml --settings config/layer1.yaml
python scripts/verify_layer1.py --existing
python -B -m pytest tests/layer1 -q -p no:cacheprovider
Get-Content data/canonical/_manifest.json | ConvertFrom-Json | Select-Object run_id,status
```

Antes de Capa 2 verifica SUCCESS del manifest canonical y acepta explícitamente
su hash en el gate existente. Este comando actualiza solo ese campo de config:

```powershell
$canonicalHash = (Get-FileHash data/canonical/_manifest.json -Algorithm SHA256).Hash.ToLowerInvariant()
$env:APPROVED_LAYER1_SHA256 = $canonicalHash
python -c "import os,yaml; from pathlib import Path; p=Path('config/layer2.yaml'); c=yaml.safe_load(p.read_text(encoding='utf-8-sig')); c['readiness']['approved_layer1_manifest_sha256']=os.environ['APPROVED_LAYER1_SHA256']; p.write_text(yaml.safe_dump(c,sort_keys=False),encoding='utf-8')"
python scripts/run_layer2.py --mode profile
python scripts/run_layer2.py --mode validate
python scripts/run_layer2.py --mode publish
python scripts/run_layer2.py --mode publish
$env:LAYER2_REAL_INTEGRATION='1'
$env:LAYER2_VERIFY_PUBLICATION='1'
python -B -m pytest tests/layer2 -q -p no:cacheprovider
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
python scripts/run_layer3.py --mode approve --manifest-sha256 $knowledgeHash
python scripts/run_layer3.py --mode validate
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
python scripts/run_layer3.py --mode setup-model
python scripts/run_layer3.py --mode build
python scripts/run_layer3.py --mode verify
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
python scripts/run_layer3.py --mode build
python scripts/run_layer3.py --mode compare
python scripts/run_layer3.py --mode verify
python scripts/run_layer3.py --mode query --query "restauración ambiental y biodiversidad" --retrieval-mode hybrid
python scripts/run_layer3.py --mode test --real-integration
python scripts/build_layer3_contracts.py --check
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
python scripts/audit_repository.py --mode inventory
git status --short
git diff --check
git check-ignore data/graphrag/_manifest.json config/sources.yaml
```

No añadas con -f datos privados, outputs, pesos, caches, logs o configuración
local. El lock completo se conserva; pytest es dev/test, sentence-transformers
y torch son runtime Capa 3. Módulos upstream permanecen sin cambios.
Los perfiles siguen [PENDING_GROUP_REVIEW](pending/indicator_profiles.md).
No hay benchmark final vigente, selección LLM ni Capa 4 final en este refactor.

El inventario registra función y consumidores por archivo: ejecutar
python -B scripts/audit_repository.py --mode inventory. Los fixtures estáticos
de tests están en data/samples/synthetic; no son datasets institucionales.
El entorno, outputs y datos reales permanecen privados. Las carpetas generadas
se crean en runtime y no necesitan placeholders vacíos en Git.
