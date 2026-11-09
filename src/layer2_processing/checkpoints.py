"""Shared output paths and exact historical relocations; frozen bytes stay intact."""
import hashlib
import json
from pathlib import Path

OUTPUT_PREFIXES={
    'outputs/layer2_processing':'outputs/layer2',
    'outputs/layer3_graphrag':'outputs/layer3',
    'outputs/layer4_evaluation':'outputs/layer4',
    'outputs/experiments/evaluation_phase1':'outputs/runs',
}


def locate(path):
    """Read a historical locator, including isolated workspaces, via one resolver."""
    from run_paths import resolve_file
    path=resolve_file(path)
    # Existing immutable run/workspace artifacts need no registry lookup.
    if path.exists():return path
    for parent in path.parents:
        if parent.name=='outputs':
            return resolve(parent.parent,path)
        if (parent/'config/sad_relocations.json').is_file():
            return resolve(parent,path)
    return path


def run_directory(root,run_id):
    """Persistent build receipts share the existing outputs/runs convention."""
    if not run_id or Path(run_id).name!=run_id or run_id in ('.','..'):
        raise ValueError('Invalid run identifier')
    return Path(root)/'outputs/runs'/run_id


def registry(root):
    path=Path(root)/'outputs/layer4/auditoria/rutas.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    migration = Path(root)/'docs/architecture/auditoria_consolidacion/relocations.json'
    if migration.is_file():
        changes = json.loads(migration.read_text(encoding='utf-8'))
        for section in ('file_aliases', 'runtime_bindings', 'prefixes'):
            data.setdefault(section, {}).update(changes.get(section, {}))
    else:
        # Isolated workspaces may predate the relocation. Inherit only data locators;
        # never inherit another root's code acceptance or runtime bindings.
        for parent in Path(root).resolve().parents:
            candidate = parent/'config/sad_relocations.json'
            if candidate.is_file():
                changes = json.loads(candidate.read_text(encoding='utf-8'))
                data.setdefault('prefixes', {}).update(changes.get('prefixes', {}))
                data.setdefault('file_aliases', {}).update({k:v for k,v in changes.get('file_aliases', {}).items() if k.startswith('data/')})
                break
    # Current migration metadata is separate from every frozen publication.
    migration = Path(root)/'config/sad_relocations.json'
    if migration.is_file():
        changes = json.loads(migration.read_text(encoding='utf-8'))
        for section in ('file_aliases', 'runtime_bindings', 'prefixes'):
            data.setdefault(section, {}).update(changes.get(section, {}))
    for old,new in OUTPUT_PREFIXES.items():
        data.setdefault('prefixes',{}).setdefault(old,new)
    return data


def resolve(root, path):
    root=Path(root).resolve();path=Path(path)
    path=path if path.is_absolute() else root/path
    from run_paths import resolve_file
    relocated=resolve_file(path)
    if relocated!=path:return relocated
    try:name=path.relative_to(root).as_posix()
    except ValueError:return path
    data=registry(root)
    if name in data.get('file_aliases',{}):
        target=root/data['file_aliases'][name]
        return path if path.exists() and not target.exists() else target
    for old,new in sorted(data.get('prefixes',{}).items(),key=lambda x:len(x[0]),reverse=True):
        if name==old or name.startswith(old+'/'):
            target=root/(new+name[len(old):])
            return path if path.exists() and not target.exists() else target
    # Read-only fallback for older isolated runs; new writes use destination().
    if not path.exists():
        for old,new in sorted(data.get('prefixes',{}).items(),key=lambda x:len(x[1]),reverse=True):
            if name==new or name.startswith(new+'/'):
                original=root/(old+name[len(new):])
                if original.exists():return original
    return path


def destination(root, path):
    """Forward relocation only: a writer can never fall back to data/ intermedios."""
    root=Path(root).resolve();path=Path(path)
    path=path if path.is_absolute() else root/path
    try:name=path.relative_to(root).as_posix()
    except ValueError:return path
    for old,new in sorted(registry(root).get('prefixes',{}).items(),key=lambda x:len(x[0]),reverse=True):
        if name==old or name.startswith(old+'/'):return root/(new+name[len(old):])
    return path


def legacy(root, path):
    root=Path(root).resolve();path=Path(path)
    try:name=path.relative_to(root).as_posix()
    except ValueError:return path
    for old,new in sorted(registry(root).get('prefixes',{}).items(),key=lambda x:len(x[1]),reverse=True):
        if name==new or name.startswith(new+'/'):return root/(old+name[len(new):])
    return path


def verify_expected(root,name,expected):
    name=str(name).replace('\\','/')
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
        # A split module also pins every implementation extracted from it.
        for name, checksum in binding.get('related_sha256', {}).items():
            related = root/name
            if not related.is_file() or hashlib.sha256(related.read_bytes()).hexdigest()!=checksum:
                raise ValueError('Fingerprint mismatch: '+name)
        snapshots = binding.get('snapshots', [binding.get('snapshot')])
        for snapshot in snapshots:
            original = root/snapshot if snapshot else None
            if current==binding['after_sha256'] and original and original.is_file() and hashlib.sha256(original.read_bytes()).hexdigest()==expected:return
    raise ValueError('Fingerprint mismatch: '+name)
