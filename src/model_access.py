"""Computer-local preferences and credentials. No network operations."""
import getpass
import json
import os
from pathlib import Path

SERVICE = 'GraphRAG.OpenAI'
ACCOUNT = 'api-key'


def preferences(root):
    path = Path(root)/'config/model.local.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'provider':'ollama'}


def save_preferences(root, provider):
    if provider not in ('ollama','openai'):raise ValueError('Proveedor invalido')
    path=Path(root)/'config/model.local.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'provider':provider}),encoding='utf-8')


def api_key(root):
    # An explicitly accepted fallback replacement takes precedence over a vault
    # whose backend became read-only/unavailable while replacing the old value.
    path=Path(root)/'.env.openai.local'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.startswith('OPENAI_API_KEY='):return line.split('=',1)[1].strip()
    try:
        import keyring
        value=keyring.get_password(SERVICE,ACCOUNT)
        if value:return value
    except Exception:pass
    return os.environ.get('OPENAI_API_KEY')


def configure_key(root):
    if api_key(root):
        print('1. Utilizar API existente\n2. Configurar nueva API')
        answer=input('Opcion: ').strip()
        if answer=='1':return
        if answer!='2':raise ValueError('Opcion invalida')
    else:
        if input('Configurar nueva API [S/N]: ').strip().upper()!='S':raise ValueError('API sin configurar')
    # Refuse getpass fallback to an echoing stream.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        try:value=getpass.getpass('Clave OpenAI (entrada oculta): ').strip()
        except (getpass.GetPassWarning,EOFError):raise ValueError('Se requiere terminal con entrada oculta') from None
    if not value or any(c.isspace() for c in value):raise ValueError('Clave vacia o formato invalido')
    try:
        import keyring
        backend=keyring.get_keyring()
        if 'plaintext' in type(backend).__module__.lower():raise RuntimeError()
        keyring.set_password(SERVICE,ACCOUNT,value)
        (Path(root)/'.env.openai.local').unlink(missing_ok=True)
        print('Clave guardada en el almacen de credenciales del usuario.')
        return
    except Exception:pass
    print('Almacen seguro no disponible. El archivo .env.openai.local contiene texto plano; Git lo excluye, pero otros procesos del usuario pueden leerlo.')
    if input('Guardar en archivo local [S/N]: ').strip().upper()!='S':raise ValueError('Clave no guardada')
    path=Path(root)/'.env.openai.local'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as stream:stream.write('OPENAI_API_KEY='+value+'\n')
    print('Clave guardada localmente; no se ha realizado ninguna llamada API.')


def change_model(root):
    print('1. Ollama — modelo local actual\n2. OpenAI API — GPT-6.1 Terra\n0. Volver')
    answer=input('Opcion: ').strip()
    if answer=='0':return
    if answer not in ('1','2'):raise ValueError('Opcion invalida')
    if answer=='2':configure_key(root)
    save_preferences(root,'openai' if answer=='2' else 'ollama')


def label(root,provider=None):
    if (provider or preferences(root)['provider'])=='openai':return 'OPENAI API | gpt-6.1-terra'
    from layer4_evaluation.indicators.ollama_provider import DEFAULTS
    config=Path(root)/'config/pipeline_manual.json'
    model=json.loads(config.read_text(encoding='utf-8-sig')).get('llm',{}).get('model',DEFAULTS['model']) if config.exists() else DEFAULTS['model']
    return 'LOCAL | '+model
