# Fuentes institucionales de Capa 1

- `base/`: los tres CSV originales; no editarlos ni sustituirlos.
- `incoming/<identificador_entrega>/`: cada nueva entrega en una carpeta distinta,
  conservando sus nombres y archivos originales. No sobrescribir una entrega anterior.
- `reference/`: catálogos VRI y fuente territorial DANE originales.

El procesamiento del conjunto oficial descubre **base + incoming**. Referencias y
muestras no se añaden como proyectos: las referencias tienen sus consumidores
específicos; las muestras están en `tests/fixtures/` y requieren `--dataset` explícito.
Los archivos institucionales son privados y están excluidos de Git.

Los lectores existentes admiten CSV, TSV, JSON y XLSX; los documentos DOCX/TXT/MD/PDF
requieren campos etiquetados e identidad explícita (PDF sin OCR). Un Excel con varias
hojas requiere configurar `sheet`. Un archivo inválido o ambiguo conserva su original
y sus diagnósticos; no se publica parcialmente como una incorporación exitosa.

Se reutilizan los aliases de `config/sources.yaml` (o `sources.example.yaml` cuando no
existe el archivo local). Las excepciones se declaran en `config/pipeline_manual.json`,
en `files`, por ruta relativa a `layer1_sources/`; se admiten patrones de nombres.
Dos reglas coincidentes se consideran ambiguas.

Ejemplo de configuración, sin datos institucionales ficticios:

```json
{
  "files": {
    "incoming/entrega_YYYYMMDD/proyectos.xlsx": {
      "domain": "proyectos",
      "sheet": "Proyectos",
      "mapping": {"source_project_id": "id_actividad"},
      "required_fields": ["source_project_id"],
      "text_columns": {
        "include": ["beneficiarios_comunidad"],
        "exclude": ["correo_contacto"]
      }
    }
  }
}
```

Este fragmento se integra en el archivo existente, conservando sus demás claves.
Para los nombres de columnas alternativos, `mapping` asocia el campo canónico con
una columna o lista de aliases. Los aliases contradictorios dejan evidencia y no
autorizan una fusión de identidades. `primary_id` puede indicar el identificador
canónico principal en el descubrimiento. No se inventan dominios ni IDs institucionales.

Las columnas desconocidas se conservan en `original_values`, con archivo, hoja, fila
y columna. En **incoming**, ninguna columna adicional se incorpora automáticamente
al corpus por su encabezado: requiere `text_columns.include`. Las exclusiones y los
controles de privacidad prevalecen incluso sobre un `include`. Los textos autorizados
forman secciones individuales `text__<columna>`; no cambian el contrato canónico ni el
Excel final.

El descubrimiento programático de solo lectura está en
`layer2_processing.preprocessing.adapters.discover_sources`; devuelve encabezados,
registros originales, procedencia, diagnóstico y estado. `READY_FOR_VALIDATION` no
equivale a publicación: el ETL existente valida duplicados, conflictos e identidades.
La operación existente `run_pipeline_manual.py raw` muestra un resumen sin valores
de las filas; `run --through knowledge` prepara una ejecución aislada sin LLM.

Los nuevos resultados quedan en `outputs/`: Capa 2 en `layer2_processing/`, GraphRAG
en `layer3_graphrag/` y evaluación en `layer4_evaluation/`. El coordinador mantiene
cada ejecución en `outputs/runs/<run_id>/`, con esas mismas carpetas dentro de
`workspace/outputs/`. Después de agregar fuentes o cambiar mappings, crear un run
nuevo; la reanudación comprueba los originales y los checkpoints previos.

Las publicaciones trasladadas conservan sus bytes y manifiestos. El registro existente
`config/sad_relocations.json` resuelve sus rutas históricas. `outputs/layer4/` conserva
cierres, autorizaciones y exportaciones históricas protegidas; no se han renombrado
sus manifiestos congelados. Los checkpoints antiguos mantienen su distribución local
cuando es necesaria para reanudarlos, siempre dentro de `outputs/`.
