# Descubrimiento GLOBAL_DISCOVERY_V3_3

Estado: implementado y probado con datos sintéticos; no ejecutado sobre proyectos.
Versión optativa en `src/layer4/indicators/global_discovery_v3_3.py`.
GLOBAL_DISCOVERY_V3, sus planes congelados y sus resultados siguen inalterados.

## Pertinencia antes del assessment

Codex revisa los 48 perfiles y clasifica cada uno. DIRECT_EVIDENCE describe una
actividad, mecanismo, enfoque o resultado relacionado concretamente con un requisito.
PARTIAL_RELEVANT conserva vínculos específicos verificables con información faltante.
Solo estas clases pueden estar en candidates, sean ASSESS o BACKLOG.
THEMATIC_SIMILARITY, SPECULATIVE_RELATION y NO_RELATION van a rejected con una razón.
Las propuestas concretas no se descartan automáticamente: se conserva su temporalidad
y se explica el vínculo. Un beneficio hipotético o la coincidencia de sector no basta.

Cada candidato declara relevance_class y criterion_links, con criterion_id,
criterion_text exacto, evidence_indices y correspondence. Los identificadores y textos
se obtienen del mismo catálogo de criterios que utiliza V3; esto no modifica sus roles,
requisitos temporales ni rúbricas. Cada vínculo referencia una cita sustantiva literal.
Python verifica estructura, citas, referencias, identidades, categorías y procedencia.
No comprueba semánticamente la explicación ni asigna pertinencia por palabras clave.
Una declaración estructuralmente válida sigue requiriendo control de calidad semántica.

El máximo de seis es un límite, sin mínimo obligatorio. Cero candidatos es válido.
No se usan confianza, longitud textual, cuota ni categoría para asignar pertinencia.
GraphRAG solo aporta procedencia después de la selección: no es una lista obligatoria
ni una vía de excepción. Los perfiles son examinados en condiciones iguales.

## Uso posterior y separación histórica

`make_input`, `selection_schema`, `validate_selection` y `make_provider` exponen la
versión nueva. `assessment_batches` valida la respuesta completa y entrega únicamente
los IDs ASSESS en lotes de hasta tres; devuelve [] cuando no hay priorizados.
La construcción del proveedor no ejecuta inferencia.

El coordinador histórico no exige completar seis: recorre solo prioritized_ids.
No se cambia ese archivo porque su hash está congelado en los planes existentes.
Una futura prueba debe vincular explícitamente el nuevo input, schema, marcador y
handoff `assessment_batches` en un plan/autorización versionados; no basta cambiar
el import del plan histórico ni reutilizar su autorización para inputs diferentes.
Esta entrega no prepara ni activa ese plan, no modifica resume_state.json de
PROJ_20899 y no ejecuta sus argumentos históricos.

Los assessments conservan SUPPORTED, INSUFFICIENT_EVIDENCE y NOT_SUPPORTED, decididos
por Codex. La confianza sigue siendo 100 × (0.55 S + 0.45 K), posterior al assessment
válido, y nunca interviene en la selección. Los resultados históricos no se eliminan,
reclasifican ni regeneran con esta política.

## Evidencia y límites de las pruebas

Las pruebas localizadas cubren cero a seis priorizados, no completar el límite,
backlog pertinente, clases excluidas para ambos orígenes, criterio y cita obligatorios,
temporalidad propuesta, transporte simulado y handoff al assessment. También se
comprueba compatibilidad con descubrimiento/coordinador históricos. Estas pruebas
no demuestran que una LLM distinguirá correctamente todos los casos semánticos.

La revisión documental de las 20 relaciones se conserva en
`outputs/layer4/pruebas/validacion_v3_3/revision_pertinencia_v3_3.md`.
