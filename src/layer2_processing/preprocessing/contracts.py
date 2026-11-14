"""One explicit type contract, shared by Parquet writers and JSON Schema generation."""
import pyarrow as pa

PROVENANCE = {
    "record_source": "string", "source_row": "integer", "source_record_id": "string",
    "etl_run_id": "string", "provenance_json": "string",
}
FIELDS = {
    "proyectos": dict.fromkeys(["project_id", "source_project_id", "title", "summary", "methodology",
        "objectives", "expected_results", "socioeconomic_objective", "knowledge_area",
        "knowledge_subarea", "start_date", "end_date"], "string") | {"keywords": "array"},
    "articulos": dict.fromkeys(["article_id", "source_article_id", "title", "abstract", "doi", "eid",
        "issn_isbn", "journal", "document_type"], "string") | {"publication_year": "integer", "keywords": "array"},
    "investigadores": dict.fromkeys(["researcher_id", "institutional_id", "document_type", "document_number",
        "external_id", "full_name", "normalized_name", "email", "identity_status", "identity_rule"], "string"),
    "organizaciones": dict.fromkeys(["organization_id", "organization_name", "organization_name_normalized",
        "organization_type", "parent_name", "country"], "string"),
    "proyecto_investigador": {"project_id": "string", "researcher_id": "string", "role": "string", "is_responsible": "boolean"},
    "articulo_investigador": {"article_id": "string", "researcher_id": "string", "author_position": "integer", "affiliation": "string"},
    "indicadores": dict.fromkeys(["indicator_id", "category", "dimension", "indicator_name",
        "indicator_description", "indicator_type"], "string"),
}
KEYS = {"proyectos": ["project_id"], "articulos": ["article_id"], "investigadores": ["researcher_id"],
        "organizaciones": ["organization_id"], "indicadores": ["indicator_id"],
        "proyecto_investigador": ["project_id", "researcher_id", "role", "is_responsible"],
        "articulo_investigador": ["article_id", "researcher_id", "author_position", "affiliation"]}
NON_NULL = {"proyectos": ["project_id", "source_project_id"],
            "articulos": ["article_id", "title"], "investigadores": ["researcher_id", "identity_status", "identity_rule"],
            "organizaciones": ["organization_id", "organization_name", "organization_name_normalized", "organization_type"],
            "indicadores": ["indicator_id", "indicator_name"],
            "proyecto_investigador": ["project_id", "researcher_id"],
            "articulo_investigador": ["article_id", "researcher_id"]}
FINAL_FIELDS = ["source_id", "source_type", "title", "indicator_id", "indicator_name",
                "indicator_category", "indicator_dimension", "evidence_text", "evidence_source_field",
                "evidence_explanation", "confidence_score", "confidence_level", "researcher_id",
                "researcher_name", "territory", "territory_type"]


def fields(dataset):
    return FIELDS[dataset] | PROVENANCE


def arrow_schema(dataset,*,allow_missing_title=False):
    types = {"string": pa.string(), "integer": pa.int64(), "boolean": pa.bool_(), "array": pa.list_(pa.string())}
    mandatory = NON_NULL[dataset] + ["record_source", "source_row", "etl_run_id", "provenance_json"]
    if dataset=='articulos' and allow_missing_title:mandatory=[f for f in mandatory if f!='title']
    return pa.schema([pa.field(k, types[t], nullable=k not in mandatory) for k, t in fields(dataset).items()])


def logical_schema(dataset,*,allow_missing_title=False):
    mandatory = NON_NULL[dataset] + ["record_source", "source_row", "etl_run_id", "provenance_json"]
    if dataset=='articulos' and allow_missing_title:mandatory=[f for f in mandatory if f!='title']
    properties = {}
    for field, kind in fields(dataset).items():
        prop = {"type": kind if field in mandatory else [kind, "null"]}
        if kind == "array":
            prop["items"] = {"type": "string"}
        if field in ("start_date", "end_date"):
            prop["format"] = "date"
        if field == "identity_status":
            prop["enum"] = ["resolved", "ambiguous", "unresolved"]
        properties[field] = prop
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": dataset,
            "type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}

