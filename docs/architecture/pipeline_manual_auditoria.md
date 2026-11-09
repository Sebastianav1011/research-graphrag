> Ubicación vigente de originales: `data/raw/`. El código de inventario forma parte de preprocesamiento. Este documento conserva el historial; consultar el README raíz para ejecutar.

> Documento histórico anterior a la consolidación del 29-10-2026. La operación vigente está en el README raíz y `docs/architecture/AUDITORIA_CONSOLIDACION_RAW.md`.

# Auditoría previa del pipeline local — 2026-10-26

Inspección de solo lectura realizada antes de implementar la nueva entrada. La raíz
activa es `GraphRag`. `../Pruebas/Prueba GraphRag` es una implementación histórica
de capas 1/2; sus README y módulos 3/4 declaran esas capas no implementadas.
No se modifica esa carpeta ni se atribuye a ella el código posterior.

## Arquitectura encontrada

| Componente | Entrada real | Implementación/salida |
|---|---|---|
| ETL histórico | `config/sources.yaml`: descriptores, producción y miembros en `../DatosLimpios/Datos Limpios/` | `layer1_data`: CSV/XLSX, normalización, identidad, siete Parquet en `data/canonical` |
| Conocimiento | canonical aprobado por hash | `layer2_knowledge`: documentos/secciones/chunks, entidades/relaciones, ocho Parquet en `data/knowledge` |
| GraphRAG | knowledge aprobado | `layer3_graphrag`: BGE-M3 local fijado, caché, índices numpy, grafo factual, recuperación híbrida y contextos en `data/graphrag` |
| Evaluación | seis campos, perfiles/rúbricas y evidencia | `layer4/indicators`, discovery V3.3 y assessment V3, Codex CLI, validación Python |
| Territorios | publicación 4B aceptada | `territorial_consumption` y `final_projection`, solo lectura |
| Intento en vivo | archivos externos → seis campos | `run_layer4_live_demo.py`: extracción, revisión, autorización, llamadas secuenciales, reanudación y exportación; omite GraphRAG |

Los experimentos se conservan en `outputs/layer4/pruebas/piloto_v2`,
`validacion_v3_3`, `outputs/layer4/auditoria`, `archives/layer4` y los candidatos
finales. No se encontró en la raíz activa una definición única denominada
«experimento de 10 proyectos»; no se sustituye esa ausencia por otra muestra.
Se preserva íntegro el conjunto histórico, incluida la demostración de 30.

## Problemas y dependencias

- Los comandos de publicación originales sustituyen directorios compartidos.
- Las capas históricas llaman ETL a Capa 1 y conocimiento a Capa 2: se necesita
  distinguir esta nomenclatura del RAW/preprocesamiento solicitado.
- Las fuentes institucionales usan rutas absolutas de este equipo. No hay contrato
  único de recepción de documentos externos ni aislamiento RAW por conjunto.
- Capa 3 exige rutas relativas cerradas y hashes de snapshot; su proveedor resuelve
  los pesos desde la raíz del código. Se debe cambiar la raíz de datos de cada
  ejecución, conservando el almacén de pesos verificado en solo lectura.
- La prueba en vivo tiene lectores reutilizables (DOCX y encabezados), pero PDF usa
  como alternativa un Python de la caché de Codex y la exportación usa Node/Artifact
  Tool de esa caché. No son dependencias adecuadas de una CLI autónoma.
- El intento en vivo también consulta proyectos conocidos para caché y territorio.
  La nueva entrada no debe usar esas consultas como sustituto de datos ausentes.
- Los planes V3.3 y sus manifiestos fijan hashes de scripts, prompts, rúbricas y
  respuestas. Editar esos módulos invalidaría resultados y reanudaciones anteriores.
- `demo_30.mjs` sirve a exportaciones históricas y en vivo; no se puede eliminar por
  parecer un archivo temporal. Las recuperaciones y métricas en auditoría también
  son pruebas documentales de resultados anteriores.

Se añaden adaptadores; no se elimina código histórico ni se cambian algoritmos
analíticos. Los indicadores de VRI continúan exclusivamente en REFERENCE.
Las comprobaciones de integración usarán entradas nuevas mínimas, validación del
grafo sin modelo y pruebas focalizadas. Una validación sin embeddings/LLM no se
presentará como ejecución analítica completa.
