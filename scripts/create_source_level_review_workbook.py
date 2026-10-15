"""Export existing R8 PROJECT candidates for manual review against approved v2.

No pipeline imports, retrieval, model execution, or writes to published data.
Requires pyarrow/openpyxl for reads and Node with @oai/artifact-tool for authoring.
Set ARTIFACT_TOOL_NODE_MODULES to a provisioned node_modules directory when needed.
The default refuses to overwrite an existing workbook containing human annotations.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import pyarrow.parquet as pq
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
RUN = 'layer3_2026-10-14T094639_959121+0000_eca9000e'
V2 = 'data/reference/indicadores/catalogo_indicadores_v2.xlsx'
V2_HASH = '1aeb1a376c24bca7bdd7acd228da527ef0043f0574541649589badb54e1cf88f'
FIELDS = ('title', 'keywords', 'summary', 'methodology', 'objectives', 'expected_results')
HUMAN = ('human_decision', 'human_support_strength', 'human_evidence_fields',
         'human_evidence_notes', 'human_comments', 'review_status')
MAP = {'id_indicador': 'indicator_id', 'indicador': 'indicator_name',
       'categoria': 'indicator_category', 'ambito': 'indicator_dimension'}
TECH = ('discovery_chunk_ids', 'discovery_field_names', 'discovery_retrieval_origins',
        'best_vector_score', 'graph_score', 'hybrid_retrieval_score', 'best_vector_rank',
        'graph_hops', 'graph_path_json', 'context_package_id', 'layer3_run_id',
        'source_rank', 'candidate_id')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def catalog(path, sheet):
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = [list(r) for r in book[sheet].values if any(v is not None for v in r)]
    finally:
        book.close()
    headers = rows[0]
    require(all(isinstance(h, str) and h for h in headers), f'Invalid headers: {sheet}')
    require(len(headers) == len(set(headers)), f'Duplicate headers: {sheet}')
    return headers, [dict(zip(headers, row)) for row in rows[1:]]


def select_candidates(candidates, indicator_ids):
    groups = defaultdict(list)
    for row in candidates:
        if row['source_type'] == 'PROJECT':
            groups[row['indicator_id']].append(row)
    selected = []
    for iid in sorted(indicator_ids):
        if groups[iid]:
            selected.append(min(groups[iid], key=lambda r: (
                r['context_status'] != 'ASSESSMENT_READY', r['source_rank'],
                r['source_id'], r['document_id'], r['candidate_id'])))
    return selected


def split_display(text, limit=700):
    """Lossless layout fragments; never discovery chunks or assessment units."""
    if not text:
        return ['']
    parts = []
    while text:
        end = min(limit, len(text))
        if end < len(text):
            boundary = max(text.rfind('\n', 0, end), text.rfind(' ', 0, end))
            if boundary > end // 2:
                end = boundary + 1
        parts.append(text[:end])
        text = text[end:]
    return parts


def prepare():
    manifest_path = ROOT / 'data/graphrag/_manifest.json'
    manifest = read_json(manifest_path)
    require(manifest['layer3_run_id'] == RUN, 'Active publication is not approved R8')
    require(manifest['candidate_architecture'] == 'SOURCE_INDICATOR_V1', 'Wrong architecture')
    require(manifest['status'] == 'SUCCESS', 'Publication is not successful')
    require(not (ROOT / 'outputs/layer3/.publish.lock').exists(), 'Publication lock exists')
    require(not list((ROOT / 'outputs/layer3').rglob('publication_pending.json')), 'Publication journal exists')
    for basename, expected in manifest['code_hashes'].items():
        require(sha(ROOT / 'src/layer3_graphrag' / basename) == expected, f'Code changed: {basename}')
    require(sha(ROOT / V2) == V2_HASH, 'Approved v2 hash changed')
    layer2_path = ROOT / 'data/knowledge/_manifest.json'
    layer1_path = ROOT / 'data/canonical/_manifest.json'
    require(sha(layer2_path) == manifest['layer2_manifest_hash'], 'Layer2 manifest changed')
    layer2 = read_json(layer2_path)
    require(sha(layer1_path) == layer2['layer1_manifest_hash'], 'Layer1 manifest changed')
    layer1 = read_json(layer1_path)
    require(sha(ROOT / 'data/canonical/indicadores.parquet') == layer2['input_hashes']['indicadores'],
            'Canonical indicators differ from R8 upstream input')
    v1 = next(x for x in layer1['input_files'] if x['domain'] == 'indicadores')
    v1_path = ROOT / 'data/reference/indicadores' / v1['name']
    require(sha(v1_path) == v1['sha256'], 'Historical indicator source changed')
    for rel in ('retrieval/source_indicator_candidates.parquet', 'retrieval/source_context_packages.parquet'):
        require(sha(ROOT / 'data/graphrag' / rel) == manifest['output_hashes'][rel], f'Output changed: {rel}')
    tables = {}
    for name in ('source_documents', 'source_sections', 'source_chunks', 'reference_documents'):
        path = ROOT / 'data/knowledge' / f'{name}.parquet'
        require(sha(path) == manifest['input_hashes'][name], f'Layer2 table changed: {name}')
        tables[name] = pq.read_table(path).to_pylist()
    candidates = pq.read_table(ROOT / 'data/graphrag/retrieval/source_indicator_candidates.parquet').to_pylist()
    contexts = pq.read_table(ROOT / 'data/graphrag/retrieval/source_context_packages.parquet').to_pylist()
    headers, indicators = catalog(ROOT / V2, 'Indicadores_enriquecidos')
    rule_headers, rules = catalog(ROOT / V2, 'Reglas_generales')
    require(len(indicators) == 48 and len({i['id_indicador'] for i in indicators}) == 48, 'Invalid v2 indicators')
    require(len({r['id_regla'] for r in rules}) == len(rules), 'Duplicate general rule')
    ids = {i['id_indicador'] for i in indicators}
    reference_ids = {d['source_id'] for d in tables['reference_documents']}
    require(ids == reference_ids, 'v2 IDs differ from R8 reference IDs; do not infer mappings')
    require(all(c['indicator_id'] in ids and c['layer3_run_id'] == RUN for c in candidates), 'Invalid candidate lineage')
    pairs = [(c['source_type'], c['source_id'], c['indicator_id']) for c in candidates]
    require(len(set(pairs)) == len(pairs), 'Duplicate input SOURCE+INDICATOR')
    chosen = select_candidates(candidates, ids)
    documents = {d['document_id']: d for d in tables['source_documents']}
    sections = {s['section_id']: s for s in tables['source_sections']}
    chunks = {c['chunk_id']: c for c in tables['source_chunks']}
    packages = {c['context_package_id']: c for c in contexts}
    by_document = defaultdict(list)
    for section in tables['source_sections']:
        by_document[section['document_id']].append(section)
    specs = {i['id_indicador']: i for i in indicators}
    extras = [h for h in headers if h not in MAP]
    indicator_headers = ['indicator_id', 'indicator_name', 'indicator_category', 'indicator_dimension'] + extras
    review_headers = ['case_id', 'project_id', 'document_id', 'project_title'] + indicator_headers
    review_headers += ['project_' + f for f in FIELDS[1:]] + ['available_project_fields', 'context_status'] + list(HUMAN)
    review, technical, selected_ids, projects = [], [], {}, {}
    for candidate in chosen:
        iid, pid, did = candidate['indicator_id'], candidate['source_id'], candidate['document_id']
        doc = documents.get(did)
        require(doc and doc['source_type'] == 'PROJECT' and doc['source_id'] == pid, 'Invalid project document')
        package = packages.get(candidate['context_package_id'])
        require(package and all(package[k] == candidate[k] for k in ('source_type', 'source_id', 'document_id', 'context_status', 'source_context_hash', 'layer3_run_id')), 'Invalid context package')
        project_sections = by_document[did]
        counts = Counter(s['field_name'] for s in project_sections)
        require(all(n == 1 for n in counts.values()), 'Multiple sections per field; explicit mapping required')
        require(all(s['source_type'] == 'PROJECT' and s['source_id'] == pid for s in project_sections), 'Invalid section mapping')
        by_field = {s['field_name']: s for s in project_sections}
        fields = {f: by_field[f]['text_original'] if f in by_field else None for f in FIELDS}
        available = sorted(s['field_name'] for s in project_sections if (s['text_normalized'] or '').strip())
        require(available == sorted(package['available_field_names']), 'Incomplete project context')
        references = package['orientation_sections'] + package['substantive_sections']
        require({s['section_id'] for s in references} == {s['section_id'] for s in project_sections if (s['text_normalized'] or '').strip()}, 'Context omits sections')
        for ref in references:
            require(sections[ref['section_id']]['field_name'] == ref['field_name'], 'Wrong section reference')
        require(len(candidate['discovery_chunk_ids']) == len(candidate['discovery_field_names']), 'Discovery lengths differ')
        for chunk_id, field in zip(candidate['discovery_chunk_ids'], candidate['discovery_field_names']):
            chunk = chunks.get(chunk_id)
            require(chunk and chunk['source_type'] == 'PROJECT' and chunk['source_id'] == pid and chunk['document_id'] == did and chunk['field_name'] == field, 'Invalid discovery chunk')
        case = 'CASE_' + hashlib.sha256((iid + '\0' + pid + '\0' + did).encode()).hexdigest()[:16]
        selected_ids[iid] = case
        values = [specs[iid]['id_indicador'], specs[iid]['indicador'], specs[iid]['categoria'], specs[iid]['ambito']] + [specs[iid][h] for h in extras]
        review.append([case, pid, did, fields['title']] + values + [fields[f] for f in FIELDS[1:]] + [', '.join(available), candidate['context_status']] + [None] * len(HUMAN))
        technical.append([case] + [json.dumps(candidate[k], ensure_ascii=False) if isinstance(candidate[k], (list, dict)) else candidate[k] for k in TECH] + [json.dumps({f: by_field[f]['section_id'] for f in FIELDS if f in by_field}, sort_keys=True), pid, did])
        projects[(pid, did)] = fields
    indicator_rows = [[i['id_indicador'], i['indicador'], i['categoria'], i['ambito']] + [i[h] for h in extras] + ['PROJECT_CANDIDATE_AVAILABLE' if i['id_indicador'] in selected_ids else 'NO_PROJECT_CANDIDATE', selected_ids.get(i['id_indicador'])] for i in sorted(indicators, key=lambda i: i['id_indicador'])]
    reading = []
    for (pid, did), fields in sorted(projects.items()):
        for field in FIELDS:
            for part, text in enumerate(split_display(fields[field]), 1):
                reading.append([pid, field, part, text or None, did])
    require(len({r[0] for r in review}) == len(review), 'Duplicate case IDs')
    require(len({(r[1], r[4]) for r in review}) == len(review), 'Duplicate selected PROJECT+INDICATOR')
    for row in review + indicator_rows + reading:
        require(all(not isinstance(v, str) or len(v) <= 32767 for v in row), 'Text exceeds Excel cell limit; refuse truncation')
    project_candidates = [c for c in candidates if c['source_type'] == 'PROJECT']
    statuses = dict(Counter(c['context_status'] for c in project_candidates))
    metadata = {
        'active_layer3_run': RUN, 'architecture': manifest['candidate_architecture'], 'pipeline_version': manifest['pipeline_version'],
        'manifest_hash': sha(manifest_path), 'layer2_manifest_sha256': sha(layer2_path),
        'candidate_retrieval_indicator_version': v1['name'] + ' / ' + v1['sheet'] + ' (R8 original reference; v1)',
        'candidate_retrieval_indicator_sha256': v1['sha256'],
        'human_review_indicator_version': 'catalogo_indicadores_v2.xlsx', 'human_review_indicator_sha256': sha(ROOT / V2),
        'indicator_source': V2, 'indicator_source_hash': sha(ROOT / V2),
        'indicator_sheet': 'Indicadores_enriquecidos', 'general_rules_sheet': 'Reglas_generales',
        'indicator_fields_original': ', '.join(headers), 'general_rules_count': len(rules),
        'general_rules_application': 'Full verbatim rules in INSTRUCCIONES; reviewer applies them manually. No automatic interpretation or decisions.',
        'selection_method': 'One PROJECT per v2 indicator ID; prefer ASSESSMENT_READY, then ascending R8 source_rank, source_id, document_id, candidate_id; indicators sorted by indicator_id.',
        'selection_limitation': 'Existing R8/v1 retrieval pool, not regenerated with v2 enriched fields. Ranking selects review cases, not correctness.',
        'generated_at': datetime.now(timezone.utc).isoformat(), 'case_count': len(review), 'indicator_count': len(indicators),
        'generated_at_timezone': 'UTC',
        'indicators_without_PROJECT': len(ids - set(selected_ids)), 'unique_projects': len(projects),
        'candidate_count_read': len(candidates), 'project_candidate_count': len(project_candidates),
        'PROJECT_ASSESSMENT_READY': statuses.get('ASSESSMENT_READY', 0), 'PROJECT_DISCOVERY_ONLY': statuses.get('DISCOVERY_ONLY', 0),
        'selected_context_statuses': json.dumps(dict(Counter(c['context_status'] for c in chosen))),
        'project_text_source': 'data/knowledge/source_sections.parquet / text_original; all six fields separately; empty values remain empty.',
        'discovery_unit': 'source_chunk', 'display_unit': 'PROJECT complete available content', 'human_assessment_unit': 'PROJECT + INDICATOR',
        'LLM_inference': False, 'automatic_decisions': 0, 'confidence': 'NOT_IMPLEMENTED; human_support_strength is a human label',
        'validation': 'PASS: unique cases/pairs; valid project/indicator/document/discovery IDs; section lineage; no ARTICLE; blank human labels; no confidence columns.',
        'reading_fragments': 'LECTURA_PROYECTOS splits text only for display; joining parts per project+field reproduces the original field exactly. These are not discovery chunks or review cases.',
    }
    protected_paths = [p for base in ('src', 'config', 'data/canonical', 'data/knowledge') for p in (ROOT / base).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    protected_paths += [manifest_path, ROOT / V2, v1_path, ROOT / 'templates/resultado_final_indicadores.xlsx']
    protected_paths += [ROOT / 'data/graphrag' / rel for rel in manifest['output_hashes'] if not rel.endswith('.npy')]
    protected = {p: sha(p) for p in set(protected_paths)}
    return {'review_headers': review_headers, 'review': review, 'indicator_headers': indicator_headers + ['project_candidate_available', 'selected_case_id'],
            'indicators': indicator_rows, 'rules_headers': rule_headers, 'rules': [[r[h] for h in rule_headers] for r in rules],
            'metadata': list(metadata.items()), 'technical_headers': ['case_id'] + list(TECH) + ['project_section_ids_json', 'project_id', 'document_id'],
            'technical': technical, 'reading': reading}, protected


BUILDER = r'''
import fs from 'node:fs/promises';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';
const [input, output, previewDir] = process.argv.slice(2);
const p = JSON.parse(await fs.readFile(input, 'utf8'));
const wb = Workbook.create();
const names = ['REVISION','INDICADORES','INSTRUCCIONES','LECTURA_PROYECTOS','METADATA'];
const sheets = Object.fromEntries(names.map(n => [n, wb.worksheets.add(n)]));
const literal = v => typeof v === 'string' && v.startsWith('=') ? "'"+v : v;
function height(values,widths,min=32,max=300){
  return Math.min(max,Math.max(min,14+12*Math.max(...values.map((v,i)=>String(v??'').split('\n').reduce((n,line)=>n+Math.max(1,Math.ceil(line.length/(widths[i]*0.9))),0)))));
}
function table(sheet, headers, rows, tableName, first=1) {
  const matrix = [headers,...rows].map(r=>r.map(literal));
  const area=sheet.getRangeByIndexes(first-1,0,matrix.length,headers.length);
  area.values=matrix;
  area.format.font={name:'Arial',size:10,color:'#243247'};
  area.format.wrapText=true; area.format.verticalAlignment='top';
  area.format.columnWidth=28; area.format.rowHeight=108;
  sheet.showGridLines=false;
  const t=sheet.tables.add(`${col(0)}${first}:${col(headers.length-1)}${first+rows.length}`,true,tableName);
  t.style='TableStyleLight1'; t.showFilterButton=true;
  const head=sheet.getRangeByIndexes(first-1,0,1,headers.length);
  head.format.fill='#E6EAF0'; head.format.font={name:'Arial',size:10,bold:true,color:'#243247'};
  head.format.rowHeight=54; head.format.horizontalAlignment='center'; head.format.verticalAlignment='center';
  sheet.freezePanes.freezeRows(first);
  return area;
}
function col(i){let s='';for(i++;i;i=Math.floor((i-1)/26))s=String.fromCharCode(65+(i-1)%26)+s;return s;}
function width(sheet,i,w,rows){sheet.getRangeByIndexes(0,i,rows,1).format.columnWidth=w;}
table(sheets.REVISION,p.review_headers,p.review,'ProjectIndicatorReview');
sheets.REVISION.tabColor='#496986';
sheets.REVISION.freezePanes.freezeColumns(2);
for(let i=0;i<p.review_headers.length;i++){
  const h=p.review_headers[i],cell=sheets.REVISION.getRangeByIndexes(0,i,1,1);
  const group=i<3?'#E6EAF0':h.startsWith('human_')||h==='review_status'?'#FFF0CF':h.startsWith('project_')?'#E9E5F3':h==='context_status'||h==='available_project_fields'?'#E4E9EE':'#DCEAF5';
  cell.format.fill=group;
  width(sheets.REVISION,i,['case_id','project_id','document_id','indicator_id'].includes(h)?24:h==='project_title'?45:h.startsWith('project_')||['indicator_name','descripcion_ampliada','elementos_clave','evidencia_favorable','evidencia_insuficiente','terminos_relacionados','contexto_relacional','fuentes_relevantes'].includes(h)?52:28,p.review.length+1);
  if(h.startsWith('human_')||h==='review_status')sheets.REVISION.getRangeByIndexes(1,i,p.review.length,1).format.fill='#FFFAEB';
}
sheets.REVISION.getRangeByIndexes(1,0,p.review.length,p.review_headers.length).format.rowHeight=165;
function dropdown(header,values){const i=p.review_headers.indexOf(header);sheets.REVISION.getRangeByIndexes(1,i,p.review.length,1).dataValidation={rule:{type:'list',values}};}
dropdown('human_decision',['SUPPORTED','INSUFFICIENT_EVIDENCE','NOT_SUPPORTED']);
dropdown('human_support_strength',['0','1','2','3','4']);
dropdown('review_status',['PENDING','IN_REVIEW','REVIEWED']);
table(sheets.INDICADORES,p.indicator_headers,p.indicators,'CurrentIndicators');
for(let i=0;i<p.indicator_headers.length;i++)width(sheets.INDICADORES,i,i===0?20:i===2||i===3?28:52,p.indicators.length+1);
for(let r=0;r<p.indicators.length;r++)sheets.INDICADORES.getRangeByIndexes(r+1,0,1,p.indicator_headers.length).format.rowHeight=height(p.indicators[r],p.indicator_headers.map((h,i)=>i===0?20:i===2||i===3?28:52),90);
const guide=[
 ['OBJETIVO','Revisar si el proyecto completo disponible aporta evidencia suficiente para el posible indicador, usando exclusivamente la especificación v2.'],
 ['ADVERTENCIA','El proyecto aparece porque Capa 3 lo consideró candidato. Eso NO significa que cumpla el indicador. Los candidatos fueron recuperados por R8 con el catálogo anterior; v2 se utiliza para esta revisión humana.'],
 ['UNIDAD','CHUNK = descubrimiento. PROJECT completo = contenido mostrado. PROJECT + INDICATOR = evaluación humana. discovery_chunk != evidence; retrieval_score != confidence; candidate_source != indicator_match.'],
 ['FLUJO','1. Leer el indicador y su especificación v2. 2. Leer el título. 3. Leer summary. 4. Leer methodology. 5. Leer objectives. 6. Leer expected_results. 7. Leer keywords como contexto. 8. Decidir. 9. Asignar fuerza 0–4. 10. Registrar campos de evidencia. 11. Añadir comentarios cuando sean necesarios. Leer también las 12 reglas generales reproducidas abajo.'],
 ['SUPPORTED','El contenido disponible aporta evidencia suficiente y específica para sostener el indicador según su definición vigente. Una coincidencia temática NO basta.'],
 ['INSUFFICIENT_EVIDENCE','Existe relación temática o alguna señal relevante, pero la información disponible no permite sostener el indicador con suficiente evidencia.'],
 ['NOT_SUPPORTED','Después de revisar la información disponible, no existe evidencia que permita sostener el indicador. No confundir falta de información con evidencia negativa: aplicar RG-07 y documentar el motivo.'],
 ['FUERZA HUMANA','0 = sin soporte identificable; 1 = relación temática débil; 2 = evidencia parcial o insuficiente; 3 = evidencia clara; 4 = evidencia explícita y fuerte. Es una etiqueta HUMANA, no confidence del sistema.'],
 ['CAMPOS DE EVIDENCIA','Escribir nombres separados por coma: title, keywords, summary, methodology, objectives, expected_results. Ejemplo: summary, objectives. Celda editable; no se requiere copiar IDs de chunks. Sin macros.'],
 ['ORIENTACIÓN Y CONTENIDO','title y keywords orientan el descubrimiento. Su coincidencia no implica cumplimiento. Priorizar summary, methodology, objectives y expected_results cuando estén disponibles, respetando la especificación v2 y sus reglas generales.'],
 ['ESTADO DE REVISIÓN','review_status es manual: PENDING, IN_REVIEW o REVIEWED. Dejar REVIEWED solo después de registrar decisión, fuerza y una justificación trazable. Las celdas humanas comienzan vacías.'],
 ['LECTURA COMPLETA','REVISION contiene cada campo completo y separado. Excel limita la altura visible de las filas. LECTURA_PROYECTOS ofrece una lectura vertical por project_id y field_name; leer todas las partes en orden. Son fragmentos de presentación sin scores ni unidades de evaluación.'],
 ['DISPONIBILIDAD','ASSESSMENT_READY y DISCOVERY_ONLY describen disponibilidad técnica de contexto; no son decisiones de cumplimiento. Los valores ausentes permanecen vacíos.'],
 ['METADATA DE RECUPERACIÓN — NO ES EVIDENCIA NI CONFIANZA','METADATA conserva ranking, discovery IDs, campos y orígenes, scores, graph path, contexto y run. El ranking selecciona el caso a revisar; no demuestra que sea correcto.'],
 ['REGLAS GENERALES','Aplicar manualmente las reglas RG-01 a RG-12 al leer cada caso. Los textos siguientes se copian íntegros desde v2. No se ejecutaron reglas automáticas ni inferencia LLM.']
];
table(sheets.INSTRUCCIONES,['Tema','Instrucción'],guide,'ReviewInstructions');
width(sheets.INSTRUCCIONES,0,38,guide.length+1);width(sheets.INSTRUCCIONES,1,100,guide.length+1);
for(let r=0;r<guide.length;r++)sheets.INSTRUCCIONES.getRangeByIndexes(r+1,0,1,2).format.rowHeight=height(guide[r],[38,100],48);
const rulesRow=guide.length+4;
table(sheets.INSTRUCCIONES,p.rules_headers,p.rules,'GeneralReviewRules',rulesRow);
for(let i=0;i<p.rules_headers.length;i++)width(sheets.INSTRUCCIONES,i,i===0?38:i===1?100:70,rulesRow+p.rules.length);
for(let r=0;r<p.rules.length;r++)sheets.INSTRUCCIONES.getRangeByIndexes(rulesRow+r,0,1,p.rules_headers.length).format.rowHeight=height(p.rules[r],[38,100,70,70,70],100);
sheets.INSTRUCCIONES.freezePanes.unfreeze();
table(sheets.LECTURA_PROYECTOS,['project_id','field_name','parte_visual','texto_completo_por_partes','document_id'],p.reading,'FullProjectReading');
for(const [i,w]of [[0,24],[1,25],[2,14],[3,105],[4,38]])width(sheets.LECTURA_PROYECTOS,i,w,p.reading.length+1);
for(let r=0;r<p.reading.length;r++)sheets.LECTURA_PROYECTOS.getRangeByIndexes(r+1,0,1,5).format.rowHeight=height(p.reading[r],[24,25,14,105,38],32,240);
sheets.LECTURA_PROYECTOS.freezePanes.freezeColumns(2);
table(sheets.METADATA,['Clave','Valor'],p.metadata,'WorkbookMetadata');
width(sheets.METADATA,0,42,p.metadata.length+1);width(sheets.METADATA,1,110,p.metadata.length+1);
sheets.METADATA.getRangeByIndexes(1,0,p.metadata.length,2).format.rowHeight=54;
const technicalRow=p.metadata.length+4;
sheets.METADATA.getRangeByIndexes(technicalRow-2,0,1,1).values=[['METADATA DE RECUPERACIÓN — NO ES EVIDENCIA NI CONFIANZA']];
table(sheets.METADATA,p.technical_headers,p.technical,'CaseRetrievalMetadata',technicalRow);
width(sheets.METADATA,0,48,technicalRow+p.technical.length);width(sheets.METADATA,1,110,technicalRow+p.technical.length);
for(let r=0;r<p.metadata.length;r++)sheets.METADATA.getRangeByIndexes(r+1,0,1,2).format.rowHeight=height(p.metadata[r],[48,110],40);
const generatedRow=p.metadata.findIndex(([k])=>k==='generated_at')+2;
sheets.METADATA.getRange(`B${generatedRow}`).values=[[new Date(p.metadata[generatedRow-2][1])]];
sheets.METADATA.getRange(`B${generatedRow}`).setNumberFormat('yyyy-mm-dd hh:mm:ss');
sheets.METADATA.freezePanes.unfreeze();
wb.recalculate();
console.log((await wb.inspect({kind:'sheet',include:'id,name',maxChars:1200})).ndjson);
await fs.mkdir(previewDir,{recursive:true});
for(const [name,range,file] of [
 ['REVISION','D1:H3','revision'],['REVISION','Y1:AE3','human'],['INDICADORES','H1:J2','indicators'],
 ['INSTRUCCIONES','A1:B4','instructions'],['INSTRUCCIONES',`A${rulesRow}:C${rulesRow+1}`,'rules'],
 ['LECTURA_PROYECTOS','A1:D5','reading'],['METADATA','A4:B10','metadata']]){
 const blob=await wb.render({sheetName:name,range,scale:1,format:'png'});
 await fs.writeFile(`${previewDir}/${file}.png`,new Uint8Array(await blob.arrayBuffer()));
}
const xlsx=await SpreadsheetFile.exportXlsx(wb);await xlsx.save(output);
'''


def author(payload, destination, previews):
    dependencies = Path(os.environ.get('ARTIFACT_TOOL_NODE_MODULES',
        str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')))
    require((dependencies / '@oai/artifact-tool/package.json').exists(),
            'Provision @oai/artifact-tool and set ARTIFACT_TOOL_NODE_MODULES; no automatic installs')
    node = os.environ.get('REVIEW_WORKBOOK_NODE') or shutil.which('node')
    require(node is not None, 'Node executable not found')
    # Named disposable work directory; published data are never a cleanup target.
    with tempfile.TemporaryDirectory(prefix='graphrag_source_review_') as scratch:
        temp = Path(scratch).resolve()
        link = temp / 'node_modules'
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(dependencies.resolve())], check=True, capture_output=True)
        else:
            link.symlink_to(dependencies.resolve(), target_is_directory=True)
        (temp / 'input.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        (temp / 'builder.mjs').write_text(BUILDER, encoding='utf-8')
        subprocess.run([node, str(temp / 'builder.mjs'), str(temp / 'input.json'), str(destination), str(previews)], check=True)


def verify_saved(path, payload):
    book = load_workbook(path, read_only=False, data_only=False)
    try:
        for sheet_name, headers, rows in [('REVISION', payload['review_headers'], payload['review']),
                ('INDICADORES', payload['indicator_headers'], payload['indicators']),
                ('LECTURA_PROYECTOS', ['project_id','field_name','parte_visual','texto_completo_por_partes','document_id'], payload['reading'])]:
            sheet = book[sheet_name]
            require(sheet.max_row == len(rows) + 1, f'Wrong row count: {sheet_name}')
            require(list(next(sheet.values)) == headers, f'Headers changed: {sheet_name}')
            for actual, expected in zip(list(sheet.values)[1:], rows):
                require(list(actual) == expected, f'Export changed/truncated a value: {sheet_name}')
            require(sheet.freeze_panes is not None and len(sheet.tables) == 1, f'Missing freeze/filter: {sheet_name}')
        sheet = book['REVISION']
        require(len(sheet.data_validations.dataValidation) == 3, 'Dropdowns missing')
        expected_lists = {
            'human_decision': 'SUPPORTED,INSUFFICIENT_EVIDENCE,NOT_SUPPORTED',
            'human_support_strength': '0,1,2,3,4',
            'review_status': 'PENDING,IN_REVIEW,REVIEWED',
        }
        from openpyxl.utils import get_column_letter
        for field, choices in expected_lists.items():
            column = get_column_letter(payload['review_headers'].index(field)+1)
            validations = [d for d in sheet.data_validations.dataValidation if str(d.sqref) == f'{column}2:{column}{sheet.max_row}']
            require(len(validations) == 1 and validations[0].type == 'list' and validations[0].formula1.strip('"') == choices,
                    f'Wrong dropdown range or options: {field}')
        require(all(sheet.cell(row, payload['review_headers'].index(h) + 1).value is None
                    for row in range(2, sheet.max_row + 1) for h in HUMAN), 'Human annotations must be blank')
        require(not any('confidence' in h for h in payload['review_headers']), 'Forbidden confidence column')
        require(not any(c.data_type == 'f' for s in book for row in s for c in row), 'Unexpected executable formulas')
        restored_fields = defaultdict(list)
        for pid, field, part, text, did in list(book['LECTURA_PROYECTOS'].values)[1:]:
            restored_fields[(pid, did, field)].append((part, text or ''))
        for row in payload['review']:
            for field in FIELDS:
                key = (row[1], row[2], field)
                original = row[payload['review_headers'].index('project_'+field)] or ''
                require(''.join(text for _, text in sorted(restored_fields[key])) == original,
                        f'Incomplete project reading field: {field}')
        rule_table = book['INSTRUCCIONES'].tables['GeneralReviewRules']
        from openpyxl.utils.cell import range_boundaries
        _, rules_row, _, _ = range_boundaries(rule_table.ref)
        require([[book['INSTRUCCIONES'].cell(rules_row+1+r, 1+c).value for c in range(len(payload['rules_headers']))]
                 for r in range(len(payload['rules']))] == payload['rules'], 'Rules changed during export')
        metadata = {book['METADATA'].cell(r,1).value: book['METADATA'].cell(r,2).value for r in range(2,len(payload['metadata'])+2)}
        expected = dict(payload['metadata'])
        actual_date = metadata.pop('generated_at')
        expected_date = datetime.fromisoformat(expected.pop('generated_at')).replace(tzinfo=None)
        require(isinstance(actual_date, datetime) and abs((actual_date-expected_date).total_seconds()) < 0.002,
                'UTC generation timestamp changed during export')
        require(metadata == expected, 'Metadata changed during export')
        require(sheet.freeze_panes == 'C2', 'Review header and IDs must both stay frozen')
        return {'PASS': True, 'duplicate_PROJECT_INDICATOR': 0, 'invalid_project_IDs': 0, 'invalid_indicator_IDs': 0,
                'invalid_document_IDs': 0, 'invalid_discovery_IDs': 0, 'ARTICLE_rows': 0, 'automatic_decisions': 0,
                'confidence_columns': 0, 'rules_preserved': len(payload['rules']), 'full_project_fields_preserved': True,
                'sheets': book.sheetnames, 'case_count': len(payload['review']), 'output_sha256': sha(path)}
    finally:
        book.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/layer4/human_review/revision_proyectos_indicadores_source_level.xlsx')
    parser.add_argument('--preview-dir', type=Path, default=Path(tempfile.gettempdir()) / 'graphrag_source_review_previews')
    parser.add_argument('--replace-unreviewed', action='store_true', help='Replace only an existing generated workbook with every human field still empty')
    args = parser.parse_args()
    output = args.output.resolve()
    require(output.is_relative_to((ROOT / 'outputs/layer4/human_review').resolve()), 'Output must remain in private human_review directory')
    if output.exists():
        require(args.replace_unreviewed, 'Workbook already exists; preserve human labels and choose a new output filename')
        previous = load_workbook(output, read_only=True, data_only=False)
        try:
            require('REVISION' in previous.sheetnames, 'Existing file is not a review workbook')
            previous_rows = list(previous['REVISION'].values)
            columns = {h: previous_rows[0].index(h) for h in HUMAN}
            require(all(row[i] is None for row in previous_rows[1:] for i in columns.values()), 'Existing human annotations must never be overwritten')
        finally:
            previous.close()
    payload, protected = prepare()
    output.parent.mkdir(parents=True, exist_ok=True)
    author(payload, output, args.preview_dir.resolve())
    verification = verify_saved(output, payload)
    changed = [p.relative_to(ROOT).as_posix() for p, digest in protected.items() if sha(p) != digest]
    require(not changed, f'Protected input/code changes detected: {changed}')
    # Artifact export diagnostics are a disposable sidecar, not a second deliverable.
    inspection = Path(str(output) + '.inspect.ndjson')
    require(inspection.parent == output.parent, 'Unexpected diagnostic path')
    if inspection.exists():
        inspection.unlink()
    print(json.dumps({'output': str(output), 'verification': verification, 'protected_files_unchanged': len(protected),
                      'summary': dict(payload['metadata'])}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
