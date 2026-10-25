// Two-sheet reader-facing delivery. All source validation is deterministic Python.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
const modulePath=require.resolve('@oai/artifact-tool',{paths:[process.env.LAYER4_ARTIFACT_RUNTIME||
  path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node')]});
const {Workbook,SpreadsheetFile,FileBlob}=await import(pathToFileURL(modulePath).href);
const spec=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
if(JSON.stringify(spec.sheets.map(s=>s.name))!==JSON.stringify(['RESULTADO_INDICADORES','TERRITORIOS']))throw Error('Two contractual sheets required');
const saved=process.argv[4]==='--render-saved';
const wb=saved?await SpreadsheetFile.importXlsx(await FileBlob.load(process.argv[3])):Workbook.create();
for(const tab of spec.sheets){
  const sh=saved?wb.worksheets.getItem(tab.name):wb.worksheets.add(tab.name);
  if(!saved){
    const values=[tab.columns,...tab.rows].map(row=>row.map(v=>typeof v==='string'&&v.startsWith('=')?`'${v}`:v));
    const all=sh.getRangeByIndexes(0,0,values.length,7);
    all.setNumberFormat('@');all.values=values;all.format.font.name='Arial';all.format.font.size=10;
    all.format.wrapText=true;all.format.verticalAlignment='top';sh.showGridLines=false;
    const widths=tab.name==='RESULTADO_INDICADORES'?[18,18,34,100,36,75,16]:[18,23,20,38,22,38,18];
    for(let c=0;c<7;c++)sh.getRangeByIndexes(0,c,values.length,1).format.columnWidth=widths[c];
    if(tab.name==='RESULTADO_INDICADORES')sh.getRangeByIndexes(0,6,values.length,1).setNumberFormat('0.00');
    all.format.autofitRows();
    for(let r=1;r<values.length;r++){
      const row=sh.getRangeByIndexes(r,0,1,7);
      if(typeof row.format.rowHeight==='number'&&row.format.rowHeight>400)row.format.rowHeight=400;
    }
    const header=sh.getRangeByIndexes(0,0,1,7);
    header.format.fill='#173D57';header.format.font.color='#FFFFFF';header.format.font.bold=true;
    header.format.horizontalAlignment='center';header.format.verticalAlignment='center';header.format.rowHeight=38;
    sh.freezePanes.freezeRows(1);
    if(values.length>1)sh.tables.add(all,true,tab.name==='RESULTADO_INDICADORES'?'ResultadosPiloto':'TerritoriosPiloto');
  }else{
    for(let c=0;c<7;c++)if(/_id$|_code$/.test(tab.columns[c]))for(let r=0;r<tab.rows.length;r++){
      const value=tab.rows[r][c];
      if(typeof value==='string'&&/^\d+$/.test(value)){
        const cell=sh.getRangeByIndexes(r+1,c,1,1);
        cell.setNumberFormat('0'.repeat(value.length));cell.format.horizontalAlignment='left';
      }
    }
  }
}
wb.recalculate();
if(saved){
  const inspections=[];
  for(const tab of spec.sheets){
    inspections.push((await wb.inspect({kind:'table',range:`${tab.name}!A1:G3`,include:'values,formulas',tableMaxRows:3,tableMaxCols:7,maxChars:1800})).ndjson);
    const ranges=tab.name==='RESULTADO_INDICADORES'?['A1:D3','E1:G3']:['A1:G5'];
    for(let i=0;i<ranges.length;i++){
      const blob=await wb.render({sheetName:tab.name,range:ranges[i],scale:1,format:'png'});
      await fs.writeFile(process.argv[3]+'.'+tab.name+`_${i}.png`,new Uint8Array(await blob.arrayBuffer()));
    }
  }
  await fs.writeFile(process.argv[3]+'.inspect.json',JSON.stringify(inspections));
}else await(await SpreadsheetFile.exportXlsx(wb)).save(process.argv[3]);
