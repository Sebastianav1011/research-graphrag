# Contrato oficial de conocimiento de Capa 2

Contrato integrado con el canonical real oficial. Autoridad ejecutable: contracts.py en
src/layer2_knowledge. Nueve JSON Schemas derivados en schemas/layer2, generados con
`python scripts/build_layer2_contracts.py`; `--check` detecta drift sin reescribirlos.
Los ocho Parquet están publicados en data/knowledge/. Sus conteos y huellas se
registran en _manifest.json y outputs/layer2/reports/acceptance.json al cierre.

## Tipos y reglas comunes

string = Arrow UTF-8; integer = Arrow int64 no negativo. Solo title, label y
text_original admiten NULL donde existan. JSON se almacena como string JSON válido.
Todos los campos enumerados son obligatorios en output, sin columnas extra; los
datasets vacíos conservan su schema. Las claves IDs son únicas por tabla.
Todo registro contiene provenance_json y layer2_run_id no nulos. canonical_run_id
aparece en documentos; layer1_run_id está en provenance de todos los outputs.

## source_documents.parquet / reference_documents.parquet

| Campo | Tipo | Significado |
| --- | --- | --- |
| document_id | string | Clave DOC_tipo_id determinística escapada |
| source_id | string | ID canónico literal |
| source_type | string | PROJECT/ARTICLE en source; INDICATOR_REFERENCE en reference |
| title | string nullable | label_field configurado sin fallback inventado |
| canonical_dataset | string | Nombre de dataset canónico sin extensión |
| canonical_run_id | string | Run ID de Capa 1 |
| metadata_json | string | Campos configurados presentes, NULL conservado |
| provenance_json | string | Extensión de procedencia con document_id |
| layer2_run_id | string | Ejecución operativa |

Un proyecto o artículo produce un source document; un indicador un reference document.
No hay documentos de investigadores/organizaciones. Identificadores técnicos son metadata.

## source_sections.parquet / reference_sections.parquet

| Campo | Tipo | Significado |
| --- | --- | --- |
| section_id | string | Clave SEC_tipo_id_campo escapada |
| document_id | string | FK documento del mismo scope |
| source_id | string | ID canónico literal |
| source_type | string | Igual a documento del mismo scope |
| field_name | string | Nombre canónico exacto |
| field_order | integer | Índice configurado base cero; ausencias pueden dejar huecos |
| text_original | string nullable | Texto canónico antes de normalización L2, con exclusión de emails autorizada |
| text_normalized | string | Texto normalizado; NULL original produce vacío |
| char_count | integer | Puntos de código de normalizado |
| word_count | integer | Coincidencias Unicode `\S+` |
| text_hash | string | Alias de text_hash_normalized |
| text_hash_original | string | SHA-256 UTF-8 original (NULL se hashea como vacío) |
| text_hash_normalized | string | SHA-256 UTF-8 normalizado |
| provenance_json | string | document/section/source_field/representación/hashes/upstream |
| layer2_run_id | string | Ejecución operativa |

Keywords list<string> se representa por unión con saltos de línea. La lista original
permanece en provenance L1, no se convierte usando repr. Nunca se mezclan campos.
OPTIONAL ausente no produce sección; columna presente NULL produce sección vacía.

## source_chunks.parquet / reference_chunks.parquet

| Campo | Tipo | Significado |
| --- | --- | --- |
| chunk_id | string | Clave tipo/id/campo/índice/hash determinística |
| section_id | string | FK sección del mismo scope |
| document_id | string | FK documento del mismo scope |
| source_id | string | ID canónico literal |
| source_type | string | PROJECT/ARTICLE o INDICATOR_REFERENCE según scope |
| field_name | string | Campo exacto, igual a sección |
| chunk_index | integer | Base cero por sección |
| text | string | Substring contiguo normalizado |
| char_start | integer | Inicio inclusivo normalizado |
| char_end | integer | Final exclusivo normalizado |
| word_count | integer | Incluye overlap |
| overlap_word_count | integer | Palabras compartidas con ventana anterior |
| chunk_hash | string | SHA-256 UTF-8 completo de text |
| provenance_json | string | Cadena completa, hashes y offsets |
| layer2_run_id | string | Ejecución operativa |

Reglas en [chunking_contract.md](chunking_contract.md). **Solo source_chunks puede
proveer futura evidence_text. Reference chunks nunca acreditan cumplimiento**.

## entities.parquet

| Campo | Tipo | Significado |
| --- | --- | --- |
| entity_id | string | Clave literal TIPO:canonical_id |
| entity_type | string | PROJECT, ARTICLE, RESEARCHER, ORGANIZATION, INDICATOR |
| canonical_id | string | Identidad de Capa 1, sin segunda resolución |
| label | string nullable | Campo configurado, sin inventar etiqueta |
| metadata_json | string | Metadata explícita sin campos personales excluidos |
| provenance_json | string | Dataset/id/run/config + upstream |
| layer2_run_id | string | Ejecución operativa |

AMBIGUOUS/UNRESOLVED son ocurrencias existentes, no identidades confirmadas.
identity_status/rule permanecen en metadata. institutional_id puede ser metadata
técnica; document_number/email no se promueven. Esta tabla no es un grafo construido.

## relations.parquet

| Campo | Tipo | Significado |
| --- | --- | --- |
| relation_id | string | REL_SHA256 de source/tipo/target/atributos en JSON estable |
| source_entity_id | string | FK PROJECT o ARTICLE |
| relation_type | string | PROJECT_HAS_RESEARCHER o ARTICLE_HAS_RESEARCHER |
| target_entity_id | string | FK RESEARCHER |
| attributes_json | string | role/is_responsible o author_position/affiliation, NULL conservado |
| evidence_type | string | Constante STRUCTURED_CANONICAL |
| provenance_json | string | Dataset, clave compuesta, hash y upstream |
| layer2_run_id | string | Ejecución operativa |

Una relación por fila canónica de membresía; atributos participan en clave lógica.
Ninguna relación hacia INDICATOR, ni territorio/similitud/proyecto-artículo inferidos.

## Provenance JSON

Objeto con layer1_run_id, layer2_run_id, canonical_dataset, canonical_id, config_version,
config_hash y layer1: proyección de las ocurrencias originales de Capa 1.
Cada ocurrencia conserva archivo/fila/hoja y mappings/valores originales de campos
pertinentes. Los originales upstream completos permanecen intactos en canonical;
layer1_provenance_hash registra SHA-256 de su JSON exacto. lineage_fields declara los
campos transportados y lineage_projection=canonical_fields_v1 identifica la proyección.
No se copian documentos personales/emails/identificadores de registros ajenos a la evidencia.
source_record_id no se transporta: archivo/fila/hoja e ID canónico localizan el origen
sin difundir identificadores personales incluidos en algunas ocurrencias.
canonical_id de relación es `[source_id, target_id, attributes]` (clave compuesta).
Documentos añaden document_id; secciones section_id/source_field/hashes;
chunks chunk_id/chunk_hash/char_start/char_end/offset_basis/overlap_word_count.
Documentos transportan texto/metadata permitidos. Secciones/chunks solo transportan su
campo textual; entidades sus atributos permitidos y relaciones sus claves/atributos.
Calidad compara cada proyección con fila canónica y hash, además de enlaces/mappings.
Todas las ocurrencias siguen localizables, incluido el origen de títulos enriquecidos.

El usuario autorizó el 2026-10-05 sustituir exclusivamente emails explícitos por
[EMAIL_EXCLUDED], conservando el resto del texto. Se aplicó a seis abstracts, sus
secciones/chunks y valores originales pertinentes en provenance. Canonical no cambia.
text_hash_original corresponde al text_original almacenado tras esa exclusión;
text_hash_normalized al normalizado. Provenance añade text_hash_input del texto
canónico previo a exclusión y email_redactions por sección. Ocurrencias añaden
privacy_redactions con campo original, count, patrón e input_value_sha256, sin emails.
NULL, vacío y campo inexistente mantienen su distinción. El paquete sigue privado
porque entidades contienen nombres y claves técnicas para hechos estructurados.
No indexar provenance/metadata como corpus.

## _manifest.json

Schema SUCCESS real: schemas/layer2/layer2_manifest.schema.json. Campos requeridos:

- layer2_run_id, pipeline_version, started_at, finished_at, status=SUCCESS,
  publication_kind=real.
- layer1_manifest_path, layer1_run_id, layer1_manifest_hash, layer2_config_hash.
- input_datasets, input_row_counts, input_hashes.
- source_documents_created, source_sections_created, source_chunks_created,
  reference_documents_created, reference_sections_created, reference_chunks_created,
  entities_created, relations_created.
- quality_summary, output_files, output_hashes, payload_hashes, code_hashes, runtime.

previous_publication_compatible compara snapshot/config con manifest previo.
output_hashes son hashes físicos de ocho Parquet; payload_hashes omite únicamente
campos operacionales L2. El manifest no se hashea a sí mismo. Metadata operacional
adicional se permite. Archivo por ejecución: outputs/layer2/manifests/run_<UTC>.json.
Un intento fallido de publicación genera manifest FAILED diagnóstico; nunca se publica
en data/knowledge y no cumple el schema SUCCESS.

## Consumo y aceptación

Respetar lock/journal de publicación antes de leer; exigir SUCCESS, schemas, hashes
y separación SOURCE/REFERENCE. Nueva Capa 1 requiere revisión y ejecución nuevas.
evidence_source_field deriva de field_name/mapping original, nunca de mecanismos
analíticos. No leer RAW. Schemas y mappings se verificaron físicamente sobre el snapshot
run_20261005_194411_225750. Parámetros calibrados: 220/340/20 palabras; las cantidades
e identidades de investigadores no son un contrato fijo para publicaciones futuras.
