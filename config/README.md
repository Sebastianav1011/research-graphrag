# Configuración

`pipeline_manual.json` es la configuración compartida del coordinador:
fuentes en `data/layer1_sources`, ejecuciones en `outputs/runs`, catálogo
institucional separado y mapeos/textos autorizados por archivo.

`openai.json` define límites, razonamiento y tarifas de referencia, sin claves.
`autonomous.json` fija la política inicial de los runs autónomos. Las preferencias
personales se guardan en `model.local.json`, excluido de Git; cada run congela
su configuración. Cambiar la preferencia no modifica un checkpoint existente.

`sources.example.yaml` documenta aliases; `sources.yaml` es local e ignorado.
No usar las rutas históricas `data/raw` o `outputs/pipeline_manual` para un run nuevo.

Se conservan los nombres de configuración contractuales: `layer1.yaml` configura
el ETL, `layer2.yaml` el conocimiento, `layer3.yaml` GraphRAG y `layer4_*.yaml`
los estudios/evaluación. No renumerarlos ni cambiar hashes de snapshots históricos.

Iniciar desde la raíz con `uv run python run.py`. Para claves, contratos y recursos
privados requeridos, consultar [la guía experimental](../docs/OPENAI_EXPERIMENTS.md).

## Qué versionar

| Archivos | GitHub | Motivo |
| --- | --- | --- |
| `pipeline_manual.json`, `pipeline_validacion_integral.json` | Sí | Rutas relativas, selección de campos y parámetros compartidos. El endpoint `127.0.0.1` es el servicio local de Ollama, sin credenciales. |
| `layer1.yaml`, `layer2.yaml`, `layer3.yaml` | Sí | Reglas de procesamiento, contratos, modelo, revisión, hashes y configuración CUDA reproducibles. |
| `layer4_closure*.yaml`, `layer4_confidence.yaml`, `layer4_experiment.yaml`, `layer4_final.yaml`, `layer4_preliminary.yaml` | Sí | Parámetros de estudios y evaluación; algunas configuraciones son históricas y están fijadas por hashes. |
| `autonomous*.json`, `openai.json` | Sí | Políticas de ejecución, recursos y límites. `openai.json` contiene tarifas de referencia, no una clave API. |
| `qwen_tokenizer.json` | Sí | Ruta relativa, revisión del tokenizer y digest del modelo. Su calibración depende del modelo y la plantilla exactos. |
| `sources.example.yaml`, `sources.synthetic.yaml` | Sí | Aliases compartidos y configuración de fixtures sintéticos. |
| `sources.institutional.example.yaml` | Sí | Copia exacta del mapeo institucional local revisado, con rutas relativas y sin registros personales. Permite reproducir ese mapeo sin publicar las fuentes. |
| `layer4_pilot.example.yaml` | Sí | Copia exacta de los parámetros del piloto histórico revisado; no contiene secretos ni rutas de usuario. |
| `sad_relocations.json` | Sí, junto con sus dependencias | Registro utilizado por la resolución de rutas y la validación estricta de fingerprints. No es una preferencia local. |
| `sources.yaml` | No | Copia de trabajo que selecciona archivos y columnas de cada entrega. Hoy no contiene secretos, pero no debe sustituir silenciosamente los mapeos de otros integrantes. |
| `*.local.yaml`, `*.local.json` | No | Configuración particular, preferencias y destinos locales. Incluye `layer4_pilot.local.yaml` y `model.local.json`. |

Los nombres de columnas `cedula`, `documento`, `full_name` o `email` describen
mapeos o exclusiones; estos archivos no incluyen los valores de los investigadores.
Tampoco son credenciales los SHA-256, las revisiones de modelos ni los nombres
`token_limit_retries` y `template_tokens`. Las claves deben permanecer en el
almacén de credenciales, variables de entorno o archivos secretos ignorados.

Las plantillas nuevas conservan byte por byte las configuraciones locales
revisadas. No reemplazan `sources.example.yaml`, cuyo catálogo de aliases es más
amplio, ni cambian ningún valor predeterminado del código. El piloto conserva
`engine: CODEX_CLI` y su destino histórico: es documentación reproducible de ese
estudio, no una configuración del run Qwen actual.

## Preparar una copia local en otro equipo

Desde la raíz, instalar dependencias con `uv sync --locked`. Solo si las copias
locales todavía no existen, crearlas sin sobrescribirlas:

```powershell
if (-not (Test-Path -LiteralPath config/sources.yaml)) {
    Copy-Item -LiteralPath config/sources.institutional.example.yaml -Destination config/sources.yaml
}
if (-not (Test-Path -LiteralPath config/layer4_pilot.local.yaml)) {
    Copy-Item -LiteralPath config/layer4_pilot.example.yaml -Destination config/layer4_pilot.local.yaml
}
```

Todas las rutas de estas plantillas son relativas al repositorio. Cada integrante
debe obtener los CSV/XLSX, catálogos y publicaciones por el canal autorizado y
colocarlos en esas rutas. Compartir la configuración no comparte los datos ni
garantiza por sí solo que existan los mismos artefactos.

El ETL histórico usa `config/sources.yaml` por defecto. El coordinador consulta
ese archivo si existe y usa `sources.example.yaml` cuando falta; además combina
sus aliases y reglas de detección compartidas. El exportador del piloto usa
`config/layer4_pilot.local.yaml` por defecto. No existe una sobreescritura genérica
de cualquier archivo por otro `.local`: respetar las opciones implementadas por
cada comando. No renombrar ni reemplazar configuraciones de runs existentes.

## Reubicaciones, manifiestos y hashes

`sad_relocations.json` contiene aliases, prefijos y vínculos entre código actual
y copias históricas exactas. Sus rutas son relativas; sus modificaciones locales
de reanudación y comandos uv deben compartirse con el código correspondiente y
las copias de `docs/architecture/resume_compatibility/` y
`docs/architecture/uv_command_compatibility/`. Publicarlo solo, con otras versiones
del código o sin las copias requeridas, no reproduce la compatibilidad.

Algunas referencias históricas apuntan a `archives/` y `outputs/`, que permanecen
ignorados y no forman parte de un clon nuevo. Reanudar esos estudios exige obtener
también sus artefactos autorizados; la ausencia debe seguir produciendo un error
de validación. No eliminar referencias, recalcular hashes ni desactivar controles
para aceptar un archivo diferente. Los manifiestos, pesos, datos y checkpoints
existentes se conservan intactos.

Los hashes aprobados de `layer2.yaml`/`layer3.yaml`, el uso de CUDA y los digests de
`qwen_tokenizer.json` son restricciones compartidas explícitas. Un equipo con otro
hardware, datos o modelo requiere una preparación y autorización compatibles;
no debe editar estos valores para forzar una reanudación histórica.

Las reglas actuales de `.gitignore` ya permiten las plantillas y el registro,
y excluyen las copias locales, entornos, secretos, datos y outputs. No requieren
cambios para esta separación.
