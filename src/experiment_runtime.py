"""Explicit CLI options scoped to the existing coordinator; frozen per run."""
from run_paths import file_path as run_file
from contextvars import ContextVar
from pathlib import Path
import json
import math

options=ContextVar('experiment_options',default={})


def binding(root,run,base,*,evaluation=None):
    from layer4_evaluation.indicators.ollama_provider import configuration
    from model_access import preferences
    requested=options.get()
    path=run_file(Path(run), 'model.binding.json')
    if path.exists():
        saved=json.loads(path.read_text(encoding='utf-8'))
        if evaluation is not None and evaluation!=saved.get('evaluation_policy',{}):raise ValueError('Modos distintos del checkpoint; crear otro run')
        if requested.get('provider') and requested['provider']!=saved['llm']['provider']:raise ValueError('Proveedor distinto del checkpoint; crear otro run')
        if requested.get('budget_usd') is not None and requested['budget_usd']!=saved['llm'].get('api',{}).get('budget_usd'):raise ValueError('Presupuesto congelado; crear otro run')
        if requested.get('contract') and requested['contract']!=saved.get('contract'):raise ValueError('Contrato distinto del checkpoint')
        return saved
    # Existing legacy checkpoints keep their provider regardless of preferences.
    if (run_file(Path(run), 'run.json')).exists():return dict(llm=configuration(base))
    provider=requested.get('provider') or preferences(root)['provider']
    if provider=='openai':
        from layer4_evaluation.indicators.openai_provider import defaults
        api=defaults(root)
        budget=requested.get('budget_usd')
        if budget is None:
            import sys
            if not sys.stdin.isatty():raise ValueError('OpenAI requiere --budget-usd explicito (recomendado: 15)')
            budget=float(input('Presupuesto operativo maximo USD (15 recomendado; reserva externa prevista 5 de 20): '))
        if not math.isfinite(budget) or budget<=0:raise ValueError('Presupuesto positivo requerido')
        api['budget_usd']=budget
        llm=configuration(dict(provider='openai',model='gpt-6.1-terra',api=api))
    else:llm=configuration(base)
    result=dict(llm=llm,contract=requested.get('contract'))
    if evaluation:result['evaluation_policy']=evaluation
    return result
