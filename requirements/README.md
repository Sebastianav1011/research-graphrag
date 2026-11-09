# Dependencias de GraphRAG

El gestor oficial es **uv**. Desde la raíz del clon:

```powershell
uv sync
uv run python run.py
```

No crear ni activar `.venv` manualmente. Se mantiene excluido de Git.
La instalación completa se documenta en [instalación](../docs/instalacion.md).

## Fuentes de configuración

| Archivo | Función |
|---|---|
| [pyproject.toml](../pyproject.toml) | Dependencias reales, grupos y plataformas. |
| [uv.lock](../uv.lock) | Versiones, índices y hashes reproducibles. |
| [.python-version](../.python-version) | Python 3.14.0. |
| [requirements.txt](../requirements.txt) y [requirements-dev.txt](../requirements-dev.txt) | Entradas anteriores conservadas por compatibilidad; no son el flujo oficial. |
| [runtime-constraints.txt](runtime-constraints.txt) y [dev-constraints.txt](dev-constraints.txt) | Referencia del entorno previo; sus restricciones se trasladaron a pyproject. |
| [layer3-windows-cuda.lock.txt](layer3-windows-cuda.lock.txt) | Lock histórico Windows/CUDA conservado sin regenerar. |

## Grupos

```powershell
uv sync --no-dev
uv sync --group pdf
uv sync --group performance
uv sync --all-groups
```

`dev` contiene pytest y se incluye por defecto. Los otros grupos corresponden a
los anteriores `manual-input.txt` (pypdf) y `performance.txt` (psutil/NVML).
Los fallbacks de lectores/sensores permanecen sin cambios.

Para adoptar una `.venv` previa sin retirar sus paquetes adicionales:

```powershell
uv sync --locked --inexact
```

El proyecto es una aplicación con `package = false`, ejecutada desde la raíz;
no necesita backend de empaquetado ni modificar imports o entrypoints.
No requiere un SDK Python de Ollama: usa HTTP estándar y el servicio se instala
externamente solo para el proveedor local.

Actualizar dependencias debe ser deliberado: editar pyproject y ejecutar
`uv lock`; revisar el diff antes de compartir el lock. No usar `uv lock --upgrade`
como paso de instalación. No incluir credenciales ni índices privados en estos
archivos; `uv.toml` queda reservado para ajustes locales ignorados por Git.
