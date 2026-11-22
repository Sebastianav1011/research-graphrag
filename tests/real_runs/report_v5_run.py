"""Detailed, read-only Markdown report of a finished V5 run (no model calls).

Every figure and quotation is read from the run's verified artifacts:
resultados/evaluaciones_validas.json, estado_indicadores.json, performance/openai_usage.json,
the batch plans (rubrics, source fields) and call.json timings. Not a pytest module.

  uv run python tests/real_runs/report_v5_run.py <run_dir> <output.md>
"""
import collections
import datetime as dt
import glob
import json
import re
import sys
from pathlib import Path

DECISION = {'SUPPORTED': 'Acreditado', 'INSUFFICIENT_EVIDENCE': 'Evidencia insuficiente',
            'NOT_APPLICABLE': 'No aplica', 'NOT_SUPPORTED': 'No acreditado'}
SUPPORT = {'CLEAR': 'Claro', 'PARTIAL': 'Parcial', 'NOT_DEMONSTRATED': 'No demostrado'}
STAGE = {'ACTIVITY_PROPOSED': 'actividad propuesta', 'ACTIVITY_EXECUTED': 'actividad ejecutada',
         'RESULT_EXPECTED': 'resultado esperado', 'RESULT_DEMONSTRATED': 'resultado demostrado', 'CONTEXT': 'contexto',
         'DESIGN_DOCUMENTED': 'diseño documentado', 'MECHANISM_ESTABLISHED': 'mecanismo establecido'}
FIELD = {'title': 'título', 'summary': 'resumen', 'methodology': 'metodología', 'objectives': 'objetivos',
         'expected_results': 'resultados esperados', 'text__abstract': 'resumen del artículo', 'keywords': 'palabras clave'}


def cell(text, limit=None):
    text = ' '.join(str(text or '').split()).replace('|', '\\|')
    return text if limit is None or len(text) <= limit else text[:limit - 1] + '…'


def main(run, out):
    run = Path(run)
    valid = json.loads((run / 'resultados/evaluaciones_validas.json').read_text(encoding='utf-8'))['assessments']
    states = json.loads((run / 'resultados/estado_indicadores.json').read_text(encoding='utf-8'))['indicators']
    usage = json.loads((run / 'resultados/performance/openai_usage.json').read_text(encoding='utf-8'))
    plans = [json.loads(Path(p).read_text(encoding='utf-8')) for p in sorted(glob.glob(str(run / 'evaluation/batch_*/plan.json')))]
    rubrics, profiles, sources = {}, {}, {}
    for plan in plans:
        rubrics.update(plan['rubrics']); profiles.update(plan['profiles'])
        for p in plan['projects']:
            sources[p['project_id']] = p
    times = []
    for f in glob.glob(str(run / 'evaluation/**/call.json'), recursive=True):
        c = json.loads(Path(f).read_text(encoding='utf-8'))
        times.append((dt.datetime.fromisoformat(c['timestamp']), dt.datetime.fromisoformat(c['finished_at'])))
    by_source = collections.defaultdict(list)
    for a in valid:
        by_source[a['siap_id']].append(a)
    L = []
    w = L.append
    w(f'# Reporte detallado de evaluación GraphRAG V5 — {run.name}\n')
    w('Generado automáticamente a partir de los artefactos verificados del run. Todas las citas son copias literales '
      'del texto de la fuente; las decisiones las calcula Python (`VALIDATED_CRITERIA_DECISION_V1`) a partir de los '
      'juicios por criterio del modelo, y la confianza con `EVIDENCE_CONFIDENCE_SK_V1`. '
      '**Son clasificaciones basadas en la evidencia disponible, no mediciones de impacto.**\n')
    # 1. Summary
    w('## 1. Resumen de la ejecución\n')
    span = (max(e for _, e in times) - min(s for s, _ in times)) if times else None
    w('| Concepto | Valor |\n|---|---|')
    w(f"| Modelo | {usage.get('model')} (OpenAI Responses, razonamiento `{(usage.get('pricing') or {}).get('reasoning_effort')}`) |")
    w(f'| Fuentes | {len(by_source)} |')
    w(f'| Evaluaciones válidas | {len(valid)} de {len(states)} previstas |')
    w(f"| Llamadas a la API | {usage['calls']} |")
    w(f"| Tokens de entrada / salida / razonamiento | {usage['input_tokens']:,} / {usage['output_tokens']:,} / {usage['reasoning_tokens'] or 0:,} |".replace(',', '.'))
    w(f"| Costo real | USD {usage['estimated_cost_usd']:.4f} (reservas inciertas: USD {usage['reserved_uncertain_usd']:.4f}) |")
    if span:
        w(f'| Tiempo de llamadas (primera a última) | {span.total_seconds()/60:.1f} min; media {sum((e-s).total_seconds() for s,e in times)/len(times):.1f} s por llamada |')
    w('')
    w('| Fuente | Acreditados | Evidencia insuficiente | No aplica | Con evidencia parcial (confianza > 0) | Confianza media (válidas) | Costo USD |')
    w('|---|---|---|---|---|---|---|')
    for sid, rows in sorted(by_source.items()):
        c = collections.Counter(a['decision'] for a in rows)
        scores = [a['confidence_raw_score'] for a in rows if isinstance(a['confidence_raw_score'], (int, float))]
        internal = rows[0].get('articulo_id_interno') or rows[0]['project_id']
        w(f"| {sid} | {c['SUPPORTED']} | {c['INSUFFICIENT_EVIDENCE']} | {c['NOT_APPLICABLE']} | {sum(1 for s in scores if s > 0)} | "
          f"{sum(scores)/len(scores):.1f} | {usage['projects'].get(internal, 0):.4f} |")
    crit = collections.Counter(c['support'] for a in valid for c in a['criterion_assessments'])
    w(f"\nJuicios por criterio (todas las evaluaciones): claros {crit['CLEAR']}, parciales {crit['PARTIAL']}, "
      f"no demostrados {crit['NOT_DEMONSTRATED']}.\n")
    errors = [s for s in states if s['status'] != 'VALID']
    w(f"Evaluaciones no válidas (errores técnicos o pendientes): {len(errors)}" +
      (''.join(f"\n- {s['siap_id']} · {s['indicator_id']}: {s['status']} {s.get('technical_error') or ''}" for s in errors) if errors else '.') + '\n')
    w('**Regla de decisión V5:** un indicador se acredita solo si **todos sus criterios esenciales** son *claros* y la '
      'aplicabilidad no está excluida. Un criterio *parcial* en un esencial basta para quedar en *evidencia insuficiente*, '
      'aunque la confianza sea alta. La confianza resume fuerza y cobertura de la evidencia (0–100); no es una probabilidad.\n')
    # 2. Sources
    w('## 2. Fuentes evaluadas\n')
    for sid, rows in sorted(by_source.items()):
        internal = rows[0]['project_id']
        p = sources.get(internal, {})
        f = p.get('fields', {})
        w(f'### {sid}\n')
        bib = rows[0].get('bibliographic') or p.get('bibliographic')
        if bib:
            w('| Campo | Valor |\n|---|---|')
            for k, label in (('title', 'Título'), ('eid', 'EID'), ('doi', 'DOI'), ('journal', 'Revista'), ('publication_year', 'Año')):
                w(f'| {label} | {cell(bib.get(k))} |')
            w(f'| ID interno | `{internal}` |\n')
            w('**Resumen (única evidencia citable):**\n')
            w('> ' + cell(f.get('text__abstract')) + '\n')
        else:
            w(f"**Título:** {cell(f.get('title'))}\n")
            for key in ('summary', 'objectives', 'methodology', 'expected_results'):
                if f.get(key):
                    w(f'**{FIELD[key].capitalize()}:**\n\n> ' + cell(f[key]) + '\n')
    # 3. Overview table
    w('## 3. Resultado por indicador\n')
    for sid, rows in sorted(by_source.items()):
        w(f'### {sid}\n')
        w('| Indicador | Nombre | Decisión | Confianza | Claros / Parciales / No dem. | Esenciales sin «claro» |')
        w('|---|---|---|---|---|---|')
        for a in sorted(rows, key=lambda a: (-(a['confidence_raw_score'] or 0), a['indicator_id'])):
            c = collections.Counter(x['support'] for x in a['criterion_assessments'])
            m = re.search(r'esenciales sin CLEAR \[([^\]]*)\]', a['evidence_explanation'] or '')
            missing = ', '.join(re.findall(r"'([^']+)'", m.group(1))) if m else ''
            score = '—' if a['confidence_raw_score'] is None else f"{a['confidence_raw_score']:.2f}"
            w(f"| {a['indicator_id']} | {cell(a['indicator_name'], 90)} | {DECISION.get(a['decision'], a['decision'])} | {score} | "
              f"{c['CLEAR']} / {c['PARTIAL']} / {c['NOT_DEMONSTRATED']} | {missing or '—'} |")
        w('')
    # 4. Near misses
    w('## 4. Casos que quedaron a un paso de acreditarse\n')
    w('Evaluaciones en *evidencia insuficiente* cuyos criterios esenciales faltantes son **todos parciales** (ninguno '
      '«no demostrado»). No cambia ninguna decisión: es una lectura descriptiva para la discusión metodológica.\n')
    near = []
    for a in valid:
        m = re.search(r'esenciales sin CLEAR \[([^\]]*)\]', a['evidence_explanation'] or '')
        missing = re.findall(r"'([^']+)'", m.group(1)) if m else []
        support = {c['criterion_id']: c['support'] for c in a['criterion_assessments']}
        if missing and all(support.get(x) == 'PARTIAL' for x in missing):
            near.append((a, missing))
    w('| Fuente | Indicador | Confianza | Esenciales parciales |\n|---|---|---|---|')
    for a, missing in sorted(near, key=lambda x: -x[0]['confidence_raw_score']):
        w(f"| {a['siap_id']} | {a['indicator_id']} | {a['confidence_raw_score']:.2f} | {', '.join(missing)} |")
    w('')
    # 5. Detail
    w('## 5. Detalle con el texto que respalda cada juicio\n')
    w('Se detallan todas las evaluaciones con confianza mayor que 0 (las que tienen alguna evidencia), de mayor a menor '
      'confianza, y las *no aplica*. Para cada criterio: lo que exige la rúbrica, si es esencial, el juicio del modelo y '
      'las citas literales que usó.\n')
    for sid, rows in sorted(by_source.items()):
        w(f'### {sid}\n')
        chosen = [a for a in rows if (a['confidence_raw_score'] or 0) > 0 or a['decision'] == 'NOT_APPLICABLE']
        for a in sorted(chosen, key=lambda a: (-(a['confidence_raw_score'] or 0), a['indicator_id'])):
            rubric = {c['criterion_id']: c for c in rubrics[a['indicator_id']]['criteria']}
            score = '—' if a['confidence_raw_score'] is None else f"{a['confidence_raw_score']:.2f}"
            w(f"#### {a['indicator_id']} — {DECISION.get(a['decision'], a['decision'])} (confianza {score})\n")
            w(f"*{cell(a['indicator_name'])}*\n")
            w(f"- **Aplicabilidad:** {a['applicability']['status']} — {cell(a['applicability']['explanation'])}")
            sr = a['strength_rubric']
            w(f"- **Fuerza de la evidencia** (0–4): directa {sr['directness']}, específica {sr['specificity']}, clara {sr['clarity']}, "
              f"alineación temporal {sr['temporal_alignment']}. {cell(sr.get('explanation'))}")
            w(f"- **Decisión (Python):** {cell(a['evidence_explanation'], 400)}\n")
            for c in a['criterion_assessments']:
                r = rubric.get(c['criterion_id'], {})
                role = 'esencial' if r.get('role') == 'REQUIRED' else ('alternativo ' + str(r.get('alternative_group'))
                                                                      if r.get('alternative_group') else str(r.get('role', '')).lower())
                w(f"**{c['criterion_id']} · {cell(r.get('criterion'))}** ({role}) → **{SUPPORT.get(c['support'], c['support'])}**"
                  f" (cobertura {c['coverage']}/4)\n")
                w(f"- Juicio: {cell(c['explanation'])}")
                for i in c.get('evidence_indices') or []:
                    if i < len(a['evidence_texts']):
                        w(f"- Cita [{FIELD.get(a['evidence_source_fields'][i], a['evidence_source_fields'][i])}, "
                          f"{STAGE.get(a['evidence_stages'][i], a['evidence_stages'][i])}]: «{cell(a['evidence_texts'][i])}»")
                w('')
    # 6. Notes
    w('## 6. Notas para la lectura\n')
    acceptance = collections.Counter(r.get('acceptance') for r in rubrics.values())
    w(f"- Estado de las rúbricas: {dict(acceptance)}. Las adaptaciones prospectivas de los criterios siguen pendientes de revisión humana institucional.")
    w('- Proyectos: modo prospectivo; una contribución prevista bien descrita puede contar, pero no se infiere impacto observado.')
    w('- Artículos: solo el resumen es evidencia; título y palabras clave no se citan; sin contexto relacional ni evidencia de proyectos.')
    w('- Los nombres de investigadores se enviaron seudonimizados a la API; no afectan la evidencia (el contexto relacional no es citable).')
    w('- Una confianza alta con *evidencia insuficiente* indica evidencia sustancial pero incompleta en algún criterio esencial.')
    Path(out).write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('escrito', out, len(L), 'lineas')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
