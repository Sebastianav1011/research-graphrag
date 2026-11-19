"""Apply BALANCED_CRITERIA_DECISION_V2 to an already finished V5 run (no model calls).

Runs sealed with earlier code cannot be re-exported; this writes a NEW Excel (same sheets
and columns; only estado_cumplimiento and the decision paragraph of changed rows differ)
and a comparison JSON to the output directory. The run itself is never modified.

  uv run python scripts/redecide_run.py <run_dir> <output_dir>
"""
import collections
import glob
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from layer4_evaluation.indicators import decision_v2  # noqa: E402
from layer4_evaluation.indicators.prospective_v2 import EXTERNAL_RECORD_CRITERIA  # noqa: E402

MARK = '\n\nEvidencia literal:'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(run, out):
    import openpyxl
    run, out = Path(run), Path(out)
    out.mkdir(parents=True, exist_ok=False)
    source = run / 'resultados/resultado_indicadores.xlsx'
    before = sha(source)
    valid = json.loads((run / 'resultados/evaluaciones_validas.json').read_text(encoding='utf-8'))['assessments']
    rubrics = {}
    for plan in glob.glob(str(run / 'evaluation/batch_*/plan.json')):
        rubrics.update(json.loads(Path(plan).read_text(encoding='utf-8'))['rubrics'])
    receipts = {}
    for a in valid:
        receipts[(a['siap_id'], a['indicator_id'])] = decision_v2.final_decision(
            a, rubrics[a['indicator_id']], EXTERNAL_RECORD_CRITERIA.get(a['indicator_id'], ()))[1]
    book = openpyxl.load_workbook(source)
    rows = 0
    for sheet in book.worksheets:
        header = [c.value for c in sheet[1]]
        state, paragraph = header.index('estado_cumplimiento') + 1, header.index('parrafo_evidencia') + 1
        for r in range(2, sheet.max_row + 1):
            key = (str(sheet.cell(r, 1).value), sheet.cell(r, 2).value)
            receipt = receipts[key]
            text = sheet.cell(r, paragraph).value or ''
            original, _, quotes = text.partition(MARK)
            sheet.cell(r, state).value = receipt['decision']
            sheet.cell(r, paragraph).value = decision_v2.explanation(receipt, original) + (MARK + quotes if quotes else '')
            rows += 1
    if rows != len(receipts):
        raise ValueError(f'Filas del Excel ({rows}) distintas de las evaluaciones validas ({len(receipts)})')
    excel = out / 'resultado_indicadores_decision_v2.xlsx'
    book.save(excel)
    if sha(source) != before:
        raise ValueError('El Excel original cambio durante la reevaluacion')
    transitions = collections.Counter(f"{r['decision_v5']} -> {r['decision']}" for r in receipts.values())
    summary = dict(version=decision_v2.VERSION, run=run.name, source_excel_sha256=before, evaluations=len(receipts),
                   transitions=dict(sorted(transitions.items())),
                   by_rule=dict(collections.Counter(r['rule'] for r in receipts.values()).most_common()),
                   changed=[dict(siap_id=k[0], indicator_id=k[1], **r) for k, r in sorted(receipts.items()) if r['changed']],
                   excel=str(excel), excel_sha256=sha(excel))
    (out / 'decision_v2.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'recibos.json').write_text(json.dumps({f'{k[0]}|{k[1]}': r for k, r in sorted(receipts.items())},
                                                 ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('evaluations', 'transitions', 'by_rule')}, ensure_ascii=False, indent=1))
    for c in summary['changed']:
        print('CAMBIO', c['siap_id'], c['indicator_id'], c['decision_v5'], '->', c['decision'], c['rule'], c['evidence_nature'])


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
