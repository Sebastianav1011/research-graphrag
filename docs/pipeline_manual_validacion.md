> Ubicación vigente de originales: `data/raw/`. El código de inventario forma parte de preprocesamiento. Este documento conserva el historial; consultar el README raíz para ejecutar.

> Documento histórico anterior a la consolidación del 29-10-2026. La operación vigente está en el README raíz y `docs/architecture/AUDITORIA_CONSOLIDACION_RAW.md`.

# Cierre de la integración manual — 2026-10-26

Implementación terminada en la raíz activa `GraphRag`; no se modificó el repositorio
histórico `Pruebas/Prueba GraphRag`. Auditoría anterior a los cambios:
[pipeline_manual_auditoria.md](architecture/pipeline_manual_auditoria.md).
Operación y contrato: [pipeline_manual.md](pipeline_manual.md).

## Cambios y código conservado

- Añadidas las dos entradas RAW, sin sembrarlas con muestras históricas.
- Añadidos `manual_pipeline/preprocess.py`, `manual_pipeline/runner.py`, CLI delgada,
  configuración JSON local y dependencia opcional PDF.
- Se reutilizan lectura semántica de encabezados y DOCX, ETL, identidad, deduplicación,
  enriquecimiento por llaves explícitas, chunking, contratos Parquet, calidad,
  embeddings, grafo, recuperación, executor y validadores originales.
- Cada ejecución posee su raíz de datos, caché, diagnósticos y respuestas. Los hashes
  ligan RAW, intermedios, código, configuración y snapshots; no hay fallback.
- El catálogo VRI enriquecido queda en REFERENCE, separado del corpus evaluado.
- Excel se exporta con openpyxl ya instalado, sin depender del Node de Codex. Se
  conserva el score guardado, incluyendo evidencia parcial sin umbral; exactamente
  seis columnas de indicadores y cuatro territoriales, sin clasificación visible.
- La CLI anterior en vivo queda documentada como heredada; se conservan sus fuentes
  intactas porque manifiestos, reanudaciones y renderer histórico dependen de ellas.
  Su preparación, caché de 30, consulta territorial, fallback PDF y renderer no se
  ejecutan en esta entrada. No se eliminó ningún componente histórico.

## Comprobaciones realizadas

1. **13 pruebas nuevas aprobadas**, en 32,69 s:

   `uv run python -B -m pytest -q -p no:cacheprovider tests/test_manual_pipeline.py --basetemp outputs/pipeline_manual_operational_validation_temp`

   Cubren JSON nuevo, CSV institucional con columnas faltantes, XLSX, DOCX, nulos,
   ID con ceros iniciales, ID de artículo, duplicados, título de miembros, vínculos
   explícitos, provenance RAW en chunks, entradas vacías/rotas/sin ID/contradictorias,
   fórmulas rechazadas, protección de destinos históricos, detección de RAW cambiado,
   exportación vacía y exportación parcial de baja confianza numérica sin estados.

2. **98 regresiones focalizadas aprobadas** en 1,55 s: `test_graph.py`,
   `test_indicator_retrieval.py`, `test_assessment_v3.py` y
   `test_global_discovery_v3_3.py`. Los algoritmos originales no se editaron.
   La primera ejecución produjo una advertencia por una caché pytest preexistente;
   las comprobaciones finales nuevas desactivaron cacheprovider y pasaron sin ella.

3. El build, publicación, recuperación y paquetes de contexto existentes se ejecutaron
   con un proveedor de vectores sintéticos **solo dentro del test**. La puerta de
   producción rechazó ese grafo por incompatibilidad del proveedor; no es evidencia
   de calidad semántica ni un resultado de investigación.

4. Se preparó un plan de Capa 4 de prueba con los 48 perfiles congelados. El intento
   sin autorización se bloqueó antes de crear authorization o dispatch claim.
   No se ejecutó Codex CLI ni un modelo. Se conservaron los controles secuenciales,
   presupuestos, métricas y reanudación del executor existente.

5. La CLI real se invocó desde **Windows PowerShell**, dentro de una raíz aislada con
   espacios: `prepare`, `validate`, `export`, `verify`. Código de salida cero, RAW
   idéntico y libro vacío correctamente marcado PARTIAL. Los cuatro bloques PowerShell
   del manual pasaron el parser de Windows sin errores; el `--help` real también pasó.

6. Se verificaron contra sus hashes anteriores los tres Excel preservados:

| Publicación | SHA-256 |
|---|---|
| Oficial V2 | `fc6f876493ee327f140f5fbdbd234b93242eeaee15d86aa752388980f03332e1` |
| Demo 30 original | `cdd83be1ecf06bc732d00e6f85d6b8602314282200a222a019b2199e1cf7690f` |
| Demo 30 ampliada | `d75379384c042025b607dbc80c3bc6f6cd780ea689948732bc51dd7ba78ca64e` |

No se realizaron operaciones Git ni se movieron/reorganizaron los resultados
anteriores. Los fixtures y resultados de validación son aislados; no alimentan la
entrada real. La muestra histórica de diez mencionada por el usuario no se identificó
como una definición única en esta raíz; no se reejecutó ni se certifica su reproducción
completa. Se conservan todos los experimentos anteriores y sus puntos de entrada.

## Límites de esta validación

- **Cero inferencias nuevas: cero tokens y cero tiempo de inferencia.** No se ejecutó
  un build nuevo real con BGE-M3 ni se demostró calidad analítica con documentos nuevos.
- La extracción PDF requiere instalar pypdf en `.venv`; no estaba instalada durante
  esta validación. DOCX/XLSX/CSV/JSON sí se probaron con archivos nuevos mínimos.
- Documentos sin ID, campos sustantivos reconocibles, con OCR requerido o con formatos
  distintos se rechazan con diagnóstico. Se necesita la intervención documental del
  custodio, no completar contenido mediante inferencia.
- La ruta en vivo completa conserva V3.3: usa seis campos globales para discovery y
  assessment; no redefine la evaluación para restringirla al ranking de GraphRAG.
- No se generan nuevos territorios; la hoja tiene encabezados mientras no exista un
  puente 4B verificado de esta misma ejecución. No se reutilizan territorios ajenos.
- No se probó una importación en Power BI Desktop. Se comprobó el contrato de Excel.
- Inferencia real depende de runtime fijado, autenticación, créditos y presupuestos.
  Una fase incierta queda bloqueada; no hay reintentos ni recuperaciones inventadas.

El siguiente paso operativo es depositar documentos reales, preparar/revisar, aprobar
el build local y autorizar explícitamente Capa 4 según los comandos del manual.
