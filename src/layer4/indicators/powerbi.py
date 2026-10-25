"""Seven-column consumer projection. Never assess, rewrite quotes or compute scores."""
import math

COLUMNS=['siap_id','indicador_id','estado_cumplimiento','parrafo_evidencia',
         'fuente_evidencia','ubicacion_evidencia','confianza']
FIELD_NAMES={'title':'Título','keywords':'Palabras clave','summary':'Resumen',
             'methodology':'Metodología','objectives':'Objetivos','expected_results':'Resultados esperados'}
DECISIONS={'SUPPORTED','INSUFFICIENT_EVIDENCE','NOT_SUPPORTED'}
TERRITORY_COLUMNS=['siap_id','territory_type','territory_code','territory_name',
                   'department_code','department_name','code_system']


def territory_rows(relationships, dimension, siap_ids):
    """Projection of the published bridge only; no territorial extraction."""
    from ..territories.contracts import consumption_rows as published_rows
    selected=[r for r in relationships if r['project_id'] in siap_ids]
    rows=[]
    for row in published_rows(selected,dimension):
        siap_id=siap_ids[row['project_id']]
        if not isinstance(siap_id,str) or not siap_id:raise ValueError('Missing institutional ID')
        rows.append({k:siap_id if k=='siap_id' else row[k] for k in TERRITORY_COLUMNS})
    if len({(r['siap_id'],r['territory_type'],r['territory_code']) for r in rows})!=len(rows):
        raise ValueError('Duplicate institutional territory relationship')
    return rows


def territorial_workbook_bytes(original, rows):
    """Edit the existing artifact-authored package entirely in memory.

    Preserve sheet1, its table, styles and shared strings byte for byte. Only the
    territory sheet/table and required package registrations are added/replaced.
    No temporary files, alternative workbooks or authoring sidecars are created.
    """
    from copy import deepcopy
    from io import BytesIO
    import zipfile
    import xml.etree.ElementTree as ET
    main='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    package='http://schemas.openxmlformats.org/package/2006/relationships'
    content='http://schemas.openxmlformats.org/package/2006/content-types'
    def q(name):return '{'+main+'}'+name
    def xml(element):return ET.tostring(element,encoding='utf-8',xml_declaration=True)
    with zipfile.ZipFile(BytesIO(original)) as archive:
        parts={name:archive.read(name) for name in archive.namelist()}
        wb=ET.fromstring(parts['xl/workbook.xml']);sheets=wb.find(q('sheets'))
        names=[s.attrib['name'] for s in sheets]
        if names not in (['RESULTADO_INDICADORES'],['RESULTADO_INDICADORES','TERRITORIOS']):
            raise ValueError('Unexpected existing workbook sheets')
        sheet=deepcopy(ET.fromstring(parts['xl/worksheets/sheet1.xml']))
        data=sheet.find(q('sheetData'))
        header_style=data[0][0].get('s');body_style=data[1][0].get('s')
        data.clear()
        for index,values in enumerate([TERRITORY_COLUMNS,*[[r[c] for c in TERRITORY_COLUMNS] for r in rows]],1):
            row=ET.SubElement(data,q('row'),{'r':str(index),'ht':'28' if index==1 else '24','customHeight':'1'})
            for column,value in enumerate(values):
                cell=ET.SubElement(row,q('c'),{'r':chr(65+column)+str(index),'s':header_style if index==1 else body_style})
                if value is not None:
                    if not isinstance(value,str):raise ValueError('Territory output must contain strings/null only')
                    cell.set('t','inlineStr')
                    text=ET.SubElement(ET.SubElement(cell,q('is')),q('t'));text.text=value
        columns=sheet.find(q('cols'));columns.clear()
        for i,width in enumerate((18,23,20,40,22,40,20),1):
            ET.SubElement(columns,q('col'),{'min':str(i),'max':str(i),'width':str(width),'customWidth':'1'})
        for view in sheet.iter(q('sheetView')):view.set('tabSelected','0')
        dimension=sheet.find(q('dimension'))
        if dimension is not None:dimension.set('ref',f'A1:G{len(rows)+1}')
        table_parts=sheet.find(q('tableParts'));table_parts.clear();table_parts.set('count','1')
        ET.SubElement(table_parts,q('tablePart'),{'{'+rel+'}id':'rIdTerritoriesTable'})
        table=deepcopy(ET.fromstring(parts['xl/tables/table1.xml']))
        table.attrib.update(id='2',name='Territorios',displayName='Territorios',ref=f'A1:G{len(rows)+1}')
        table_columns=table.find(q('tableColumns'));table_columns.clear();table_columns.set('count','7')
        for i,name in enumerate(TERRITORY_COLUMNS,1):ET.SubElement(table_columns,q('tableColumn'),{'id':str(i),'name':name})
        auto=table.find(q('autoFilter'))
        if auto is None:auto=ET.Element(q('autoFilter'));table.insert(0,auto)
        auto.set('ref',f'A1:G{len(rows)+1}')
        sheet_rels=ET.Element('{'+package+'}Relationships')
        ET.SubElement(sheet_rels,'{'+package+'}Relationship',{'Id':'rIdTerritoriesTable','Type':rel+'/table','Target':'../tables/table2.xml'})
        if len(names)==1:
            ET.SubElement(sheets,q('sheet'),{'name':'TERRITORIOS','sheetId':'2','{'+rel+'}id':'rIdTerritories'})
            wb_rels=ET.fromstring(parts['xl/_rels/workbook.xml.rels'])
            ET.SubElement(wb_rels,'{'+package+'}Relationship',{'Id':'rIdTerritories','Type':rel+'/worksheet','Target':'/xl/worksheets/sheet2.xml'})
            parts['xl/_rels/workbook.xml.rels']=xml(wb_rels)
            types=ET.fromstring(parts['[Content_Types].xml'])
            for part,kind in (('/xl/worksheets/sheet2.xml','worksheet'),('/xl/tables/table2.xml','table')):
                ET.SubElement(types,'{'+content+'}Override',{'PartName':part,
                    'ContentType':'application/vnd.openxmlformats-officedocument.spreadsheetml.'+kind+'+xml'})
            parts['[Content_Types].xml']=xml(types)
        parts['xl/workbook.xml']=xml(wb)
        parts['xl/worksheets/sheet2.xml']=xml(sheet)
        parts['xl/worksheets/_rels/sheet2.xml.rels']=xml(sheet_rels)
        parts['xl/tables/table2.xml']=xml(table)
        output=BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as target:
            for entry in archive.infolist():target.writestr(entry,parts.pop(entry.filename))
            for name,payload in parts.items():target.writestr(name,payload)
    return output.getvalue()


def consumption_rows(assessments, siap_ids):
    """One row per institutional PROJECT+INDICATOR, retaining all verified quotes.

    siap_ids must come from Layer2 metadata.source_project_id; never strip an
    invented prefix. SIAP is the source; locations identify numbered source fields.
    confidence_raw_score is copied unchanged, never interpreted as probability.
    """
    result=[];seen=set()
    for source in assessments:
        if source['assessment_validation_status']!='VALID' or source['validation_errors']:
            raise ValueError('Invalid assessment cannot enter the consumer table')
        siap_id=siap_ids.get(source['project_id'])
        if not isinstance(siap_id,str) or not siap_id.strip():raise ValueError('Missing original institutional ID')
        decision=source['decision']
        if decision not in DECISIONS:raise ValueError('Unknown decision')
        key=siap_id,source['indicator_id']
        if key in seen:raise ValueError('Duplicate SIAP+INDICATOR')
        seen.add(key)
        fields,texts=source['evidence_source_fields'],source['evidence_texts']
        if len(fields)!=len(texts):raise ValueError('Evidence arrays not aligned')
        if any(f not in FIELD_NAMES for f in fields):raise ValueError('Unknown evidence field')
        if any(not isinstance(t,str) or not t.strip() for t in texts):raise ValueError('Invalid quote')
        score=source['confidence_raw_score']
        if source['confidence_version']!='RAW_CONFIDENCE_V1':raise ValueError('Unexpected confidence version')
        if source['confidence_status']=='COMPUTED':
            if decision!='SUPPORTED' or not isinstance(score,(int,float)) or isinstance(score,bool) or not math.isfinite(score) or not 0<=score<=100:
                raise ValueError('Invalid raw score')
        elif score is not None:raise ValueError('Inapplicable score must remain NULL')
        if source['confidence_probability'] is not None or source['confidence_level'] is not None:
            raise ValueError('Probability/level must remain NULL')
        result.append(dict(zip(COLUMNS,[siap_id,source['indicator_id'],decision,
            '\n\n'.join(f'[{i}] {text}' for i,text in enumerate(texts,1)) or None,
            'SIAP' if texts else None,
            '\n'.join(f'[{i}] {FIELD_NAMES[field]}' for i,field in enumerate(fields,1)) or None,score])))
    return result
