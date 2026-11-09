# Capa 2 — preprocesamiento

Entrada vigente: `data/raw`, leída por `adapters.py`. El único coordinador de documentos nuevos es `scripts/run_pipeline_manual.py`; el comando ETL original que sigue es una herramienta de mantenimiento.

## Propósito

Transforma fuentes estructuradas autorizadas en hechos canónicos, sin asignar indicadores. Incluye la referencia DANE como operación independiente del ETL.

## Archivos principales

| Archivo | Responsabilidad |
|---|---|
| [pipeline.py](pipeline.py) | Coordina preflight, ingesta, normalización, identidad, calidad y publicación con conservación del canonical anterior. |
| [ingestion.py](ingestion.py) | Lee CSV/XLSX, mapea columnas explícitas, valida filas y registra anomalías con su fila física. |
| [normalize.py](normalize.py) | Normaliza identificadores, fechas y texto mediante funciones puras; conserva el origen. |
| [identity.py](identity.py) | Resuelve componentes por identificadores exactos; bloquea contradicciones y separa homónimos. |
| [canonicalize.py](canonicalize.py) | Consolida entidades, títulos y membresías; escribe tablas Parquet tipadas. |
| [quality.py](quality.py) | Produce resúmenes, anomalías y cuarentena descriptiva de conflictos de producción. |
| [provenance.py](provenance.py) | Construye referencias a filas/campos, hashes y registros de trazabilidad. |
| [runtime.py](runtime.py) | Carga YAML y controla rutas de entrada/salida y logging de la capa. |
| [contracts.py](contracts.py) | Define campos, tipos Arrow y schemas lógicos usados por escritores y generadores. |
| [dane_reference.py](dane_reference.py) | Inspecciona el XLSX DANE, valida códigos, construye dimensión e índices y publica referencia versionada separada. |
| [__init__.py](__init__.py) | Declara la identidad y versión del paquete. |

## Funcionamiento

ETL: preflight → ingesta/validación → normalización → identidad → consolidación → calidad/provenance → publicación. La referencia DANE sigue inspect_catalog → validación → snapshot/manifest; no es un paso implícito de run_layer1.

## Entradas y salidas

Recibe CSV/XLSX y mappings locales de config/sources.yaml. Publica siete Parquet en data/canonical y staging/auditoría bajo data/staging y outputs/layer1. DANE recibe su XLSX autorizado y escribe data/reference/processed, sin alterar canonical.

## Relación con otras capas

Capa 2 solo lee canonical aprobado. Capa 4B consume la dimensión DANE mediante load_reference; no hay un paquete activo layer1_territories.

## Ejecución

Usar [la guía principal](../../README.md#ejecución-paso-a-paso) y los entrypoints [run_layer1.py](../../scripts/run_layer1.py) y [build_dane_reference.py](../../scripts/build_dane_reference.py). Ambos escriben publicaciones.
