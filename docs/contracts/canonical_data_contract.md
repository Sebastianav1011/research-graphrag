# Contrato canónico Capa 1, versión 1.0

**Capa 2 NO puede leer RAW. Capa 2 NO debe leer directamente los archivos RAW.**
Su única entrada documental autorizada es data/canonical/, incluidos los valores originales
y mapeos almacenados en provenance_json. Ni descriptores-limpio.csv ni produccion-limpio.csv
ni staging son entradas de las capas posteriores.

## Datasets y claves

| Parquet | Representación | Clave |
| --- | --- | --- |
| proyectos | Proyectos descritos en la fuente | project_id |
| articulos | Producción institucional (incluye otros tipos documentales) | article_id |
| investigadores | Identidades resueltas y ocurrencias ambiguas/no resueltas | researcher_id |
| organizaciones | Facultades/dependencias explícitas | organization_id |
| proyecto_investigador | Membresías explícitas dentro de la cobertura de proyectos | project_id + researcher_id + role + is_responsible |
| articulo_investigador | Autor/investigador explícito de la fila de producción | article_id + researcher_id + author_position + affiliation |
| indicadores | Catálogo estructurado de referencia, sin asignaciones | indicator_id |

Los atributos nulos participan en la unicidad lógica de relaciones. No se inventa
un rol ni una posición. Las relaciones mantienen integridad referencial a sus entidades.
No existe dataset proyecto-artículo ni vínculo inferido entre ellos. Tampoco existen
relaciones semánticas, indicadores detectados, territorios inferidos o scores.

## Fuentes y mapeo local verificado

proyectos proviene de descriptores-limpio.csv: id_actividad → source_project_id;
resumen → summary; metodologia → methodology; objetivos → objectives;
resultados_investigacion → expected_results; palabras_clave → keywords;
objetivo_socioeconomico → socioeconomic_objective; gran_area → knowledge_area;
area_conocimiento → knowledge_subarea. Esta fuente no incluye título ni fechas.
El título se enriquece con miembros.titulo por descriptores.id_actividad = miembros.id_actividad,
llave institucional confirmada del mismo proyecto. Fechas ausentes permanecen NULL.
No se usa convocatoria_nombre como título.

articulos proviene de produccion-limpio.csv: nombre_producto → title;
resumen → abstract; anio → publication_year; tipo_documental → document_type;
nombre_revista_libro → journal; doi, eid, issn_isbn y palabras_clave conservan su significado.
No existe ID genérico de producción configurado: source_article_id queda NULL.
La cédula y el nombre de la fila alimentan identidad y relación explícita.

investigadores se alimenta de una o varias fuentes configuradas; localmente se verificó
miembros-doc-limpio.csv. id_empleado, documento, tipo_documento y nombre_completo son
los campos de identidad del miembro. Se retiran comillas literales envolventes de esos
campos mediante configuración, manteniendo su original. Está confirmada la equivalencia
id_investigador ≡ id_empleado: ambos se mapean a institutional_id mediante aliases explícitos.
Son nombres del MISMO atributo, sin namespaces separados; coexistir con el mismo valor
no genera conflicto ni identidades adicionales. researcher_id es la llave técnica generada
por el pipeline, distinta del identificador institucional de origen.
Si falta uno se utiliza el otro; si difieren se conserva la contradicción, institutional_id
queda NULL en esa ocurrencia y se bloquea la fusión del componente relacionado.
cedula, documento, id_documento y numero_documento se mapean a document_number cuando
la configuración declara que son documentos personales del investigador/empleado.
cedula_empleado ≡ cedula_investigador también son aliases de nomenclatura de document_number;
no aparecen actualmente en estas fuentes y no se agregan mapeos hacia columnas ausentes.
No se descubren aliases por semejanza ni se mezclan con institutional_id.
id_actividad, rol_miembro y responsable alimentan membresías; facultad y
departamento_academico alimentan organizaciones. También se incorporan identidades
explícitas en producción, sin adivinar las listas de coautores.

indicadores proviene exclusivamente de Catalogo_Indicadores en el XLSX conservado:
id_indicador, categoria, ambito, indicador y tipo. Las otras columnas originales se
conservan en provenance_json. El texto oficial completo se usa como indicator_name;
no se genera una descripción corta artificial. Este catálogo de referencia contiene 48 filas; Capa 1 conserva su contenido
y no certifica externamente su vigencia.

## Tipos y nullabilidad

El diccionario CSV enumera cada columna de los siete datasets. JSON Schemas y el esquema
Arrow explícito definen tipos incluso en tablas sin filas. Strings vacíos configurados pasan
a NULL; no se convierten automáticamente palabras como 'No aplica' en información ausente.
keywords es list<string>; publication_year, source_row y author_position son int64;
is_responsible es boolean; fechas son strings ISO YYYY-MM-DD.

Son obligatorios los IDs canónicos, record_source, source_row, etl_run_id y provenance_json.
Además: source_project_id en proyectos; title en artículos; identity_status/identity_rule
en investigadores; nombre/nombre normalizado/tipo en organizaciones; indicator_name en
indicadores; ambas claves referenciadas en las relaciones. El resto puede ser NULL.
Los campos opcionales ausentes son NULL, nunca datos fabricados.

## Identificadores estables

PROJ_ + ID institucional escapado sin pérdida identifica proyectos.
Artículos priorizan ART_SRC_<id> explícito, luego ART_<eid>, luego ART_DOI_<hash>;
sin identificador válido usan ART_HASH_<hash de ruta y fila original completa>.
RES_<hash> usa el ancla de identidad más fuerte; para ambiguos/no resueltos usa ruta,
línea y contenido original. ORG_<hash> incluye tipo, nombre normalizado, padre y país.
Los hashes usan SHA-256 truncado a 24 hexadecimales sobre JSON UTF-8 determinístico.
Los códigos de indicadores se conservan literalmente desde el catálogo.

Mismos archivos/rutas y configuración producen mismos IDs y datos, salvo etl_run_id.
No se garantiza estabilidad de IDs de ocurrencias si se mueve o reordena la fuente; no son
identidades personales confirmadas. Añadir evidencia más fuerte puede cambiar el ancla de
una persona. Esa migración requiere una decisión posterior de gobernanza, no coincidencias
semánticas automáticas. El run_id usa timestamp UTC con microsegundos y no interviene
en hashes de entidades. Los Parquet no se acumulan entre ejecuciones.

## Procedencia y garantías

record_source/source_row apuntan a la primera ocurrencia según ruta y fila.
source_record_id guarda el ID original si existe. provenance_json almacena todas las
ocurrencias con original_values, field_mapping y source_sheet. Esto conserva incluso campos
no promovidos a columnas canónicas y textos originales antes de normalizar.
Cada archivo fuente tiene SHA-256, tamaño, dominio, filas leídas, encoding/delimitador cuando
aplica y fecha en el manifest. La ejecución verifica que las huellas no cambien.

Para consumir la instantánea, comprobar canonical/_manifest.json (SUCCESS), las huellas y
la cobertura de dominios habilitados. Consultar latest_run.json para detectar intentos
posteriores fallidos. Un dataset vacío puede significar fuente deshabilitada o falta de
registros aceptados; no demuestra ausencia institucional.

Capa 2 no debe asumir identidad confirmada para ambiguous/unresolved, exactitud semántica,
títulos completos, cobertura universal, DOI registrado en una agencia, validez de dígitos
de control de documentos/ISSN/ISBN, autoría de coautores no estructurados, ni que un proyecto
cumple un indicador. Capa 1 solo asegura estructura, normalización explicable y trazabilidad.

## Decisiones finales de dominio (2026-10-05)

### Título y procedencia

Miembros declara project_title: titulo y source_project_id: id_actividad. Se consideran
todas sus filas interpretadas con llave válida, independientemente de la resolución de
identidad personal. Solo se enriquecen proyectos canónicos sin título; no se crean proyectos
ni relaciones a partir del título. Repeticiones equivalentes son normales.
Para comparar se usa Unicode NFC, espacios normalizados, retiro de comillas dobles
envolventes del formato conocido y casefold, sin eliminar acentos ni usar similitud.
Si existe un único título equivalente se publica el texto ORIGINAL de la primera fila
por ruta/hoja/fila, incluidos sus espacios y comillas originales. Más de un título distinto
produce PROJECT_TITLE_CONFLICT (WARNING), title NULL y conserva todos los títulos y filas
en provenance_json y en el reporte. Sin título disponible se conserva NULL en completitud.
record_source/source_row siguen apuntando a descriptores. provenance_json añade miembros
con field_mapping.title = titulo, field_mapping.source_project_id = id_actividad y
enrichment con campo, llave, valor y estado CONSISTENT/CONFLICT. project_id no cambia.

### Identidad definitiva

1. institutional_id válido exacto identifica una persona salvo contradicciones.
2. document_number válido exacto identifica una persona salvo contradicciones.
3. Si ambos existen, deben ser compatibles en todo el componente antes de fusionar.
4. Un mismo institutional_id con documentos diferentes bloquea la fusión.
5. Un mismo documento con institutional_id diferentes bloquea la fusión.
6. Nombre solo nunca fusiona; repeticiones sin corroboración son candidatos ambiguos.
7. Nombre + email exacto permite exact_name_and_email. Se conserva exact_external_id
   para fuentes explícitas del mismo espacio de nombres. Ninguna supera contradicciones.

RESOLVED (valor canónico resolved): evidencia estructurada suficiente.
AMBIGUOUS (ambiguous): candidatos múltiples o evidencia contradictoria.
UNRESOLVED (unresolved): evidencia insuficiente. Se conserva la codificación minúscula
del contrato. Un nombre solo sin otros candidatos queda unresolved; repeticiones sin
corroboración quedan como ocurrencias ambiguous, nunca fusionadas.
identity_rule explica la resolución. manifest/summary incluyen conflict_occurrences_by_field;
audit indica campos incompatibles sin imprimir documentos personales. Todos los aliases
de una fila participan en la validación; no se ocultan contradicciones entre ellos.
IDs de ocurrencias dependen de fuente/hoja/fila/contenido. Nueva evidencia institucional puede
cambiar el ancla RES_ o consolidar ocurrencias: se mide por procedencia y se documenta.
No hay registro persistente de aliases de researcher_id entre versiones.
La auditoría vigente de nomenclatura, discrepancias materiales de las columnas fuente y
efecto de la política de bloqueo está en ../identity_alias_audit.md.

### Conflictos de producción y resoluciones futuras

Versiones incompatibles bajo el mismo ID siguen en cuarentena; no se elige la más larga,
reciente, parecida ni una respuesta de LLM. quality/production_conflicts.csv proyecta la
decisión CONFLICTING_SOURCE_ID de canonical_entities, sin un segundo resolver.
Una fila por ocurrencia rechazada contiene source_id, source_file, source_row, title, year,
doi, eid, conflict_type, conflict_group, resolution_status y description.
conflict_group es la clave canónica candidata; resolution_status es UNRESOLVED.
Originales previos a normalización permanecen en rejected_records.jsonl y staging.
Los CSV neutralizan prefijos de fórmulas para inspección y permanecen privados.
Se reserva conceptualmente config/resolutions/production_conflicts.csv para una futura
resolución institucional explícita con autoridad, fecha, evidencia, huella de la fuente y
versiones afectadas. No hay lector ni decisiones aplicadas: crear ese archivo NO resuelve
casos. El soporte futuro deberá validar huellas/vigencia y auditar sin editar RAW.

### Ausencias legítimas

Solo se enriquece desde fuentes estructuradas confiables mediante llave explícita y regla
documentada. El resto permanece NULL o como conflicto. No se usan inferencia semántica,
placeholders ni campos parecidos. RAW permanece inmutable; Capa 2 solo puede leer canonical
y su procedencia, nunca RAW ni staging. La plantilla de resultados permanece vacía.
