"""Generic two-sheet Power BI and independent human review exports."""
import csv
from contextlib import closing
import json
from pathlib import Path
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET

from .experiment import verify_prepared, report, read_jsonl, write_json, write_jsonl
from .experiment_inputs import ROOT, read, sha256, verify_hashes
from .powerbi import COLUMNS, TERRITORY_COLUMNS, consumption_rows
from .preliminary_output import verify_workbook
from .review import DECISIONS, evidence_locations, human_metrics


def sheet(name, columns, rows):
    return {'name': name, 'columns': columns, 'rows': [[r.get(c) for c in columns] for r in rows]}


def specs(selected, profiles, records, territories, selection_hash, technical_hash):
    rows = [r for record in records.values() for r in record['rows'] if r['assessment_validation_status']=='VALID']
    mapping = {p['project_id']: p['siap_id'] for p in selected}
    powerbi_rows = consumption_rows(rows, mapping)
    powerbi = {'sheets': [sheet('RESULTADO_INDICADORES', COLUMNS, powerbi_rows), sheet('TERRITORIOS', TERRITORY_COLUMNS, territories)]}
    review, blind, sources = [], [], []
    for p in selected:
        record = records.get(p['project_id'], {})
        by_id = {r['indicator_id']: r for r in record.get('rows', [])}
        assessments = {a['indicator_id']: a for a in (record.get('wrapper') or {}).get('assessments', [])}
        for c in p['candidates']:
            row = by_id.get(c['indicator_id'])
            identity = {'siap_id': p['siap_id'], 'project_id': p['project_id'], 'indicator_id': c['indicator_id']}
            review.append({**identity, 'indicador': profiles[c['indicator_id']]['indicator_name'],
                'estado_ejecucion': record.get('status', 'PENDING_INFERENCE'),
                'decision': row['decision'] if row else None,
                'evidencia_literal': '\n\n'.join(row['evidence_texts']) if row else None,
                'campo': '\n'.join(row['evidence_source_fields']) if row else None,
                'ubicacion': json.dumps(evidence_locations(p, assessments[c['indicator_id']]), ensure_ascii=False) if row else None,
                'strength': row['support_strength'] if row else None,
                'raw_confidence': row['confidence_raw_score'] if row else None,
                'validacion_automatica': row['assessment_validation_status'] if row else 'NOT_EXECUTED',
                'errores_validacion': json.dumps(row['validation_errors'], ensure_ascii=False) if row else None,
                'explicacion': row['evidence_explanation'] if row else None,
                'K': row['key_element_coverage'] if row else None, 'F': row['field_relevance_score'] if row else None,
                'C': row['corroboration_score'] if row else None, 'S': row['support_strength_score'] if row else None,
                'evidence_valid': None, 'evidence_reviewer_id': None, 'evidence_independent': None, 'observaciones': None})
            blind.append({**identity, 'indicador': profiles[c['indicator_id']]['indicator_name'],
                          'human_label': None, 'reviewer_id': None, 'independent': None, 'observaciones': None})
        for field, text in p['fields'].items():
            text = text or ''
            # Bound visible row height as well as Excel's cell limit. All chunks
            # concatenate to the original field; offsets are original codepoints.
            for offset in range(0, max(1, len(text)), 1500):
                sources.append({'siap_id': p['siap_id'], 'project_id': p['project_id'], 'campo': field,
                                'section_id': p['field_provenance'][field]['section_id'], 'inicio_original': offset,
                                'texto_original': text[offset:offset+1500] or None})
    review_columns = ['siap_id', 'project_id', 'indicator_id', 'indicador', 'estado_ejecucion', 'decision',
                      'evidencia_literal', 'campo', 'ubicacion', 'strength', 'raw_confidence', 'validacion_automatica',
                      'errores_validacion', 'explicacion', 'K', 'F', 'C', 'S',
                      'evidence_valid', 'evidence_reviewer_id', 'evidence_independent', 'observaciones']
    catalog = [{'indicator_id': p['indicator_id'], 'indicador': p['indicator_name'], 'categoria': p['indicator_category'],
                'dimension': p['indicator_dimension'], 'definicion': p['descripcion_ampliada'],
                'elementos_clave': '\n'.join(p['key_elements']), 'evidencia_favorable': p['favorable_evidence'],
                'evidencia_insuficiente': p['insufficient_evidence']} for p in sorted(profiles.values(), key=lambda p:p['indicator_id'])]
    guide = [
        {'campo':'selection_sha256', 'instruccion':selection_hash},
        {'campo':'technical_results_sha256', 'instruccion':technical_hash},
        {'campo':'Estado', 'instruccion':'PENDIENTE: las celdas humanas permanecen vacías hasta la revisión responsable.'},
        {'campo':'Orden de revisión', 'instruccion':'Etiquetar primero en ETIQUETADO con FUENTES y CATALOGO, antes de consultar REVISION. Registrar identidad y independent=TRUE solo si se cumplió este protocolo.'},
        {'campo':'Dos revisores', 'instruccion':'Cada revisor usa una copia independiente del libro. El importador acepta varias copias y calcula acuerdo entre revisores sobre pares comunes.'},
        {'campo':'Etiquetas', 'instruccion':', '.join(DECISIONS)},
        {'campo':'Validez de evidencia', 'instruccion':'Tras etiquetar, revisar citas y explicación en REVISION. evidence_valid TRUE/FALSE evalúa también el soporte semántico. Registrar evidence_reviewer_id y evidence_independent TRUE si aplica.'},
        {'campo':'Ubicación', 'instruccion':'Offsets base cero y final exclusivo. La ubicación declara si corresponde al original o al texto NFC con whitespace colapsado; nunca se atribuye el offset normalizado al original.'},
        {'campo':'Confianza', 'instruccion':'RAW_CONFIDENCE_V1 no es probabilidad ni exactitud. Solo SUPPORTED válido y computable recibe score.'},
        {'campo':'Evaluación', 'instruccion':'Métricas condicionadas a candidatos seleccionados. No miden recall end-to-end. Muestra intencional de 50 proyectos, no representativa; hasta dos pares dependientes por proyecto.'},
        {'campo':'Procedencia', 'instruccion':'Campos originales publicados por Capa 2 (incluye exclusión de emails ya autorizada allí). Identidades y versiones completas en selection_manifest.json. Territorios: solo bridge RESOLVED publicada por Capa 4B.'}]
    human = {'sheets': [sheet('ETIQUETADO', ['siap_id','project_id','indicator_id','indicador','human_label','reviewer_id','independent','observaciones'], blind),
        sheet('REVISION', review_columns, review),
        sheet('FUENTES', ['siap_id','project_id','campo','section_id','inicio_original','texto_original'], sources),
        sheet('CATALOGO', ['indicator_id','indicador','categoria','dimension','definicion','elementos_clave','evidencia_favorable','evidencia_insuficiente'], catalog),
        sheet('GUIA', ['campo','instruccion'], guide)]}
    return powerbi, human


def preserve_strings(output, spec):
    """Repair known exporter coercions for declared literal strings only."""
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    def tag(name):return '{'+ns+'}'+name
    from openpyxl.utils import get_column_letter
    replacements = {}
    with zipfile.ZipFile(output) as archive:
        for i, tab in enumerate(spec['sheets'], 1):
            name = f'xl/worksheets/sheet{i}.xml'
            element = ET.fromstring(archive.read(name))
            cells = {c.get('r'): c for c in element.iter(tag('c'))}
            for r, values in enumerate([tab['columns'], *tab['rows']], 1):
                for c, value in enumerate(values, 1):
                    if isinstance(value, str) and value:
                        cell = cells.get(get_column_letter(c)+str(r))
                        if cell is None:
                            raise ValueError('Exporter omitted a declared string cell')
                        for child in list(cell):cell.remove(child)
                        cell.set('t','inlineStr')
                        text = ET.SubElement(ET.SubElement(cell,tag('is')),tag('t'))
                        text.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
                        text.text = value
            replacements[name] = ET.tostring(element, encoding='utf-8', xml_declaration=True)
        temporary = Path(str(output)+'.pending')
        with zipfile.ZipFile(temporary,'w') as target:
            for entry in archive.infolist():target.writestr(entry,replacements.get(entry.filename,archive.read(entry.filename)))
    temporary.replace(output)


def export_spec(root, spec, output):
    for tab in spec['sheets']:
        for values in [tab['columns'], *tab['rows']]:
            if len(values) != len(tab['columns']) or any(isinstance(v,str) and len(v)>32767 for v in values):
                raise ValueError('Excel row width/cell limit exceeded; no truncation allowed')
    output = Path(output)
    if output.exists():
        return verify_workbook(output,spec)
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node and @oai/artifact-tool runtime required')
    spec_path = output.with_suffix('.spec.json')
    write_json(spec_path,spec)
    completed = subprocess.run([node,str(Path(root)/'scripts/render_layer4_experiment.mjs'),str(spec_path),str(output)],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240,shell=False)
    if completed.returncode:
        raise RuntimeError('Artifact export failed: '+completed.stderr[-1500:])
    preserve_strings(output,spec)
    # Render the persisted workbook after literal-string repair. Rendering the
    # pre-export in-memory version can misleadingly show COUNTRY/000 as 0.
    completed = subprocess.run([node,str(Path(root)/'scripts/render_layer4_experiment.mjs'),str(spec_path),str(output),'--render-saved'],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240,shell=False)
    if completed.returncode:
        raise RuntimeError('Saved workbook visual QA failed: '+completed.stderr[-1500:])
    return verify_workbook(output,spec)


def export(root=ROOT, config_path='config/layer4_experiment.yaml', *, require_complete=False):
    from .experiment import run_lock
    verified = verify_prepared(root,config_path)
    config,out,manifest,data,selected,requests,runtime = verified
    with run_lock(out):
        progress = report(root,config_path,verified=verified)
        if require_complete and not progress['execution_complete']:
            raise ValueError('Final export requires every requested assessment valid; partial export remains explicit')
        technical_hash = sha256(out/'technical_results.jsonl')
        directory = out/'exports'/technical_hash[:16]
        directory.mkdir(parents=True,exist_ok=True)
        records = {p.stem:read(p) for p in (out/'records').glob('*.json')}
        powerbi,human = specs(selected,data['profiles'],records,read_jsonl(out/'territories.jsonl'),manifest['selection_sha256'],technical_hash)
        qa = {name:export_spec(root,spec,directory/name) for name,spec in (
            ('powerbi.xlsx',powerbi),('revision_humana.xlsx',human))}
        for name,spec in (('resultado_indicadores.csv',powerbi['sheets'][0]),('territorios.csv',powerbi['sheets'][1])):
            with (directory/name).open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(spec['columns']);writer.writerows(spec['rows'])
        result = {'status':'ASSESSMENTS_COMPLETE_PENDING_HUMAN_REVIEW' if progress['execution_complete'] else 'PARTIAL_PENDING_INFERENCE',
                  'technical_results_sha256':technical_hash,'selection_sha256':manifest['selection_sha256'],
                  'projects_selected':len(selected),'valid_assessments_exported':progress['assessments_valid'],
                  'territory_rows':len(powerbi['sheets'][1]['rows']),'workbook_qa':qa,
                  'powerbi_path':(directory/'powerbi.xlsx').relative_to(out).as_posix(),
                  'human_workbook_path':(directory/'revision_humana.xlsx').relative_to(out).as_posix(),
                  'output_hashes':{p.relative_to(out).as_posix():sha256(p) for p in sorted(directory.glob('*')) if p.is_file()}}
        write_json(out/'export_manifest.json',result)
        return result


def import_reviews(paths, root=ROOT, config_path='config/layer4_experiment.yaml'):
    from openpyxl import load_workbook
    from .experiment import run_lock
    verified = verify_prepared(root,config_path)
    config,out,manifest,data,selected,requests,runtime = verified
    valid_rows = [r for r in read_jsonl(out/'technical_results.jsonl') if r['assessment_validation_status']=='VALID']
    identities = {(p['project_id'],c['indicator_id']):p['siap_id'] for p in selected for c in p['candidates']}
    labels=[]
    for path in paths:
        with closing(load_workbook(path,data_only=False)) as wb:
            guide=dict((a,b) for a,b in wb['GUIA'].values if a and a!='campo')
            if guide.get('selection_sha256')!=manifest['selection_sha256'] or guide.get('technical_results_sha256')!=sha256(out/'technical_results.jsonl'):
                raise ValueError('Human workbook refers to another sample/result snapshot')
            for name in ('ETIQUETADO','REVISION'):
                values=iter(wb[name].values);columns=next(values)
                for values_row in values:
                    row=dict(zip(columns,values_row))
                    key=row['project_id'],row['indicator_id']
                    if identities.get(key)!=row['siap_id']:
                        raise ValueError('Human workbook candidate/SIAP identity mismatch')
                    if name=='ETIQUETADO':
                        label={k:row.get(k) for k in ('project_id','indicator_id','human_label','reviewer_id','independent')}
                    else:
                        label={'project_id':key[0],'indicator_id':key[1], 'human_label':None,
                               'evidence_valid':row.get('evidence_valid'), 'reviewer_id':row.get('evidence_reviewer_id'),
                               'independent':row.get('evidence_independent')}
                    for field in ('independent','evidence_valid'):
                        if label.get(field) in ('TRUE','FALSE'):
                            label[field] = label[field] == 'TRUE'
                    if label.get('human_label') or label.get('evidence_valid') is not None:
                        labels.append(label)
    metrics=human_metrics(valid_rows,labels)
    with run_lock(out):
        directory=out/'reviews';directory.mkdir(exist_ok=True)
        for path in paths:
            destination=directory/(sha256(path)+'.xlsx')
            if not destination.exists():shutil.copyfile(path,destination)
        write_json(out/'human_labels.json',{'labels':labels,'source_hashes':[sha256(path) for path in paths]})
        write_json(out/'human_metrics.json',metrics)
        report(root,config_path,verified=verified)
    return metrics
