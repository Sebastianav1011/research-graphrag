"""Export/check Layer 4 preparation schemas only. No pipeline or provider execution."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from layer4_evaluation.indicators.contracts import check_contracts
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--v2',action='store_true',help='Versioned ASSESSMENT_V2 and confidence contracts only')
    args=parser.parse_args()
    if args.v2:
        from layer4_evaluation.indicators.assessment_v2 import write_contracts
        write_contracts(ROOT,check=args.check)
        print('Layer 4 V2 schemas:',3,'CHECKED' if args.check else 'PREPARED')
    else:
        print('Layer 4 schemas:',check_contracts(ROOT,write=not args.check),'CHECKED' if args.check else 'PREPARED')
