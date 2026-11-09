# Arquitectura de Capa 1

Proyecto: Analítica de datos para la caracterización de la investigación y la identificación
de su impacto regional en la Vicerrectoría de Investigación de la Pontificia Universidad Javeriana.

Flujo: fuentes → ingestion.py (parsing y validación) → staging → normalize.py → identity.py →
canonicalize.py → quality.py + provenance.py. pipeline.py coordina y scripts/run_layer1.py
solo interpreta argumentos. Las etapas registradas son INGEST, VALIDATION, STAGING,
NORMALIZATION, IDENTITY RESOLUTION, CANONICALIZATION y QUALITY + AUDIT.

## Ingesta y fronteras

CSV usa lectura estricta con soporte de comillas y campos multilínea; source_row es la primera
línea física del registro, no el ordinal de pandas. XLSX usa hoja configurada y números de
fila base 1; no evalúa fórmulas. Encoding explícito tiene prioridad; fallback solo usa la lista
configurada y siempre genera WARNING. Un fallback técnicamente válido no garantiza que el
texto esté correctamente codificado semánticamente. El catálogo nunca se modifica.

Los encabezados normalizan acentos, espacios y caso para el mapeo. Encabezados vacíos o
duplicados tras normalización bloquean la ejecución. Un archivo con errores de quoting
bloquea la publicación porque no se conocen con seguridad los límites de las filas restantes.
Los registros de anchura incorrecta y vacíos se auditan con fila. Los bytes originales
siguen disponibles en la fuente cuya huella está registrada; no se descartan silenciosamente.

Staging mantiene por ejecución el contenido original de cada fila interpretable, la
representación técnica limpia y el mapa de campos. Se escribe antes de rechazar registros
por validación de negocio estructural. La normalización de fechas y tipos validados pasa al
contrato canónico; no se atribuyen indicadores ni impacto. Queda prohibido reescribir RAW.

## Identidad

Se construyen componentes de coincidencias exactas de ID institucional, documento,
ID externo configurado o nombre normalizado + email exacto. Se inspecciona el componente
completo antes de fusionar: más de un valor distinto de ID institucional, documento,
ID externo o tipo de documento impide la fusión. Esto evita que un registro puente fusione
personas con IDs contradictorios. La prioridad del ancla es institucional, documento,
externo, nombre + email. El documento se compara exactamente; tipos incompatibles bloquean.

Nombre igual sin corroboración no produce fusión. Los casos repetidos quedan ambiguous;
sin otra evidencia quedan unresolved. Sus IDs identifican ocurrencias, no personas
confirmadas. Los homónimos con IDs diferentes se mantienen separados. No se eliminan acentos
de nombres ni se aplica comparación aproximada. Un identificador externo configurado debe
pertenecer al mismo espacio de nombres en todas las fuentes; usar prefijos si se mezclan
sistemas. No hay verificación contra directorios externos.

## Duplicación y cobertura

Un ID explícito repetido genera auditoría. En filas base de proyectos, producción e
indicadores, un conflicto de título (y año en producción) bajo el mismo ID rechaza el grupo.
El enriquecimiento posterior desde miembros conserva el proyecto: títulos distintos
generan PROJECT_TITLE_CONFLICT y mantienen title NULL.
La consolidación de filas compatibles mantiene todas las ocurrencias en provenance_json.
Si un campo secundario difiere, se registra FIELD_CONFLICT y se toma el primer valor no nulo
según ruta y fila; todos los originales siguen accesibles. Los artículos sin IDs confiables
usan el hash de la ruta y contenido completo de la fila; no se fusionan por título.

Miembros permite relaciones proyecto-investigador; producción permite artículo-investigador
solo para el documento/nombre explícito de la fila. No se analiza la lista de coautores
ni se deducen posiciones. Las membresías fuera de la cobertura de proyectos se auditan como
ORPHAN_RELATION y no se publican como claves huérfanas. Un vínculo a una identidad ambiguous
o unresolved identifica únicamente esa ocurrencia, no confirma identidad transversal.

Facultades y departamentos provienen únicamente de columnas estructuradas configuradas.
El hash organizacional incluye tipo, nombre, contexto superior y país si se proporciona.
No se infieren afiliaciones a partir de texto libre.

## Publicación y fallos

Un archivo .layer1.lock impide escritores concurrentes. Solo debe retirarse manualmente
si se confirmó que no hay ejecución activa. Las salidas deben estar dentro del proyecto,
separadas entre sí y fuera de raw, reference, samples, src, config, schemas, templates y docs.
Una fuente tampoco puede estar dentro de una salida.

Cada ejecución conserva staging, auditoría, quality y manifest independientes.
Canonical se construye completo en un directorio candidato, se valida y se publica con
renombrado de directorio. La versión anterior queda en outputs/layer1/runs/<run>/previous_canonical.
Hay una breve ventana de renombrado: lectores deben abrir una instantánea y comprobar que
_manifest.json no cambió durante su lectura, reintentando si cambió. No es un servicio transaccional.
Un fallo CRITICAL conserva la última publicación exitosa. latest_run.json puede indicar
FAILED mientras canonical/_manifest.json sigue identificando la última instantánea válida;
las capas posteriores deben comprobar ambos y nunca confundir una ejecución fallida con datos nuevos.

CRITICAL siempre bloquea. ERROR rechaza registros afectados; por defecto permite publicar
el resto. WARNING documenta faltantes opcionales, identificadores opcionales inválidos,
conflictos secundarios y ambigüedades. INFO es informativo.
errors.fail_on_error permite bloquear ante ERROR; max_anomalies limita el total.
severity_overrides cambia presentación/política de ejecución, pero no recupera registros ya
rechazados ni rebaja CRITICAL. SUCCESS significa proceso completado con la política configurada,
no calidad perfecta ni cobertura completa.

Los informes contienen información privada y permanecen ignorados por Git.
Los logs solo muestran etapas y conteos; no documentos ni nombres completos.

## Integración final de dominio

canonicalize.enrich_project_titles integra miembros.titulo por id_actividad. Compara Unicode,
espacios, comillas envolventes y caso; publica un original determinístico si es consistente.
Conserva la procedencia de descriptores y añade cada fila de soporte con mapeo y llave.
No cambia project_id ni crea relaciones. Ausencias/conflictos quedan NULL y documentados.
mapping admite listas explícitas de aliases institucionales/documentales; validate comprueba
todas las columnas/valores. normalize conserva toda la evidencia; identity bloquea componentes
contradictorios, incluso por aliases de una misma fila. id_investigador ≡ id_empleado está
confirmado para estas fuentes. Cédula/documento personal ≡ document_number, nunca institutional_id.
resolved: evidencia suficiente; ambiguous: candidatos múltiples/contradicción;
unresolved: evidencia insuficiente. Sin fuzzy matching, embeddings ni LLM.
quality/production_conflicts.csv agrupa la cuarentena existente como UNRESOLVED.
config/resolutions/production_conflicts.csv es una reserva conceptual sin lector ni resoluciones.
Se preservan RAW, Parquet, auditoría, manifests y plantilla vacía; Capa 2 solo lee canonical.
Los detalles normativos están en docs/contracts/canonical_data_contract.md.

## Referencia territorial independiente y código DANE integrado

La extensión territorial se incorporó el 16 de octubre de 2026. Tras la unificación
de código, `src/layer1_data/dane_reference.py` y `scripts/build_dane_reference.py` procesan exclusivamente
el XLSX autorizado `data/reference/Codigos Dane/Tabla_Codigos_Dane.xlsx`.
Esta extensión es posterior a la aceptación histórica: no añade tablas al
snapshot canonical, no reescribe su manifest y no requiere reconstruir Capas 2–3.
No existe un paquete territorial paralelo en Capa 1. El pipeline canonical no
importa ni ejecuta automáticamente este constructor.

La dimensión independiente se publica en `data/reference/processed/` como
`dane_territories.parquet`, con `dane_reference_manifest.json`, auditoría,
índice explícito de ambigüedad y copia del XLSX. `versions/<reference_id>/`
conserva snapshots inmutables identificados por hashes de fuente, payload y código.
La carga verifica hashes físicos/lógicos y schema antes de consumirlos.

El archivo inspeccionado tiene Sheet1 con encabezados en filas 1–3, cuatro
columnas y 1.120 municipios; Sheet2 y Sheet3 vacías. Contiene 33 unidades
departamentales según su clasificación, incluida BOGOTA. La fila 611 está vacía;
no hay códigos duplicados ni nulos en filas de datos. Los tipos XLSX numéricos
y texto se documentan: únicamente se aceptan componentes con ancho DD/MMM y
todos los códigos publicados son strings. El código municipal es DDMMM.
Los valores originales y source_sheet/source_row permanecen trazables.
Se registran 68 grupos de nombres municipales repetidos y nueve nombres DANE
que cruzan nivel departamental/municipal. No se corrigen nombres ni se crean aliases.

Por instrucción posterior del usuario, `ALCANCE_NACIONAL` añade explícitamente
`000 | Colombia | COUNTRY`. Es una extensión `USER_DEFINED_COUNTRY`, no un
código DANE de departamento o municipio. Sus campos departamentales, municipales
y padre son NULL. Sheet1–Sheet3 permanecen intactas; el XLSX original se conserva
en el snapshot anterior `701a2468c65a5d86dcfa7823f66741ddc8e7289db0a0e841f292651ee84b0176`.
La política de publicación nacional pertenece a [Capa 4B](layer4.md).


### Aceptación del constructor actual

Los diez archivos canonical preexistentes, incluido `__init__.py`, conservaron
sus bytes durante la unificación. Dimensión DANE, fuente autorizada y versiones
siguen fuera de `data/canonical/`. El traslado cambió el fingerprint del
constructor, no los datos publicados. La [aceptación de la unificación DANE](../status/layer1_dane_unification_acceptance.md)
registra dos referencias aisladas idénticas y la revalidación real de su consumidor
de Capa 4B, con 677 pruebas PASS en la validación conjunta. La referencia de prueba
no sustituyó la dimensión vigente; los manifests y actas anteriores no se modificaron.

### Entrypoints y herramientas auxiliares

`scripts/run_layer1.py` ejecuta el ETL canónico y `scripts/build_dane_reference.py`
construye la referencia independiente. `verify_layer1.py` y `build_contracts.py`
permanecen en la raíz de `scripts/`. Las auditorías de aliases están en
`scripts/auxiliary/audit_identity_aliases.py` y
`scripts/auxiliary/audit_identity_alias_forensics.py`; no son etapas del ETL.
Los comandos y sus efectos se detallan en el [README principal](../../README.md#ejecución-paso-a-paso)
y el [índice de scripts](../../scripts/README.md).
