# Perfiles operacionales de indicadores para Capa 4

Versión: `INDICATOR_ASSESSMENT_PROFILES_V2`. Fuente autorizada:
`data/reference/indicadores/catalogo_indicadores_v2.xlsx`. No modifica la reserva
histórica de perfiles, REFERENCE, queries o embeddings de Capa 3.

La inspección real registra `Indicadores_enriquecidos` (49 filas, 14 columnas,
encabezados fila 1, 48 indicadores válidos) y `Reglas_generales` (13 filas,
cinco columnas, 12 reglas). No hay IDs duplicados ni filas vacías. Los únicos
nulos son `ambito` (11) y `unidad` (37); no se rellenan. SHA-256 de entrada:
`1aeb1a376c24bca7bdd7acd228da527ef0043f0574541649589badb54e1cf88f`.

| Columna real | Proyección operacional |
|---|---|
| id_indicador | indicator_id |
| indicador | indicator_name |
| categoria | indicator_category |
| ambito | indicator_dimension |
| descripcion_ampliada | descripcion_ampliada |
| elementos_clave | key_elements_original + key_elements |
| evidencia_favorable | favorable_evidence |
| evidencia_insuficiente | insufficient_evidence |
| terminos_relacionados | related_terms |
| contexto_relacional | relational_context |
| fuentes_relevantes | fuentes_relevantes_original + preferred_evidence_fields |
| tipo, forma_evaluacion, unidad | Conservados con las 14 columnas originales en source_record_json |

Cada perfil conserva catálogo, hoja, fila y SHA-256 de entrada, versión y método
de transformación. Los textos originales no se resumen ni se completan.

## Elementos clave

Solo se utiliza `elementos_clave`. Se admiten arrays JSON de strings, listas con
marcadores, listas separadas por punto y coma y listas de frases terminadas en
punto. Este último caso exige reconstrucción exacta, inicio en mayúscula,
ausencia de puntos decimales/iniciales abreviadas y fragmentos no triviales.
Se mantienen los puntos en cada elemento. Comas, conjunciones, `o` e `y/o` no
se separan. En casos inciertos se conserva el valor completo como un elemento.
El original completo siempre permanece disponible.

NULL o texto vacío produce `key_elements=[]`, `key_elements_status=MISSING`.
SUPPORTED válido sin ese catálogo tendrá confidence_status=NOT_COMPUTABLE.
No se generan elementos con LLM. El snapshot real tiene 48 perfiles AVAILABLE,
cero MISSING; mínimo 4, mediana 5 y máximo 7 elementos.

## Preferencias de campos

Solo se admiten etiquetas completas inequívocas: nombres canónicos y los aliases
explícitos Título, Palabras clave, Resumen, Metodología, Objetivos y Resultados
esperados. Se toleran caso, tildes y espacios en estas etiquetas; no se buscan
palabras de campos dentro de prosa ni se interpreta su significado.

`indicator_preferred_field_mappings.parquet` registra indicator_id,
original_value, mapped_fields, mapping_status y preferred_evidence_fields.
MAPPED exige que todas las etiquetas pertenezcan al mapping explícito.
PARTIALLY_MAPPED conserva las reconocidas únicamente para auditoría;
preferred_evidence_fields queda vacío. UNMAPPED y EMPTY también producen [].
Solo MAPPED alimenta preferencias de confidence.

Las 48 celdas reales de fuentes_relevantes son descripciones narrativas y quedan
UNMAPPED. Por ello, las preferencias están vacías en los 48 perfiles. Esto no
bloquea RAW_CONFIDENCE_V1: se conserva su política ya validada de F=1.00 para un
campo sustantivo cuando no hay preferencias. No se inventa un mapping semántico.

## Reglas y publicación

`indicator_assessment_rules.json` conserva las 12 reglas y sus cinco columnas
originales, procedencia y SHA. Todas declaran `rule_status=RULE_TEXT` e
`implemented_rule=false`. Ninguna interpretación semántica de esas reglas se
presenta como un gate programado. Los gates efectivamente implementados se
describen por separado en el [contrato de assessment](layer4_assessment_contract.md).

`scripts/build_indicator_assessment_profiles.py` publica bajo
`data/reference/processed/` los perfiles Parquet, manifest, reglas, auditoría y
mappings. `indicator_assessment_versions/<reference_id>/` conserva versiones
inmutables de esos artefactos y copia byte-for-byte del XLSX. El ID vincula
fuente, payload y código; se verifican schema, hashes y roundtrip.
No se abre RAW ni se reconstruye ninguna capa upstream.
