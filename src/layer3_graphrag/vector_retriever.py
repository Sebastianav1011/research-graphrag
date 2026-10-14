"""Retrieve within a single knowledge space, retaining Layer 2 provenance."""
from __future__ import annotations

from time import perf_counter
from typing import Any
import numpy as np


class VectorRetriever:
    def __init__(self, index: Any, provider: Any, snapshot: Any, space: str = "SOURCE"):
        if space not in {"SOURCE", "REFERENCE"} or index.space != space:
            raise ValueError("Retriever/index source space mismatch")
        self.index, self.provider, self.snapshot, self.space = index, provider, snapshot, space
        self.last_metrics: dict = {}
        prefix = "source" if space == "SOURCE" else "reference"
        self.chunks = {r["chunk_id"]: r for r in snapshot.tables[f"{prefix}_chunks"]}
        if len(self.chunks) != len(snapshot.tables[f"{prefix}_chunks"]):
            raise ValueError("Duplicate chunk IDs in knowledge snapshot")
        self.sections = {r["section_id"]: r for r in snapshot.tables[f"{prefix}_sections"]}
        self.documents = {r["document_id"]: r for r in snapshot.tables[f"{prefix}_documents"]}
        self._validate_compatibility()

    def _validate_compatibility(self) -> None:
        self.index.validate()
        for field, attr in (("model", "model_name"), ("model_version", "model_version"),
                            ("dimensions", "dimensions")):
            if self.index.metadata.get(field) != getattr(self.provider, attr):
                raise ValueError(f"Provider/index incompatibility: {field}")
        expected_hash = self.index.metadata.get("layer2_manifest_hash")
        if expected_hash is not None and expected_hash != self.snapshot.manifest_hash:
            raise ValueError("Index belongs to a different Layer 2 snapshot")
        for record in self.index.records:
            chunk = self.chunks.get(record["chunk_id"])
            if chunk is None:
                raise ValueError("Index references missing chunk")
            if record.get("chunk_hash") is not None and record["chunk_hash"] != chunk.get("chunk_hash"):
                raise ValueError("Index references changed chunk")

    def retrieve(self, query_text: str, top_k: int) -> list[dict]:
        if not isinstance(query_text, str) or not query_text.strip():
            raise ValueError("Nonempty query text required")
        self._validate_compatibility()
        start = perf_counter()
        vectors = np.asarray(self.provider.embed_queries([query_text]))
        if vectors.shape != (1, self.provider.dimensions):
            raise ValueError("Query provider returned an invalid matrix")
        embedded = perf_counter()
        hits = self.index.search(vectors[0], top_k)
        searched = perf_counter()
        results = []
        for hit in hits:
            chunk = self.chunks[hit["chunk_id"]]
            section = self.sections.get(chunk.get("section_id"))
            document = self.documents.get(chunk.get("document_id"))
            if section is None or document is None or section.get("document_id") != chunk.get("document_id"):
                raise ValueError("Broken chunk → section → document provenance")
            if not chunk.get("provenance_json"):
                raise ValueError("Missing retrieval provenance")
            results.append({**{key: chunk.get(key) for key in (
                "chunk_id", "source_id", "source_type", "field_name", "document_id", "section_id", "text",
                "provenance_json")}, **hit, "vector_score": hit["score"], "graph_distance": None,
                "structured_relation_strength": 0.0, "layer2_manifest_hash": self.snapshot.manifest_hash,
                "layer2_run_id": self.snapshot.manifest.get("layer2_run_id"),
                "layer1_run_id": self.snapshot.manifest.get("layer1_run_id"),
                "layer1_manifest_hash": self.snapshot.manifest.get("layer1_manifest_hash"),
                "is_discovery_chunk": self.space == "SOURCE"})
        self.last_metrics = {"embedding_latency_ms": (embedded-start)*1000,
                             "vector_search_latency_ms": (searched-embedded)*1000,
                             "total_retrieval_latency_ms": (perf_counter()-start)*1000}
        return results
