# Índice documental

Cierre actual de 4A: [procedimiento V2](methodology/layer4_closure_v2.md) y
[assessment/confianza V2](contracts/layer4_assessment_v2_contract.md).
Su aceptación está pendiente; las actas históricas siguen describiendo sus versiones.

## Propósito

Permite navegar arquitectura, contratos y actas sin confundir una descripción
histórica con el estado del código actual. La instalación y ejecución vigente
comienza en el [README principal](../README.md); las responsabilidades por archivo,
en los [README de src](../src/README.md).

## Archivos principales

### Orientación y decisiones

| Documento | Responsabilidad |
|---|---|
| [CODE_MAP.md](CODE_MAP.md) | Mapa detallado de responsabilidades/consumidores y decisiones del refactor, incluida la integración DANE y la separación de Capa 4. |
| [RUNBOOK.md](RUNBOOK.md) | Procedimientos de aprobación, datos privados, snapshots, locks y reproducción Windows; algunas secciones describen fases previas al adaptador provisional de 4A. Para comandos actuales usar el README raíz. |
| [identity_alias_audit.md](identity_alias_audit.md) | Análisis técnico de aliases de identidad y decisiones de dominio, no un paso del pipeline. |
| [data_dictionary/data_dictionary.csv](data_dictionary/data_dictionary.csv) | Diccionario de campos canónicos y plantilla histórica; generado por build_contracts.py. |

### Arquitectura

| Documento | Qué explica |
|---|---|
| [architecture/layer1.md](architecture/layer1.md) | ETL, identidad, validación, calidad, publicación y extensión DANE. |
| [architecture/layer2.md](architecture/layer2.md) | Preparación SOURCE/REFERENCE, chunking, provenance, privacidad y gates. |
| [architecture/layer3.md](architecture/layer3.md) | Recuperación chunk-level, agrupación SOURCE, contexto por campos y publicación GraphRAG. |
| [architecture/layer3_source_level_acceptance.md](architecture/layer3_source_level_acceptance.md) | Cierre histórico SOURCE_INDICATOR_V1 y separación discovery/evidencia/confianza. |
| [architecture/layer4.md](architecture/layer4.md) | Ramas indicators/territories, alcance provisional de 4A, política territorial e historia de migración. |

Los documentos de Capa 3 y su aceptación SOURCE-level se conservan con los hashes
históricos que comprueban los verificadores. Su mención de assessment futuro y
perfiles PENDING_GROUP_REVIEW corresponde a ese cierre de retrieval: no describe
la preparación v2 ni el preliminar técnico posterior de 4A. Para ese estado y la
revalidación territorial vigente, consultar [Capa 4](architecture/layer4.md).
La sección fechada de aceptación de Capa 2 conserva las métricas de su snapshot;
sus fronteras de consumo se describen en presente en el mismo documento.

### Contratos

| Documento | Qué fija |
|---|---|
| [contracts/canonical_data_contract.md](contracts/canonical_data_contract.md) | Identidades, hechos, campos, relaciones y procedencia canónica. |
| [contracts/layer2_knowledge_contract.md](contracts/layer2_knowledge_contract.md) | Ocho tablas de conocimiento y sus fronteras de consumo. |
| [contracts/chunking_contract.md](contracts/chunking_contract.md) | Normalización, cortes, offsets y conservación del texto. |
| [contracts/layer3_graphrag_contract.md](contracts/layer3_graphrag_contract.md) | Artefactos y garantías del pipeline GraphRAG. |
| [contracts/graph_contract.md](contracts/graph_contract.md) | Entidades, relaciones factuales y expansión del grafo. |
| [contracts/retrieval_contract.md](contracts/retrieval_contract.md) | Recuperación, ranking y contexto SOURCE sin assessment. |
| [contracts/layer4_indicator_profiles_contract.md](contracts/layer4_indicator_profiles_contract.md) | Catálogo v2, elementos explícitos, RULE_TEXT y preferencias no inferidas. |
| [contracts/layer4_assessment_contract.md](contracts/layer4_assessment_contract.md) | Decisiones/strength, proveedor neutral y citas comprobables. |
| [contracts/layer4_confidence_contract.md](contracts/layer4_confidence_contract.md) | RAW_CONFIDENCE_V1, K/F/C/S, gates y futura calibración; las rutas originales del paquete describen su implementación previa archivada. |
| [contracts/layer4_output_contract.md](contracts/layer4_output_contract.md) | Datos de las cuatro hojas y metadata de exportación reusable. |
| [contracts/layer4_powerbi_contract.md](contracts/layer4_powerbi_contract.md) | Proyección de consumo de resultados preliminares y territorios. |
| [contracts/final_output_contract.md](contracts/final_output_contract.md) | Plantilla histórica vacía Proyectos/Artículos; no equivale al workbook preliminar de cuatro hojas. |

### Historia y pendientes

| Documento | Alcance |
|---|---|
| [status/layer3_source_refactor_review.md](status/layer3_source_refactor_review.md) | Cronología y motivos del refactor SOURCE-level; no es una arquitectura alternativa activa. |
| [status/layer4_territory_v1_acceptance.md](status/layer4_territory_v1_acceptance.md) | Aceptación territorial histórica de una publicación/fingerprint concretos. |
| [status/layer4_territory_migrated_real_acceptance.md](status/layer4_territory_migrated_real_acceptance.md) | Aceptación real del código territorial migrado en copias aisladas; no reescribe la publicación histórica. |
| [status/layer1_dane_unification_acceptance.md](status/layer1_dane_unification_acceptance.md) | Revalidación posterior de DANE integrado en Capa 1 y de su consumidor territorial, sin sustituir publicaciones vigentes. |
| [pending/indicator_profiles.md](pending/indicator_profiles.md) | Reserva PENDING_GROUP_REVIEW de Capa 3; distinguir de perfiles operacionales v2 de assessment. |

No se crean índices adicionales en architecture/contracts/status: este README ya
describe sus documentos y evita repetir navegación. data_dictionary y pending
tienen un único archivo relevante, explicado aquí.

## Funcionamiento

Leer arquitectura para comprender fronteras → contrato para modificar formas y
reglas → README de código/tests para localizar implementación → acta para conocer
qué snapshot fue aceptado. Un acta histórica no autoriza relajar fingerprints.

## Entradas y salidas

Documentos versionados y referencias a evidencias privadas. Los manifests,
resultados, JUnit y baselines citados bajo outputs/data no vienen con un clon
público ni deben copiarse a esta carpeta.

## Relación con otras capas

Cada capa conserva su contrato. [history.py](../src/layer4/history.py) espera
originales ZIP en `archives/layer4/` para verificar bytes sin importarlos. Esos
archivos no están incluidos; las verificaciones históricas y pruebas de migración
que dependan de ellos requieren obtenerlos por un canal autorizado. El README
congelado de Capa 2 y los directorios protegidos de Capa 3 se documentan
actualmente desde sus README padres para no cambiar hashes/inventarios.

No se ejecuta ningún pipeline desde este índice.
