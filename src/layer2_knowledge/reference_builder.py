"""Indicator descriptions are reference knowledge, never evidence of compliance."""
from .document_builder import build_documents
from .section_builder import build_sections, normalize_sections
from .chunking import build_chunks


def build_reference(datasets, config, context):
    documents = build_documents(datasets, config, context, reference=True)
    sections = normalize_sections(build_sections(documents, datasets, config, context), config)
    return documents, sections, build_chunks(sections, config, context)
