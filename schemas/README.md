# Schemas y contratos de datos

## Propósito

Un schema declara la estructura que debe tener un dato: nombres y tipos de
campos, propiedades obligatorias, valores permitidos y restricciones. Permite
detectar un registro incompleto o incompatible antes de publicarlo o consumirlo.

**Schema** es la regla; **datos** son las filas concretas que deben cumplirla;
**código** es quien genera, transforma y valida esas filas. Un schema no es un
dataset, no ejecuta el pipeline y no demuestra que una cita sea verdadera.

## Archivos principales

### Contratos canónicos y plantilla histórica

| Archivo | Qué valida |
|---|---|
| [proyecto.schema.json](proyecto.schema.json) | Identidad PROJECT, campos descriptivos, keywords y procedencia canónica. |
| [articulo.schema.json](articulo.schema.json) | ARTICLE, metadata bibliográfica, abstract, keywords y procedencia. |
| [investigador.schema.json](investigador.schema.json) | Identificadores personales/institucionales, estado y regla de identidad, con provenance. |
| [organizacion.schema.json](organizacion.schema.json) | Identidad, tipo y contexto explícito de organización. |
| [indicador.schema.json](indicador.schema.json) | Catálogo canónico de indicadores, nombre/category/dimension y fuente. |
| [relationships.schema.json](relationships.schema.json) | Contratos de membresía proyecto-investigador y artículo-investigador. |
| [final_output.schema.json](final_output.schema.json) | Forma de la plantilla histórica Proyectos/Artículos, vacía en Capa 1; no acredita resultados finales de 4A. |

### Familias

| Familia | Capa / responsabilidad |
|---|---|
| [layer2](layer2/README.md) | Documentos/secciones/chunks SOURCE y REFERENCE, entidades, relaciones y manifest. |
| [layer3](#capa-3-contratos-protegidos) | Embeddings, consultas, contexto y candidatos SOURCE+INDICATOR. |
| [layer4_confidence](layer4_confidence/README.md) | Entrada mínima y salida del cálculo RAW_CONFIDENCE_V1. |
| [layer4_assessment](layer4_assessment/README.md) | Perfiles operacionales, assessment, filas técnicas y workbook reusable. |
| [layer4_preliminary](layer4_preliminary/README.md) | Lotes de transporte y diagnósticos del preliminar. |

Un nombre repetido no implica duplicación: indicator_profile de Capa 3 es una
reserva congelada; el de confidence contiene solo elementos/preferencias; el
de assessment conserva el perfil v2 y su procedencia. Lo mismo ocurre con las
formas de assessment y de resultado preliminar.

## Funcionamiento

Las autoridades Python de contracts definen los tipos Arrow y/o JSON. Los
constructores exportan schemas; los checks detectan drift sin reescribirlos.
Los validadores aplican además reglas que JSON Schema no puede resolver por
sí solo: citas contra campos reales, claves externas, hashes, offsets,
pertenencia al catálogo y consistencia de publicaciones.

## Entradas y salidas

Recibe registros o manifests para validación. Produce errores o confirma
compatibilidad estructural; los JSON son definiciones versionadas. Los contratos
Arrow de territorio viven en [contracts.py](../src/layer4/territories/contracts.py)
y DANE en [dane_reference.py](../src/layer1_data/dane_reference.py): no existe una
familia JSON territorial independiente que deba inventarse.

## Relación con otras capas

Capa 1 fija hechos canónicos; Capa 2 conserva textos y linaje; Capa 3 describe
retrieval, no evidencia confirmada; Capa 4 valida assessment/confianza y proyecciones
de consumo. Los datos institucionales que cumplen estas formas siguen siendo privados.

## Capa 3: contratos protegidos

No se añade README dentro de schemas/layer3: su inventario completo participa
en el fingerprint territorial protegido.

| Archivo | Qué valida |
|---|---|
| [embedding.schema.json](layer3/embedding.schema.json) | Relación embedding–chunk, espacio SOURCE/REFERENCE, modelo, revisión, hashes y dimensiones. |
| [evaluation_query.schema.json](layer3/evaluation_query.schema.json) | Query, tipo y ground truth explícito para experimentos de retrieval. |
| [context_package.schema.json](layer3/context_package.schema.json) | Paquete de consulta con hits, entidades, relaciones, candidatos/contextos SOURCE y métricas. |
| [source_indicator_candidate.schema.json](layer3/source_indicator_candidate.schema.json) | Par SOURCE+INDICATOR, discovery chunks, ranking, scores y referencias al contexto. |
| [source_context_package.schema.json](layer3/source_context_package.schema.json) | Secciones disponibles por SOURCE, roles de campos, context_status y hash del contexto. |
| [layer3_manifest.schema.json](layer3/layer3_manifest.schema.json) | Snapshot/modelo/configuración, conteos, artefactos y hashes de publicación GraphRAG. |
| [indicator_profile.schema.json](layer3/indicator_profile.schema.json) | Reserva PENDING_GROUP_REVIEW de la arquitectura histórica; no reemplazar por perfiles v2 de assessment. |

## Ejecución

Solo comparar contratos exportables:

```powershell
python scripts/build_layer2_contracts.py --check
python scripts/build_layer3_contracts.py --check
python scripts/build_layer4_contracts.py --check
```

Sin --check esos scripts escriben JSON. build_contracts.py también puede
reescribir plantilla/diccionario y no tiene --check. RAW_CONFIDENCE_V1 tiene
schemas propios, no regenerados por build_layer4_contracts. Para modificar un
contrato, revisar autoridad Python, consumidores y tests antes de regenerar.
Esta tarea documental no modifica JSON.
