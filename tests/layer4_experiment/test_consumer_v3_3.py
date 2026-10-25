from copy import deepcopy
import json
from pathlib import Path

import pytest
from layer4.indicators.consumer_v3_3 import build_spec,COLUMNS,TERRITORY_COLUMNS
from layer4.indicators.experiment_inputs import read

ROOT=Path(__file__).resolve().parents[2]
STUDY=ROOT/'outputs/layer4/pruebas/validacion_v3_3'


@pytest.fixture
def bundle():
    p=read(STUDY/'continuacion_prompt_v3_1/plan.json')
    projects=[x for x in p['projects'] if x['project_id'] in ('PROJ_20022','PROJ_20456')]
    rows=[json.loads(x) for x in (STUDY/'pilot_five.assessment_results.jsonl').read_text(encoding='utf-8').splitlines() if x]
    rows=[r for r in rows if r['project_id'] in ('PROJ_20022','PROJ_20456')]
    selections={'PROJ_20022':read(STUDY/'control_positivo_v3_3_PROJ_20022.response.json'),
        'PROJ_20456':read(STUDY/'cierre_homogeneo_v3_3/PROJ_20456/discovery/codex_runs/PROJ_20456/attempt_1/response.json')}
    return projects,rows,p['profiles'],read(STUDY/'continuacion_prompt_v3_1/rubrics.json'),selections,dict(dimension=[],relationships=[])


def test_exact_two_sheet_contract_and_internal_decisions(bundle):
    spec,audit=build_spec(*bundle,require_complete=False)
    assert [s['name'] for s in spec['sheets']]==['RESULTADO_INDICADORES','TERRITORIOS']
    assert spec['sheets'][0]['columns']==COLUMNS and len(COLUMNS)==6
    assert 'estado_cumplimiento' not in COLUMNS
    assert spec['sheets'][1]['columns']==TERRITORY_COLUMNS==['siap_id','territory_type','territory_code','code_system']
    assert len(spec['sheets'][0]['rows'])==2
    assert all(len(r)==6 and r[-1]==86.25 for r in spec['sheets'][0]['rows'])
    assert any(r['decision']=='INSUFFICIENT_EVIDENCE' and not r['exported'] for r in audit['records'])
    assert not audit['confidence_is_probability'] and not audit['publication_performed']


def test_missing_soc02_prevents_complete_export(bundle):
    with pytest.raises(ValueError,match='Missing/invalid assessment'):
        build_spec(*bundle)


@pytest.mark.parametrize('mutation',[
    lambda rows:rows[0].update(confidence_raw_score=99),
    lambda rows:rows[0].update(evidence_texts=['INVENTED']*len(rows[0]['evidence_texts'])),
    lambda rows:rows[0].update(assessment_version='ASSESSMENT_V2'),
    lambda rows:rows.append(deepcopy(rows[0])),
])
def test_false_confidence_quotes_contract_or_duplicate_rejected(bundle,mutation):
    args=list(deepcopy(bundle));mutation(args[1])
    with pytest.raises(ValueError):build_spec(*args,require_complete=False)


def test_invalid_row_stays_internal_and_cannot_complete(bundle):
    args=list(deepcopy(bundle));args[1][0]['assessment_validation_status']='INVALID_ASSESSMENT'
    spec,audit=build_spec(*args,require_complete=False)
    assert len(spec['sheets'][0]['rows'])==1
    assert any(x['reason']=='INVALID_INTERNAL_ONLY' for x in audit['records'])


def test_absent_selection_is_never_invented(bundle):
    args=list(deepcopy(bundle));args[4].pop('PROJ_20456')
    with pytest.raises(ValueError,match='Exact project/selection'):build_spec(*args)


def test_synthetic_negative_is_audited_and_never_exported(bundle):
    from layer4.indicators import assessment_v3 as v3
    args=list(deepcopy(bundle));old=args[1][0]
    project=next(p for p in args[0] if p['project_id']==old['project_id'])
    assessment=dict(assessment_version=v3.VERSION,decision='NOT_SUPPORTED',support_strength=0,
        criterion_assessments=[dict(criterion_id=x['criterion_id'],support='NOT_DEMONSTRATED',
            evidence_indices=[],explanation='Synthetic negative contract test only.')
            for x in old['criterion_assessments']],evidence=[],explanation='Synthetic test, no historical decision changed.')
    negative=v3.indicator_row(project,args[2][old['indicator_id']],assessment,args[3][old['indicator_id']])
    assert negative['assessment_validation_status']=='VALID'
    args[1][0]=negative
    spec,audit=build_spec(*args,require_complete=False)
    entry=next(r for r in audit['records'] if r['project_id']==old['project_id'] and r['indicator_id']==old['indicator_id'])
    assert entry['decision']=='NOT_SUPPORTED' and not entry['exported']
    assert len(spec['sheets'][0]['rows'])==1
