# Código fuente

## Propósito

Organiza la implementación activa por responsabilidades. Los entrypoints están en
[scripts](../scripts/README.md); importar un paquete no es una orden de publicación.

## Archivos principales

| Ruta | Responsabilidad |
|---|---|
| [layer1_data](layer1_data/README.md) | ETL canónico y referencia DANE independiente. |
| [layer2_knowledge](#capa-2-procesamiento-y-conocimiento) | Preparación determinística de documentos, campos, chunks y relaciones. |
| [layer3_graphrag](#capa-3-graphrag) | Embeddings, índices, grafo y candidatos SOURCE+INDICATOR. |
| [layer4](layer4/README.md) | Dos ramas: indicadores y territorios; verificación de historia archivada. |

No existen paquetes activos layer1_territories ni los namespaces layer4_* anteriores.
Las pruebas y scripts importan layer1_data.dane_reference y layer4.indicators /
layer4.territories.

## Funcionamiento

Fuentes → canonical → knowledge → GraphRAG → evaluación de indicadores.
En paralelo, knowledge + referencia DANE → caracterización territorial.
Los módulos pipeline coordinan; contratos, transformación y validación permanecen
en módulos especializados.

## Entradas y salidas

CSV/XLSX autorizados y YAML son entradas de Capa 1; las capas posteriores consumen
publicaciones Parquet con manifests. Datos, modelos, resultados y auditoría viven
en data/outputs privados; este directorio contiene código.

## Relación con otras capas

Capa 3 localiza posibles fuentes, sin confirmar evidencia ni cumplimiento.
Capa 4 calcula confianza solo tras validar el assessment; la rama territorial
no depende de ranking o candidatos.

## Capa 2: procesamiento y conocimiento

El [README interno](layer2_knowledge/README.md) es una nota histórica congelada,
con su mención de Capa 3 como pendiente.
**No se actualiza por su protección histórica.** Estado vigente:
[arquitectura de Capa 2](../docs/architecture/layer2.md).

| Archivo | Responsabilidad |
|---|---|
| [pipeline.py](layer2_knowledge/pipeline.py) | Coordina snapshot → paquete → calidad → candidato/publicación con journal y rollback. |
| [validate_inputs.py](layer2_knowledge/validate_inputs.py) | Carga configuración, exige aprobación y lee exclusivamente canonical verificado. |
| [documents.py](layer2_knowledge/documents.py) | Construye documentos/secciones SOURCE y referencia INDICATOR_REFERENCE separada. |
| [text_normalization.py](layer2_knowledge/text_normalization.py) | Convierte listas/texto y normaliza conservadoramente sin interpretación semántica. |
| [chunking.py](layer2_knowledge/chunking.py) | Crea ventanas jerárquicas con límites, overlap y offsets trazables. |
| [graph_data.py](layer2_knowledge/graph_data.py) | Proyecta entidades y membresías explícitas; no infiere relaciones. |
| [contracts.py](layer2_knowledge/contracts.py) | Define los tipos Arrow y JSON de ocho tablas y manifest. |
| [provenance.py](layer2_knowledge/provenance.py) | IDs/hashes y linaje a campos de canonical, sin reabrir RAW. |
| [security.py](layer2_knowledge/security.py) | Excluye datos sensibles, aplica política de email y detecta fugas. |
| [quality.py](layer2_knowledge/quality.py) | Perfiles de texto, cobertura, calidad y cadena de procedencia. |
| [__init__.py](layer2_knowledge/__init__.py) | Identidad y versión de la capa. |

Entrada: siete tablas canonical y manifest aprobados. Salida: ocho tablas
SOURCE/REFERENCE/entities/relations en data/knowledge. Capa 3 las indexa; 4B usa
documentos y secciones completos. No ejecuta modelos ni asigna indicadores.

## Capa 3: GraphRAG

No se añade README al paquete: el fingerprint territorial compara todos los
archivos de este directorio protegido. Este índice documenta sus módulos sin
cambiar esa membresía. Arquitectura: [layer3.md](../docs/architecture/layer3.md).

| Archivo | Responsabilidad |
|---|---|
| [pipeline.py](layer3_graphrag/pipeline.py) | Plan/validate/build/query/evaluate y publicación de artefactos completos. |
| [configuration.py](layer3_graphrag/configuration.py) | Valida límites, rutas y gates de aprobación del snapshot. |
| [validate_inputs.py](layer3_graphrag/validate_inputs.py) | Lee ocho tablas knowledge, comprueba tipos, hashes y lineage. |
| [contracts.py](layer3_graphrag/contracts.py) | Define snapshots, bundles y contratos de embeddings/contextos/candidatos. |
| [embeddings.py](layer3_graphrag/embeddings.py) | Interfaz de proveedor, BGE-M3 lazy, fingerprints, cache y bundles verificables. |
| [vector_index.py](layer3_graphrag/vector_index.py) | Índice NumPy exacto de cosine, persistencia y validación de dimensiones. |
| [graph.py](layer3_graphrag/graph.py) | Construye/persiste el grafo factual y perfila topología e identidades. |
| [graph_retriever.py](layer3_graphrag/graph_retriever.py) | Expande seeds con límites y bridges permitidos; no resuelve identidades nuevas. |
| [retrieval.py](layer3_graphrag/retrieval.py) | Compone motores vector/hybrid, ranking y contexto de consultas. |
| [indicator_retrieval.py](layer3_graphrag/indicator_retrieval.py) | Queries REFERENCE, recheck semántico y candidatos agrupados por SOURCE+INDICATOR. |
| [source_context.py](layer3_graphrag/source_context.py) | Resuelve referencias a todas las secciones disponibles y separa orientación/sustancia. |
| [evaluation.py](layer3_graphrag/evaluation.py) | Métricas de retrieval con etiquetas explícitas; sin ground truth devuelve no evaluable. |
| [quality.py](layer3_graphrag/quality.py) | Integridad de índice/grafo/embeddings, provenance y privacidad de candidatos/contextos. |
| [security.py](layer3_graphrag/security.py) | Detecta contenido sensible y limita identificadores en la proyección del grafo. |
| [provenance.py](layer3_graphrag/provenance.py) | IDs, hashes y linaje técnico del retrieval. |
| [manifest.py](layer3_graphrag/manifest.py) | Manifests y comprobación física de artefactos publicados. |
| [operations.py](layer3_graphrag/operations.py) | Verify, compare, regresiones por procesos separados y aprobación del manifest. |
| [model_setup.py](layer3_graphrag/model_setup.py) | Descarga fijada, censo de tokens y calibración GPU al invocarse explícitamente. |
| [__init__.py](layer3_graphrag/__init__.py) | Versión de pipeline; importación sin cargar modelos. |

Flujo: chunks SOURCE + queries REFERENCE → vector → grafo/recheck → agrupación
SOURCE → contexto por campos → calidad/publicación. Entradas: knowledge aprobado
y modelo BGE-M3 local. Salidas: data/graphrag con índice/grafo/embeddings y
retrieval/source_indicator_candidates.parquet, source_context_packages.parquet.
Capa 4A resuelve sus referencias en Capa 2; no reconstruye el grafo.

## Ejecución

Usar [la guía principal](../README.md#ejecución-paso-a-paso). No ejecutar módulos
internos para eludir gates; los scripts publican, verifican o exportan según su CLI.
