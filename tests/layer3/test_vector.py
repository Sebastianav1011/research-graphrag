"""Local in-memory fixtures only; no corpus or embeddings are published."""
from types import SimpleNamespace
import json
import numpy as np
import pytest

from src.layer3_graphrag.vector_index import NumpyVectorIndex, create_vector_index
from src.layer3_graphrag.vector_retriever import VectorRetriever


def bundle(space="SOURCE", vectors=None):
    metadata = dict(model="test", model_version="1", dimensions=2, config_hash="cfg")
    records = [dict(chunk_id=chunk, embedding_id="emb-"+chunk, source_space=space,
                    model="test", model_version="1", dimensions=2) for chunk in ("z", "a", "b")]
    return SimpleNamespace(metadata=metadata, records=records,
                           vectors=np.array([[2, 0], [1, 0], [0, 1]]) if vectors is None else vectors)


def index():
    result = NumpyVectorIndex("SOURCE")
    result.build(bundle())
    return result


def test_exact_cosine_and_deterministic_ties():
    hits = index().search([3, 0], 5)
    assert [h["chunk_id"] for h in hits] == ["a", "z", "b"]
    assert [h["rank"] for h in hits] == [1, 2, 3]
    assert [h["score"] for h in hits] == [1, 1, 0]


@pytest.mark.parametrize("vector", [[0, 0], [float("nan"), 1], [float("inf"), 1], [1, 2, 3]])
def test_invalid_query_embeddings_rejected(vector):
    with pytest.raises(ValueError):
        index().search(vector, 2)


@pytest.mark.parametrize("vectors", [np.zeros((3, 2)), np.ones((2, 2)), np.full((3, 2), np.nan)])
def test_bad_build_does_not_replace_existing_index(vectors):
    result = index()
    with pytest.raises(ValueError):
        result.build(bundle(vectors=vectors))
    assert result.search([1, 0], 1)[0]["chunk_id"] == "a"


def test_cross_space_duplicate_and_fingerprint_rejected():
    item = bundle()
    item.records[0]["source_space"] = "REFERENCE"
    with pytest.raises(ValueError, match="space"):
        NumpyVectorIndex("SOURCE").build(item)
    item = bundle()
    item.records[0]["chunk_id"] = "a"
    with pytest.raises(ValueError, match="duplicate"):
        NumpyVectorIndex("SOURCE").build(item)
    item = bundle()
    item.records[0]["model_version"] = "2"
    with pytest.raises(ValueError, match="fingerprint"):
        NumpyVectorIndex("SOURCE").build(item)


def test_bundle_metadata_space_and_record_config_must_match():
    item = bundle()
    item.metadata["source_space"] = "REFERENCE"
    with pytest.raises(ValueError, match="space"):
        NumpyVectorIndex("SOURCE").build(item)
    item = bundle()
    item.records[0]["embedding_config_hash"] = "other-config"
    with pytest.raises(ValueError, match="configuration"):
        NumpyVectorIndex("SOURCE").build(item)


def test_save_load_roundtrip_and_compatibility(tmp_path):
    result = index()
    result.save(tmp_path)
    loaded = NumpyVectorIndex.load(tmp_path, {"config_hash": "cfg", "model_version": "1"})
    assert loaded.search([1, 0], 3) == result.search([1, 0], 3)
    with pytest.raises(ValueError, match="incompatible"):
        NumpyVectorIndex.load(tmp_path, {"config_hash": "other"})


def test_corrupt_matrix_and_metadata_are_rejected(tmp_path):
    result = index()
    result.save(tmp_path)
    with (tmp_path/"vectors.npy").open("ab") as stream:
        stream.write(b"corruption")
    with pytest.raises(ValueError, match="matrix checksum"):
        NumpyVectorIndex.load(tmp_path)
    result.save(tmp_path)
    payload = json.loads((tmp_path/"index.json").read_text())
    payload["records"][0]["chunk_id"] = "changed"
    (tmp_path/"index.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="metadata checksum"):
        NumpyVectorIndex.load(tmp_path)


class Provider:
    model_name = "test"
    model_version = "1"
    dimensions = 2
    def embed_queries(self, texts):
        return np.array([[1, 0] for _ in texts])


def snapshot():
    chunks = [dict(chunk_id=chunk, section_id="section", document_id="document", source_id="src",
                   source_type="PROJECT", field_name="abstract", text="fixture",
                   provenance_json='{"source_row": 1}') for chunk in ("a", "b", "z")]
    return SimpleNamespace(tables={"source_chunks": chunks,
                                  "source_sections": [dict(section_id="section", document_id="document")],
                                  "source_documents": [dict(document_id="document")]},
                           manifest_hash="manifest", manifest={"layer2_run_id": "run2"})


def test_vector_retrieval_preserves_provenance_and_latency():
    retriever = VectorRetriever(index(), Provider(), snapshot())
    hit = retriever.retrieve("consulta", 1)[0]
    assert hit["source_id"] == "src"
    assert hit["section_id"] == "section"
    assert hit["provenance_json"] == '{"source_row": 1}'
    assert hit["source_space"] == "SOURCE"
    assert hit["graph_distance"] is None
    assert hit["is_discovery_chunk"] is True
    assert retriever.last_metrics["embedding_latency_ms"] >= 0


def test_retriever_rejects_wrong_provider_snapshot_and_broken_links():
    provider = Provider()
    provider.model_version = "2"
    with pytest.raises(ValueError, match="Provider"):
        VectorRetriever(index(), provider, snapshot())
    result = index()
    result.metadata["layer2_manifest_hash"] = "old"
    with pytest.raises(ValueError, match="snapshot"):
        VectorRetriever(result, Provider(), snapshot())
    snap = snapshot()
    snap.tables["source_sections"] = []
    with pytest.raises(ValueError, match="provenance"):
        VectorRetriever(index(), Provider(), snap).retrieve("q", 1)


def test_reference_space_is_distinct_and_not_evidence():
    result = NumpyVectorIndex("REFERENCE")
    result.build(bundle("REFERENCE"))
    snap = snapshot()
    snap.tables = {key.replace("source_", "reference_"): value for key, value in snap.tables.items()}
    with pytest.raises(ValueError, match="space"):
        VectorRetriever(result, Provider(), snap)
    retriever = VectorRetriever(result, Provider(), snap, "REFERENCE")
    assert retriever.retrieve("q", 1)[0]["is_discovery_chunk"] is False


def test_backend_selection_is_explicit():
    assert isinstance(create_vector_index("numpy_exact", "SOURCE"), NumpyVectorIndex)
    with pytest.raises(ValueError):
        create_vector_index("external", "SOURCE")
