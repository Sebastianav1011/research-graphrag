from copy import deepcopy
from pathlib import Path
import json

import pytest
from layer4.indicators import final_export


def sample():
    selected = [{'project_id': 'P', 'siap_id': '001', 'fields': {'summary': 'Texto literal.'},
                 'field_provenance': {'summary': {'section_id': 'SEC'}}}]
    rows = []
    for indicator, decision, score in [('A', 'SUPPORTED', 100), ('B', 'INSUFFICIENT_EVIDENCE', 55.63),
                                       ('C', 'NOT_SUPPORTED', 0)]:
        rows.append({'project_id': 'P', 'indicator_id': indicator, 'decision': decision,
            'assessment_version': 'ASSESSMENT_V2', 'confidence_version': 'EVIDENCE_CONFIDENCE_V2',
            'assessment_validation_status': 'VALID', 'validation_errors': [],
            'confidence_status': 'COMPUTED', 'confidence_raw_score': score,
            'confidence_probability': None, 'confidence_level': None,
            'evidence_texts': [] if decision == 'NOT_SUPPORTED' else ['Texto literal.'],
            'evidence_source_fields': [] if decision == 'NOT_SUPPORTED' else ['summary'],
            'candidate_source': 'LAYER4_SEMANTIC_FALLBACK' if indicator == 'B' else 'LAYER3_RETRIEVAL'})
    return selected, rows


def test_final_two_sheets_exact_columns_and_all_valid_states():
    selected, rows = sample()
    records = final_export.records_from_rows(selected, rows)
    spec = final_export.build_spec(selected, records, {'dimension': [], 'relationships': []})
    assert [tab['name'] for tab in spec['sheets']] == ['RESULTADO_INDICADORES', 'TERRITORIOS']
    assert spec['sheets'][0]['columns'] == ['siap_id', 'indicador_id', 'estado_cumplimiento',
        'parrafo_evidencia', 'fuente_evidencia', 'ubicacion_evidencia', 'confianza']
    assert spec['sheets'][1]['columns'] == ['siap_id', 'territory_type', 'territory_code', 'code_system']
    assert len(spec['sheets'][0]['rows']) == 3
    assert [row[-1] for row in spec['sheets'][0]['rows']] == [100, 55.63, 0]
    assert spec['sheets'][0]['rows'][-1][3:6] == [None, None, None]
    assert 'candidate_source' not in spec['sheets'][0]['columns']


@pytest.mark.parametrize('mutation', [
    lambda rows: rows.append(deepcopy(rows[0])),
    lambda rows: rows[0].update(project_id='UNKNOWN'),
    lambda rows: rows[0].update(evidence_source_fields=[]),
    lambda rows: rows[0].update(evidence_texts=['Invented quote']),
    lambda rows: rows[0].update(assessment_validation_status='INVALID_ASSESSMENT'),
    lambda rows: rows[0].update(confidence_raw_score=101),
])
def test_final_rejects_duplicates_invalid_scores_and_fabricated_evidence(mutation):
    selected, rows = sample()
    mutation(rows)
    with pytest.raises(ValueError):
        final_export.build_spec(selected, final_export.records_from_rows(selected, rows),
                                {'dimension': [], 'relationships': []})


def test_no_official_workbook_without_acceptance(tmp_path):
    result = final_export.verify_final(tmp_path, 'not-needed-until-accepted.yaml')
    assert result['status'] == 'BLOCKED'
    assert not (tmp_path / 'outputs/layer4/final/resultado_capa4.xlsx').exists()


def test_explicit_definitive_execution_is_used_for_acceptance(tmp_path, monkeypatch):
    from layer4.indicators import semantic_fallback
    selected, rows = sample()
    folder = tmp_path / 'outputs/layer4/pruebas/piloto_v2/cierre_20'
    folder.mkdir(parents=True)
    (folder / 'plan.json').write_text('{}', encoding='utf-8')
    seen = []
    def accepted(root, directory, approval, review):
        seen.append(directory)
        return {'status':'PASS', 'rows':rows, 'human_review_summary':{},
                'effective_results_sha256':'RESULTS', 'supplemental_plan_sha256':'PLAN'}
    monkeypatch.setattr(semantic_fallback, 'publication_check', accepted)
    result = final_export._accepted_records(tmp_path, None, {}, selected, {},
        {'supplemental_output_directory':'outputs/layer4/pruebas/piloto_v2/cierre_20'}, 'unused')
    assert seen == [folder]
    assert result[2]['supplemental_plan_sha256'] == 'PLAN'


@pytest.mark.parametrize('directory', ['outputs/layer4/pruebas/missing', 'outputs/layer4/elsewhere'])
def test_explicit_execution_cannot_fall_back_to_historical_records(tmp_path, directory):
    with pytest.raises(ValueError):
        final_export._accepted_records(tmp_path, None, {}, [], {},
            {'supplemental_output_directory':directory}, 'unused')


def test_pending_journal_blocks_verification(tmp_path):
    pending = tmp_path / 'outputs/layer4/auditoria/cierre_v2/publication_pending.json'
    pending.parent.mkdir(parents=True)
    pending.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='recovery journal'):
        final_export.verify_final(tmp_path, 'not-needed-until-recovered.yaml')


def test_interrupted_publication_keeps_journal_and_previous_bytes(tmp_path, monkeypatch):
    selected, rows = sample()
    out = tmp_path / 'outputs/layer4/old'
    out.mkdir(parents=True)
    (out / 'protected_inputs.json').write_text('{}', encoding='utf-8')
    (out / 'technical_results.jsonl').write_text('', encoding='utf-8')
    config = {'version': 'LAYER4A_20_V2'}
    state = {'verified': (config, out, {'execution_id': 'SYNTH', 'selection_sha256': 'SELECTION'},
                         {'dimension': [], 'relationships': []}, selected, [], {}), 'verification': {'status': 'PASS'}}
    monkeypatch.setattr(final_export, '_runtime', lambda *args: state)
    monkeypatch.setattr(final_export, '_accepted_records', lambda *args:
        (final_export.records_from_rows(selected, rows), {}, {}))
    def render(root, spec, target, audit):
        target.write_bytes(b'synthetic-new-workbook')
        return {'status': 'PASS_SYNTHETIC_WRITER_ONLY'}
    monkeypatch.setattr(final_export, 'render_workbook', render)
    for name in ('final_export.py', 'final_projection.py', 'closure_runtime.py'):
        path = tmp_path / 'src/layer4/indicators' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# synthetic', encoding='utf-8')
    approval, review = tmp_path / 'approval.json', tmp_path / 'review.json'
    approval.write_text('{}', encoding='utf-8'); review.write_text('{}', encoding='utf-8')
    official = tmp_path / 'outputs/layer4/final/resultado_capa4.xlsx'
    official.parent.mkdir(parents=True)
    official.write_bytes(b'synthetic-previous-workbook')
    original_write = final_export.experiment.write_json
    def fail_final_manifest(path, value):
        if path.name == 'final_manifest.json':
            raise OSError('Synthetic publication interruption')
        return original_write(path, value)
    monkeypatch.setattr(final_export.experiment, 'write_json', fail_final_manifest)
    with pytest.raises(OSError, match='interruption'):
        final_export.publish(tmp_path, 'config.yaml', approval, review)
    pending = tmp_path / 'outputs/layer4/auditoria/cierre_v2/publication_pending.json'
    assert pending.exists()
    archived = list((pending.parent / 'publications').glob('previous_*/resultado_capa4.xlsx'))
    assert len(archived) == 1 and archived[0].read_bytes() == b'synthetic-previous-workbook'
    with pytest.raises(ValueError, match='recovery journal'):
        final_export.verify_final(tmp_path, 'config.yaml')
