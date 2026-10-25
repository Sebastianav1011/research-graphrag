# Capa 4A: implementación de 50 proyectos, sin aceptación final

Fecha: 2026-10-19. Motor definitivo: **CODEX_CLI**. No se añadieron APIs ni motores
alternativos. Estado de ejecución: **PREPARED_PENDING_PILOT_AUTHORIZATION**.

## Resultado de implementación

La infraestructura está implementada y probada con fixtures/procesos simulados:
selección determinística diversa, verificación de publicaciones, prompts por
campos/perfil v2, adaptador no interactivo restringido, schema y validación de
citas, confianza contractual, checkpoints, recuperación de transporte terminado,
bloqueo de repetición incierta, lotes explícitos, gate de autorización/aprobación,
informes parciales, exportación reusable y revisión/métricas humanas pendientes.

La [metodología y reproducción](../methodology/layer4a_codex_50.md) explica las
responsabilidades de Python, Codex CLI y el modelo LLM, comandos, límites y
condiciones para cerrar la prueba. Configuración: `config/layer4_experiment.yaml`.
Entrypoint: `scripts/run_layer4_experiment.py`.

## Auditoría y muestra real

- Capa 2 real/SUCCESS y Capa 3 SOURCE_INDICATOR_V1/SUCCESS verificadas mediante
  manifests, hashes, runs, documentos, secciones y contextos.
- Capa 3 tiene 2.400 candidatos totales: 1.519 PROJECT/ASSESSMENT_READY elegibles,
  correspondientes a 280 proyectos distintos. ARTICLE queda excluido.
- Muestra fijada: 50 PROJECT/SIAP distintos y 77 parejas elegibles. Hay 23
  proyectos con un candidato y 27 con dos. No se completan artificialmente 100.
- Cobertura observada: cuatro categorías, seis áreas institucionales y 41
  indicadores. Dos proyectos no tienen área disponible. No se afirma
  representatividad estadística ni se asignan negativos a indicadores omitidos.
- `selection_manifest.json` fija IDs, procedencia, versiones, campos, candidatos
  y criterios por proyecto. SHA256:
  `c0f35cbed13d0681e561f01aae528ec14e03447137429a7176a6f05b845fdc78`.
- Se verificaron 226 hashes de outputs históricos y se revalidaron contra campos
  reales/perfiles/respuestas originales los 31 assessments históricos de 20
  proyectos. Esa auditoría de datos no concede aceptación al código nuevo.
- Los ocho checks históricos de preservación de código requieren
  `archives/layer4/pre_namespace_migration.zip` y
  `archives/layer4/pre_layer1_unification.zip`, ausentes. No se fabricaron archivos
  ni se sustituyeron hashes para hacerlos pasar.

## Versión y modelo

Instalación verificada: **codex-cli 0.163.0**, distinta de 0.162.1 del histórico.
Se guardan ayuda/features, ruta, binario y fingerprints verificables en runtime.json.
La configuración actual no fija un modelo; `--ignore-user-config` impide inferirlo
desde la configuración personal. **Modelo efectivo no observado** mientras no
exista evidencia de una ejecución real. No se atribuye el modelo del desarrollador
al experimento. Uso/tokens reales de esta ejecución: **sin observaciones**, cero
llamadas de assessment realizadas; no se estiman costos ni consumos inexistentes.

## Pruebas y verificación

La regresión disponible pasó **372 pruebas**, excluyendo explícitamente los ocho
checks que requieren los ZIP ausentes. Después del ajuste visual se aprobaron las
**16 pruebas del experimento**, incluida una prueba nueva de reconstrucción exacta
de campos fragmentados, y **3 pruebas focalizadas de exportación** con el renderer
final. Hay 373 casos distintos aprobados entre estas corridas; los conjuntos se
solapan y no se suman sus totales como observaciones independientes.

La primera corrida tuvo errores de setup por un directorio padre temporal faltante;
se creó y se repitió la regresión. Los reportes de esa corrida se conservan y no
se presentan como aprobación. Los reportes efectivos están en:

- `outputs/layer4/auditoria/qa/experimento_20261019/available_regression.xml`
- `outputs/layer4/auditoria/qa/experimento_20261019/final_experiment.xml`
- `outputs/layer4/auditoria/qa/experimento_20261019/final_export.xml`
- `outputs/layer4/auditoria/qa/experimento_20261019/historical_data_audit.json`

Se verifican reanudación sin repetir inferencia, diez lotes simulados para 50
proyectos, exclusión de citas inventadas, score contractual 87.50, bloqueo ante
modificación de datos/respuestas/parámetros, locks y autorizaciones, etiquetas
pendientes, métricas con etiquetas sintéticas y conservación de IDs/códigos como
strings. La revisión visual detectó y corrigió alturas mayores al límite de
Excel: FUENTES fragmenta a 1.500 caracteres sin pérdida y conserva offsets.
Las previews finales se renderizan desde el XLSX guardado después de reparar
coerciones del exportador, preservando también la visualización de `000`.

Las verificaciones reales de publicación territorial e integridad upstream
pasaron. No se reconstruyeron Capas 1, 2 o 3 ni se ejecutó detección territorial.
No se modificaron el código ni las publicaciones aceptadas de 4B. El preliminar
histórico permanece intacto. No se realizó commit ni push.

## Salidas disponibles y pendientes

Raíz activa: `outputs/layer4/auditoria/historicos/experimento_50`.

| Condición | Estado real |
|---|---|
| Infraestructura de 4A | Implementada; validada offline y sobre entradas publicadas |
| Selección real | 50 proyectos, 77 evaluaciones previstas |
| Piloto real | Pendiente de autorización aplicable |
| Evaluaciones reales válidas del nuevo experimento | 0 de 77 |
| Ejecución de los 50 | Pendiente |
| Revisión humana/benchmark | Pendiente; etiquetas vacías |
| Calibración | No realizada; no hay referencia humana suficiente |
| Distribución K/F/C/S de la muestra | Pendiente; n=0 y estadísticos NULL |
| Regresión histórica de código | Ocho checks bloqueados por ZIP ausentes |
| Aceptación académica final | No concedida |

`exports/e3b0c44298fc1c14/revision_humana.xlsx` tiene 77 filas para etiquetado,
77 para revisión, campos originales fragmentados, los 48 perfiles y guía. Está
lista la estructura de revisión; faltan las decisiones reales que se revisarán.
`exports/e3b0c44298fc1c14/powerbi.xlsx` tiene exactamente RESULTADO_INDICADORES y
TERRITORIOS: **0 decisiones** y **63 relaciones RESOLVED** publicadas de la muestra.
No contiene AMBIGUOUS. DANE permanece string y COUNTRY/000 es INTERNAL.
Este workbook es parcial y no se presenta como resultado final de las 77 parejas.

Además se conservan selección/distribución, prompts sin enviar, runtime y
fingerprints, diagnósticos JSONL/Parquet vacíos con schema, auditoría de evidencia,
progress, métricas pendientes y manifests de exportación. La salida previa al
ajuste visual se conservó en borradores `experiment_50_before_visual_fix*`, sin
inferencias; la ruta activa y su manifest identifican los artefactos vigentes.

## Siguiente acción necesaria

Verificar/registrar autorización para enviar los textos institucionales a Codex
CLI y ejecutar únicamente el piloto de estos cinco proyectos:

| PROJECT | SIAP | Indicadores candidatos |
|---|---|---|
| PROJ_20022 | 20022 | ASC-01 |
| PROJ_22027 | 22027 | SAL-01, SAL-02 |
| PROJ_21410 | 21410 | DIV-01, DIV-02 |
| PROJ_22037 | 22037 | COL-01 |
| PROJ_21457 | 21457 | ECO-07, SOC-02 |

Son cinco llamadas previstas con ocho assessments, antes de reintentos técnicos.
Revisar esos resultados, registrar aprobación ligada a su hash y autorizar la
continuación en lotes de cinco. Después, completar 77 respuestas válidas, exportar
con `finalize`, verificar hashes, realizar benchmark independiente y analizar
métricas/limitaciones. Recuperar los dos ZIP originales por su canal autorizado
para desbloquear los checks históricos. La calibración requiere una referencia
adecuada adicional; conservar raw confidence sin calibrar mientras no exista.
