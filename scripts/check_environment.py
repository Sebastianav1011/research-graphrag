"""Read-only installation checks. Never loads model weights or runs inference."""
import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import sys
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ['pandas','numpy','pyarrow','openpyxl','PyYAML','jsonschema',
            'sentence-transformers','transformers','huggingface_hub','torch']


def inspect(root=ROOT, external=True):
    root=Path(root);versions={};errors=[];warnings=[];details={}
    for name in PACKAGES:
        try: versions[name]=metadata.version(name)
        except metadata.PackageNotFoundError: errors.append('Paquete ausente: '+name)
    if external:
        import yaml
        config=json.loads((root/'config/pipeline_manual.json').read_text(encoding='utf-8'))
        graph=yaml.safe_load((root/'config/layer3.yaml').read_text(encoding='utf-8'))
        llm=config['llm'];details['model']=llm['model']
        endpoint=llm['endpoint'];url=urlsplit(endpoint)
        if url.scheme!='http' or url.hostname not in ('localhost','127.0.0.1','::1') or url.username or url.password:
            errors.append('Ollama debe estar configurado en localhost')
        else:
            try:
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(endpoint.rstrip('/')+'/api/tags',timeout=3) as response:
                    models=json.load(response)['models']
                details['ollama_available']=True
                if not any(m.get('name')==llm['model'] or m.get('model')==llm['model'] for m in models):
                    warnings.append('Falta modelo local. Ejecutar: ollama pull '+llm['model'])
            except (OSError,ValueError,KeyError):
                details['ollama_available']=False
                warnings.append('Ollama no disponible en '+endpoint+'. Instalar Ollama y abrirlo o ejecutar ollama serve.')
        try:
            import torch
            details['cuda_available']=torch.cuda.is_available()
            if graph['embeddings']['device']=='cuda' and not details['cuda_available']:
                warnings.append('GraphRAG exige CUDA en su configuracion actual. Se necesita GPU NVIDIA, controlador compatible y PyTorch cu128. No se cambia a CPU automaticamente.')
        except ImportError: errors.append('No se pudo importar PyTorch')
        model_path=root/graph['embeddings']['local_model_path']
        if not (model_path/'pytorch_model.bin').is_file():
            warnings.append('Faltan pesos BGE-M3 fijados: '+str(model_path)+'. Ver docs/instalacion.md.')
        for name in [config['reference_catalog'],'outputs/layer4/pruebas/validacion_v3_3/cierre_homogeneo_v3_3/closure.plan.json']:
            if not (root/name).is_file():warnings.append('Recurso institucional requerido no distribuido por Git: '+name)
        details['models_loaded']=False
        details['inference_calls']=0
    return dict(status='ERROR' if errors else 'INSTALLED_WITH_EXTERNAL_WARNINGS' if warnings else 'READY',
                python=platform.python_version(),packages=versions,errors=errors,warnings=warnings,details=details)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strict',action='store_true')
    parser.add_argument('--skip-external',action='store_true')
    args=parser.parse_args();result=inspect(external=not args.skip_external)
    print(json.dumps(result,ensure_ascii=True,indent=2))
    return 2 if result['errors'] else 3 if args.strict and result['warnings'] else 0


if __name__=='__main__':raise SystemExit(main())
