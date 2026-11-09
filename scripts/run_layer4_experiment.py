"""Explicit experiment commands; defaults to help, never implicit inference."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from layer4_evaluation.indicators import experiment
from layer4_evaluation.indicators import experiment_export


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default=experiment.CONFIG)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('prepare','verify','report','export','finalize'):
        command=sub.add_parser(name)
        if name=='finalize':
            command.add_argument('--approval',type=Path)
            command.add_argument('--review',type=Path)
    for name in ('audit','compare','review','performance','verify-final'):
        command=sub.add_parser(name)
        if name=='performance':
            command.add_argument('--historical',action='store_true')
    execute=sub.add_parser('execute-batch')
    execute.add_argument('--stage',choices=('pilot','continue'),required=True)
    execute.add_argument('--authorization',type=Path,required=True)
    execute.add_argument('--pilot-approval',type=Path)
    metrics=sub.add_parser('human-metrics')
    metrics.add_argument('workbooks',type=Path,nargs='+')
    args=parser.parse_args()
    if args.command=='audit':
        from layer4_evaluation.indicators.closure_audit import audit
        result=audit(experiment.ROOT)
    elif args.command in ('compare','review','performance','verify-final'):
        from layer4_evaluation.indicators import closure_export, performance_report
        if args.command=='performance':
            result=performance_report.generate(experiment.ROOT,None if args.historical else args.config)
        elif args.command=='verify-final':
            result=closure_export.verify_final(experiment.ROOT,args.config)
        else:
            result=getattr(closure_export,'comparison' if args.command=='compare' else 'review')(experiment.ROOT,args.config)
    elif args.command=='execute-batch':
        result=experiment.execute_batch(config_path=args.config,stage=args.stage,
            authorization=args.authorization,pilot_approval=args.pilot_approval)
    elif args.command in ('export','finalize'):
        config,_=experiment.configuration(path=args.config)
        if experiment.is_v2(config):
            from layer4_evaluation.indicators import closure_export
            result=(closure_export.publish(experiment.ROOT,args.config,args.approval,args.review)
                    if args.command=='finalize' else closure_export.review(experiment.ROOT,args.config))
        else:
            result=experiment_export.export(config_path=args.config,require_complete=args.command=='finalize')
    elif args.command=='human-metrics':
        config,_=experiment.configuration(path=args.config)
        if experiment.is_v2(config):
            from layer4_evaluation.indicators.closure_export import review_metrics
            if len(args.workbooks)!=1 or args.workbooks[0].suffix.lower()!='.json':
                raise ValueError('V2 human-metrics requires one completed human-review JSON')
            result=review_metrics(experiment.ROOT,args.config,args.workbooks[0])
        else:
            result=experiment_export.import_reviews(args.workbooks,config_path=args.config)
    else:
        result=getattr(experiment,args.command)(config_path=args.config)
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':
    main()
