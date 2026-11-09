"""Single active closure procedure; frozen initial assessments stay reproducible."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import yaml
from layer4_evaluation.indicators.experiment_inputs import read, safe_path, sha256
from layer4_evaluation.indicators import experiment
from layer4_evaluation.indicators.selection import canonical_hash
from layer4_evaluation.paths import legacy


def settings(path='config/layer4_closure.yaml'):
    value=yaml.safe_load(safe_path(ROOT,path).read_text(encoding='utf-8'))
    if set(value)!={'version','base_config','pilot_directory','closure_directory','fallback'} or value['version']!='LAYER4_CLOSURE_CONTROL_V1':
        raise ValueError('Unknown closure settings')
    from layer4_evaluation.indicators.semantic_fallback import options
    options(value['fallback'])
    for key in ('pilot_directory','closure_directory'):
        out=safe_path(ROOT,value[key])
        if legacy(ROOT, out).parent!=(ROOT/'outputs/layer4/pruebas').resolve():
            raise ValueError('Active study directories must be direct children of pruebas')
    if value['pilot_directory']==value['closure_directory']:
        raise ValueError('Pilot control and closure execution must have distinct roles')
    return value


def pilot_ids(plan):
    return [item['project']['project_id'] for item in plan['projects'][:5]]


def pilot_digest(directory,plan):
    hashes={}
    for pid in pilot_ids(plan):
        completion=Path(directory)/'completed'/(pid+'.json')
        if not completion.is_file():
            raise ValueError('BLOCKED: pilot complementary evaluation is incomplete')
        hashes[pid]=sha256(completion)
    return canonical_hash({'plan_sha256':sha256(Path(directory)/'plan.json'),'completed_projects':hashes})


def validate_execution_scope(stage,plan,directory,authorization,pilot_approval=None):
    ids=authorization.get('project_ids',[])
    pilot=set(pilot_ids(plan))
    if stage=='pilot':
        if not isinstance(ids,list) or set(ids)!=pilot or len(ids)!=len(pilot):
            raise ValueError('Pilot authorization must cover exactly the five prepared pilot projects')
        return
    remaining={item['project']['project_id'] for item in plan['projects']}-pilot
    if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or not set(ids).issubset(remaining):
        raise ValueError('Continuation authorization must cover only pending projects outside the pilot')
    approved=pilot_approval or {}
    if (approved.get('plan_sha256')!=sha256(Path(directory)/'plan.json') or
        approved.get('pilot_results_sha256')!=pilot_digest(directory,plan) or
        approved.get('approved') is not True or approved.get('discrepancies_resolved') is not True or
        any(not isinstance(approved.get(k),str) or not approved[k].strip() for k in
            ('approved_by','approved_at','comparison_reference','human_review_reference'))):
        raise ValueError('BLOCKED: explicit pilot benefit/quality review and bound approval required')


def pilot_control(value, checked):
    """References and review inputs, not a second copy of model outputs."""
    directory=safe_path(ROOT,value['closure_directory']);plan=read(directory/'plan.json')
    out=safe_path(ROOT,value['pilot_directory']);out.mkdir(parents=True,exist_ok=True)
    existing=read(out/'index.json') if (out/'index.json').exists() else None
    index={'version':'LAYER4_PILOT_CONTROL_V1','source_directory':value['closure_directory'],
        'plan_sha256':sha256(directory/'plan.json'),'project_ids':pilot_ids(plan),
        'original_execution_id':plan['source_execution_id'],
        'purpose':'Review and compare the five-project pilot; inference artifacts live once in cierre_v2_20',
        'human_review_source':str(Path(checked['human_review']['workbook']).relative_to(ROOT)).replace('\\','/')}
    if existing and existing['plan_sha256']!=index['plan_sha256']:
        raise ValueError('Preserve existing pilot control bound to another plan')
    experiment.write_json(out/'index.json',index)
    auth=read(directory/'authorization.example.json');auth['project_ids']=pilot_ids(plan)
    for filename,data in [('authorization.pilot.example.json',auth),
                          ('human_opinions.original.json',checked['human_review']),
                          ('pilot_approval.example.json',{'plan_sha256':index['plan_sha256'],
                           'pilot_results_sha256':None,'approved':False,'discrepancies_resolved':False,
                           'approved_by':'','approved_at':'','comparison_reference':'','human_review_reference':''})]:
        if not (out/filename).exists():experiment.write_json(out/filename,data)
    return index


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings',default='config/layer4_closure.yaml')
    parser.add_argument('--output',type=Path)
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('verify','status','compare','verify-final'):
        commands.add_parser(name)
    prep=commands.add_parser('prepare')
    prep.add_argument('--correction-pair',action='append',default=[],metavar='PROJECT:INDICATOR')
    for name in ('execute-pilot','execute-remaining'):
        execute=commands.add_parser(name)
        execute.add_argument('--authorization',type=Path,required=True)
        execute.add_argument('--batch-size',type=int,default=5)
        if name=='execute-remaining':execute.add_argument('--pilot-approval',type=Path,required=True)
    final=commands.add_parser('finalize')
    final.add_argument('--approval',type=Path,required=True);final.add_argument('--review',type=Path,required=True)
    args=parser.parse_args();value=settings(args.settings)
    from layer4_evaluation.indicators import semantic_fallback as sf
    from layer4_evaluation.indicators.closure_runtime import verify_current
    directory=safe_path(ROOT,value['closure_directory'])
    if args.command in ('verify','status'):
        checked=verify_current(ROOT,value['base_config'])
        result={'initial':checked['verification'],'human_review':checked['human_review'],
                'supplemental':sf.verify(ROOT,directory) if (directory/'plan.json').exists() else None,
                'status':'BLOCKED','cause':'Explicit new inference authorization, discrepancy resolution and final acceptance required',
                'official_output':'outputs/layer4/final/resultado_capa4.xlsx'}
    elif args.command=='prepare':
        pairs=[]
        for pair in args.correction_pair:
            bits=pair.split(':')
            if len(bits)!=2 or not all(bits):raise ValueError('Expected PROJECT:INDICATOR')
            pairs.append(tuple(bits))
        from layer4_evaluation.indicators.codex_cli import inspect_runtime
        result=sf.prepare(ROOT,value['base_config'],value['closure_directory'],
            options_value=value['fallback'],correction_pairs=pairs,include_remaining=True,
            runtime_value=inspect_runtime())
        result={'supplemental':result,'pilot':pilot_control(value,verify_current(ROOT,value['base_config']))}
    elif args.command in ('execute-pilot','execute-remaining'):
        plan=read(directory/'plan.json');authorization=read(args.authorization)
        sf.verify(ROOT,directory)
        validate_execution_scope('pilot' if args.command=='execute-pilot' else 'remaining',plan,directory,
            authorization,read(args.pilot_approval) if args.command=='execute-remaining' else None)
        result=sf.execute(ROOT,directory,args.authorization,batch_size=args.batch_size)
    elif args.command=='compare':
        result=sf.comparison(ROOT,directory)
        try:result['pilot_results_sha256']=pilot_digest(directory,read(directory/'plan.json'))
        except ValueError:result['pilot_results_sha256']=None
        control=safe_path(ROOT,value['pilot_directory'])
        if control.exists():experiment.write_json(control/'comparison.json',result)
    else:
        from layer4_evaluation.indicators import final_export
        result=(final_export.verify_final(ROOT,value['base_config']) if args.command=='verify-final' else
                final_export.publish(ROOT,value['base_config'],args.approval,args.review))
    if args.output:
        path=safe_path(ROOT,args.output);path.parent.mkdir(parents=True,exist_ok=True);experiment.write_json(path,result)
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
