"""Preparation only: no assessment, retrieval, sample selection or real workbook."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from layer4.indicators.preparation import prepare
if __name__=='__main__':
    try:
        report=prepare(ROOT)
        print(json.dumps({'status':report['preparation_status'],'indicators':report['profile_metrics']['valid_indicator_rows'],
                          'selected_projects':0,'assessment_rows':0,'real_workbooks':0},ensure_ascii=True))
    except (ValueError,OSError) as exc:
        print(json.dumps({'status':'BLOCKED','error':str(exc)},ensure_ascii=True))
        raise SystemExit(2)
