"""Deterministic discovery and the actual layer-2/GraphRAG boundary; no inference."""
import json
from types import SimpleNamespace

import openpyxl
import pyarrow.parquet as pq
import pytest
import yaml

from .test_manual_pipeline import sandbox, SOURCE
from scripts import pipeline_coordinator as runner
from layer2_processing.preprocessing.adapters import discover_sources, select_text_columns, sha, source_registry
from layer2_processing.preprocessing.knowledge_fields import analyze_columns, describe_columns
from layer3_graphrag.source_context import SourceContextResolver


CATALOG = yaml.safe_load((SOURCE/'config/sources.example.yaml').read_text(encoding='utf-8'))['knowledge_detection']


@pytest.mark.parametrize('column,category', [
    ('OBJETIVO_GENERAL','objectives'),('Descripción-Objetivo','objectives'),('finalidad','objectives'),
    ('propósito','objectives'),('metas','objectives'),('RESUMEN_EJECUTIVO','summaries'),
    ('síntesis','summaries'),('resultados_obtenidos','results'),('avances','results'),('logros','results'),
    ('impacto_social','impacts'),('Impacto-REGIONAL','impacts'),('hallazgos_principales','findings'),
    ('descubrimientos','findings'),('consideraciones_finales','conclusions'),
    ('enfoque_metodológico','methodology'),('productos_obtenidos','products'),
    ('población_beneficiaria','beneficiaries'),('comunidades','beneficiaries'),
    ('información_general','description'),('alcance','description'),('transferencia','applications'),
])
def test_categories_are_normalized_candidates_not_automatic_consent(column, category):
    report=describe_columns([column],[(2,{column:'Synthetic narrative without private data.'})],{},CATALOG)[0]
    assert report['category']==category and report['authorization']=='PENDING_AUTHORIZATION'
    _,selected,_,_=analyze_columns([column],[(2,{column:'Synthetic narrative.'})],{},CATALOG,
        {'auto_keywords':[]},select_text_columns)
    assert selected=={}


def test_ambiguity_content_types_privacy_and_whole_tokens():
    headers=['objetivos_resultados','resultado_total','impactometro','codigo_tipo_objetivo','correo_resultados','nota_inedita']
    rows=[(2,dict(zip(headers,['Ambiguous narrative',12,'Not a whole word','A','secret@example.test','Unknown text']))) ]
    _,selected,_,report=analyze_columns(headers,rows,{},CATALOG,
        {'include':headers,'auto_keywords':[]},select_text_columns)
    index={r['column']:r for r in report}
    assert index['objetivos_resultados']['role']=='ambiguous'
    assert index['resultado_total']['role']=='ambiguous'
    assert not index['impactometro']['categories']
    assert index['codigo_tipo_objetivo']['role']=='metadata'
    assert index['correo_resultados']['role']=='excluded_sensitive'
    assert set(selected.values())=={'impactometro','nota_inedita'}  # Explicit consent only.


def test_new_category_and_phrase_can_be_configured_without_python():
    catalog=CATALOG | {'categories':CATALOG['categories']|{'collaboration':['alianza documentada']}}
    _,selected,_,report=analyze_columns(['Alianza_documentada_local'],[(2,{'Alianza_documentada_local':'Synthetic agreement description'})],{},catalog,
        {'authorized_categories':['collaboration'],'auto_keywords':[]},select_text_columns)
    assert list(selected.values())==['Alianza_documentada_local']
    assert report[0]['category']=='collaboration' and report[0]['authorization']=='AUTHORIZED'


def write_excel(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    book=openpyxl.Workbook()
    headers=list(rows[0]);book.active.append(headers)
    for row in rows:book.active.append([row.get(c) for c in headers])
    book.save(path);book.close()


def test_repeated_supplementary_records_reach_graphrag_as_separate_evidence(sandbox):
    root,_,config=sandbox
    config['files']={}
    config['text_columns']={'authorized_categories':['objectives','results'],'auto_keywords':[]}
    path=root/'data/layer1_sources/incoming/new/arbitrary_name.xlsx'
    records=[dict(id_proyecto='000701',id_propuesta='UNRELATED_PROPOSAL',titulo='Synthetic single project',
        descripcion_objetivo=f'Synthetic objective number {i}',proposito=f'Synthetic purpose number {i}',
        resultados_obtenidos=f'Synthetic reported result number {i}',otra_columna='Preserve unknown value',
        nombre_investigador='Fictitious private name',correo_contacto='private@example.test') for i in (1,2)]
    write_excel(path,records);original=sha(path)
    preview=discover_sources(root,config)
    item=preview['files'][0]
    assert item['status']=='READY_FOR_VALIDATION' and item['source_role']=='complementary'
    assert item['mapping']['source_project_id']==['id_proyecto']
    assert next(c for c in item['column_classification'] if c['column']=='id_propuesta')['identifier_namespaces']==['proposal']
    run=root/'outputs/runs/semantic'
    runner.prepare(root,run,root/'data/layer1_sources','raw',config)
    folder=run/'workspace/outputs/layer2'
    canonical=pq.read_table(folder/'canonical/proyectos.parquet').to_pylist()
    assert len(canonical)==1 and canonical[0]['source_project_id']=='000701'
    assert len(json.loads(canonical[0]['provenance_json']))==2
    tables={name:pq.read_table(folder/f'knowledge/{name}.parquet').to_pylist() for name in ('source_documents','source_sections','source_chunks')}
    extra=[s for s in tables['source_sections'] if s['field_name'].startswith('text__')]
    assert len(extra)==6 and len({s['field_name'] for s in extra})==6
    for section in extra:
        p=json.loads(section['provenance_json']);ref=next(r for r in p['layer1'] if section['field_name'] in r['field_mapping'])
        column=ref['field_mapping'][section['field_name']]
        assert section['text_original']==ref['original_values'][column]
        assert ref['field_provenance'][column]['row'] in (2,3)
        assert ref['field_provenance'][column]['sheet']=='Sheet'
        assert ref['delivery']=='new'
        assert ref['source_occurrence_id'].startswith('OCC_')
        assert p['knowledge_semantics'][0]['category'] in ('objectives','results')
        assert 'Fictitious private name' not in json.dumps(p)
    manifest=json.loads((folder/'knowledge/_manifest.json').read_text(encoding='utf-8'))
    resolver=SourceContextResolver(SimpleNamespace(tables=tables,manifest=manifest,manifest_hash=sha(folder/'knowledge/_manifest.json')))
    doc=tables['source_documents'][0]
    context=resolver.reconstruct('PROJECT',doc['source_id'],doc['document_id'])
    assert len(context['substantive_sections'])==6 and context['context_status']=='ASSESSMENT_READY'
    assert runner.graph(root,run)['status']=='VALIDATED_APPROVED_LAYER_2_INPUT'
    assert sha(path)==original


def test_canonical_aliases_and_other_occurrences_are_not_lost(sandbox):
    root,_,config=sandbox;config['files']={}
    path=root/'data/layer1_sources/incoming/new/summaries.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps([dict(id_proyecto='P1',titulo='Synthetic project',resumen=f'Summary {i}',
        resumen_ejecutivo=f'Executive summary {i}') for i in (1,2)]),encoding='utf-8')
    run=root/'outputs/runs/summaries';runner.prepare(root,run,root/'data/layer1_sources','raw',config)
    sections=pq.read_table(run/'workspace/outputs/layer2/knowledge/source_sections.parquet').to_pylist()
    texts={s['text_original'] for s in sections}
    assert {'Summary 1','Summary 2','Executive summary 1','Executive summary 2'}<=texts


def test_namespaces_conflicts_rejections_and_no_guessed_proposals(sandbox):
    root,_,config=sandbox;config['files']={}
    path=root/'data/layer1_sources/incoming/new/mixed.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps([dict(id_proyecto='P1',id_actividad='OTHER',resumen='Controlled narrative'),
        dict(id_proyecto='P2',id_actividad='P2',resumen='Controlled narrative')]),encoding='utf-8')
    item=discover_sources(root,config)['files'][0]
    assert item['status']=='INVALID'
    assert item['record_validation']['valid']==1 and item['record_validation']['rejected']==1
    path.write_text(json.dumps([dict(id_propuesta='P1',descripcion_objetivo='Synthetic objective')]),encoding='utf-8')
    assert discover_sources(root,config)['files'][0]['status']=='PENDING_CONFIGURATION'


def test_review_can_resolve_ambiguous_column_with_an_explicit_category():
    column='Objetivos_Resultados'
    rows=[(2,{column:'Synthetic declared result'})]
    catalog=CATALOG|{'column_overrides':{column:'results'}}
    _,selected,_,report=analyze_columns([column],rows,{},catalog,
        {'authorized_categories':['results'],'auto_keywords':[]},select_text_columns)
    assert set(selected.values())=={column} and report[0]['category']=='results'


def test_detection_can_be_authorized_then_resumed_without_reinterpreting_unknowns(sandbox):
    root,_,config=sandbox;config['files']={}
    path=root/'data/layer1_sources/incoming/new/unknown.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps([dict(id_proyecto='P1',titulo='Synthetic project',finalidad_investigacion='Synthetic aim',
        resumen_ejecutivo='Synthetic summary',dato_nuevo='Kept private but not authorized')]),encoding='utf-8')
    preview=discover_sources(root,config)['files'][0]
    assert 'finalidad_investigacion' in preview['pending_authorization']
    assert next(c for c in preview['column_classification'] if c['column']=='dato_nuevo')['role']=='unknown'
    config['text_columns']={'authorized_categories':['objectives']}
    run=root/'outputs/runs/consented'
    runner.prepare(root,run,root/'data/layer1_sources','raw',config)
    sections=pq.read_table(run/'workspace/outputs/layer2/knowledge/source_sections.parquet').to_pylist()
    assert any(s['text_original']=='Synthetic aim' for s in sections)
    assert not any('Kept private' in json.dumps(s) for s in sections)
    assert runner.prepare(root,run,root/'data/layer1_sources','raw',config)['status']=='ALREADY_PREPARED'


def test_base_relation_diagnostic_keeps_proposal_namespace_distinct(sandbox):
    root,_,config=sandbox;config['files']={}
    base=root/'data/layer1_sources/base/descriptores.json'
    base.write_text(json.dumps([dict(id_actividad='P1',summary='Synthetic base')]),encoding='utf-8')
    source=root/'data/layer1_sources/incoming/new/supplement.json';source.parent.mkdir(parents=True)
    source.write_text(json.dumps([dict(id_proyecto='P1',id_propuesta='OTHER',proposito='Synthetic purpose')]),encoding='utf-8')
    report=discover_sources(root,config)
    item=next(i for i in report['files'] if i['file'].endswith('supplement.json'))
    project=next(r for r in item['relations'] if r['namespace']=='project')
    proposal=next(r for r in item['relations'] if r['namespace']=='proposal')
    assert project['exact_base_matches']==1 and project['unmatched_identifiers']==0
    assert proposal['resolution']=='distinct_namespace_not_joined'


def test_unmatched_complement_cannot_create_an_unverified_project(sandbox):
    root,_,config=sandbox;config['files']={}
    base=root/'data/layer1_sources/base/descriptores.json'
    base.write_text(json.dumps([dict(id_actividad='P1',summary='Synthetic base')]),encoding='utf-8')
    source=root/'data/layer1_sources/incoming/new/supplement.json';source.parent.mkdir(parents=True)
    source.write_text(json.dumps([dict(id_proyecto='FOREIGN_KEY',proposito='Synthetic purpose')]),encoding='utf-8')
    report=discover_sources(root,config)
    item=next(i for i in report['files'] if i['file'].endswith('supplement.json'))
    assert item['status']=='READY_FOR_VALIDATION' and item['relationship_status']=='UNRESOLVED_REFERENCES'
    run=root/'outputs/runs/unresolved'
    with pytest.raises(ValueError,match='Entrada rechazada'):
        runner.prepare(root,run,root/'data/layer1_sources','raw',config)
    assert not (run/'workspace/outputs/layer2/canonical').exists()


def test_local_registry_inherits_catalog_and_new_identifier_aliases(sandbox):
    root,_,config=sandbox
    (root/'config/sources.yaml').write_text('proyectos:\n  mapping:\n    source_project_id: id_actividad\n    summary: resumen\n',encoding='utf-8')
    registry=source_registry(root,config)
    assert 'id_proyecto' in registry['proyectos']['mapping']['source_project_id']
    assert 'objectives' in registry['knowledge_detection']['categories']


def test_article_discovery_and_knowledge_boundary(sandbox):
    root,_,config=sandbox;config['files']={}
    config['text_columns']={'authorized_categories':['findings']}
    path=root/'data/layer1_sources/incoming/new/article.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps([dict(id_articulo='ART_TEST',title='Synthetic article',hallazgos_principales='Synthetic finding')]),encoding='utf-8')
    assert discover_sources(root,config)['files'][0]['domain']=='articulos'
    run=root/'outputs/runs/article';runner.prepare(root,run,root/'data/layer1_sources','raw',config)
    docs=pq.read_table(run/'workspace/outputs/layer2/knowledge/source_documents.parquet').to_pylist()
    assert len(docs)==1 and docs[0]['source_type']=='ARTICLE'
    assert runner.graph(root,run)['status']=='VALIDATED_APPROVED_LAYER_2_INPUT'
