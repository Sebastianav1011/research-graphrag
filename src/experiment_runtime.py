"""Explicit CLI options scoped to the existing coordinator; frozen per run."""
from run_paths import file_path as run_file
from contextvars import ContextVar
from pathlib import Path
import json
import math

API_RETRIEVED_CONTEXT=32768  # API window for BASE_RETRIEVED_GRAPH_V1 (local model keeps its own limits)

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
        if requested.get('unlimited_budget'):
            # Explicit choice: no internal limit; the OpenAI account limit/balance applies.
            if budget is not None:raise ValueError('Elegir presupuesto o sin limite, no ambos')
            api.pop('budget_usd',None)
        else:
            if budget is None:
                import sys
                if not sys.stdin.isatty():raise ValueError('OpenAI requiere --budget-usd o --sin-limite explicitos')
                budget=float(input('Presupuesto operativo maximo USD: '))
            if not math.isfinite(budget) or budget<=0:raise ValueError('Presupuesto positivo requerido')
            api['budget_usd']=budget
        settings=dict(provider='openai',model='gpt-6.1-terra',api=api)
        if (evaluation or {}).get('context_mode')=='BASE_RETRIEVED_GRAPH_V1':
            # The 8000-token evidence cap applies only to the local model. The API
            # receives every ranked fragment and relation of the project; its window
            # covers the largest BASE project (~13k tokens) with ample margin.
            settings.update(num_ctx=API_RETRIEVED_CONTEXT,num_predict=4096,context_margin_tokens=1024)
        llm=configuration(settings)
    else:llm=configuration(base)
    result=dict(llm=llm,contract=requested.get('contract'))
    if evaluation:result['evaluation_policy']=evaluation
    return result
