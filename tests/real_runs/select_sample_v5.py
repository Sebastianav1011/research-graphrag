"""Reproducible 10 PROJECT + 10 ARTICLE sample from the active BASE Knowledge (read-only).

Criterion (documented in the manifest): fixed sources first, then a seeded random draw
stratified by knowledge area (projects) or journal (articles), among sources whose
authorized substantive text length lies between the 25th and 90th percentile.
No outcome-based filtering (positive-looking cases are not preferred). Not a pytest module.
"""
import json, random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
import knowledge_store as ks
import pyarrow.parquet as pq

SEED = 20261119
FIXED_PROJECTS = ['21844', '21736', '21869']
FIXED_ARTICLES = ['ART_2-s2.0-105001255605']  # PREDICOL
SUBSTANTIVE = ('summary', 'methodology', 'objectives', 'expected_results')


def main(out):
    active = ks.read_active(ROOT); manifest, _ = ks.load_version(ROOT, active['version_id'])
    w = Path(ks.location(ROOT, manifest)) / 'workspace/outputs/layer2'
    projects = pq.read_table(w / 'canonical/proyectos.parquet', columns=['project_id', 'source_project_id', 'title', 'knowledge_area',
        'knowledge_subarea', 'socioeconomic_objective', 'start_date', 'end_date', 'record_source', 'source_row']).to_pylist()
    articles = pq.read_table(w / 'canonical/articulos.parquet', columns=['article_id', 'eid', 'doi', 'title', 'journal', 'document_type',
        'publication_year', 'record_source', 'source_row']).to_pylist()
    sections = pq.read_table(w / 'knowledge/source_sections.parquet', columns=['source_id', 'source_type', 'field_name', 'text_original']).to_pylist()
    length = {}
    for s in sections:
        if (s['source_type'] == 'PROJECT' and (s['field_name'] in SUBSTANTIVE or s['field_name'].startswith('text__'))) or \
           (s['source_type'] == 'ARTICLE' and s['field_name'] == 'abstract'):
            length[s['source_id']] = length.get(s['source_id'], 0) + len((s['text_original'] or '').strip())
    def band(ids):
        v = sorted(length.get(i, 0) for i in ids if length.get(i, 0) > 0)
        return v[int(.25 * len(v))], v[int(.90 * len(v))]
    plo, phi = band([p['project_id'] for p in projects]); alo, ahi = band([a['article_id'] for a in articles])
    rng = random.Random(SEED)
    chosen_p = [p for f in FIXED_PROJECTS for p in projects if p['source_project_id'] == f]
    areas = {p['knowledge_area'] for p in chosen_p}
    pool = sorted((p for p in projects if p['source_project_id'] not in FIXED_PROJECTS and plo <= length.get(p['project_id'], 0) <= phi),
                  key=lambda p: p['project_id'])
    rng.shuffle(pool)
    for p in pool:
        if len(chosen_p) == 10: break
        if p['knowledge_area'] and p['knowledge_area'] not in areas:
            chosen_p.append(p); areas.add(p['knowledge_area'])
    for p in pool:  # fewer areas than slots: fill with the same draw order
        if len(chosen_p) == 10: break
        if p not in chosen_p: chosen_p.append(p)
    chosen_a = [a for f in FIXED_ARTICLES for a in articles if a['article_id'] == f]
    journals = {a['journal'] for a in chosen_a}
    pool = sorted((a for a in articles if a['article_id'] not in FIXED_ARTICLES and a['document_type'] == 'ARTICLE'
                   and alo <= length.get(a['article_id'], 0) <= ahi), key=lambda a: a['article_id'])
    rng.shuffle(pool)
    for a in pool:
        if len(chosen_a) == 10: break
        if a['journal'] and a['journal'] not in journals:
            chosen_a.append(a); journals.add(a['journal'])
    assert len(chosen_p) == 10 and len(chosen_a) == 10 and len({p['project_id'] for p in chosen_p}) == 10 and len({a['article_id'] for a in chosen_a}) == 10
    result = dict(knowledge_version=active['version_id'], knowledge_manifest_sha256=active['manifest_sha256'], seed=SEED,
        criterion=dict(projects='Fijos 21844, 21736, 21869; resto: sorteo con semilla, un proyecto por knowledge_area distinta, '
                                'con longitud de texto sustantivo (summary+methodology+objectives+expected_results) entre p25 y p90',
                       articles='Fijo PREDICOL; resto: sorteo con semilla, document_type ARTICLE, una revista distinta por articulo, '
                                'longitud del resumen entre p25 y p90',
                       bands=dict(project_chars=[plo, phi], article_abstract_chars=[alo, ahi]),
                       outcome_filtering='NINGUNO: no se usaron resultados previos ni se prefirieron casos positivos'),
        projects=[dict(source_type='PROJECT', **p, substantive_chars=length.get(p['project_id'], 0)) for p in chosen_p],
        articles=[dict(source_type='ARTICLE', **a, abstract_chars=length.get(a['article_id'], 0)) for a in chosen_a])
    Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    for p in chosen_p: print('P', p['source_project_id'], p['knowledge_area'], length.get(p['project_id']), (p['title'] or '')[:70])
    for a in chosen_a: print('A', a['article_id'], a['publication_year'], length.get(a['article_id']), (a['journal'] or '')[:30], '|', (a['title'] or '')[:60])
    print('bands', plo, phi, alo, ahi)


if __name__ == '__main__':
    main(sys.argv[1])
