# Registro metodológico del refactor de Capa 3

> Nota de cierre posterior: este documento representa una revisión intermedia.
> El cierre posterior quedó aprobado en
> [layer3_source_level_acceptance.md](../architecture/layer3_source_level_acceptance.md)
> y en outputs/layer3/reports/source_level_final_acceptance.json.

HISTORICAL_REQUIRED. Este documento explica la migración. El estado vigente
pertenece a [arquitectura Capa 3](../architecture/layer3.md); no prescribe repetir
procesamiento ya aprobado.

## Motivo del cambio

Un hit de title/keywords descubre un PROJECT/ARTICLE sin demostrar cumplimiento.
El diseño anterior entregaba candidatos chunk-oriented. El refactor agrupa por
SOURCE+INDICATOR y referencia todas las secciones disponibles de la fuente,
incluidas las que no fueron hits. Normalizar los contextos por SOURCE evita
duplicar textos por indicador y prepara el assessment posterior.

ASSESSMENT_READY expresa disponibilidad de contexto sustantivo; DISCOVERY_ONLY
conserva fuentes que únicamente orientan discovery. Ninguno decide cumplimiento.
El grafo conserva relaciones factuales y bridges resolved_only, sin fabricar
SOURCE→INDICATOR. Los scores significan retrieval. Capa 2, su chunking y los
embeddings compatibles se conservaron.

Los [perfiles operacionales](../pending/indicator_profiles.md) siguen
PENDING_GROUP_REVIEW. El benchmark anterior de Capa 4 es diagnóstico metodológico,
no ground truth final.

## Cronología verificable

El recovery review del 14 de octubre a las 09:06 UTC describía pendientes de ese
momento. Hubo después un intento cuya integración fue interrumpida y una secuencia
completa que terminó correctamente.

Los builds finales terminaron a las 09:46:20 y 09:48:02 UTC. Comparten los 27
code_hashes, configuración y snapshot Capa 2. Reutilizaron 45.362 embeddings SOURCE
y 133 REFERENCE, sin calcular embeddings del corpus.

La comparación final pasó a las 09:48:20 UTC; verify pasó después. El JUnit final,
escrito a las 10:00:08 UTC, registra 191 pruebas unitarias y 28 de integración real
aprobadas, sin fallos, errores o skips. Contratos y upstream también pasaron.

## Evidencia y alcance

Las fases, hashes originales, manifests y el intento interrumpido están
consolidados localmente en outputs/layer3/reports/source_closure_evidence.json.
La publicación activa, idempotence.json, source_publication_verification.json y
layer3_source_regression.xml conservan la autoridad sobre esos resultados.

Los controladores del cierre, generadores puntuales de documentación y wrappers
retirados fueron eliminados después de consolidar la evidencia. Los historiales
de publicaciones reales y el diagnóstico metodológico de Capa 4 permanecen
privados. final_acceptance.json pertenece al diseño anterior y no acredita
aceptación source-level. La limpieza no ejecutó modelos, builds, retrieval,
integración real ni Capa 4.
