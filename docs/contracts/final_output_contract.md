# Contrato futuro de salida, versión 1.0

Este contrato define la estructura de los resultados futuros del sistema.

Existen exactamente dos datasets independientes, representados en las hojas Proyectos y
Artículos de templates/resultado_final_indicadores.xlsx. Un proyecto y un artículo son fuentes
independientes; no se inventa una relación proyecto-artículo. El archivo tiene solo
encabezados. Capa 1 NO genera estas filas todavía y el ETL no abre ni modifica la plantilla.

La granularidad es fuente analizada + indicador detectado. La clave lógica dentro de cada
hoja será (source_id, indicator_id). Una fuente puede aparecer en varias filas para distintos
indicadores. No se emite una fila para un indicador sin evidencia suficiente; ausencia de
fila no demuestra ausencia de impacto. Si existen varias evidencias para el mismo par,
Capa 4 definirá su consolidación sin cambiar esta granularidad.

Ambas hojas tienen exactamente estas columnas y orden:

| Campo | Significado y nullabilidad |
| --- | --- |
| source_id | ID canónico project_id o article_id; obligatorio |
| source_type | PROJECT en Proyectos; ARTICLE en Artículos; obligatorio |
| title | Título real de la fuente; obligatorio para futuras filas finales |
| indicator_id | Código estable del catálogo oficial; obligatorio |
| indicator_name | Texto/nombre del indicador del catálogo; obligatorio |
| indicator_category | Categoría literal del catálogo; obligatoria |
| indicator_dimension | Ámbito del catálogo; NULL si no existe |
| evidence_text | Fragmento textual real que sustenta la detección; obligatorio |
| evidence_source_field | Nombre del campo/sección ORIGINAL de la evidencia; obligatorio |
| evidence_explanation | Explicación posterior de la evidencia; obligatoria en filas finales, no generada en Capa 1 |
| confidence_score | Número o NULL; reservado sin fórmula, rango ni escala definidos |
| confidence_level | Texto o NULL; taxonomía y umbrales por definir en Capa 4 |
| researcher_id | ID canónico opcional, solo con relación confiable |
| researcher_name | Nombre opcional ligado a esa identidad |
| territory | Territorio opcional, sin inferencia en Capa 1 |
| territory_type | Tipo territorial opcional |

La obligatoriedad de title en salida futura no autoriza rellenar títulos faltantes en
Capa 1. Se incorpora miembros.titulo por id_actividad cuando es consistente. Para los casos
que sigan sin título, las capas futuras deberán contar con evidencia estructurada adicional
o decidir una versión de contrato antes de producir filas finales. La plantilla no cambia.

evidence_text debe ser verificable contra original_values en la procedencia canónica.
evidence_source_field es, por ejemplo, resumen, metodologia, objetivos,
resultados_investigacion, abstract o keywords, según la columna real. No usar el nombre de
una tecnología: GraphRAG nunca es considerado una fuente; tampoco LLM, embedding, modelo,
IA u OpenAI. La tecnología de recuperación no sustituye la procedencia documental.

Las categorías y dimensiones se toman del catálogo, no de ejemplos hardcodeados.
No se crean columnas de revisión humana. Investigador y
territorio son opcionales. La confianza se calculará posteriormente; HIGH/MEDIUM/LOW son
solo ejemplos, no una clasificación implementada ni un enum obligatorio.

schemas/final_output.schema.json representa un objeto con las dos colecciones. Valida
estructura, tipos, campos y separación de source_type; las colecciones vacías son válidas.
La unicidad fuente-indicador, la pertenencia al catálogo y la correspondencia literal de
evidencia se validarán cuando se implemente Capa 4; un JSON Schema por sí solo no demuestra
que un texto constituye evidencia de un indicador.

No existe código de llenado, clasificación de impacto, asignación de indicadores,
cálculo de scores, embeddings ni llamadas a modelos.

