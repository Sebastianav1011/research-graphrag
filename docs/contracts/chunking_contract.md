# Contrato de chunking — hierarchical_words_v1

Motor 2.0.0. Parámetros calibrados con el snapshot real
`run_20261005_194411_225750`: target=220, max=340, overlap=20 palabras.
Se compararon cinco candidatos sobre todos los textos PROJECT/ARTICLE disponibles.
El máximo conserva 7075/7400 abstracts completos (95,61%); target 220 produce mediana
de 220 palabras entre ventanas de secciones divididas. Overlap 20 añade 4,56% de palabras,
frente a 7,17% con overlap 30 para el mismo target/máximo. No hubo fragmentos <40
en secciones divididas, ni chunks sobredimensionados. La longitud mínima observada
en esas ventanas fue 61 palabras. El perfil incluye NULL como longitud cero y los
cuenta separadamente. Ver outputs/layer2/reports/text_field_profile.csv,
chunking_candidates.json y chunking_analysis.md para resultados reproducibles.

## Unidad y límites

Un chunk es un substring contiguo de text_normalized de una sección y una fuente.
Nunca cruza field_name, documento o source_type. PROJECT/ARTICLE son fuentes de
futura evidencia; INDICATOR_REFERENCE es referencia y nunca acredita cumplimiento.
NULL/vacío no produce chunks. Una sección con <=max palabras queda en un único chunk.
Palabra significa coincidencia Unicode de `\S+`; no se usa tokenizador de modelos.

## Jerarquía

1. Conservar sección completa si cabe.
2. En sección larga, preferir finales de párrafo dentro del máximo. Línea vacía
   (`\n\s*\n`) delimita párrafos. Elegir final más cercano a target, empate temprano.
   Párrafos contiguos pueden compartir ventana.
3. Sin final de párrafo admisible, buscar final de oración: palabra terminada en
   `.`, `!` o `?`, con comillas/cierres opcionales. Misma regla de selección.
4. Sin final admisible, dividir por palabras en target.
5. Último fragmento llega al final si cabe en máximo.

preserve_paragraphs/preserve_sentences habilitan preferencias; no autorizan superar
máximo. Es heurística, no parser lingüístico: abreviaturas pueden formar límites.
Una palabra muy extensa sigue siendo una palabra; se registra en perfiles de caracteres.

## Overlap y cobertura

Ventana siguiente comienza overlap_words palabras antes del final de la anterior.
Guardar overlap real en overlap_word_count/provenance; primer chunk tiene cero.
Exigir `0 <= overlap < target <= max`. Cada ventana añade al menos una palabra nueva;
no hay ventanas de solo overlap. No se elimina ni oculta repetición. Overlap=0 no
repite palabras. Todas las palabras quedan cubiertas; espacios entre ventanas sin
overlap pueden no incluirse en chunks y permanecen completos en la sección original.

## Offsets y hashes

char_start inclusivo y char_end exclusivo, base cero, puntos de código Python sobre
**text_normalized**. No bytes, UTF-16 ni offsets RAW/originales.
Exigir `text == section.text_normalized[char_start:char_end]`.
chunk_hash: SHA-256 UTF-8 completo de text. Sección almacena hashes original/normalizado;
text_hash es alias del normalizado. NULL y vacío comparten hash de cadena vacía,
pero text_original distingue ambos estados.
El usuario autorizó excluir emails explícitos con [EMAIL_EXCLUDED]. text_original
almacena el texto previo a normalización con esa exclusión; text_hash_original lo
hashea. Provenance conserva text_hash_input del texto canónico previo a exclusión
y email_redactions. Offsets se refieren siempre al normalizado que ya contiene el
marcador, nunca a posiciones de emails originales. No se almacenan los emails removidos.

## Identidad y estabilidad

`CHUNK_<tipo>_<canonical_id>_<field_name>_<índice base cero>_<SHA256 completo>`.
Componentes usan percent-encoding UTF-8, incluido `_`→`%5F` para evitar colisiones.
Documento: DOC_tipo_id. Sección: SEC_tipo_id_campo, con igual escape.
No hay UUID aleatorio. Entidad reutiliza literalmente TIPO:canonical_id.
Igual snapshot/config/versión del motor produce iguales IDs y payloads, salvo run/timestamps
operacionales de L2. Cambios de textos/cortes pueden cambiar IDs; cambios de metadata
pueden cambiar payloads sin cambiar IDs. Manifest registra config y code hashes.
No comparar bytes Parquet entre runs como prueba de idempotencia.

## Provenance

field_name conserva columna canónica. layer1[].field_mapping conecta columna original;
original_values/record_source/source_sheet/source_row se conservan sin abrir archivos.
Chunk lleva document/section/source_field/hashes/offset_basis=text_normalized.
evidence_source_field futuro conserva field_name y puede resolver nombre original
mediante mapping, nunca nombre de mecanismo analítico ni “documento completo”.
Calidad comprueba cadena y offsets; mapping ausente es UPSTREAM_DATA_ISSUE.
