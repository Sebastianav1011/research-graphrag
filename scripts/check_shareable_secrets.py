"""Offline conservative scan of tracked and unignored candidates; never prints matches."""
from pathlib import Path
import re
import subprocess


def check(root):
    root=Path(root)
    names=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=root).decode().split('\0')
    findings=[];checked=0
    token=re.compile(rb'\bsk-[A-Za-z0-9_-]{20,}')
    for name in set(names)-{''}:
        path=root/name
        if not path.is_file():continue
        checked+=1
        if (path.name.startswith('.env') and path.name!='.env.example' or
                any(part in ('.venv','.aws','.ssh','.ollama','.huggingface') for part in path.parts) or
                path.suffix in ('.key','.p12','.pfx') or token.search(path.read_bytes())):
            findings.append(name)
    return checked,sorted(findings)


if __name__=='__main__':
    count,findings=check(Path(__file__).resolve().parents[1])
    print(f'Archivos candidatos revisados: {count}; hallazgos: {len(findings)}')
    for name in findings:print('REVISAR: '+name)
    raise SystemExit(bool(findings))
