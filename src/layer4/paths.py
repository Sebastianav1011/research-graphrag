"""Explicit relocation of Layer4 artifacts without rewriting frozen manifests."""
import hashlib
import json
from pathlib import Path


def registry(root):
    path=Path(root)/'outputs/layer4/auditoria/rutas.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def resolve(root, path):
    root=Path(root).resolve();path=Path(path)
    path=path if path.is_absolute() else root/path
    try:name=path.relative_to(root).as_posix()
    except ValueError:return path
    data=registry(root)
    if name in data.get('file_aliases',{}):return root/data['file_aliases'][name]
    for old,new in sorted(data.get('prefixes',{}).items(),key=lambda x:len(x[0]),reverse=True):
        if name==old or name.startswith(old+'/'):
            return root/(new+name[len(old):])
    return path


def legacy(root, path):
    root=Path(root).resolve();path=Path(path)
    try:name=path.relative_to(root).as_posix()
    except ValueError:return path
    for old,new in sorted(registry(root).get('prefixes',{}).items(),key=lambda x:len(x[1]),reverse=True):
        if name==new or name.startswith(new+'/'):return root/(old+name[len(new):])
    return path


def verify_expected(root,name,expected):
    root=Path(root).resolve();path=resolve(root,name)
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==expected:return
    # Historical source checks remain exact. A reviewed path-only migration
    # binds current source bytes separately and retains the original bytes once.
    bindings=registry(root).get('runtime_bindings',{})
    binding=bindings.get(name)
    if binding is None:
        try:binding=bindings.get(path.relative_to(root).as_posix())
        except ValueError:pass
    if binding and path.is_file():
        current=hashlib.sha256(path.read_bytes()).hexdigest()
        original=root/binding['snapshot']
        if current==binding['after_sha256'] and original.is_file() and hashlib.sha256(original.read_bytes()).hexdigest()==expected:return
    raise ValueError('Fingerprint mismatch: '+name)
