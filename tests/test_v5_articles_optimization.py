"""V5 consolidation: article sources, Excel 'Articulos', menu and retrieval optimization.

Offline and deterministic: no Ollama, API, embeddings or Knowledge rebuild.
"""
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import openpyxl
import pytest

from layer3_graphrag.vector_index import NumpyVectorIndex
from layer4_evaluation.indicators.mapped_index import open_mapped
from layer4_evaluation import thesis_output as output
from layer4_evaluation.indicators import article_sources, scoped_retrieval as sr

ROOT = Path(__file__).resolve().parents[1]


def canonical():
    return [dict(article_id='ART_2-s2.0-1', eid='2-s2.0-1', doi='10.1/a', title='Uno', record_source='p.csv', source_row='3'),
            dict(article_id='ART_2-s2.0-2', eid='2-s2.0-2', doi='10.1/shared', title='Dos', record_source='p.csv', source_row='4'),
            dict(article_id='ART_2-s2.0-3', eid='2-s2.0-3', doi='10.1/SHARED', title='Tres', record_source='p.csv', source_row='5')]


def test_article_identity_is_stable_and_never_duplicated():
    rows = canonical()
    assert article_sources.resolve(rows, ['ART_2-s2.0-1', '2-s2.0-2']) == ['ART_2-s2.0-1', 'ART_2-s2.0-2']
    assert article_sources.resolve(rows, ['10.1/A']) == ['ART_2-s2.0-1']  # unique DOI, case-insensitive
    with pytest.raises(ValueError, match='DOI compartido'):
        article_sources.resolve(rows, ['10.1/shared'])
    with pytest.raises(ValueError, match='una sola vez'):
        article_sources.resolve(rows, ['ART_2-s2.0-1', '2-s2.0-1'])  # same publication twice
    with pytest.raises(ValueError, match='no encontrados'):
        article_sources.resolve(rows, ['ART_x'])


def section(field, text, source='ART_2-s2.0-1'):
    provenance = dict(layer1=[dict(field_mapping={field: {'abstract': 'resumen', 'title': 'nombre_producto'}.get(field, field)},
                                   record_source='p.csv', source_row=3)])
    return dict(section_id=f'SEC_{field}', source_id=source, source_type='ARTICLE', field_name=field, text_original=text,
                text_hash_original='h', provenance_json=json.dumps(provenance))


def test_article_input_keeps_identity_metadata_and_raw_column():
    sections = article_sources.mapped([section('title', 'Uno'), section('abstract', 'Resumen. Resultado.'),
                                       section('abstract', 'Otro', source='ART_2-s2.0-2')], {'ART_2-s2.0-1'})
    assert [s['field_name'] for s in sections] == ['title', 'text__abstract', 'abstract']  # only the selected article
    value = article_sources.article_input(canonical()[0], sections, ('title', 'keywords', 'summary', 'methodology',
                                                                      'objectives', 'expected_results'))
    assert value['source_type'] == 'ARTICLE' and value['siap_id'] == 'ART_2-s2.0-1'
    assert value['fields']['text__abstract'] == 'Resumen. Resultado.' and value['fields']['summary'] == ''
    raw = value['field_provenance']['text__abstract']['raw_sources'][0]
    assert raw['field_mapping']['text__abstract'] == 'resumen'  # original column preserved
    assert value['bibliographic']['doi'] == '10.1/a' and value['bibliographic']['eid'] == '2-s2.0-1'
    assert article_sources.has_evidence(value)


def record(source, decision='INSUFFICIENT_EVIDENCE', score=12.5):
    return {'proyecto/articulo_siap_id': source, 'indicador_id': 'SAL-02', 'estado_cumplimiento': decision,
            'parrafo_evidencia': 'Explicacion.', 'fuente_evidencia': 'resumen', 'ubicacion_evidencia': '[1] fila=3',
            'territorio_region': None, 'confianza': score}


def test_excel_has_projects_and_articles_with_bibliographic_columns(tmp_path):
    article = dict(record('ART_2-s2.0-1', 'SUPPORTED', 81.25), titulo='Uno', doi='10.1/a', eid='2-s2.0-1')
    target = tmp_path / 'resultado.xlsx'
    output.render(ROOT, target, [record('21844')], [article], contract=output.PROSPECTIVE_CONTRACT)
    book = openpyxl.load_workbook(target, read_only=True, data_only=True)
    try:
        assert book.sheetnames == output.SHEETS
        projects, articles = list(book['Proyectos'].values), list(book['Artículos'].values)
        assert list(projects[0]) == output.GENERAL_COLUMNS
        assert list(articles[0]) == output.GENERAL_COLUMNS + output.ARTICLE_COLUMNS
        assert articles[1][0] == 'ART_2-s2.0-1' and articles[1][6] == 81.25 and articles[1][7:] == ('Uno', '10.1/a', '2-s2.0-1')
        assert projects[1][0] == '21844' and len(projects[1]) == 7
    finally:
        book.close()
    # Without articles the sheet keeps only its header (project-only runs unchanged).
    output.render(ROOT, target, [record('21844')], [], contract=output.PROSPECTIVE_CONTRACT)
    book = openpyxl.load_workbook(target, read_only=True)
    try:
        assert len(list(book['Artículos'].values)) == 1
    finally:
        book.close()


def test_menu_offers_articles_only_after_projects_and_can_be_declined(monkeypatch):
    import run
    inventory = [dict(article_id='ART_2-s2.0-1', eid='2-s2.0-1', doi='10.1/a', title='Uno', publication_year=2025, has_abstract=True,
                      original_id='2-s2.0-1', original_id_type='EID'),
                 dict(article_id='ART_2-s2.0-2', eid='2-s2.0-2', doi='10.1/b', title='Dos', publication_year=2024, has_abstract=False,
                      original_id='2-s2.0-2', original_id_type='EID')]
    monkeypatch.setattr(article_sources, 'inventory', lambda root: inventory)
    answers = iter(['N'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(answers))
    selection = dict(project_id=['21844'])
    assert run.menu_sources(selection, ROOT, 42) is True and 'articles' not in selection
    # S -> invalid option -> IDs with dots -> confirmation.
    answers = iter(['si', '9', '2', 'ART_2-s2.0-1', 'S'])
    selection = dict(project_id=['21844'])
    assert run.menu_sources(selection, ROOT, 42) is True and selection['articles'] == '2-s2.0-1'  # original EID, never ART_
    # S -> back (0) returns to the question; then N keeps the projects without articles.
    answers = iter(['S', '0', 'N'])
    selection = dict(limit=3)
    assert run.menu_sources(selection, ROOT, 42) is True and selection == dict(limit=3)
    # Quantity uses only articles with an abstract, reproducibly.
    answers = iter(['S', '1', '1', 'S'])
    selection = dict(limit=3)
    run.menu_sources(selection, ROOT, 42)
    assert selection['articles'] == '2-s2.0-1'


def test_cli_article_ids_are_validated():
    import argparse, run
    assert run.selected_article_ids(argparse.Namespace(articles=None)) is None
    assert run.selected_article_ids(argparse.Namespace(articles='ART_2-s2.0-1, 2-s2.0-2')) == ['ART_2-s2.0-1', '2-s2.0-2']
    with pytest.raises(ValueError):
        run.selected_article_ids(argparse.Namespace(articles='A,A'))


def small_index(tmp_path, n=40, d=8):
    rng = np.random.default_rng(0)
    vectors = rng.normal(size=(n, d))
    class Bundle:
        metadata = dict(model='m', model_version='1', dimensions=d, config_hash='cfg')
        records = [dict(chunk_id=f'C{i:03d}', embedding_id=f'E{i:03d}', source_space='SOURCE', model='m',
                        model_version='1', dimensions=d) for i in range(n)]
    Bundle.vectors = vectors
    index = NumpyVectorIndex('SOURCE'); index.build(Bundle); index.save(tmp_path)
    return index


def test_mapped_index_is_identical_to_load_and_detects_tampering(tmp_path):
    small_index(tmp_path)
    loaded, mapped = NumpyVectorIndex.load(tmp_path, {'config_hash': 'cfg'}), open_mapped(tmp_path, {'config_hash': 'cfg'})
    assert isinstance(mapped.vectors, np.memmap) and mapped.vectors.dtype == np.float64
    assert np.array_equal(np.asarray(mapped.vectors), loaded.vectors) and mapped.records == loaded.records
    with pytest.raises(ValueError):
        open_mapped(tmp_path, {'config_hash': 'other'})
    del loaded, mapped  # Windows: a mapped file cannot be rewritten while open.
    import gc; gc.collect()
    raw = bytearray((tmp_path / 'vectors.npy').read_bytes()); raw[-1] ^= 1
    (tmp_path / 'vectors.npy').write_bytes(bytes(raw))
    with pytest.raises(ValueError, match='checksum|unit norm'):
        open_mapped(tmp_path)


def full_reference(projects, chunks, records, vectors, queries):
    """The previous full-matrix scoring, kept here only as an equivalence oracle."""
    result = {}
    for iid, (refs, q) in queries.items():
        q = q / np.linalg.norm(q, axis=1)[:, None]
        scores = np.clip(q @ vectors.T, -1, 1); best = scores.max(axis=0)
        for p in projects:
            own = [n for n, r in enumerate(records) if r['chunk_id'] in {c['chunk_id'] for c in chunks if c['source_id'] == p['project_id']}]
            order = sorted(own, key=lambda n: (-float(best[n]), records[n]['chunk_id']))
            result[(p['project_id'], iid)] = [(records[n]['chunk_id'], [r for k, r in enumerate(refs) if scores[k, n] == best[n]]) for n in order]
    return result


def test_selected_rows_ranking_matches_full_scoring(tmp_path):
    index = small_index(tmp_path)
    mapped = open_mapped(tmp_path)
    chunks = [dict(chunk_id=r['chunk_id'], source_id='P1' if n % 3 == 0 else 'ART_1' if n % 3 == 1 else 'OTHER',
                   source_type='ARTICLE' if n % 3 == 1 else 'PROJECT', field_name='methodology' if n % 3 != 1 else 'text__abstract',
                   text='t') for n, r in enumerate(index.records)]
    projects = [dict(project_id='P1', fields={'methodology': 'x'}),
                dict(project_id='ART_1', source_type='ARTICLE', fields={'text__abstract': 'x'})]
    rng = np.random.default_rng(1)
    queries = {f'I{k}': ([f'R{k}a', f'R{k}b'], rng.normal(size=(2, 8))) for k in range(5)}
    ranked, scored = sr._rank_selected(projects, {i: {} for i in queries}, chunks, mapped.records, mapped.vectors, queries)
    oracle = full_reference(projects, chunks, index.records, index.vectors, queries)
    assert scored == sum(1 for c in chunks if c['source_id'] in ('P1', 'ART_1'))  # never the whole index
    for candidate in ranked:
        got = [(h['chunk_id'], h['reference_chunk_ids']) for h in candidate['discovery_chunks']]
        assert got == oracle[(candidate['source_id'], candidate['indicator_id'])]
        assert candidate['source_type'] == ('ARTICLE' if candidate['source_id'] == 'ART_1' else 'PROJECT')


def test_original_identifier_is_the_exact_source_eid_or_literal_doi():
    def article(eid, doi, raw_eid, raw_doi, aid):
        provenance = [dict(original_values=dict(eid=raw_eid, doi=raw_doi))]
        return dict(article_id=aid, eid=eid, doi=doi, provenance_json=json.dumps(provenance))
    with_eid = article('2-s2.0-85089837524', '10.1/x', '2-s2.0-85089837524', '10.1/X', 'ART_2-s2.0-85089837524')
    assert article_sources.original_identifier(with_eid) == ('2-s2.0-85089837524', 'EID')  # no ART_, prefix kept
    without = article(None, '10.15446/rsap.v25n4.107594', '', '10.15446/rsap.V25n4.107594', 'ART_DOI_abc')
    assert article_sources.original_identifier(without) == ('10.15446/rsap.V25n4.107594', 'DOI')  # literal source DOI
    assert article_sources.original_identifiers([with_eid, without]) == {'ART_2-s2.0-85089837524': '2-s2.0-85089837524',
                                                                       'ART_DOI_abc': '10.15446/rsap.V25n4.107594'}
    # The original EID still resolves to the same internal source (checkpoint compatibility).
    assert article_sources.resolve([with_eid, without], ['2-s2.0-85089837524', 'ART_DOI_abc']) == ['ART_2-s2.0-85089837524', 'ART_DOI_abc']
