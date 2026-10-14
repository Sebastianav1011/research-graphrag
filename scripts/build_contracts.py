"""Build empty future-output template and machine-readable contracts; not an ETL stage."""
import csv
import json
import sys
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from layer1_data.contracts import FIELDS, FINAL_FIELDS, NON_NULL, PROVENANCE, fields, logical_schema

DESCRIPTIONS = {
    "project_id": "Clave canónica estable del proyecto",
    "source_project_id": "Identificador explícito del proyecto en la fuente",
    "article_id": "Clave canónica estable del artículo/producto",
    "source_article_id": "Identificador explícito de producción, si existe",
    "researcher_id": "Clave determinística de identidad o de ocurrencia no resuelta",
    "institutional_id": "Identificador institucional personal: id_empleado ≡ id_investigador; aliases compatibles; sensible",
    "document_type": "Tipo de documento personal en investigadores; tipo documental en artículos",
    "document_number": "Documento personal: cedula/documento/id_documento/numero_documento según mapping; distinto de institutional_id; sensible",
    "external_id": "Identificador externo configurado en un único espacio de nombres",
    "full_name": "Nombre de persona conservando mayúsculas y acentos",
    "normalized_name": "Nombre en Unicode NFC, espacios simples y casefold",
    "email": "Correo normalizado en minúsculas; sensible",
    "identity_status": "resolved: evidencia suficiente; ambiguous: candidatos múltiples/contradicción; unresolved: evidencia insuficiente",
    "identity_rule": "Regla determinística que justifica el estado",
    "title": "Título original; proyectos: miembros.titulo por id_actividad consistente; conflicto/ausencia NULL; nunca convocatoria",
    "summary": "Resumen textual original normalizado",
    "abstract": "Resumen/abstract de producción",
    "methodology": "Metodología textual proporcionada",
    "objectives": "Objetivos textuales proporcionados",
    "expected_results": "Resultados de investigación proporcionados; sin inferencia de cumplimiento",
    "keywords": "Lista de palabras clave separadas por delimitador configurado",
    "socioeconomic_objective": "Objetivo socioeconómico declarado",
    "knowledge_area": "Gran área declarada",
    "knowledge_subarea": "Área de conocimiento declarada",
    "start_date": "Fecha inicial ISO 8601",
    "end_date": "Fecha final ISO 8601",
    "doi": "DOI sin prefijo URL/doi y en minúsculas",
    "eid": "EID Scopus válido estructuralmente",
    "issn_isbn": "ISSN/ISBN sin guiones ni espacios; validación de forma, no de registro",
    "journal": "Revista o libro declarado",
    "publication_year": "Año de publicación entero dentro del rango configurado",
    "organization_id": "Hash del tipo, nombre normalizado, contexto y país",
    "organization_name": "Nombre explícito de organización",
    "organization_name_normalized": "Nombre institucional normalizado sin inferir equivalencias",
    "organization_type": "Tipo declarado en configuración del campo estructurado",
    "parent_name": "Nombre del contexto organizacional explícito, si existe",
    "country": "País estructurado opcional",
    "role": "Rol explícito de membresía",
    "is_responsible": "Booleano declarado; null si no interpretable",
    "author_position": "Posición explícita de autor; no se deduce del orden de filas",
    "affiliation": "Afiliación estructurada explícita de la relación",
    "indicator_id": "Código estable conservado del catálogo",
    "category": "Categoría literal del catálogo",
    "dimension": "Ámbito/dimensión literal o null",
    "indicator_name": "Texto oficial del indicador; no inventa una etiqueta abreviada",
    "indicator_description": "Descripción adicional si existe en la fuente",
    "indicator_type": "Tipo literal del catálogo",
    "record_source": "Ruta absoluta al archivo original de la primera ocurrencia",
    "source_row": "Primera línea física del registro CSV o fila Excel (base 1)",
    "source_record_id": "Identificador original cuando existe; opcional",
    "etl_run_id": "Identificador único de ejecución UTC; no es identidad de entidad",
    "provenance_json": "JSON con ocurrencias, hoja, originales, mapeos y soporte de enriquecimiento por llave explícita",
}


def final_schema():
    optional = {"indicator_dimension", "researcher_id", "researcher_name", "territory", "territory_type",
                "confidence_score", "confidence_level"}
    properties = {f: {"type": ["string", "null"] if f in optional else "string"} for f in FINAL_FIELDS}
    for f in set(FINAL_FIELDS) - optional:
        properties[f]["minLength"] = 1
    properties["confidence_score"] = {"type": ["number", "null"], "description": "Reserved; formula and scale not defined yet"}
    properties["source_type"] = {"enum": ["PROJECT", "ARTICLE"]}
    forbidden = ["graphrag", "llm", "embedding", "modelo", "ia", "openai"]
    alternatives = ["".join("[" + c + c.upper() + "]" for c in word) for word in forbidden]
    properties["evidence_source_field"]["not"] = {"pattern": r"^\s*(?:" + "|".join(alternatives) + r")\s*$"}
    row = {"type": "object", "additionalProperties": False, "required": FINAL_FIELDS, "properties": properties}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Future Layer 4 output, empty in Layer 1",
            "type": "object", "additionalProperties": False, "required": ["Proyectos", "Artículos"],
            "properties": {
                "Proyectos": {"type": "array", "items": {"allOf": [row, {"properties": {
                    "source_type": {"const": "PROJECT"}, "source_id": {"pattern": "^PROJ_"}}}]}},
                "Artículos": {"type": "array", "items": {"allOf": [row, {"properties": {
                    "source_type": {"const": "ARTICLE"}, "source_id": {"pattern": "^ART_"}}}]}},
            }}


def main():
    names = {"proyectos": "proyecto", "articulos": "articulo", "investigadores": "investigador",
             "indicadores": "indicador", "organizaciones": "organizacion"}
    for dataset, filename in names.items():
        (ROOT / "schemas" / (filename + ".schema.json")).write_text(
            json.dumps(logical_schema(dataset), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    relations = {"$schema": "https://json-schema.org/draft/2020-12/schema",
                 "oneOf": [logical_schema(d) for d in ("proyecto_investigador", "articulo_investigador")]}
    (ROOT / "schemas/relationships.schema.json").write_text(json.dumps(relations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "schemas/final_output.schema.json").write_text(json.dumps(final_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (ROOT / "docs/data_dictionary/data_dictionary.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["dataset", "field", "type", "nullable", "description", "source", "transformation"])
        writer.writeheader()
        for dataset in FIELDS:
            for field, kind in fields(dataset).items():
                nullable = field not in NON_NULL[dataset] + ["record_source", "source_row", "etl_run_id", "provenance_json"]
                writer.writerow({"dataset": dataset, "field": field, "type": kind, "nullable": str(nullable).lower(),
                                 "description": DESCRIPTIONS[field], "source": "config/sources.yaml; provenance_json.field_mapping",
                                 "transformation": "provenance.py" if field in PROVENANCE else
                                 ("identity.py" if dataset == "investigadores" else "normalize.py; canonicalize.py")})
    book = Workbook()
    book.remove(book.active)
    for sheet_name, source_type in (("Proyectos", "PROJECT"), ("Artículos", "ARTICLE")):
        sheet = book.create_sheet(sheet_name)
        sheet.append(FINAL_FIELDS)
        sheet.freeze_panes = "D2"
        sheet.auto_filter.ref = "A1:P1"
        sheet.sheet_view.showGridLines = False
        sheet.row_dimensions[1].height = 34
        for column, field in enumerate(FINAL_FIELDS, 1):
            cell = sheet.cell(1, column)
            cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="17365D" if column <= 7 else "27636B")
            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            sheet.column_dimensions[get_column_letter(column)].width = max(20, min(32, len(field) + 3))
        validation = DataValidation(type="list", formula1='"' + source_type + '"', allow_blank=False)
        validation.errorTitle = "Tipo de fuente inválido"
        validation.error = "Utilice el tipo correspondiente a esta hoja."
        validation.showErrorMessage = True
        validation.errorStyle = "stop"
        sheet.add_data_validation(validation)
        validation.add("B2:B1048576")
    destination = ROOT / "templates/resultado_final_indicadores.xlsx"
    book.save(destination)
    check = load_workbook(destination, read_only=True)
    assert check.sheetnames == ["Proyectos", "Artículos"]
    for sheet in check:
        assert sheet.max_row == 1 and sheet.max_column == 16
        assert list(next(sheet.values)) == FINAL_FIELDS
    check.close()
    print("Contracts generated; empty template verified (2 sheets, 16 columns, zero data rows)")


if __name__ == "__main__":
    main()
