"""Revalidate original pilot responses and integrated delivery; never infer."""
from collections import defaultdict
from contextlib import closing
import json
from pathlib import Path
import re
import sys

from openpyxl import load_workbook

from export_layer4_pilot import ROOT, DEFAULT_CONFIG, FILENAMES, pilot_projects, indicator_projection
from layer4_evaluation.indicators import experiment
from layer4_evaluation.indicators.experiment_inputs import read, safe_path, sha256, selected_territories
from layer4_evaluation.indicators.powerbi import COLUMNS, TERRITORY_COLUMNS


def verify(root=ROOT, config_path=DEFAULT_CONFIG):
    root=Path(root).resolve()
    core=experiment.verify(root,config_path)
    config,out,manifest,data,selected,requests,runtime=experiment.verify_prepared(root,config_path)
    pilot=pilot_projects(selected,config,manifest)
    ids={p['project_id'] for p in pilot}
    paths=list((out/'records').glob('*.json'))
    if {p.stem for p in paths}-ids:
        raise ValueError('A project outside the authorized pilot was processed')
    records={p.stem:read(p) for p in paths}
    calls=[read(p) for p in sorted((out/'codex_runs').glob('*/attempt_*/call.json'))]
    if any(c['project_id'] not in ids for c in calls):
        raise ValueError('CLI call outside the authorized pilot')
    delivery=read(out/'pilot_delivery/latest_manifest.json')
    experiment.verify_hashes(root,delivery['code_hashes'])
    experiment.verify_hashes(out,delivery['technical_hashes'])
    folder=safe_path(root,delivery['delivery_directory'])
    if {p.name for p in folder.iterdir()}!=set(FILENAMES):
        raise ValueError('The public package must have exactly three files')
    experiment.verify_hashes(folder,delivery['delivery_hashes'])
    public,audit=indicator_projection(pilot,data['profiles'],records)
    territories=selected_territories(data,pilot)
    with closing(load_workbook(folder/'resultado_capa4.xlsx',data_only=False)) as book:
        if book.sheetnames!=['RESULTADO_INDICADORES','TERRITORIOS']:
            raise ValueError('Exactly two workbook sheets required')
        for name,columns,rows in (('RESULTADO_INDICADORES',COLUMNS,public),('TERRITORIOS',TERRITORY_COLUMNS,territories)):
            values=list(book[name].values)
            if values!=[tuple(columns),*[tuple(row[c] for c in columns) for row in rows]]:
                raise ValueError('Published workbook differs from revalidated source data: '+name)
            if any(cell.data_type in ('f','e') for row in book[name] for cell in row):
                raise ValueError('Unexpected workbook formula/error')
        for row in book['TERRITORIOS'].iter_rows(min_row=2):
            if row[0].data_type!='s' or row[2].data_type!='s' or row[4].value is not None and row[4].data_type!='s':
                raise ValueError('Institutional or territorial code lost its string type')
        for row in book['RESULTADO_INDICADORES'].iter_rows(min_row=2):
            if row[0].data_type!='s':raise ValueError('SIAP ID is not a string')
    if len((folder/'resumen_resultados.md').read_text(encoding='utf-8').split())>1000:
        raise ValueError('Summary exceeds the delivery word budget')
    for name in FILENAMES[1:]:
        if re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',(folder/name).read_text(encoding='utf-8')):
            raise ValueError('Unnecessary personal email in delivery')
    if delivery['experiment_manifest_sha256']!=sha256(out/'experiment_manifest.json'):
        raise ValueError('Refresh the delivery after experiment metadata changes')
    errors=[row for record in records.values() for row in record['rows'] if row['assessment_validation_status']!='VALID']
    result={'status':'PILOT_AUTOMATIC_VALIDATION_PASSED_PENDING_HUMAN_REVIEW' if len(public)==8 else 'PARTIAL_PILOT_VALIDATED',
        'core_verification':core,'pilot_project_count':len(pilot),'pilot_expected_assessments':8,
        'assessments_valid':len(public),'assessments_invalid':len(errors),'raw_responses_preserved':len(records),
        'cli_calls':len(calls),'retries':sum(c['retry']>0 for c in calls),
        'verified_literal_fragments':sum(len(r['locations']) for r in audit),
        'territory_relationships':len(territories),'territory_source':'ACCEPTED_RESOLVED_LAYER4B_ONLY',
        'territorial_processing_executed':False,'remaining_69_executed':False,
        'workbook_sheets':['RESULTADO_INDICADORES','TERRITORIOS'],'columns_per_sheet':7,
        'delivery_files':list(FILENAMES),'reproducibility':'ORIGINAL_RESPONSES_REVALIDATED_NO_NEW_INFERENCE',
        'human_benchmark':'PENDING','calibration':'NOT_CALIBRATED','academic_acceptance':False,
        'historical_code_checks_blocked':8,'model_effective':'NOT_REPORTED_BY_CLI',
        'authorization_kind':delivery.get('authorization_kind'),
        'verification_code_sha256':sha256(Path(__file__)),
        'delivery_manifest_sha256':sha256(out/'pilot_delivery/latest_manifest.json')}
    experiment.write_json(out/'pilot_delivery/acceptance_verification.json',result)
    return result


if __name__=='__main__':
    print(json.dumps(verify(),ensure_ascii=True,indent=2))
