"""Read-only original inventory verification, with an optional audit report.

Some historical test fixtures have different sandbox/native ACL visibility.
Reports distinguish permission failures from missing files or hash mismatches.
Never invokes inference, deletes files or generates a workbook.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from layer4_evaluation.paths import verify_expected, resolve


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    result=dict(verified=[],permission_denied=[],errors=[],inference_calls=0)
    audit=ROOT/'outputs/layer4/auditoria'
    for name in ('inventory_before.json','inventory_restricted.json'):
        for row in json.loads((audit/name).read_text(encoding='utf-8'))['files']:
            try:
                actual=hashlib.sha256(resolve(ROOT,row['path']).read_bytes()).hexdigest()
                if actual!=row['sha256']:
                    verify_expected(ROOT,row['path'],row['sha256'])
                result['verified'].append(row['path'])
            except PermissionError:result['permission_denied'].append(row['path'])
            except Exception as exc:result['errors'].append(dict(path=row['path'],error=str(exc)))
    registry=json.loads((audit/'rutas.json').read_text(encoding='utf-8'))
    for name,binding in registry['runtime_bindings'].items():
        try:
            # Verify the previous runtime bytes and separately pinned relocation.
            verify_expected(ROOT,name,binding['after_sha256'])
            path=ROOT/binding['snapshot']
            if hashlib.sha256(path.read_bytes()).hexdigest()!=binding['before_sha256']:
                raise ValueError('Original migration snapshot mismatch')
        except Exception as exc:
            result['errors'].append(dict(path=name,error=str(exc)))
    v2=ROOT/'outputs/layer4/final/resultado_capa4.xlsx'
    result['v2_sha256']=hashlib.sha256(v2.read_bytes()).hexdigest()
    if result['v2_sha256']!='fc6f876493ee327f140f5fbdbd234b93242eeaee15d86aa752388980f03332e1':
        result['errors'].append(dict(path=str(v2),error='Official V2 mismatch'))
    if args.report:
        destination=args.report.resolve()
        if not destination.is_relative_to(audit.resolve()):raise ValueError('Report must stay inside Layer4 audit directory')
        destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(verified=len(result['verified']),permission_denied=len(result['permission_denied']),
                         errors=len(result['errors']),v2_sha256=result['v2_sha256']),ensure_ascii=False))
    if result['errors']:raise SystemExit(1)


if __name__=='__main__':main()
