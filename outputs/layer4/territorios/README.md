# Capa 4B: territorios

- `publicacion/`: dimensión y relaciones territoriales aceptadas, manifiesto y
  evidencias de generación.
- `aceptacion/`: revisión y aceptación institucional conservadas.
- `versiones/`: versiones anteriores referenciadas por la auditoría.
- `auditoria_matching.json`: auditoría de resolución conservada.

La resolución es determinista: usa documentos/secciones de Capa 2 y referencias
territoriales, sin LLM ni GraphRAG. No se han cambiado reglas ni identificadores.
Las rutas históricas se resuelven con `../auditoria/rutas.json`; los consumidores
activos apuntan a `publicacion/`. No regenerar datos para verificar esta migración.
La proyección de consumo mantiene `siap_id`, `territory_type`, `territory_code`,
`code_system`; códigos como `05`, `05001` y `000` siguen siendo texto.
COUNTRY/000 utiliza INTERNAL; departamento y municipio utilizan DANE.
