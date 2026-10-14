# Capa 4 — IN PROGRESS, indicator profiles pending

La arquitectura de entrada ahora es SOURCE+INDICATOR, con contextos completos
por campo referenciados en SOURCE context packages de Capa 3. Capa 4 resolverá
section_id en source_sections de Capa 2 y usará discovery chunks como orientación.
No debe reconstruir grafos ni repetir retrieval.

El benchmark anterior, sus labels/revisión, código y manifest se preservan fuera
de Git bajo outputs/layer4/diagnostic_pre_source_refactor. Son diagnóstico de
diseño, no ground truth final; se invalidó el estado de espera anterior y no se
pide terminar filas pendientes. No se han corregido ni completado labels humanos.

Antes de un benchmark final deben revisarse los perfiles con el grupo de tesis:
[indicator profiles](../pending/indicator_profiles.md), PENDING_GROUP_REVIEW.
No se han inventado definitions, applicability, required evidence o preferred
fields, ni se ha usado LLM. La selección de modelo, inferencia final, confidence,
resultado final y visualización permanecen pendientes.

El estado local se conserva en outputs/layer4/state.json. No existe todavía un
entrypoint de assessment final. La implementación antigua está retirada de la
arquitectura activa para evitar consumir outputs chunk-oriented reemplazados.
