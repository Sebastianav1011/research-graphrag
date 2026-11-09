# Schemas de Capa 2

## Propósito

Define formas lógicas de las ocho tablas knowledge y su manifest. SOURCE y
REFERENCE tienen estructuras semejantes, pero funciones y espacios separados.

## Archivos principales

| Archivo | Qué valida |
|---|---|
| [source_documents.schema.json](source_documents.schema.json) | Un documento PROJECT/ARTICLE, identidad canónica, metadata y linaje. |
| [source_sections.schema.json](source_sections.schema.json) | Campo fuente independiente, texto original/normalizado, hashes y orden. |
| [source_chunks.schema.json](source_chunks.schema.json) | Fragmentos SOURCE con offsets, overlap, hash y vínculo sección/documento. |
| [reference_documents.schema.json](reference_documents.schema.json) | Documento INDICATOR_REFERENCE del catálogo, separado del corpus SOURCE. |
| [reference_sections.schema.json](reference_sections.schema.json) | Campos originales/normalizados de la referencia y su procedencia. |
| [reference_chunks.schema.json](reference_chunks.schema.json) | Fragmentos REFERENCE usados para consultas, con offsets y linaje propios. |
| [entities.schema.json](entities.schema.json) | Entidades canónicas proyectadas al grafo con metadata/provenance. |
| [relations.schema.json](relations.schema.json) | Membresías factuales entre entidades, atributos y evidence_type. |
| [layer2_manifest.schema.json](layer2_manifest.schema.json) | Snapshot upstream, configuración, runtime, conteos, calidad y hashes de tablas. |

## Funcionamiento

[contracts.py](../../src/layer2_knowledge/contracts.py) es autoridad compartida de
Arrow/JSON. El pipeline valida tablas, roundtrip y hashes antes de publicar; la
validación estructural se complementa con claves, privacidad y lineage.

## Entradas y salidas

Registros de data/knowledge y manifest; errores ante columnas/tipos incompatibles.
Los textos SOURCE y REFERENCE no se concatenan ni se intercambian de espacio.

## Relación con otras capas

Capa 2 publica estas formas desde canonical. Capa 3 valida las ocho tablas;
Capa 4B lee los documentos/secciones SOURCE.

## Ejecución

Desde la raíz: `uv run python scripts/build_layer2_contracts.py --check`.
Sin --check regenera JSON; no publica datos.
