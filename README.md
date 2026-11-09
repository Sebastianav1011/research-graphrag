# GraphRag — arquitectura SAD

Fuentes institucionales → procesamiento y conocimiento → GraphRAG → evaluación → Power BI externo.

## Inicio rápido

Requisitos: Git, conexión a los índices de paquetes y **uv (Astral)**. El proyecto
fija Python **3.14.0** en `.python-version`; uv puede descargarlo si no está
instalado. No hace falta crear ni activar un entorno virtual manualmente.

Instalar uv una sola vez en Windows PowerShell:

```powershell
winget install --id astral-sh.uv --exact
```

Alternativa oficial de Windows:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

En Linux o macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Reabrir la terminal si uv todavía no está en PATH. Después, los mismos comandos
sirven en PowerShell, Linux y macOS:

```powershell
git clone https://github.com/Sebastianav1011/research-graphrag.git
cd research-graphrag
uv sync --locked
uv run python run.py
```

`pyproject.toml` declara dependencias y grupos; `uv.lock` fija sus versiones,
fuentes y hashes. uv administra `.venv/`, que permanece fuera de Git.
`uv sync --locked` comprueba el lock sin permitir una resolución distinta.
No se ejecutan proyectos ni inferencias al instalar dependencias o abrir el menú.

La resolución contempla Windows x64, Linux x86_64 y macOS Apple Silicon. Se
conserva PyTorch **2.11.0/CUDA 12.8** en Windows/Linux; macOS usa su distribución
sin CUDA para el menú y pruebas. El pipeline completo mantiene su configuración
CUDA vigente: esta migración no lo convierte a CPU/MPS ni certifica su ejecución
en macOS. Más detalles en [instalación](docs/instalacion.md).

## Modelo, clave y contratos

En el menú, **Cambiar modelo** permite elegir Ollama o OpenAI API. El encabezado
muestra el proveedor y modelo activos. La preferencia se guarda localmente y
no cambia el proveedor de checkpoints existentes.

```powershell
uv run python run.py model --provider openai
uv run python run.py contracts
```

La clave se introduce con entrada oculta y se guarda preferentemente en el
almacén seguro del usuario mediante `keyring`. Si no está disponible, se ofrece
un archivo local de texto plano excluido de Git, explicando su limitación.
Puede reutilizarse o reemplazarse; guardarla no prueba la API ni consume créditos.

**Contratos de evaluación** permite crear versiones con cantidad y semilla,
o reutilizar IDs y orden con verificación de hashes. Compartir únicamente
contratos autorizados; `data/contratos/` se ignora por defecto. Crear o elegir
un contrato no sustituye las autorizaciones de ejecución.

```powershell
uv run python run.py status --run-id ID_EJECUCION
uv run python run.py stop --run-id ID_EJECUCION
uv run python run.py export --run-id ID_EJECUCION --partial
uv run python run.py resume --run-id ID_EJECUCION
```

Los flujos normal y autónomo mantienen sus comandos y opciones bajo `uv run`.
Véase [OpenAI y comparación experimental](docs/OPENAI_EXPERIMENTS.md) para
presupuesto, ampliaciones y autorización por manifiesto.

## Datos y recursos externos

Obtener por un canal autorizado las mismas fuentes bajo `data/layer1_sources/`,
catálogo institucional, referencia DANE y perfiles/rúbricas/plan de catálogo
descritos en [instalación](docs/instalacion.md) y [guía experimental](docs/OPENAI_EXPERIMENTS.md).
El repositorio comparte código y el contrato; no comparte las bases ni publicaciones privadas.

OpenAI no necesita Ollama. La recuperación GraphRAG sigue siendo local y requiere
BGE-M3, su revisión/hash configurados y hardware CUDA compatible. Para Qwen,
instalar aparte Ollama y `qwen3.5:4b-q4_K_M`. Cada integrante configura su propia
clave OpenAI; guardarla no hace una llamada de prueba ni consume créditos.

## Cantidad, toda la base y contrato compartido

El submenú de proyectos base permite cantidad, todos o contratos. Antes de procesar
toda la base muestra modelo, total, elegibles, bloqueados, rutas y advertencia de
tiempo/costo; exige confirmación. Los proyectos sin texto autorizado quedan con
motivo, sin evaluaciones inventadas ni estado completo. Para CLI, `--all` requiere
confirmación interactiva o `--confirm-all`; se mantienen las demás autorizaciones.

El contrato **incluido específicamente en Git** es
`data/contratos/tesis_comparacion_30.v1.json`: 30 IDs únicos, semilla 42,
muestreo estratificado sobre la población con texto autorizado, hashes y orden.
No se modificó durante la reorganización. Desde el menú: **Contratos de evaluación →
Utilizar contrato existente → tesis_comparacion_30.v1.json → N**. Los demás contratos
permanecen privados por defecto. Ver [validación del contrato](docs/status/validacion_contrato_tesis30.md).

Los siguientes comandos son para iniciar personalmente cuando se hayan preparado
los datos, pesos, servicios y claves; no son pruebas de instalación:

```powershell
uv run python run.py run --provider ollama --contract data/contratos/tesis_comparacion_30.v1.json --run-id qwen_30
uv run python run.py run --provider openai --budget-usd 15 --contract data/contratos/tesis_comparacion_30.v1.json --run-id terra_30
uv run python run.py run --provider ollama --all --confirm-all
```

El presupuesto API conserva reservas para llamadas en curso e inciertas; es una
protección preventiva y no consulta saldo real ni garantiza sobrecosto cero.
Cada proveedor usa su propio run, sin mezclar checkpoints o respuestas.

## Runs, resultados e histórico

```text
outputs/runs/local/<ID>/        Ollama, reciente o recuperable
outputs/runs/api/<ID>/          OpenAI, reciente o recuperable
outputs/runs/anteriores/<ID>/   Proveedor heredado no identificable
outputs/historico/<grupo>/<ID>/ Resultados permanentes y revisiones verificadas
```

Dentro de un run: `estado/`, `manifiestos/`, `grafo/`, `logs/`, `preprocess/`,
`workspace/`, checkpoints técnicos y `resultados/`. Las tres salidas son
`resultados/indicadores.csv`, `resultados/indicadores_territorios.csv` y
`resultados/performance/`. Importar `codigo_dane` como texto en herramientas externas.

Cada exportación conserva una copia verificada en histórico con evidencias,
performance y metadata. Las revisiones no sobrescriben snapshots previos; consultar
`latest.json` o la ruta informada por consola. El histórico no caduca. Los resultados
parciales siguen marcados como parciales y los checkpoints recuperables permanecen
en runs.

Desde otra terminal:

```powershell
uv run python run.py status --run-id terra_30 --provider openai
uv run python run.py stop --run-id terra_30 --provider openai
uv run python run.py export --run-id terra_30 --provider openai --partial
uv run python run.py resume --run-id terra_30 --provider openai
uv run python run.py cleanup --dry-run
uv run python run.py cleanup --apply
```

Si un ID existe en ambos proveedores, indicar `--provider`. Stop/Ctrl+C intentan
guardar y exportar sin repetir resultados válidos. Una llamada en curso puede
terminar o quedar incierta. Export no inicia inferencias.

La retención es de **72 horas**, pero solo se borra un run completo, definitivamente
cerrado, inactivo y con archivo íntegro vigente. Se conservan incompletos,
reanudables, inciertos, desconocidos o sin fecha fiable. Apply exige confirmar
escribiendo `ELIMINAR`. La limpieza automática está deshabilitada por defecto.
No elimina histórico, fuentes ni contratos. Ver [almacenamiento y recuperación](docs/ALMACENAMIENTO.md).

## Validación y publicación

```powershell
uv run python run.py --help
uv run python scripts/check_environment.py --skip-external
uv run python -m pytest tests/test_run_storage.py tests/test_api_contract_integration.py tests/test_indicator_csv.py -q
```

Estas pruebas usan temporales/simulaciones; no ejecutan modelos. Las pruebas
históricas que requieren snapshots privados no son una comprobación rápida de
instalación. El [informe de almacenamiento](docs/status/almacenamiento_final.md)
documenta la migración, protección de checkpoints y límites de validación.

El conjunto de publicación contiene código, schemas, configuración pública,
plantillas vacías, contrato autorizado, documentación y archivos uv. `outputs/`,
bases privadas, credenciales, preferencias, cachés, pesos y entornos permanecen
excluidos. Las actas y reportes históricos no revisados se conservan localmente
fuera del conjunto preparado para Git. No se ejecutó commit ni push.
