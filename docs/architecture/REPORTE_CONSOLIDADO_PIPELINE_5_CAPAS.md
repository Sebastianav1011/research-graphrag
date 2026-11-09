> Ubicación vigente de originales: `data/raw/`. El código de inventario forma parte de preprocesamiento. Este documento conserva el historial; consultar el README raíz para ejecutar.

> Documento histórico anterior a la consolidación del 29-10-2026. La operación vigente está en el README raíz y `docs/architecture/AUDITORIA_CONSOLIDACION_RAW.md`.

# Reporte consolidado — estado final del pipeline GraphRAG

Consolidado documental: **27 de octubre de 2026**. Reúne la auditoría, los cambios
realizados, la estructura final, el funcionamiento manual, las validaciones y los
pendientes de la reorganización ejecutada el 26 de octubre. Esta consolidación no
vuelve a ejecutar pruebas, modelos o inferencias ni modifica resultados.

**Flujo final:** RAW → PREPROCESSING → KNOWLEDGE → GRAPHRAG → RESULTS → POWER BI.

Documentación operativa complementaria:

- [README principal y comandos PowerShell](../../README.md).
- [Arquitectura activa y compatibilidad](cinco_capas.md).
- [Manual detallado y reanudación](../pipeline_manual.md).
- [Contrato entre capas](../contracts/cinco_capas.md).
- [Auditoría de la preparación manual previa](pipeline_manual_auditoria.md).
- [Validación de la preparación manual previa](../pipeline_manual_validacion.md).
- [Informe de migración original y sus evidencias](../migration_5_layers/INFORME.md).

La sección siguiente contiene el informe completo de lo realizado, con enlaces a
los árboles originales/finales, movimientos, imports, hashes y resultados de pruebas.
Los estados PASS y los problemas históricos son los registrados durante aquella
validación; no representan una ejecución nueva del pipeline.

---

# Reorganización de cinco capas — informe final

Raíz exclusiva: `C:\Users\sebas\Workspace\Docs Tesis\GraphRag`.
No se accedió a otra implementación para ejecutar el pipeline. No se hicieron
staging, commit, push, llamadas LLM ni generación de embeddings reales.

## 1. Estructura original inspeccionada

Se inspeccionaron 138.864 entradas mediante recorrido recursivo, con 1.940 referencias
de imports/rutas/entorno registradas y 2.841 fingerprints de fuentes, contratos y
artefactos protegidos. El recorrido incluyó entorno, metadatos y temporales además
de todas las carpetas solicitadas. Se documentaron 48 errores de acceso; no se
afirma haber leído sus descendientes inaccesibles.

- [Árbol original completo observado](../migration_5_layers/arbol_original.txt).
- [Inventario original tipado](../migration_5_layers/estructura_original.json).
- [Imports, rutas absolutas/relativas y entorno](../migration_5_layers/dependencias_originales.json).
- [Resumen y errores de acceso](../migration_5_layers/auditoria_inventario.json).
- [Plan previo a los movimientos](../migration_5_layers/plan_migracion.md).

Resumen de las partes activas originales:

```text
src/
  layer1_data/       ETL, identidad y canonical
  layer2_knowledge/  documentos, secciones, chunks y relaciones
  layer3_graphrag/   embeddings, grafo, retrieval y contexto
  layer4/            indicadores, territorios, Excel y auditoría
  manual_pipeline/  adaptación de documentos y coordinación aislada
capa_1_raw/{prueba_controlada,prueba_en_vivo}/
data/{raw,canonical,knowledge,graphrag,reference}/
outputs/{layer1,layer2,layer3,layer4,pipeline_manual,...}/
config/             fuentes y configuraciones aprobadas
tests/{layer1,layer2,layer3,layer4_*,territories}/
scripts/            runners activos e históricos
docs/, schemas/, requirements/, templates/, archives/
```

No se consideró inactiva una carpeta por su nombre. Se identificaron consumidores
en scripts, imports, manifiestos congelados, helpers de auditoría, exportadores y
tests. El intento en vivo es funcional y está referenciado por fingerprints: se
reutiliza su ejecutor, sin eliminarlo ni ejecutar sus inferencias.

## 2. Estructura final

- [Árbol final observado](../migration_5_layers/arbol_final.txt), con targets de los junctions.
- [Inventario final tipado](../migration_5_layers/estructura_final.json).
- [Relación de movimientos y archivos](../migration_5_layers/archivos_cambiados.csv).

```text
src/
  layer1_raw/                inventario de originales, sin transformar
  layer2_preprocessing/      paquete ETL trasladado
  layer3_knowledge/          paquete de conocimiento trasladado
  layer4_graphrag/           paquete GraphRAG trasladado
  layer5_results/            paquete de resultados trasladado
  manual_pipeline/           coordinador adaptado, no reemplazado
  pipeline_compat.py          identidad de imports históricos/canónicos
  layer1_data -> layer2_preprocessing
  layer2_knowledge -> layer3_knowledge
  layer3_graphrag -> layer4_graphrag
  layer4 -> layer5_results
data/raw/{prueba_controlada,prueba_en_vivo}/
capa_1_raw -> data/raw
tests/{layer2_preprocessing,layer3_knowledge,layer4_graphrag,layer5_*}/
config/{layer2_preprocessing,layer3_knowledge,layer4_graphrag,layer5_*}.yaml
outputs/layer5/README.md      índice, sin duplicar publicaciones históricas
outputs/pipeline_manual/<run_id>/
  workspace/data/{canonical,knowledge,graphrag}/
  preprocess/, layer5_results/, resultado_indicadores.xlsx
outputs/layer1..4/            publicaciones y evidencias históricas intactas
```

## 3. Movimientos y nombres

| Origen | Destino físico | Compatibilidad |
|---|---|---|
| src/layer1_data | src/layer2_preprocessing | Junction en origen |
| src/layer2_knowledge | src/layer3_knowledge | Junction en origen |
| src/layer3_graphrag | src/layer4_graphrag | Junction en origen |
| src/layer4 | src/layer5_results | Junction en origen |
| tests/layer1 | tests/layer2_preprocessing | Junction en origen |
| tests/layer2 | tests/layer3_knowledge | Junction en origen |
| tests/layer3 | tests/layer4_graphrag | Junction en origen |
| tests/layer4_* | tests/layer5_* | Junction en cada origen |
| tests/territories | tests/layer5_territories | Junction en origen |
| capa_1_raw/prueba_* | data/raw/prueba_* | capa_1_raw enlaza data/raw |
| config/layer1,2,3.yaml | Nuevos nombres layer2_preprocessing,layer3_knowledge,layer4_graphrag | Originales conservados; copias pequeñas de configuración con valores idénticos |
| config/layer4_*.yaml | config/layer5_*.yaml | Originales conservados |
| outputs/layer1..4, schemas, publicaciones data | Sin movimiento | Contratos y fingerprints históricos |

Los movimientos se hicieron con rutas absolutas comprobadas dentro del workspace,
destinos inexistentes y movimientos nativos. Los enlaces contienen una única
implementación física. Se validaron 15 junctions. No se renombraron Excel, respuestas,
evidencias, run IDs ni campos de los contratos para falsificar su numeración histórica.

## 4. Imports y referencias

El [inventario final de imports](../migration_5_layers/imports_finales.json) registra 1.778 imports de
src/scripts, su ubicación y el namespace efectivo tras resolver compatibilidad.

- Los imports activos del coordinador apuntan a `layer2_preprocessing`,
  `layer3_knowledge`, `layer4_graphrag` y `layer5_results`.
- `pipeline_compat.install()` conecta imports históricos con los mismos objetos
  módulo canónicos. Se comprobaron identidad de objetos y metadata de imports.
- Los fuentes analíticos y runners congelados conservan sus imports y rutas
  originales como referencias compatibles. No se hicieron sustituciones globales.
- Los junctions permiten que sus glob y verificadores encuentren exactamente los
  mismos bytes. Los 89 archivos analíticos protegidos permanecen idénticos.
- El coordinador prefiere configuraciones con nombres nuevos; conserva nombres
  físicos internos requeridos por los validadores de canonical/knowledge/GraphRAG.
- RAW nuevo es `data/raw`; el alias anterior permite resolver runs previos.
- `outputs/layer5` es un índice hacia las publicaciones existentes, sin copiar datos.
- README, manual e índices técnicos activos reflejan cinco capas. Los contratos,
  aceptaciones y documentos protegidos conservan su contenido/numeración original;
  la arquitectura actual está en [cinco_capas.md](cinco_capas.md).
- El registro operacional `outputs/layer4/auditoria/rutas.json` añade los dos
  fingerprints del coordinador adaptado y sus snapshots originales exactos, usando
  el verificador ya existente. No se cambió su implementación ni las políticas del
  ejecutor. El registro anterior también fue archivado íntegramente.

No se encontraron dependencias activas hacia `Pruebas\Prueba GraphRag`: sus menciones
restantes son contexto histórico o patrones de validación que prohíben ese fallback.

## 5. Archivos creados, modificados y eliminados

La lista exhaustiva observada está en `archivos_cambiados.csv`, incluidos movimientos
y artefactos de validación aislados. Los cambios funcionales se limitan a:

- Creación de `layer1_raw`, `pipeline_compat.py`, runners canónicos, verificador de
  junctions, índice outputs/layer5 y pruebas de migración.
- Adaptación de los dos módulos del coordinador manual: selección RAW canónica,
  imports nuevos, operaciones separadas y encadenamiento mediante `run`.
- Configuración manual, pytest y documentación activa actualizados; nuevas
  configuraciones con los valores existentes y nuevos nombres.
- `tests/test_manual_pipeline.py` adapta fixtures de rutas y nombres del run.
- Archivo de los dos fuentes anteriores del coordinador y del registro de rutas en
  `archives/layer_migration_5/`; no se crea otra implementación analítica activa.

No se eliminó ningún fuente analítico ni resultado original. Las carpetas movidas
conservan vistas históricas. El borrado del contenedor RAW vacío solo permitió crear
su junction; los dos subdirectorios y sus archivos fueron trasladados primero.

## 6. Estado de las capas y comandos

| Capa | Estado comprobado |
|---|---|
| RAW | Canónico y separado; inventario de solo lectura; sin fallback |
| PREPROCESSING | Ejecutable de forma independiente; checkpoint PREPROCESSED, sin knowledge/modelos |
| KNOWLEDGE | Ejecución independiente desde canonical; checkpoint PREPARED y reutilización idempotente |
| GRAPHRAG | Paquete/imports funcionales y publicación existente íntegra; sin embeddings reales nuevos |
| RESULTS | V3.3/V3 congelado verificado, exportación/consumo y autorización preservados; sin inferencias nuevas |
| Power BI | Consumidor de Excel; contrato comprobado, Desktop no importado |

Desde la raíz, para uno o dos proyectos originales depositados por el usuario:

```powershell
$ejecucion = 'vivo_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
.\.venv\Scripts\python.exe -B scripts/run_layer1_raw.py --dataset prueba_en_vivo
.\.venv\Scripts\python.exe -B scripts/run_layer2_preprocessing.py --dataset prueba_en_vivo --run-id $ejecucion
.\.venv\Scripts\python.exe -B scripts/run_layer3_knowledge.py --dataset prueba_en_vivo --run-id $ejecucion
.\.venv\Scripts\python.exe -B scripts/run_pipeline_manual.py validate --dataset prueba_en_vivo --run-id $ejecucion
```

GraphRAG y los resultados se ejecutan solo cuando se desean y se aprueban:

```powershell
.\.venv\Scripts\python.exe -B scripts/run_layer4_graphrag.py --dataset prueba_en_vivo --run-id $ejecucion --approve-build
.\.venv\Scripts\python.exe -B scripts/run_layer5_results.py review --dataset prueba_en_vivo --run-id $ejecucion
```

Después de leer review.txt:

```powershell
.\.venv\Scripts\python.exe -B scripts/run_layer5_results.py evaluate --dataset prueba_en_vivo --run-id $ejecucion --authorize
.\.venv\Scripts\python.exe -B scripts/run_layer5_results.py export --dataset prueba_en_vivo --run-id $ejecucion
.\.venv\Scripts\python.exe -B scripts/run_layer5_results.py verify --dataset prueba_en_vivo --run-id $ejecucion
```

Pipeline con el mismo coordinador: `run --through knowledge` prepara las capas 2/3;
`run --through results --approve-build` llega a revisión; repetir tras leerla con
`--authorize` permite evaluar y exportar. La primera llegada nunca autoriza textos
sin revisión previa. Para la muestra controlada cambiar `--dataset`; para más de dos
proyectos elegir los IDs del lote. Ver el README y el manual para los comandos completos.

## 7. Pruebas y comprobaciones

| Grupo | PASS | SKIP | FAIL | ERROR | Evidencia |
|---|---:|---:|---:|---:|---|
| Datos y pipeline manual | 134 | 12 | 0 | 0 | tests_datos.xml |
| Analítica/territorios/contratos existentes | 834 | 28 | 15 | 17 | tests_analitica.xml |
| Migración y runners canónicos finales | 10 | 0 | 0 | 0 | tests_entradas.xml |

Los tres grupos suman 978 casos aprobados, 40 omitidos por gates explícitos y 32
incidencias históricas. Además `tests_migracion.xml` registra 21 aprobaciones de
manual/migración, solapadas con los grupos anteriores, y no se suman otra vez.

Los fallos NO se ocultaron ni se resolvieron modificando controles:

- 17 errores de fixture comparten la preparación histórica que espera un directorio
  experiment_* directamente bajo outputs/layer4, incompatible con su configuración
  organizada posteriormente. El error representativo se reprodujo sin el adaptador.
- 3 pruebas de cleanup esperan journals en una ruta anterior; 1 de cierre espera
  otra organización de estudios; 1 espera el estado intermedio del cierre de 22292.
- 1 prueba Power BI busca powerbi_preliminary_20 sin usar el resolver de rutas.
- 8 pruebas dependen de ZIP históricos ausentes antes de esta migración.
- 1 prueba territorial espera un marcador de fallo en una ubicación histórica.

Los 15 fallos se reprodujeron con imports originales y sin conftest/adaptador nuevo,
junto con el error de fixture representativo: `tests_control_legado.xml` (18 PASS,
15 FAIL, 1 ERROR). Se preservan como pendientes de revisión de tests/historial; no
se alteraron políticas para hacerlos pasar.

Los cinco runners canónicos devolvieron 0 en --help. Las seis secuencias PowerShell
del README pasaron el parser. Los runners RAW/preprocessing/knowledge/results se
ejecutaron realmente en Windows PowerShell en una raíz aislada con espacios.
El alcance predeterminado de pytest conserva el anterior (ahora
`tests/layer2_preprocessing`); las suites amplias se invocaron explícitamente. La
vista histórica `tests/layer1` también recolecta sus 70 casos correctamente.
Los checkpoints, reutilización, evidencia parcial y score numérico se validaron.
El build de integración empleó vectores sintéticos exclusivos del test, rechazados
como proveedor de producción. No se ejecutó el LLM ni BGE-M3 reales.

## 8. Integridad histórica

[integridad.json](../migration_5_layers/integridad.json) verifica 2.841 archivos: **2.835 idénticos** y
seis modificaciones estructurales declaradas (coordinador, configuración/manual,
fixture y registro operacional). Cero archivos protegidos ausentes y cero cambios
inesperados. Los 89 fuentes analíticos trasladados están íntegros.

| Libro | SHA-256 idéntico antes/después | Filas indicadores / territorios |
|---|---|---|
| Oficial V2 | fc6f876493ee327f140f5fbdbd234b93242eeaee15d86aa752388980f03332e1 | 29 / 13 |
| Demo 30 original | cdd83be1ecf06bc732d00e6f85d6b8602314282200a222a019b2199e1cf7690f | 3 / 22 |
| Demo 30 ampliada | d75379384c042025b607dbc80c3bc6f6cd780ea689948732bc51dd7ba78ca64e | 81 / 22 |

El manifiesto de cobertura mantiene 30 seleccionados/procesados, 81 assessments
válidos y 3 SUPPORTED. No se tocaron evidencia, confianza ni respuestas originales.

La lectura y verificación de la publicación GraphRAG existente pasó: ocho tablas de
knowledge, 45.362 embeddings SOURCE y 133 REFERENCE, grafo válido de 33.915 entidades
y 24.821 relaciones, 2.400 candidatos y 464 paquetes de contexto. No se regeneraron
vectores: [validación](../migration_5_layers/validacion_graphrag_existente.json).

El plan congelado V3.3 pasó con los 48 perfiles. El consumo territorial pasó en sus
10 archivos obligatorios y 2.654 relaciones RESOLVED de la publicación completa.
La muestra conserva sus 22 relaciones. El verificador histórico completo sigue
notificando la imagen opcional ausente `qa/METADATA.png`; no se inventó ni sustituyó.
[Validación territorial](../migration_5_layers/validacion_territorial.json).

## 9. Riesgos y revisión manual

1. Junctions NTFS: revisar su representación al preparar los movimientos en Git o
   clonar en otro equipo. No se hizo staging/commit/push. El verificador Python no
   sobrescribe directorios ni cambia la política de ejecución de PowerShell.
2. Conservar las vistas históricas mientras scripts y fingerprints las requieran.
   Para integraciones programáticas mixtas instalar pipeline_compat antes de importar.
3. Revisar las pruebas históricas pendientes y recuperar ZIP ausentes desde su
   procedencia auténtica; no fabricar archivos para hacer pasar las verificaciones.
4. 48 directorios de caché/temporales no pudieron enumerarse por permisos. El informe
   conserva sus ubicaciones; no se les atribuye contenido inspeccionado.
5. PDF requiere pypdf; documentos sin identidad/campos/texto extraíble se rechazan.
6. No se afirma calidad nueva de inferencia ni importación en Power BI Desktop.
   Nuevos territorios requieren su propio puente validado; no se reutilizan ajenos.
7. No se renombraron schemas ni claves históricas: son contratos, no carpetas
   obsoletas. Cambiarlos requeriría otra migración de contratos fuera de este alcance.

Inferencias nuevas: **0 llamadas, 0 tokens y 0 tiempo de inferencia**.
