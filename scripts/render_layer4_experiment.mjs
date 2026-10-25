// Offline workbook authoring only. Never executes assessments or modifies sources.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
const modulePath=require.resolve('@oai/artifact-tool',{paths:[process.env.LAYER4_ARTIFACT_RUNTIME ||
  path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node')]});
const {Workbook,SpreadsheetFile,FileBlob}=await import(pathToFileURL(modulePath).href);
const spec=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const renderSaved=process.argv[4]==='--render-saved';
const wb=renderSaved?await SpreadsheetFile.importXlsx(await FileBlob.load(process.argv[3])):Workbook.create();
if(renderSaved)for(const tab of spec.sheets){
  const sh=wb.worksheets.getItem(tab.name);
  for(let c=0;c<tab.columns.length;c++)if(/_id$|_code$/.test(tab.columns[c])){
    for(let r=0;r<tab.rows.length;r++){
      const value=tab.rows[r][c];
      if(typeof value==='string'&&/^\d+$/.test(value)){
        // The renderer treats numeric-looking strings as numbers even after
        // import. Apply display masks only in this unsaved QA view.
        const cell=sh.getRangeByIndexes(r+1,c,1,1);
        cell.setNumberFormat('0'.repeat(value.length));cell.format.horizontalAlignment='left';
      }
    }
  }
}
if(!renderSaved)for(const tab of spec.sheets){
  const sh=wb.worksheets.add(tab.name);
  const values=[tab.columns,...tab.rows].map(row=>row.map(v=>typeof v==='string'&&v.startsWith('=')?`'${v}`:v));
  const range=sh.getRangeByIndexes(0,0,values.length,tab.columns.length);
  range.setNumberFormat('@');range.values=values;
  range.format.font.name='Arial';range.format.font.size=10;range.format.wrapText=true;
  range.format.verticalAlignment='top';sh.showGridLines=false;
  for(let c=0;c<tab.columns.length;c++){
    const name=tab.columns[c],column=sh.getRangeByIndexes(0,c,values.length,1);
    column.format.columnWidth=tab.widths?.[name] ?? (/literal|original$|ubicacion|explicacion|definicion|elementos|favorable|insuficiente|instruccion/.test(name)?75:
      /decision|validacion|cumplimiento|indicador$|observaciones|campo|independent/.test(name)?34:23);
    if(/confidence|confianza|^[KFCS]$/.test(name))column.setNumberFormat('0.00');
    if(/strength|inicio_original/.test(name))column.setNumberFormat('0');
    if(tab.numericFormats?.[name])column.setNumberFormat(tab.numericFormats[name]);
    if(/human_label|reviewer_id|independent|evidence_valid|observaciones/.test(name)&&values.length>1){
      const input=sh.getRangeByIndexes(1,c,values.length-1,1);input.format.fill='#FFF2CC';
      if(name==='human_label')input.dataValidation={rule:{type:'list',values:['SUPPORTED','INSUFFICIENT_EVIDENCE','NOT_SUPPORTED']}};
      if(/independent|evidence_valid/.test(name))input.dataValidation={rule:{type:'list',values:['TRUE','FALSE']}};
    }
  }
  range.format.autofitRows();
  // Excel supports at most 409 points per row. Long originals are chunked by
  // Python; retain full cell values for any unusually long future model quote.
  for(let r=1;r<values.length;r++){
    const row=sh.getRangeByIndexes(r,0,1,tab.columns.length);
    if(typeof row.format.rowHeight==='number'&&row.format.rowHeight>400)row.format.rowHeight=400;
  }
  const header=sh.getRangeByIndexes(0,0,1,tab.columns.length);
  header.format.fill='#173D57';header.format.font.color='#FFFFFF';header.format.font.bold=true;
  header.format.horizontalAlignment='center';header.format.verticalAlignment='center';header.format.rowHeight=tab.headerHeight ?? 38;
  sh.freezePanes.freezeRows(1);
  if(tab.freezeColumns)sh.freezePanes.freezeColumns(tab.freezeColumns);
  if(tab.name==='REVISION'||tab.name==='ETIQUETADO')sh.freezePanes.freezeColumns(3);
  if(values.length>1)sh.tables.add(range,true,'Experiment_'+tab.name);
}
wb.recalculate();
if(renderSaved){
const inspections=[];
for(const tab of spec.sheets){
  inspections.push((await wb.inspect({kind:'table',range:`${tab.name}!A1:C3`,include:'values,formulas',tableMaxRows:3,tableMaxCols:3,maxChars:1400})).ndjson);
  const ranges=tab.previewRanges ?? (tab.name==='REVISION'?['A1:F4','G1:N3','O1:V3']:
    tab.name==='ETIQUETADO'?['A1:H4']:
    tab.name==='RESULTADO_INDICADORES'?['A1:G4']:
    tab.name==='TERRITORIOS'?['A1:G4']:['A1:C3']);
  for(let i=0;i<ranges.length;i++){
    const blob=await wb.render({sheetName:tab.name,range:ranges[i],scale:1,format:'png'});
    await fs.writeFile(process.argv[3]+'.'+tab.name+`_${i}.png`,new Uint8Array(await blob.arrayBuffer()));
  }
}
await fs.writeFile(process.argv[3]+'.inspect.json',JSON.stringify(inspections));
}else await(await SpreadsheetFile.exportXlsx(wb)).save(process.argv[3]);
