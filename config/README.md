# Configuración

## Propósito

Separa mappings privados de las políticas versionadas y aprobaciones explícitas.
No contiene credenciales ni sustituye los contratos de datos.

## Archivos principales

| Archivo | Responsabilidad |
|---|---|
| [layer4_closure_definitive.yaml](layer4_closure_definitive.yaml) | Configuración operativa del cierre V2: dos candidatos y fallback desactivado. Usar --settings explícito; el archivo anterior se conserva por fingerprints históricos. |
| [sources.example.yaml](sources.example.yaml) | Plantilla portable de rutas, hojas, delimitadores y mappings autorizados de Capa 1. |
| sources.yaml — local, ignorado por Git | Mapping real de las fuentes del custodio; crearlo copiando la plantilla, sin sobrescribir el existente. |
| [sources.synthetic.yaml](sources.synthetic.yaml) | Entrada de fixtures públicas; ejecutarla fuera de tests puede reemplazar canonical por datos sintéticos. |
| [layer1.yaml](layer1.yaml) | Normalización, validación, severidad y rutas de staging/canonical/auditoría. |
| [layer2.yaml](layer2.yaml) | Mapeo canónico, campos/corpus/metadata, privacidad, chunking y aprobación del manifest de Capa 1. |
| [layer3.yaml](layer3.yaml) | Aprobación knowledge, BGE-M3 fijado, índices, límites del grafo, pesos hybrid y publicación. |
| [layer4_confidence.yaml](layer4_confidence.yaml) | RAW_CONFIDENCE_V1: pesos, relevancia, corroboración y campos permitidos. |
| [layer4_preliminary.yaml](layer4_preliminary.yaml) | Contrato de preparación y versiones de referencias; flags de selección/assessment/workbook false. |

El preliminar técnico posee un runner explícito independiente; los flags de
preparación no son un control de autorización para --execute.

## Funcionamiento

Capa 1 interpreta sus mappings sin adivinar columnas. Capa 2 exige SUCCESS y
hash aprobado de canonical, mappings_verified y chunking_calibrated. Capa 3
exige estado final de Capa 2 y hash exacto; approve valida antes de actualizar
config/layer3.yaml. Confidence valida versión, rangos y suma exacta de pesos 1.0.

Un nuevo snapshot requiere revisión y nueva aprobación. No cambiar políticas
o hashes para hacer pasar una incompatibilidad. DANE y perfiles v2 usan rutas
por defecto declaradas en sus módulos; no existe una configuración territorial
YAML adicional activa.

## Entradas y salidas

YAML versionados y mapping local → opciones y gates del runtime. Las rutas de
publicación se resuelven desde la raíz. Los snapshots exactos de configuración
usados por los pipelines se conservan en sus runs privados.

## Relación con otras capas

Cada capa valida su frontera; no se lee sources.yaml desde Capa 2/3 para acceder
a RAW. Las referencias assessment v2 permanecen separadas del catálogo congelado
de retrieval.

## Variables de entorno

| Variable | Uso real |
|---|---|
| LAYER2_CONFIG | Configuración alternativa en tests reales de Capa 2; no reemplaza --config del CLI. |
| LAYER2_REAL_INTEGRATION | Opt-in de integración real de Capa 2 con valor 1. |
| LAYER2_VERIFY_PUBLICATION | Opt-in adicional para validar dos publicaciones existentes. |
| LAYER3_RUN_REAL_INTEGRATION | Opt-in de integración real Capa 3; puede ejecutar embeddings/builds. |
| TERRITORY_ARTIFACT_RUNTIME | Ruta de búsqueda del runtime externo Node/Artifact Tool del render territorial. |
| LAYER4_ARTIFACT_RUNTIME | Ruta de búsqueda del runtime externo para exportaciones de indicadores. |
| ARTIFACT_TOOL_NODE_MODULES / REVIEW_WORKBOOK_NODE | Módulos y ejecutable del workbook auxiliar de revisión histórica. |

No es necesario crear .env para la ejecución local base.
[.env.example](../.env.example) solo declara esa ausencia de credenciales.
Tokens y sesiones de herramientas externas se administran fuera de Git.

## Ejecución

Preparación del mapping y comandos por capa: [README principal](../README.md).
Los archivos *.local.yaml y sources.yaml se mantienen privados.
