"""Validate a complete consumer bundle; never create/publish an Excel workbook."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from layer4_evaluation.indicators.consumer_v3_3 import build_spec, VERSION
from layer4_evaluation.indicators.experiment_inputs import read, verify_hashes
from layer4_evaluation.territorial_consumption import verify_consumption


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',required=True,type=Path)
    parser.add_argument('--check-only',required=True,action='store_true')
    args=parser.parse_args();bundle=read(args.bundle)
    if bundle.get('consumer_contract')!=VERSION:raise ValueError('Explicit new consumer contract required')
    if len(bundle['projects'])!=20:raise ValueError('Final bundle must cover the fixed twenty projects')
    verify_hashes(ROOT,bundle['source_hashes'])
    territorial_qa=verify_consumption(ROOT,selected=bundle['projects'],consumer_data=bundle['territories'])
    spec,audit=build_spec(bundle['projects'],bundle['rows'],bundle['profiles'],bundle['rubrics'],bundle['selections'],bundle['territories'])
    print(json.dumps(dict(status='PASS',contract=VERSION,sheets=[dict(name=s['name'],columns=s['columns'],rows=len(s['rows'])) for s in spec['sheets']],audit=audit,territorial_qa=territorial_qa,publication_performed=False),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
