# Consumo y migración Power BI / Capa 5

## Contrato futuro preparado, no activado

`LAYER4_CONSUMER_V3_3_V1` se define en
[layer4_output_contract.md](layer4_output_contract.md): seis columnas en
RESULTADO_INDICADORES y cuatro en TERRITORIOS, exactamente dos pestañas.
La publicación V2 sigue intacta con siete columnas; no cambiar el consumidor
actual antes de aprobar la sustitución.

Para migrar, quitar `estado_cumplimiento` de selección de columnas, tipos, pasos
Power Query, filtros, relaciones, visuales y DAX que la referencien. Comprobar
explícitamente la versión/columnas esperadas al refrescar para evitar cambios
silenciosos. La futura hoja solo contiene VALID SUPPORTED priorizados: los
insuficientes y negativos siguen disponibles en auditoría, no en ese Excel.
La ausencia de una fila no demuestra ausencia de la condición institucional.
Confianza es respaldo calculado, no probabilidad ni estado de cumplimiento.

Mantener `siap_id` como texto y la clave territorial tipo+código+sistema; preservar
ceros iniciales y COUNTRY/000/INTERNAL. No modificar los identificadores de 4B.

La inspección del repositorio no encontró archivos PBIX/PBIT/PBIP ni una
implementación de Capa 5 que permita modificar o validar esos consumidores
externos aquí. Sus responsables deben aplicar y comprobar estos ajustes antes
del cambio de publicación. No se afirma haber validado un dashboard externo.

## Documentación del contrato V2 vigente

# RESULTADO_INDICADORES — contrato oficial V2 y proyecciones históricas

## Contrato oficial de cierre V2 (publicado y aceptado)

La única publicación oficial de Capa 5 será
`outputs/layer4/final/resultado_capa4.xlsx`, creada mediante
`scripts/run_layer4_closure.py --settings config/layer4_closure_definitive.yaml finalize --approval ... --review ...`.
`scripts/run_layer4_closure.py --settings config/layer4_closure_definitive.yaml verify-final`
es su verificador único. No se publica antes de completar los
20 proyectos, validar sus evaluaciones V2 y aceptar humanamente fórmula y resultados.

Exactamente dos hojas, en este orden, con encabezados en fila 1:

- RESULTADO_INDICADORES: siap_id, indicador_id, estado_cumplimiento,
  parrafo_evidencia, fuente_evidencia, ubicacion_evidencia, confianza.
- TERRITORIOS: siap_id, territory_type, territory_code, code_system.

SIAP proviene de metadata_json.source_project_id, nunca de recortar un prefijo.
Una fila por SIAP+indicador evaluado válido, con todas las decisiones preservadas.
confianza usa EVIDENCE_CONFIDENCE_V2 aprobada, como número 0–100; cero real se
conserva y NULL no se convierte en cero. No hay umbral al exportar. Un assessment
inválido conserva NULL en auditoría y bloquea el cierre, sin publicarse como válido.
parrafo_evidencia conserva únicamente las citas literales verificadas, numeradas;
fuente identifica SIAP y campo, y ubicación declara sección, offsets y sistema de
coordenadas. Sin citas los tres campos son NULL, no se fabrica evidencia explicativa.

TERRITORIOS consume solo la bridge RESOLVED aceptada de 4B, filtrada por la muestra
final, independientemente de los estados de indicadores. Códigos como texto;
000 es INTERNAL; municipio/departamento son DANE. Nunca se reconstruye ni se
convierte AMBIGUOUS en una relación. No se infiere una relación departamental adicional.

La proyección oficial mínima se implementa en `final_projection.py` y su publicación
en `final_export.py`. Los exportadores históricos conservan sus siete columnas
territoriales originales y no se vuelven a publicar como oficiales.

La dimensión aceptada `data/reference/processed/dane_territories.parquet` tiene
1.154 filas y un `territory_id` canónico único: por ejemplo
`DANE:DEPARTMENT:05`, `DANE:MUNICIPALITY:05001` y
`USER_DEFINED:COUNTRY:000`. No se inventa ni se renombra esa clave.
El triple `(territory_type, territory_code, code_system)` de la bridge equivale
inequívocamente al triple `(territory_type, dane_code, sistema)` de la dimensión,
donde `sistema = INTERNAL` si `territory_origin = USER_DEFINED_COUNTRY`, y DANE
en las demás filas. La dimensión utiliza códigos municipales completos de cinco
dígitos: `department_code` no hace falta para desambiguarlos. Por ello la bridge
no incorpora nombres, código departamental ni otro identificador redundante.

Power BI puede formar una clave técnica de relación en ambas tablas con la
concatenación de los tres componentes, manteniendo los códigos como texto, o
relacionarlas mediante una dimensión proyectada que conserve el `territory_id`
existente. La transformación de consumo debe respetar `USER_DEFINED` como prefijo
del identificador canónico de país; no debe fabricar `INTERNAL:COUNTRY:000`.
Los nombres y la jerarquía departamental se obtienen de la dimensión aceptada.

La publicación solo admite las evaluaciones efectivas verificadas. El cierre
definitivo utiliza dos candidatos iniciales y fallback desactivado; los resultados
experimentales no se mezclan con sus registros. Su procedencia
LAYER3_RETRIEVAL/LAYER4_SEMANTIC_FALLBACK permanece en los registros privados.
La aceptación suplementaria debe estar vinculada a su plan y resultados efectivos;
una revisión del piloto original no acepta automáticamente el fallback.

## Selector dinámico de confianza en Capa 5

No se construye Power BI en esta implementación. El contrato permite un parámetro
numérico desconectado `Confianza mínima` de 0 a 100 (paso 1). La visualización
principal filtra `estado_cumplimiento = SUPPORTED` y `confianza >= mínimo`.
40/70/90 son selecciones de respaldo, no niveles probabilísticos ni decisiones.
Las vistas exploratorias de otros estados deben declararlos explícitamente.
Un INSUFFICIENT_EVIDENCE con score alto sigue siendo insuficiente.

Ejemplo de medida para una tabla a nivel SIAP+indicador:

```dax
Mostrar soporte =
VAR Minimo = SELECTEDVALUE('Confianza mínima'[Valor], 0)
VAR Estado = SELECTEDVALUE(RESULTADO_INDICADORES[estado_cumplimiento])
VAR Respaldo = SELECTEDVALUE(RESULTADO_INDICADORES[confianza])
RETURN IF(Estado = "SUPPORTED" && NOT ISBLANK(Respaldo) && Respaldo >= Minimo, 1, 0)
```

Usar la medida como filtro de visual (=1), sin reescribir datos ni decisiones.
Construir una dimensión de proyecto con SIAP único para relacionar ambas hojas
mediante relaciones uno-a-varios; no hacer un JOIN físico que multiplique
indicadores por territorios. Si los mapas deben seguir la selección de indicadores,
definir sus medidas por el conjunto de SIAP filtrados y documentar la dirección
de filtrado en Capa 5. El workbook no impone relaciones muchos-a-muchos.

## Proyecciones históricas V1

Proyección del assessment validado, una fila por SIAP+indicador. Conserva el
archivo técnico QA y sus publicaciones sin cambios; no ejecuta LLM ni confidence.

| Columna | Origen y significado |
|---|---|
| siap_id | ID institucional original: metadata_json.source_project_id de source_documents PROJECT de Capa 2. String, sin quitar prefijos por suposición. |
| indicador_id | indicator_id canónico. |
| estado_cumplimiento | decision sin reinterpretación: SUPPORTED, INSUFFICIENT_EVIDENCE o NOT_SUPPORTED. |
| parrafo_evidencia | Todas las citas literales verificadas, numeradas en su orden original y separadas por párrafo. NULL si no existe cita. No es explicación generada. |
| fuente_evidencia | SIAP cuando hay evidencia; NULL sin citas. |
| ubicacion_evidencia | Campo original de cada cita, con la misma numeración: Título, Palabras clave, Resumen, Metodología, Objetivos, Resultados esperados. |
| confianza | confidence_raw_score copiado: RAW_CONFIDENCE_V1, 0–100. **No es probabilidad**. NULL si no se calculó; nunca reemplazar con cero. |

Solo assessments VALID, sin errores, pueden publicarse. La exportación se bloquea
ante IDs faltantes, duplicados o evidencia desalineada; no elimina registros
silenciosamente. No incluye K/F/C/S, strength, validation ni metadata Codex en la
tabla de consumo. Los diagnósticos permanecen en el QA y en el manifest separado.

El entrypoint histórico `scripts/export_layer4_powerbi.py` está ligado al
preliminar de 20 proyectos y no se usa como exportador genérico. La ruta vigente
es `python -B scripts/run_layer4_experiment.py export` (parcial) o `finalize`
(exige todos los assessments válidos). Produce exactamente RESULTADO_INDICADORES
y TERRITORIOS, y CSV UTF-8 con BOM. TERRITORIOS proyecta únicamente la bridge
publicada RESOLVED de 4B para la muestra; no ejecuta detección. Los códigos son
strings: COUNTRY/000 es INTERNAL, departamentos/municipios son DANE.
Un parcial no rellena decisiones faltantes: exporta solo filas válidas y registra
cuántas faltan en `export_manifest.json`. `finalize` rechaza una ejecución
incompleta. Nunca implica aceptación académica ni benchmark humano completado.
