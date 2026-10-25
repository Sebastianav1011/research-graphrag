// Offline workbook exporter using the configured/bundled artifact runtime.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url);
const dependencyRoot = process.env.TERRITORY_ARTIFACT_RUNTIME ||
  path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node');
let modulePath;
try { modulePath = require.resolve('@oai/artifact-tool', { paths: [dependencyRoot] }); }
catch { console.error('ARTIFACT_RUNTIME_UNAVAILABLE'); process.exit(3); }
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(modulePath).href);
const spec = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
const wb = Workbook.create();
for (const tab of spec.sheets) {
  const sheet = wb.worksheets.add(tab.name);
  const rows = [tab.columns, ...tab.rows].map(row => row.map(value =>
    typeof value === 'string' && value.startsWith('=') ? `'${value}` : value));
  const range = sheet.getRangeByIndexes(0, 0, rows.length, tab.columns.length);
  range.values = rows;
  range.format.font.name = 'Arial';
  range.format.font.size = 10;
  range.format.verticalAlignment = 'top';
  range.format.wrapText = true;
  range.format.rowHeight = 60;
  for (let column = 0; column < tab.columns.length; column++) {
    const field = tab.columns[column];
    const columnRange = sheet.getRangeByIndexes(0, column, rows.length, 1);
    columnRange.format.columnWidth = tab.widths?.[column] || 23;
    if (/code|_id$/.test(field)) columnRange.setNumberFormat('@');
    // The renderer interprets digit-only text for display. A width-specific
    // display format retains zeros visually while the XLSX value stays string.
    if (/code$/.test(field)) {
      for (let row = 1; row < rows.length; row++) {
        const value=rows[row][column];
        if(typeof value==='string' && /^\d+$/.test(value))
          sheet.getRangeByIndexes(row,column,1,1).setNumberFormat('0'.repeat(value.length));
      }
    }
  }
  if(tab.name==='METADATA') sheet.getRange('B2').setNumberFormat('yyyy-mm-dd hh:mm:ss');
  range.format.autofitRows();
  const header = sheet.getRangeByIndexes(0, 0, 1, tab.columns.length);
  header.format.fill = tab.name === 'AMBIGUOS' ? '#6D451C' : '#173D57';
  header.format.font.color = '#FFFFFF';
  header.format.font.bold = true;
  header.format.rowHeight = 30;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.tables.add(range, true, `Territory_${tab.name}`);
}
wb.recalculate();
await (await SpreadsheetFile.exportXlsx(wb)).save(process.argv[3]);
const report={engine:'@oai/artifact-tool',sheets:[]};
const previewDirectory=process.argv[4];
if(previewDirectory) await fs.mkdir(previewDirectory,{recursive:true});
for (const tab of spec.sheets) {
  report.sheets.push({name:tab.name,rows:tab.rows.length,columns:tab.columns.length});
  if (previewDirectory) {
    const columns=Math.min(7,tab.columns.length);
    const endColumn=String.fromCharCode(64+columns);
    const preview=await wb.render({sheetName:tab.name,range:`A1:${endColumn}${Math.min(5,tab.rows.length+1)}`,scale:1.25,format:'png'});
    await fs.writeFile(path.join(previewDirectory,`${tab.name}.png`),new Uint8Array(await preview.arrayBuffer()));
    const detail=tab.name==='RESUELTOS'?'H1:K5':tab.name==='AMBIGUOS'?'H1:N5':null;
    if(detail){
      const extra=await wb.render({sheetName:tab.name,range:detail,scale:1.25,format:'png'});
      await fs.writeFile(path.join(previewDirectory,`${tab.name}_detail.png`),new Uint8Array(await extra.arrayBuffer()));
    }
  }
}
await fs.writeFile(process.argv[3]+'.qa.json',JSON.stringify(report,null,2));
console.log(JSON.stringify(report));
