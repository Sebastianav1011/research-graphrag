> Ubicación vigente de originales: `data/raw/`. El código de inventario forma parte de preprocesamiento. Este documento conserva el historial; consultar el README raíz para ejecutar.

> Documento histórico anterior a la consolidación del 29-10-2026. La operación vigente está en el README raíz y `docs/architecture/AUDITORIA_CONSOLIDACION_RAW.md`.

# Pipeline manual: RAW → PREPROCESSING → KNOWLEDGE → GRAPHRAG → RESULTS

Entrada operativa: `scripts/run_pipeline_manual.py`, desde la raíz `GraphRag`.
No es necesario que un agente prepare los archivos ni escriba prompts. La inferencia
de Capa 4 sigue utilizando Codex CLI como transporte, con sesión/créditos disponibles.

## Capas y conservación

La arquitectura activa tiene cinco capas: `layer1_raw`, `layer2_preprocessing`,
`layer3_knowledge`, `layer4_graphrag`, `layer5_results`. Power BI es consumidor.
Los paquetes analíticos se movieron sin editar sus fuentes; los nombres anteriores
son junctions de compatibilidad para mantener contratos y hashes históricos.
La [arquitectura activa](architecture/cinco_capas.md) y el README principal contienen
la tabla de capas, entradas y salidas actuales.

`preprocess` ejecuta únicamente Capa 2 y deja un checkpoint PREPROCESSED;
`knowledge` consume ese checkpoint para Capa 3. `prepare` continúa ejecutando ambas
como compatibilidad. `run --through preprocessing|knowledge|graphrag|results`
encadena las mismas operaciones y conserva la revisión/autorización explícita.
Los runners `run_layer1_raw.py` a `run_layer5_results.py` son entradas delgadas del
mismo coordinador. Todos admiten `--help`.

```text
data/raw/
  prueba_controlada/         # copias depositadas explícitamente por el usuario
  prueba_en_vivo/            # documentos nuevos
config/pipeline_manual.json
src/manual_pipeline/        # adaptadores y coordinación, no otro motor analítico
scripts/run_pipeline_manual.py
outputs/pipeline_manual/<run_id>/
  run.json, raw_manifest.json, prepared_hashes.json
  preprocess/
    adapted/                # CSV intermedios; nunca se escriben en RAW
    extracted/              # texto de DOCX/PDF
    review.json, lineage.json, diagnostics.json
  workspace/
    config/                 # configuración fijada para esta ejecución
    data/canonical/         # siete tablas tipadas y manifest
    data/knowledge/         # ocho tablas; SOURCE separado de REFERENCE
    data/graphrag/           # solo después de graph
    outputs/layer1, layer2, layer3/
  layer5_results/batch_<hash>/       # plan, revisión, autorización, respuestas y métricas
  resultado_indicadores.xlsx, export.json, evidence_lineage.json
  failure.json, last_error.json  # si corresponde
```

`data/canonical`, `data/knowledge`, `data/graphrag` y `outputs/layer4` de la raíz
original no son destinos de esta entrada. Los pesos fijados se leen del almacén
existente `outputs/layer3/models`; la caché de embeddings nueva es privada de cada
ejecución. No se descargan modelos automáticamente.

## Instalación local (PowerShell)

Sobre el entorno existente, desde la raíz:

```powershell
Set-Location -LiteralPath 'C:\Users\sebas\Workspace\Docs Tesis\GraphRag'
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Solo para PDF con texto extraíble:
.\.venv\Scripts\python.exe -m pip install -r requirements/manual-input.txt
.\.venv\Scripts\python.exe scripts/run_pipeline_manual.py --help
```

Para una instalación nueva, crear antes el entorno con `python -m venv .venv`.
GraphRAG requiere además las dependencias ya documentadas en
`requirements/layer3.txt` y el lock Windows/CUDA
`requirements/layer3-windows-cuda.lock.txt`, hardware compatible y los pesos BGE-M3
de la revisión `5617a9f61b028005a4858fdac845db406aefb181`. Esta modificación no cambia
el modelo ni instala otro backend. No usar `setup-model` para una prueba de integración
sin decidir explícitamente descargar los pesos.

Codex CLI debe conservar el runtime fijado por el cierre V3.3, actualmente 0.163.0,
su autenticación y sus fingerprints. No se ejecuta ni se modifica durante prepare,
validate, review o export. Si cambió el runtime, la llamada se bloquea antes de enviar
el texto: no se altera automáticamente la versión ni se omiten sus controles.

## Qué archivos se aceptan

- JSON: un objeto, una lista o `{"projects": [...]}`; admite `fields` anidado.
- CSV: UTF-8/UTF-8-BOM o cp1252, separadores coma, punto y coma, tabulación o barra.
  Las comillas y la cantidad de columnas se validan.
- XLSX: una sola hoja, o `sheet` explícito en configuración. No se aceptan fórmulas
  como datos; entregar sus valores. IDs de texto conservan ceros; números con formato
  `00000` también. Si Excel ya perdió los ceros y no tiene ese formato, no se recuperan.
- DOCX: párrafos y tablas del cuerpo, mediante la biblioteca estándar de Python.
- PDF: texto extraíble mediante `pypdf` instalado en el mismo entorno. Sin OCR ni
  alternativa a runtimes de la caché de Codex. PDF cifrado o sin texto se rechaza.

Para proyectos se reconocen `title`, `keywords`, `summary`, `methodology`,
`objectives`, `expected_results`, sus alias españoles y las columnas institucionales
de descriptores. ID: `siap_id`, `source_project_id`, `id_actividad` o alias documentados
en `EXTRA` del adaptador. `PROJ_*` es la clave técnica canónica del ETL, no un nuevo
identificador institucional. **Se requiere un ID proporcionado por la fuente** y al
menos un campo sustantivo. Sin ID se registra el error; esta entrada no genera SIAP
temporales. Para evaluar un documento sin ID, el custodio debe aportar una identidad
documentada; el pipeline no la inventa.

Los campos opcionales ausentes se mantienen vacíos y se advierten. En Word/PDF se
requieren encabezados explícitos: `ID SIAP:`, `Título:`, `Resumen:`, `Metodología:`,
`Objetivos:`, `Resultados esperados:` y `Palabras clave:`. No se interpreta un cuerpo
libre como resumen por conjetura. El texto extraído queda disponible incluso cuando
se rechaza la estructura. Se puede entregar después un JSON/CSV con el contenido
original organizado por su custodio, conservando la referencia documental.

Proyectos, artículos e investigadores se distinguen por subcarpetas de dominio
(`proyectos`, `articulos`, `investigadores`) o por los nombres institucionales
`descriptores*`, `produccion*`, `miembros*`. Documentos de proyectos con campos
reconocidos pueden ir directamente en la carpeta del conjunto. Dominios ambiguos
se rechazan. No se carga automáticamente ninguna de las fuentes históricas.

Los mapeos reutilizan `config/sources.yaml`, pero **no sus rutas de entrada**.
Miembros permite enriquecer títulos únicamente mediante `id_actividad` coincidente;
los investigadores y las membresías usan las reglas de identidad existentes. No se
fusionan personas solo por coincidencia de nombre. La deduplicación y los conflictos
se registran en la auditoría ETL. Un ERROR bloquea la preparación completa.

Para columnas diferentes, copiar `config/pipeline_manual.json` a
`config/pipeline_manual.local.json` y declarar solo los campos presentes, por ejemplo:

```json
"files": {
  "proyectos/recibidos.xlsx": {
    "domain": "proyectos",
    "sheet": "Proyectos",
    "mapping": {"source_project_id": "Código institucional", "title": "Nombre", "summary": "Descripción"}
  }
}
```

Usar el mismo `--config config/pipeline_manual.local.json` en todos los comandos de
esa ejecución. `files` usa rutas relativas al conjunto seleccionado. También admite
`researcher_mapping` y `organizations` con el contrato de fuentes existente. Los
alias contradictorios bloquean el archivo; las columnas no mapeadas se enumeran en
diagnósticos y se conservan en la procedencia. No se adivinan sus significados.

## Ejecución manual completa

Copiar los documentos **antes** de preparar. Por ejemplo, para uno o varios formatos:

```powershell
Set-Location -LiteralPath 'C:\Users\sebas\Workspace\Docs Tesis\GraphRag'
Copy-Item -LiteralPath 'C:\Documentos\proyecto_recibido.pdf' -Destination '.\capa_1_raw\prueba_en_vivo\'
$ejecucion = 'vivo_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
.\.venv\Scripts\python.exe -B scripts/run_pipeline_manual.py prepare --dataset prueba_en_vivo --run-id $ejecucion
Get-Content -Raw -LiteralPath ".\outputs\pipeline_manual\$ejecucion\preprocess\review.json"
Get-Content -Raw -LiteralPath ".\outputs\pipeline_manual\$ejecucion\preprocess\diagnostics.json"
.\.venv\Scripts\python.exe -B scripts/run_pipeline_manual.py validate --dataset prueba_en_vivo --run-id $ejecucion
```

La misma copia admite `.docx`, `.xlsx`, `.csv` o `.json`; no requiere cambiar código.
Revisar cada salida y detenerse si el comando devuelve código 2. No continuar pegando
comandos tras un error. `prepare` no hace embeddings ni inferencias; `validate`
comprueba contratos y grafo factual sin cargar el modelo.

Después de revisar, construir GraphRAG local y preparar la revisión de Capa 4:

```powershell
.\.venv\Scripts\python.exe -B scripts/run_pipeline_manual.py graph --dataset prueba_en_vivo --run-id $ejecucion --approve-build
.\.venv\Scripts\python.exe -B scripts/run_pipeline_manual.py review --dataset prueba_en_vivo --run-id $ejecucion
Get-ChildItem -LiteralPath ".\outputs\pipeline_manual\$ejecucion\layer5_results" -Filter 'review.txt' -Recurse | ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName }
```

Si la entrada tiene más de dos proyectos, `review` exige seleccionar uno o dos con
`--project-id 'ID_ORIGINAL'`, repitiendo la opción para el segundo. Usar exactamente
la misma selección al ejecutar. Procesar otros IDs en otro lote de la misma ejecución;
no se permite solaparlos para evitar repetir inferencias. Una entrada de uno o dos
proyectos no necesita esas opciones.

Tras leer la revisión, autorizar el envío y exportar:

```powershell
.\.venv\Scripts\python.exe -B scripts/run_pipeline_manual.py evaluate --dataset prueba_en_vivo --run-id $ejecucion --authorize
.\.venv\Scripts\python.exe -B scripts/run_pipeline_manual.py export --dataset prueba_en_vivo --run-id $ejecucion
.\.venv\Scripts\python.exe -B scripts/run_pipeline_manual.py verify --dataset prueba_en_vivo --run-id $ejecucion
```

`--authorize` autoriza expresamente el texto y el plan preparados. El ejecutor conserva
sus autorizaciones ligadas a request, presupuestos, máximo de tres llamadas por
proyecto (un discovery y hasta dos lotes de assessments), ejecución secuencial y cero
reintentos. No se llama al LLM durante la instalación o preparación del mecanismo.

Para la prueba controlada, depositar explícitamente las copias seleccionadas en
`data/raw/prueba_controlada` y usar los mismos comandos con
`--dataset prueba_controlada` y otro `$ejecucion`. No hay muestra de relleno. No se
incluyen los proyectos históricos por defecto ni se ejecutan de nuevo sus inferencias.

## Reanudación, errores y salida

Cerrar la terminal no borra las respuestas guardadas. En otra sesión, asignar
`$ejecucion = 'EL_RUN_ID_ANTERIOR'` y repetir el comando de la etapa interrumpida.
`prepare` terminado verifica y reutiliza; `graph` terminado valida y reutiliza;
`evaluate` conserva la autorización anterior y no necesita volver a pasar
`--authorize`. Repetir los mismos `--project-id` si se seleccionaron explícitamente.

Una preparación fallida se conserva; corregir/depositar la entrada y usar un nuevo
run ID. Una ejecución con request despachado sin desenlace verificable queda
bloqueada como `UNCERTAIN_OUTCOME`; no se reintenta automáticamente. Modelo ocupado,
créditos agotados, timeout, falta de métricas o deriva del runtime detienen la fase.
Los errores aparecen en stderr, `last_error.json` y los logs originales del lote.
Se puede exportar el progreso válido después de una interrupción de evaluación.
No borrar claims ni autorizaciones para forzar otra llamada.

RAW modificado, eliminado o ampliado después de preparar invalida esa ejecución;
crear una nueva. `INPUT_REJECTED`, `MISSING_FIELDS`, alias contradictorios, dominio
ambiguo y columnas sin mapear se explican en `preprocess/diagnostics.json`. La
auditoría detallada de duplicados, conflictos y descartes está en
`workspace/outputs/layer1/audit/`; la calidad de secciones y chunks en layer2.

Contrato entre preparación y GraphRAG: exactamente las ocho tablas del contrato
[Layer 2](contracts/layer2_knowledge_contract.md), con IDs canónicos, espacios
SOURCE/REFERENCE, hashes, origen RAW, registro/hoja/campo y offsets de chunks dentro
de secciones normalizadas. Las siete tablas canónicas y sus esquemas existentes
también se validan. `prepared_hashes.json` sella productos y configuración; no editar
una revisión sellada para alterar una evaluación.

El Excel tiene exactamente `RESULTADO_INDICADORES` (seis columnas acordadas) y
`TERRITORIOS` (cuatro). La confianza es numérica, 0–100, original del assessment,
con `100 × (0.55S + 0.45K)`, sin umbral y sin etiquetas de cumplimiento. Se incluyen
evaluaciones parciales con criterio pertinente y cita válida; no filas ficticias.
Los datos textuales se escriben como texto, incluidas cadenas que empiezan por `=`.
`evidence_lineage.json` conserva los campos RAW y offsets; los offsets de Excel se
refieren al campo preparado, según el sistema de coordenadas indicado.

No se reconstruye Capa 4B ni se consultan territorios de otras ejecuciones. Esta
entrada no genera relaciones territoriales nuevas: TERRITORIOS queda con encabezados
hasta disponer de un puente verificado de esa misma ejecución. La publicación
territorial y el Excel oficial V2 permanecen intactos.

Un Excel vacío puede significar evaluación pendiente o evaluación terminada sin
evidencia pertinente; consultar `export.json` (estado, proyectos pendientes y
procesados). `COMPLETE` exige todos los proyectos preparados, no solo el lote elegido.
La compatibilidad de estructura Excel se verifica; Power BI Desktop no se ha importado
como parte de estas pruebas. Confianza no equivale a probabilidad calibrada ni a
certificación institucional; las rúbricas conservan su aceptación técnica y revisión
humana pendiente.

## Código heredado y validación

`run_layer4_live_demo.py` se mantiene por los hashes y reanudaciones históricas. Para
entradas nuevas se utiliza esta CLI. Solo se reutilizan sus utilidades puras de
extracción y su motor secuencial/validadores: no se ejecutan su preparación, búsqueda
de caché de 30 proyectos, consulta territorial, alternativa PDF externa ni renderer
Node. No se eliminan módulos referenciados por manifiestos anteriores.

La auditoría previa está en [pipeline_manual_auditoria.md](architecture/pipeline_manual_auditoria.md).
Las pruebas nuevas están en `tests/test_manual_pipeline.py`; incluyen documentos
nuevos mínimos, ETL real, calidad/chunking y validación del grafo existente. La
integración de build/retrieval usa vectores sintéticos inyectados exclusivamente
desde el test; no son resultados analíticos y el control de producción rechaza ese
proveedor. Los tests de exportación usan un assessment sintético del contrato V3,
incluida evidencia parcial de baja confianza.

No se hizo una prueba completa nueva con BGE-M3 ni LLM. PDF requiere instalar la
dependencia opcional antes de usarlo; esa extracción no está verificada en el entorno
actual sin pypdf. No se garantiza inferencia sobre documentos arbitrarios sin campos
reconocibles o textos que excedan los presupuestos; no se truncan en silencio.

## Migración de estructura

Las rutas físicas heredadas dentro de workspace se conservan porque sus validadores
las exigen; la numeración lógica actual está en architecture/cinco_capas.md. Los
resultados históricos bajo outputs/layer4 conservan su numeración y su contenido.
Un run previo que ya tenga layer4/ se reanuda allí; uno nuevo utiliza layer5_results/.
El registro de rutas existente enlaza los dos fuentes originales del coordinador
con sus snapshots exactos y sus hashes actuales, usando el verificador ya existente;
no se modificó su política ni la del ejecutor LLM.
