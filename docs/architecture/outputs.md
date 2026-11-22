# README de `outputs/`: dónde buscar cada resultado

> Vive en `docs/` y no en `outputs/README.md` por dos motivos: `tests/test_output_layout.py` exige que la raíz de
> `outputs/` contenga solo directorios con dueño documentado, y `.gitignore` excluye todo `outputs/`, así que el
> README nunca se compartiría. Clasificación completa en [`catalogo_rutas.yaml`](catalogo_rutas.yaml); flujo en
> [`arquitectura_vigente.md`](arquitectura_vigente.md).

## Busco…

| Necesito | Ruta | Categoría |
|---|---|---|
| Resultados de un run (Excel, CSV, estado) | `outputs/runs/<local\|api>/<run_id>/resultados/` | ACTUAL |
| Estado o progreso de un run, o por qué se detuvo | `outputs/runs/<bucket>/<run_id>/estado/` (`progress.json`, `failure.json`, `execution.json`) | ACTUAL |
| Configuración, modelo y Knowledge que usó un run | `outputs/runs/<bucket>/<run_id>/manifiestos/` (`run.json` → `knowledge_ref`, `model.binding.json`) | ACTUAL |
| Respuestas y evaluaciones del LLM de un run | `outputs/runs/<bucket>/<run_id>/evaluation/` | ACTUAL |
| Copia inmutable de una exportación | `outputs/historico/<local\|api>/<run_id>/` (`latest.json` → revisión vigente) | ACTUAL |
| Evidencia compactada de runs retirados | `outputs/historico/compactados/` (ZIP e índice; extraer con `scripts/manage_run_retention.py --extract-run`) | HISTORICO |
| Knowledge y GraphRAG que reutilizan los runs | `outputs/shared/base/active.json` → `versions/<id>/artifacts/workspace/outputs/{layer2,layer3}` | COMPARTIDO |
| Pesos de embeddings y tokenizer | `outputs/layer3/models/bge-m3/…`, `outputs/layer3/tokenizers/qwen3.5/` | COMPARTIDO |
| Plan, perfiles y rúbricas de evaluación | `outputs/layer4/pruebas/validacion_v3_3/cierre_homogeneo_v3_3/closure.plan.json`, `outputs/layer4/indicator_profiles/` | COMPARTIDO |
| Referencia DANE procesada | `outputs/layer2/reference/` (fuente original: `data/layer1_sources/reference/Codigos Dane/`) | COMPARTIDO |
| Publicación oficial de Capa 4 (V2, Power BI) | `outputs/layer4/final/resultado_capa4.xlsx` | HISTORICO, fijado |
| Territorios 4B aceptados | `outputs/layer4/territorios/publicacion/` (versiones anteriores en `versiones/`) | HISTORICO |
| Pilotos y cierres V2 / V3.3 | `outputs/layer4/pruebas/{piloto_v2,validacion_v3_3}/` | HISTORICO |
| Experimentos de 20 y 50 proyectos, preliminares y entregas | `outputs/layer4/auditoria/historicos/` y `outputs/layer4/pruebas/piloto_v2/{muestra_20,original_5}` | HISTORICO |
| Demo de 30 proyectos | `outputs/layer4/final/candidatos/`, `outputs/layer4/auditoria/PROJ_*` | HISTORICO |
| Publicación global de Capas 2 y 3 de octubre | `outputs/layer2/{canonical,knowledge}`, `outputs/layer3/publication` | HISTORICO |
| Diagnósticos, pilotos ad hoc y revisiones manuales | `outputs/audits/`, `outputs/pilotos/`, `outputs/reviews/`, `outputs/runs/source_evaluation/` | EXPERIMENTAL |

## Reglas de mantenimiento

- **No mover ni renombrar** carpetas de `outputs/layer2`, `layer3` ni `layer4`. Los manifiestos sellados guardan rutas
  literales o rutas heredadas, que se resuelven con `rutas.json` y `config/sad_relocations.json`. Varios verificadores
  (`verify-final` V2, `verify_layer4_layout.py`, plan V3.3) fallarían.
- **Carpetas nuevas en la raíz de `outputs/`:** crearlas solo con un dueño en `OUTPUT_DIRECTORIES`
  (`tests/test_output_layout.py`). `audits` y `pilotos` están registradas en `OUTPUT_DIRECTORIES` con sus dueños:
  - `audits`: la escriben `scripts/benchmark_scoped_retrieval.py` y `tests/semantic_validation/harness.py`; la leen
    `tests/test_semantic_correction_v2.py`, `tests/test_claude_recommendations.py` y `tests/real_runs/run_v5_openai.py`.
  - `pilotos`: la escribe `scripts/pilot_prospective_v2.py`, que exige esta raíz; la leen `tests/test_prospective_v2_*`.

  El registro autoriza su ubicación, pero no las fija por hash: ningún manifiesto sellado las cita.
  Su contenido no se movió ni se modificó. Validación del 2026-11-20:
  - los 9 tests de organización pasan (`tests/test_output_layout.py` y `tests/layer5_experiment/test_layout_relocation.py`);
  - los 89 tests de la selección de consumidores pasan;
  - siguen sin cambios las 42/1.854 diferencias históricas del verificador V2 y los 32 errores de `verify_layout`.
- **Limpieza de runs:** solo con `run.py cleanup` (regla de 72 horas) o `scripts/manage_run_retention.py` (simulación
  por defecto). Ver [`ALMACENAMIENTO.md`](../ALMACENAMIENTO.md).
- Los `*-test-temp` de `outputs/layer4/territorios/aceptacion` y `auditoria/historicos/preliminar_20` **no son
  temporales**: la publicación V2 los fija por ruta y hash.
