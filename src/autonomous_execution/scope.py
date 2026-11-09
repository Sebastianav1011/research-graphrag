"""Watch approved intake without reading new documentary sources into prompts."""
import os
from pathlib import Path
from layer2_processing.preprocessing.adapters import source_files
from layer2_processing.checkpoints import resolve
from . import store as s


def inventory(root,state,selection):
    root=Path(root).resolve();raw=resolve(root,state['raw_path'])
    paths=source_files(raw,state['configuration'].get('source_paths'))
    directories=[]
    if selection['mode']=='delivery':
        parent=Path(os.path.commonpath([str(p.parent) for p in paths]))
        discovered=source_files(parent)
        if {p.resolve() for p in discovered}!={p.resolve() for p in paths}:
            raise ValueError('Fuentes nuevas en entrega; preparar nuevamente el alcance')
        directories=[parent.relative_to(root).as_posix()]
    elif not state['configuration'].get('source_paths'):
        directories=[raw.relative_to(root).as_posix()]
    files={}
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Fuente redirigida fuera del alcance')
        stat=path.stat()
        files[path.relative_to(root).as_posix()]=dict(sha256=s.sha(path),size=stat.st_size,mtime_ns=stat.st_mtime_ns)
    return dict(directories=directories,files=files)


def check(root,approved,cache=None):
    root=Path(root).resolve();cache=cache if cache is not None else {}
    paths=set(approved['files'])
    if approved['directories']:
        actual=set()
        for directory in approved['directories']:
            folder=(root/directory).resolve()
            if not folder.is_relative_to(root):
                raise ValueError('Directorio fuera del alcance')
            for path in source_files(folder):
                if path.is_symlink():
                    raise ValueError('Fuente redirigida')
                actual.add(path.relative_to(root).as_posix())
        if paths!=actual:
            raise ValueError('Fuentes agregadas o retiradas del alcance autorizado')
    for name,receipt in approved['files'].items():
        path=root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError('Fuente autorizada ausente o redirigida')
        stat=path.stat();stamp=(stat.st_size,stat.st_mtime_ns)
        if cache.get(name)!=stamp:
            if s.sha(path)!=receipt['sha256']:
                raise ValueError('Fuente documental autorizada modificada')
            cache[name]=stamp
