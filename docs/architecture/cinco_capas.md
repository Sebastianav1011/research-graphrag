> Ubicación vigente de originales: `data/raw/`. El código de inventario forma parte de preprocesamiento. Este documento conserva el historial; consultar el README raíz para ejecutar.

> Documento histórico anterior a la consolidación del 29-10-2026. La operación vigente está en el README raíz y `docs/architecture/AUDITORIA_CONSOLIDACION_RAW.md`.

# Arquitectura activa de cinco capas

`RAW → PREPROCESSING → KNOWLEDGE → GRAPHRAG → RESULTS → POWER BI`

Power BI consume la salida; no es una sexta capa implementada. Se conserva el
contrato físico de datos y la numeración incluida en artefactos históricos.

| Capa | Paquete canónico | Entrada | Salida / contrato físico conservado |
|---|---|---|---|
| 1 RAW | `layer1_raw` | Archivos depositados por el custodio en `data/raw/prueba_controlada` o `prueba_en_vivo` | Originales intactos; inventario de solo lectura |
| 2 PREPROCESSING | `layer2_preprocessing` | Conjunto RAW seleccionado, mappings explícitos | `workspace/data/canonical`, staging y auditoría ETL |
| 3 KNOWLEDGE | `layer3_knowledge` | Siete tablas canónicas y manifest | Ocho tablas en `workspace/data/knowledge`; SOURCE y REFERENCE separados |
| 4 GRAPHRAG | `layer4_graphrag` | Knowledge validado | `workspace/data/graphrag`, índices, embeddings, grafo y contextos |
| 5 RESULTS | `layer5_results` | Secciones/proyectos, contextos y configuración V3.3 | Assessments/evidencias/confianza, exportación y auditoría; territorios verificados |

`workspace` pertenece a `outputs/pipeline_manual/<run_id>`. Los motores históricos
siguen publicando en los mismos nombres internos `outputs/layer1`, `layer2`, `layer3`
dentro de esa raíz privada: se conserva el contrato de sus validadores. No son otras
capas adicionales. La planificación nueva de resultados vive en `layer5_results/`;
el coordinador conserva `layer4/` al reanudar un run que ya lo tenía.

Las publicaciones globales existentes `data/canonical`, `data/knowledge`,
`data/graphrag` y `outputs/layer1..4` permanecen donde están. Sus manifiestos y hashes
no se reescriben para aparentar una ejecución con numeración nueva. En particular,
los Excel oficiales y de 30 proyectos permanecen en `outputs/layer4/final`.

Los paquetes se trasladaron físicamente sin editar sus fuentes. Los cuatro nombres
antiguos bajo src son junctions NTFS hacia los canónicos. Los tests tienen equivalentes
de cinco capas y vistas históricas. Esto mantiene los fingerprints y los scripts
congelados que enumeran rutas antiguas. No existe otra copia analítica ejecutándose.
`pipeline_compat.install()` hace que los imports históricos y canónicos compartan
el objeto módulo en las entradas nuevas y en pytest; no modifica verificadores,
autorizaciones, fórmulas ni criterios.

Para integración programática mixta, instalar `pipeline_compat.install()` antes de
importar paquetes. Los scripts históricos pueden continuar con su namespace original.
No se hace una sustitución global del texto de los fuentes: sus referencias antiguas
son intencionales y operan mediante las vistas de compatibilidad.

Configuraciones nuevas (`layer2_preprocessing.yaml`, `layer3_knowledge.yaml`,
`layer4_graphrag.yaml`, `layer5_*.yaml`) conservan los mismos valores que sus originales.
El coordinador manual prefiere las tres primeras para nuevos checkpoints; las versiones
originales continúan disponibles para los runners y manifests anteriores. Las claves
de contrato `layer1_run_id`, `layer2_run_id`, readiness y similares no se renombran.

Los contratos de datos permanecen íntegros: [índice](../contracts/cinco_capas.md).
La operación manual y reanudación están en [manual](../pipeline_manual.md).

## Portabilidad

Los junctions son una propiedad del sistema de archivos Windows y requieren revisión
al trasladar/clonar el repositorio. `scripts/verify_layer_aliases.py` los verifica;
`--commands` muestra comandos nativos para enlaces faltantes y nunca sobrescribe
directorios físicos ni modifica la política de ejecución de PowerShell. No se
debe hacer una sustitución de rutas que cambie hashes históricos. En otra plataforma
se requiere preparar enlaces equivalentes antes de usar runners congelados. No se
hizo staging, commit ni push; revisar la representación de estos movimientos antes
de registrarlos en Git.

Los documentos `layer1.md`..`layer4.md`, las aceptaciones y los README dentro de
paquetes conservados describen la numeración del cierre original. `layer3.md` y su
aceptación están protegidos por la publicación territorial; se mantienen intactos.
Este documento es la referencia activa de numeración.
