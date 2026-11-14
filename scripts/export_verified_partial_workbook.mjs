// Workbook presentation for the read-only, verified partial-result exporter.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const runtime=path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const working=path.join(root,'.tmp/thesis-partial-build');
await fs.mkdir(working,{recursive:true});
const junction=path.join(working,'node_modules');
try { await fs.symlink(runtime,junction,'junction'); }
catch (e) { if(e.code!=='EEXIST') throw e; }
if((await fs.realpath(junction)).toLowerCase()!==(await fs.realpath(runtime)).toLowerCase()) throw Error('Dependencias no autorizadas');
const require=createRequire(path.join(working,'package.json'));
const { Workbook, SpreadsheetFile }=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const data=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const output=process.argv[3];
try { await fs.access(output); throw Error('El Excel ya existe: no sobrescribir'); }
catch(e) { if(e.code!=='ENOENT') throw e; }
const workbook=Workbook.create();
const result=workbook.worksheets.add('Resultados');
const summary=workbook.worksheets.add('Resumen');
const end=data.rows.length+1;
result.getRange(`A1:M${end}`).values=[data.headers,...data.rows];
result.tables.add(`A1:M${end}`,true,'EvaluacionesValidas');
result.freezePanes.freezeRows(1); result.freezePanes.freezeColumns(3);
result.getRange(`A1:M${end}`).format.font={name:'Arial',size:10};
result.getRange(`A1:M${end}`).format.verticalAlignment='top';
result.getRange(`A1:M${end}`).format.wrapText=true;
const widths=[18,21,15,55,26,115,32,24,22,35,24,110,95];
widths.forEach((w,i)=>result.getRangeByIndexes(0,i,end,1).format.columnWidth=w);
result.getRange(`A2:C${end}`).setNumberFormat('@');
result.getRange(`H2:H${end}`).setNumberFormat('0.00');
for(let i=0;i<data.rows.length;i++) {
  const row=data.rows[i];
  const lines=Math.max(...row.map((v,c)=>String(v??'').split('\n').reduce((n,l)=>n+Math.max(1,Math.ceil(l.length/(widths[c]*1.12))),0)));
  result.getRange(`A${i+2}:M${i+2}`).format.rowHeight=Math.min(409,Math.max(60,lines*13+10));
}
summary.getRange('A2').values=[['Evaluación parcial de los 30 proyectos']];
summary.getRange('A2:M2').format.font={name:'Arial',size:14,bold:true};
summary.getRange('A3').values=[[`${data.totals.projects_with_valid} proyectos con evaluaciones válidas. ${data.totals.valid} evaluaciones. ${data.totals.positive} positivas. ${data.totals.negative} negativas.`]];
summary.getRange('A4').values=[['NOT_SUPPORTED: sin respaldo en el contexto evaluado. La confianza calculada no es una probabilidad.']];
summary.getRange('A3:M4').format.font={name:'Arial',size:10};
summary.getRange('A6:M36').values=[data.summary_headers,...data.summary];
summary.tables.add('A6:M36',true,'CoberturaProyectos');
summary.getRange('A6:M37').format.font={name:'Arial',size:10};
summary.getRange('A7:A36').setNumberFormat('@');
summary.getRange('B7:H37').setNumberFormat('#,##0');
summary.getRange('J7:L37').setNumberFormat('#,##0');
summary.getRange('A7:M36').format.rowHeight=24;
summary.getRange('A6:M6').format.rowHeight=44;
summary.getRange('A6:M6').format.wrapText=true;
summary.getRange('A1:A37').format.columnWidth=18;
summary.getRange('B1:H37').format.columnWidth=15;
summary.getRange('I1:I37').format.columnWidth=16;
summary.getRange('J1:L37').format.columnWidth=19;
summary.getRange('M1:M37').format.columnWidth=22;
summary.getRange('A37').values=[['TOTAL']];
for (const col of ['B','C','D','E','F','G','H','J','K','L']) summary.getRange(`${col}37`).formulas=[[`=SUM(${col}7:${col}36)`]];
summary.getRange('A37:M37').format.font={name:'Arial',size:10,bold:true};
summary.getRange('A37:M37').format.fill='#E8EDF3';
for (const [sheet,header] of [[result,'A1:M1'],[summary,'A6:M6']]) {
  sheet.showGridLines=false; sheet.tabColor='#243B53';
  sheet.getRange(header).format={fill:'#243B53',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',verticalAlignment:'center'};
}
result.getRange('A1:M1').format.rowHeight=44;
workbook.recalculate();
console.log((await workbook.inspect({kind:'table',range:'Resumen!A37:M37',include:'values,formulas',tableMaxRows:1,tableMaxCols:13,maxChars:1800})).ndjson);
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1000});
console.log(errors.ndjson);
const file=await SpreadsheetFile.exportXlsx(workbook);
await file.save(output);
const preview=await workbook.render({sheetName:'Resumen',autoCrop:'all',scale:1,format:'png'});
await fs.writeFile(path.join(working,'resumen.png'),new Uint8Array(await preview.arrayBuffer()));
console.log(JSON.stringify({xlsx:output,rows:data.rows.length,sheets:['Resultados','Resumen']}));
