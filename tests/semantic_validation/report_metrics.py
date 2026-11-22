"""Report denominators without promoting provisional audit labels to truth."""
from .harness import *
def main():
    csv.field_size_limit(20_000_000)
    s=read(OUT/'resumen_validacion.json');history=[];quotechecks=[];bins=Counter();stages=Counter()
    for path in sorted((OUT/'historicos').glob('*.json')):
        x=read(path);a=x['assessment']
        if not a:continue
        score=a['confidence_raw_score'];bucket='100' if score==100 else '0' if score==0 else '1–49.99' if score<50 else '50–79.99' if score<80 else '80–99.99'
        bins[(a['decision'],bucket)]+=1
        evidence=x['record']['wrapper']['assessments'][0]['evidence'];fragments=x['request']['payload']['project']['fragments']
        for e in evidence:
            literal=any(f['field']==e['field'] and f['text']==e['text'] for f in fragments)
            quotechecks.append(dict(case_id=x['project']['siap_id']+':'+x['indicator_id'],field=e['field'],stage_model=e['stage'],literal_match=literal))
        labelset={e['stage'] for e in evidence}
        stages['EMPTY' if not labelset else '+'.join(sorted(labelset))]+=1
    csvwrite(OUT/'verificacion_citas.csv',quotechecks)
    with (OUT/'validacion_humana.csv').open(encoding='utf-8-sig',newline='') as f:human=list(csv.DictReader(f,delimiter=';'))
    real=[]
    for r in human:
        if r['data_type']!='REAL_HISTORICAL':continue
        real.append(dict(indicator_id=r['indicator_id'],expected=r['human_decision'],actual=r['system_decision'],
            validated=bool(r['human_status']=='CONFIRMED' and r['reviewer'] and r['rationale'] and r['definition_approved']=='YES')))
    lr=OUT/'inferencia_local/baseline_v1/results.json';local=read(lr) if lr.exists() else []
    synthetic=[dict(indicator_id=r['indicator_id'],expected=r['expected'],actual=r['actual'],validated=r['oracle_status']=='SYNTHETIC_EXPLICIT') for r in local if not r['case_id'].startswith('HIST_')]
    byhuman={r['case_id']:r for r in human};new_validated=[]
    for r in local:
        h=byhuman.get(r['case_id'])
        if h:
            new_validated.append(dict(indicator_id=r['indicator_id'],expected=h['human_decision'],actual=r['actual'],validated=bool(h['human_status']=='CONFIRMED' and h['reviewer'] and h['rationale'] and h['definition_approved']=='YES')))
    metrics=dict(real_human_validated=binary_metrics(real),new_local_human_validated=binary_metrics(new_validated),synthetic_explicit_oracle=binary_metrics(synthetic),citation_count=len(quotechecks),literal_matches=sum(r['literal_match'] for r in quotechecks),historical_blocked=100,historical_denominator=240,confidence_bins=[dict(decision=k[0],bucket=k[1],count=v) for k,v in sorted(bins.items())],stage_buckets=dict(stages))
    write(OUT/'metricas.json',metrics)
    per=[]
    for iid in sorted(catalog()[0]):
        m=binary_metrics([r for r in real if r['indicator_id']==iid]);sm=binary_metrics([r for r in synthetic if r['indicator_id']==iid])
        per.append(dict(indicador=iid,reales_validados=m['validated'],reales_evaluables=m['scored'],FP_real=m['FP'] if m['scored'] else '',FN_real=m['FN'] if m['scored'] else '',precision_real=m['precision'],recall_real=m['recall'],F1_real=m['F1'],sinteticos_ejecutados=sm['scored'],FP_sintetico=sm['FP'] if sm['scored'] else '',FN_sintetico=sm['FN'] if sm['scored'] else ''))
    csvwrite(OUT/'metricas_por_indicador.csv',per)
    table='\n'.join('| '+d['decision']+' | '+d['bucket']+' | '+str(d['count'])+' |' for d in metrics['confidence_bins'])
    model_note=('El preflight impidió usar Qwen por RAM insuficiente.' if s['local_calls']==0 else 'Se ejecutó la selección pequeña registrada en inferencia_local/baseline_v1; no representa todos los indicadores.')
    synth_note=('No disponibles: no se ejecutó el modelo por falta de RAM. Los controles de corpus no producen predicciones de Qwen sobre los 404 textos.' if not synthetic else 'Resultados frente al oráculo sintético explícito, no precisión institucional real: '+json.dumps(metrics['synthetic_explicit_oracle'],ensure_ascii=False))
    real_note=('No disponibles: no existen etiquetas humanas confirmadas y evaluables.' if not metrics['real_human_validated']['scored'] else 'Resultados de los históricos con etiquetas humanas confirmadas: '+json.dumps(metrics['real_human_validated'],ensure_ascii=False))
    text=f'''# Métricas de validación — 18 de noviembre de 2026

## Alcance y denominadores

- Corpus sintético: **{s['corpus']} escenarios, 48 indicadores**. Ocho escenarios por indicador (384), doce contrastes temporales adicionales y ocho adversariales específicos. Son datos de prueba, no evidencia institucional.
- Pytest: **{s['pytest_count']} pruebas, {s['pytest_passed']} aprobadas, {s['pytest_failed']} fallidas**. No hay xfail ni ocultación de fallos conocidos. XML completo: `pytest_resultados.xml`.
- Históricos: **240 pares únicos**, con pertenencia a grupos solapados: 44 SUPPORTED, 42 puntuaciones 100, 15 promociones, 100 bloqueados, 49 recomendaciones NA derivadas y 96 insuficientes. Los grupos no se suman para contar casos.
- Reproducción: **536 intentos** contrastados con las mismas funciones de validación, {s['replay_failures']} diferencias. Los 288 intentos de pares bloqueados siguen sin evaluación válida.
- Fórmula: **140/140** S, K y puntuaciones comparados independientemente, {s['formula_failures']} diferencias.
- Nuevas inferencias: **{s['local_pairs']} pares, {s['local_calls']} llamadas**. {model_note} No presentar casos preparados como decisiones ejecutadas.
- Recuperación GraphRAG real: cuatro pares desde índices y consultas cacheadas verificados, sin embeddings ni modelo nuevos; los cuatro contextos coinciden con sus originales. `recuperacion_real.json` documenta configuración y límites.

Las filas de resultados incluyen pruebas aisladas, recálculo, replays y preflight: no sumarlas como si fueran evaluaciones independientes ni calcular una «exactitud global» sobre ellas.

## Precisión, recall, F1 y matriz de confusión

**Decisiones reales:** {real_note} Los 27 posibles falsos positivos anteriores siguen siendo diagnóstico provisional. No se convierten en FP reales ni los cinco razonablemente justificados en TP certificados.

**Inferencias sintéticas nuevas:** {synth_note} Cuando no hay observaciones elegibles, la matriz TP/FP/FN/TN no es una matriz de ceros que demuestre ausencia de errores.

`binary_metrics` admite sólo etiquetas validadas independientes; aplica TP/(TP+FP), TP/(TP+FN) y 2TP/(2TP+FP+FN), deja métricas sin denominador en null y reporta bloqueos como abstenciones. Las pruebas incluyen una matriz independiente 1/1/1/1, resultados 0,5 y exclusión de etiquetas no validadas. NOT_APPLICABLE esperado se evalúa como estado aparte, no se fuerza a una etiqueta binaria.

`metricas_por_indicador.csv` contiene los 48 indicadores. FP/FN quedan vacíos cuando no hay decisiones con verdad validada, no se muestran como cero. Tras completar `validacion_humana.csv`, volver a ejecutar el generador. Requiere CONFIRMED, revisor, justificación, decisión y aprobación de definición. Las inferencias históricas nunca se utilizan para construir su propia etiqueta esperada.

## Bloqueos

Histórico: **100/240 = 41,67 %**. Son errores de contenido respecto al contrato semántico. Distribución por causa principal, con la precedencia de la auditoría original:

| Causa | Casos | % de bloqueos |
|---|---:|---:|
| Aplicabilidad sin cita sustantiva | 45 | 45 % |
| NOT_DEMONSTRATED con citas | 20 | 20 % |
| Soporte sin etapa/campo compatible | 20 | 20 % |
| Fuerza/relación contradictoria | 13 | 13 % |
| Fuerza incompatible con decisión | 2 | 2 % |

Estos son rechazos finales, no errores de JSON. Preflight nuevo: impedimento de recursos antes de inferencia, **no un nuevo BLOCKED_ERROR de evaluación**. Tasa nueva de bloqueos del modelo: no disponible, denominador de inferencias cero.

## Estabilidad entre reintentos

Se compararon **{s['retry_comparisons']} pares primer intento–corrección**, incluidos los de resultados no positivos. En {s['retry_pairs_with_changes']} comparaciones hay al menos un ascenso de support/coverage. Son comparaciones, no pares únicos ni errores confirmados.

En las 296 comparaciones se mantiene idéntico el payload documental, los fragmentos y las condiciones del indicador; esquema y opciones de generación no cambian. **Sí cambia el texto de instrucciones en las 296**: el corrector compacto añade errores y puede sustituir el prefijo por uno más conciso. Por tanto, misma evidencia no significa condiciones de prompt idénticas. No hubo recuperación adicional que justificara los ascensos.

Los 15 positivos inicialmente recomendados insuficientes activan un fallo de regresión por falta de adjudicación independiente. Ese fallo **no prueba que los 15 sean falsos positivos**: sus primeras respuestas eran inválidas y al menos un caso fue considerado razonable por la auditoría provisional. El comportamiento que falta es una política demostrada para resolver la contradicción, no una prohibición universal de corregir un primer juicio equivocado.

## Citas, confianza y tipo de evidencia

Se contrastaron **{metrics['citation_count']} citas de las 140 evaluaciones válidas** con los fragmentos efectivamente enviados: **{metrics['literal_matches']} coincidencias literales**. Es una prueba de procedencia, no de implicación semántica. Los mutantes demuestran que una cita literal negada o atribuida a Q puede conservar una etiqueta optimista aceptada por el gate.

| Decisión histórica | Confianza | Casos |
|---|---|---:|
{table}

No se calcula precisión por confianza sin etiquetas humanas. Las 42 puntuaciones máximas son valoraciones del modelo, no probabilidades calibradas. `metricas.json` conserva distribución por combinaciones de etapas declaradas; son etiquetas de Qwen, no una validación independiente de la temporalidad. `verificacion_citas.csv` permite cruzar campo, etapa y literalidad. Los escenarios sintéticos distinguen resultado, intención, contexto, negación y atribución ajena; faltan predicciones nuevas para medir resultados por ese tipo de evidencia.

## Capacidad de detección y límites

Cinco alteraciones de procedencia son rechazadas; cuatro alteraciones semánticas con citas literales y juicios optimistas sobreviven al contrato y provocan fallos de la batería. Se detectan los quince ascensos y se prueba que el monitor reconoce una promoción artificial. El guard localizado y el merge existentes también se prueban separadamente: su capacidad no implica que el protocolo compacto del run los active.

Los tests fallidos permanecen fallidos. El porcentaje de tests aprobados **no es precisión de GraphRAG**. La validación integral de decisiones nuevas queda pendiente de recursos locales y de adjudicación humana para los casos ambiguos/reales. No se modificó producción para hacer pasar la batería.
'''
    (OUT/'metricas_validacion.md').write_text(text,encoding='utf8')
    print(json.dumps({k:v for k,v in metrics.items() if k not in ('confidence_bins','stage_buckets')},ensure_ascii=True))
if __name__=='__main__':main()
