// Consumer workbook only. All assessments and citations were validated upstream.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
const modulePath=require.resolve('@oai/artifact-tool',{paths:[process.env.LAYER4_ARTIFACT_RUNTIME ||
    path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node')]});
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(modulePath).href);
const spec=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const wb=Workbook.create(),sheet=wb.worksheets.add(spec.name);
const values=[spec.columns,...spec.rows];
const range=sheet.getRangeByIndexes(0,0,values.length,spec.columns.length);
range.values=values;range.format.font.name='Arial';range.format.font.size=10;
range.format.wrapText=true;range.format.verticalAlignment='top';
const widths=[18,18,28,85,20,35,16];
for(let i=0;i<spec.columns.length;i++){
    const column=sheet.getRangeByIndexes(0,i,values.length,1);
    column.format.columnWidth=widths[i];
    column.setNumberFormat(i===6?'0.00':'@');
}
range.format.autofitRows();
const header=sheet.getRangeByIndexes(0,0,1,spec.columns.length);
header.format.fill='#173D57';header.format.font.color='#FFFFFF';header.format.font.bold=true;header.format.rowHeight=30;
sheet.freezePanes.freezeRows(1);sheet.showGridLines=false;
sheet.tables.add(range,true,'ResultadoIndicadores');
wb.recalculate();
await(await SpreadsheetFile.exportXlsx(wb)).save(process.argv[3]);
const image=await wb.render({sheetName:spec.name,range:'A1:G5',scale:1.25,format:'png'});
await fs.writeFile(process.argv[3]+'.png',new Uint8Array(await image.arrayBuffer()));
