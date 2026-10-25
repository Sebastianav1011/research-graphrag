"""Prepare Layer 4 profiles/rule text only. Never select projects or execute assessment."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from layer4.indicators.profiles import build_profiles

if __name__=='__main__':
    _,manifest=build_profiles(ROOT)
    print(json.dumps({'status':'INDICATOR_ASSESSMENT_PROFILES_READY',
                      'reference_id':manifest['reference_id'],'metrics':manifest['metrics']},ensure_ascii=True))
