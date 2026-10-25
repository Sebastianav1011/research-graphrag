// Offline authoring engine for the future four-sheet exporter, independent of providers.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
let modulePath;
try{modulePath=require.resolve('@oai/artifact-tool',{paths:[process.env.LAYER4_ARTIFACT_RUNTIME ||
    path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node')]});}
catch{console.error('ARTIFACT_RUNTIME_UNAVAILABLE');process.exit(3);}
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(modulePath).href);
const spec=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const wb=Workbook.create();
for(const tab of spec.sheets){
    const sheet=wb.worksheets.add(tab.name);
    const rows=[tab.columns,...tab.rows].map(row=>row.map(v=>typeof v==='string'&&v.startsWith('=')?`'${v}`:v));
    const range=sheet.getRangeByIndexes(0,0,rows.length,tab.columns.length);
    range.values=rows;range.format.font.name='Arial';range.format.font.size=10;
    range.format.wrapText=true;range.format.verticalAlignment='top';
    for(let c=0;c<tab.columns.length;c++){
        const column=sheet.getRangeByIndexes(0,c,rows.length,1),name=tab.columns[c];
        column.format.columnWidth=tab.name==='METADATA'?(c===0?40:105):(/text|explanation|summary|methodology|objectives|results/.test(name)?65:28);
        if(name.endsWith('_score')||name==='key_element_coverage')column.setNumberFormat('0.00');
        if(/code|_id$/.test(name)){
            column.setNumberFormat('@');
            for(let r=1;r<rows.length;r++)if(typeof rows[r][c]==='string'&&/^\d+$/.test(rows[r][c]))
                sheet.getRangeByIndexes(r,c,1,1).setNumberFormat('0'.repeat(rows[r][c].length));
        }
    }
    if(tab.name==='METADATA')for(let r=1;r<rows.length;r++){
        if(rows[r][0]==='generated_at')sheet.getRangeByIndexes(r,1,1,1).setNumberFormat('yyyy-mm-dd hh:mm:ss');
        if(rows[r][0]==='country_internal_code')sheet.getRangeByIndexes(r,1,1,1).setNumberFormat('000');
    }
    range.format.autofitRows();
    const header=sheet.getRangeByIndexes(0,0,1,tab.columns.length);
    header.format.fill='#173D57';header.format.font.color='#FFFFFF';header.format.font.bold=true;
    header.format.rowHeight=28;sheet.freezePanes.freezeRows(1);sheet.showGridLines=false;
    if(rows.length>1)sheet.tables.add(range,true,`Layer4_${tab.name}`);
}
wb.recalculate();
await(await SpreadsheetFile.exportXlsx(wb)).save(process.argv[3]);
for(const tab of spec.sheets){
    const last=String.fromCharCode(64+Math.min(tab.columns.length,5));
    const image=await wb.render({sheetName:tab.name,range:`A1:${last}${Math.min(tab.rows.length+1,5)}`,scale:1.25,format:'png'});
    await fs.writeFile(process.argv[3]+'.'+tab.name+'.png',new Uint8Array(await image.arrayBuffer()));
}
