# Dependencias de ejecución

## Propósito

Define el runtime adicional de embeddings y conserva el lock completo del entorno
Windows/CUDA verificado. No contiene pesos de modelos ni un proyecto npm.

## Archivos principales

| Archivo | Responsabilidad |
|---|---|
| [layer3.txt](layer3.txt) | Reutiliza requirements.txt y fija sentence-transformers, transformers, huggingface_hub y torch como dependencias directas de embeddings. |
| [layer3-windows-cuda.lock.txt](layer3-windows-cuda.lock.txt) | Fija runtime completo, transitivas y pytest para Windows x64/Python 3.14; usa índice adicional PyTorch cu128. |
| [../requirements.txt](../requirements.txt) | Dependencias directas base: pandas, NumPy, PyArrow, openpyxl, PyYAML y jsonschema. |
| [../requirements-dev.txt](../requirements-dev.txt) | Incluye runtime base y pytest para desarrollar/probar sin instalar el stack completo de modelos. |

## Funcionamiento

Pip resuelve las listas elegidas dentro de .venv. Usar el lock completo para
reproducir el camino verificado, o runtime base + dev para las pruebas ligeras.
layer3.txt no equivale al lock completo ni certifica otro hardware.

## Entradas y salidas

Archivos de requisitos → paquetes instalados en el entorno local. Modelos BGE-M3
se preparan aparte en outputs/layer3/models; no se distribuyen por Git.

## Relación con otras capas

El runtime base sirve a ETL, referencias, confianza y exportación openpyxl.
Capa 3 necesita modelos locales y stack de embeddings. Las transitivas del lock,
incluido scikit-learn, no significan que exista calibración de confianza.

## Ejecución

Seguir [instalación del README principal](../README.md#requisitos-e-instalación).
Node/Artifact Tool y Codex CLI no se instalan mediante estos archivos. No hay
versiones fijadas de Node o Artifact Tool en el repositorio; su disponibilidad
debe validarse por separado. La preparación de BGE-M3 requiere descarga o copia
autorizada de pesos y hardware compatible.
