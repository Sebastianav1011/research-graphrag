# Instalación con uv

Rutas y publicación actualizadas: [almacenamiento](ALMACENAMIENTO.md). El contrato de tesis está expresamente autorizado para Git; los demás contratos y todos los outputs siguen privados. Los informes anteriores describen su fecha.

El flujo oficial es **uv sync → uv run python run.py**, sin activar un entorno.
uv administra `.venv`, instala Python 3.14.0 si hace falta y usa `uv.lock`.
Se preservan las versiones existentes del runtime. Sincronizar paquetes no
ejecuta proyectos ni descarga pesos de los modelos.

## Instalar uv y clonar

Requisitos: Git, acceso a PyPI y al índice público de PyTorch, espacio para sus
paquetes y una plataforma declarada. Instalar uv en Windows:

```powershell
winget install --id astral-sh.uv --exact
```

Alternativa de Windows:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Linux/macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Reabrir la terminal si es necesario. Los pasos siguientes son comunes:

```powershell
uv --version
git clone https://github.com/Sebastianav1011/research-graphrag.git
cd research-graphrag
uv sync
uv run python run.py
```

No se necesita instalar Ollama para abrir el menú, configurar OpenAI o usar ese
proveedor. Sí se necesitan los recursos locales de GraphRAG para las etapas de
preparación/recuperación que lo requieran. Instalar paquetes no autoriza proyectos.

## Versiones y plataformas

Python queda fijado en `.python-version` a **3.14.0**; pyproject admite la familia
3.14. `uv.lock` resuelve las dependencias y grupos para:

| Sistema | Arquitectura | PyTorch | Alcance |
|---|---|---|---|
| Windows | x64/AMD64 | 2.11.0+cu128, índice oficial CUDA 12.8 | Runtime existente; ejecución real exige recursos autorizados y hardware. |
| Linux | x86_64 | 2.11.0+cu128, índice oficial CUDA 12.8 | Wheels resueltos; sin ejecución del pipeline en Linux durante la migración. |
| macOS | Apple Silicon/arm64 | 2.11.0, PyPI | Menú/desarrollo; la configuración CUDA actual impide ejecutar todo GraphRAG aquí. |

No se declaran Windows ARM, Linux ARM ni macOS Intel. No se cambia dispositivo,
precisión, modelo, confianza o esquema para ampliar plataformas. Los drivers y
requisitos de sistema de los wheels quedan fuera del gestor Python. Un equipo
sin NVIDIA puede abrir el menú; el pipeline completo sigue necesitando el
dispositivo establecido en `config/layer3.yaml`. OpenAI no sustituye BGE-M3.

## Entorno existente y grupos

No eliminar `.venv`. Para la adopción conservadora:

```powershell
uv sync --locked --inexact
```

`--inexact` conserva paquetes adicionales ajenos al proyecto. `uv sync` normal
sincroniza exactamente las dependencias seleccionadas y puede retirar paquetes
no declarados; no borra el entorno ni los datos del proyecto. `uv run` selecciona
el entorno automáticamente y permite ejecutar todos los entrypoints existentes.

```powershell
uv sync --no-dev
uv sync --group pdf
uv sync --group performance
uv sync --all-groups
```

El grupo dev (pytest) se incluye por defecto. pdf (pypdf) y performance
(psutil, NVIDIA NVML) son opcionales; repetir sus opciones de grupo en futuras
sincronizaciones para conservarlos. `uv run --locked` exige que el lock esté
actualizado. No ejecutar actualizaciones generales como paso de instalación.
`requirements*.txt` y locks anteriores se conservan por compatibilidad; la
autoridad vigente es `pyproject.toml` + `uv.lock`.

`setup.ps1` es un wrapper opcional de uv, innecesario para un clon nuevo.
No modificar las dependencias de una ejecución autorizada mediante recetas
antiguas de pip ni cambiando la variante de torch por fuera del lock.

## Recursos externos

1. **Ollama**, exclusivamente para el proveedor local. Instalar el servicio desde
   [Ollama](https://ollama.com/download) y preparar el modelo exacto configurado
   (actualmente `qwen3.5:4b-q4_K_M`). El código usa HTTP estándar, no su SDK Python.
   `ollama pull` es una operación posterior deliberada; no se ejecutó en la migración.
2. **OpenAI**: SDK y keyring incluidos en uv; cada persona configura su clave con
   entrada oculta. Seguir [OpenAI y contratos](OPENAI_EXPERIMENTS.md). Linux puede
   requerir un servicio de credenciales de escritorio; Windows/macOS usan sus
   almacenes de credenciales. El fallback local en texto plano exige aceptación
   y permanece ignorado por Git. Ninguna configuración ejecuta una prueba de pago.
3. **CUDA/NVIDIA** para las operaciones locales configuradas con CUDA. Se conserva
   CUDA 12.8 en PyTorch; uv no instala ni cambia un controlador del sistema.
4. **BGE-M3**, revisión fijada `5617a9f61b028005a4858fdac845db406aefb181`;
   pesos locales y hashes vigentes. Se preparan aparte mediante descarga/copia
   autorizada. No usar `setup-model` como prueba de instalación: puede ejecutar
   procesamiento y mediciones. uv instala Hugging Face, no esos pesos.
5. **Datos institucionales, catálogo, DANE y planes/perfiles/rúbricas sellados**:
   obtenerlos del responsable por un canal autorizado, manteniendo rutas y hashes.
   El código vigente depende de publicaciones privadas bajo `outputs/layer4`,
   incluido el plan de cierre descrito en la guía experimental. Un clon público
   no reconstruye esos recursos ni contiene bases, personas o resultados reales.

Node/Artifact Tool y Codex CLI solo corresponden a scripts auxiliares históricos;
el entrypoint Python y los CSV actuales no necesitan esos programas.

## Comandos y validación sin modelos

```powershell
uv run python run.py --help
uv run python run.py contracts
uv run python run.py model --provider openai
uv run python run.py status --run-id ID_EJECUCION
uv run python run.py stop --run-id ID_EJECUCION
uv run python run.py export --run-id ID_EJECUCION --partial
uv run python run.py resume --run-id ID_EJECUCION
```

Se conservan los requisitos de configuración, revisión y estado del run. No usar
stop/export/resume contra ejecuciones institucionales para probar la instalación.
Para el flujo autónomo mantener `--autonomous` donde correspondía; no cambia
ninguna autorización. Los comandos de procesamiento se ejecutan solo cuando
el integrante decida iniciar su experimento.

```powershell
uv lock --check
uv run python scripts/check_environment.py --skip-external
uv run python -m pytest tests/test_api_contract_integration.py tests/test_indicator_csv.py -q
```

El comprobador con `--skip-external` no consulta Ollama ni carga modelos. Las
pruebas indicadas usan mocks y datos sintéticos. Evitar la suite completa como
comprobación rápida: contiene procedimientos con otros requisitos de integración.

## Git y mantenimiento

Versionar `pyproject.toml`, `uv.lock`, `.python-version`, código, configuración
compartible y documentación. Mantener fuera de Git `.venv/`, cachés, preferencias
locales, claves, modelos, resultados y bases. Los contratos se ignoran por defecto;
solo pueden añadirse individualmente después de autorizar su contenido. No
compartir una `.venv` entre computadores.

La migración no hace commit/push ni reescribe checkpoints o resultados. Con código
y archivos uv publicados, un clon limpio puede sincronizar y abrir el menú; una
ejecución institucional requiere además los recursos externos anteriores.

El conjunto preparado incluye `run.py`, `scripts/__init__.py`, el coordinador,
la configuración pública, paquetes actuales y los tres archivos uv. Revisar el
índice antes del commit; publicar solamente pyproject y el lock no publica el
runtime. La reorganización actual se documenta en [almacenamiento](ALMACENAMIENTO.md).
Conservar además los schemas, configuraciones compartidas y plantillas vacías
autorizadas; excluir toda configuración `*.local.*`, secretos y datos privados.

Referencias oficiales: [instalación de uv](https://docs.astral.sh/uv/getting-started/installation/),
[lock y sync](https://docs.astral.sh/uv/concepts/projects/sync/),
[PyTorch con uv](https://docs.astral.sh/uv/guides/integration/pytorch/).
