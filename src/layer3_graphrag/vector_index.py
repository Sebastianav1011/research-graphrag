"""Provider independent indexes; exact cosine is the reproducible local backend."""
from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import numpy as np


FINGERPRINT_FIELDS = ("model", "model_version", "dimensions", "config_hash")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


class VectorIndex(ABC):
    @abstractmethod
    def build(self, bundle: Any) -> None: ...

    @abstractmethod
    def search(self, query_vector: Any, top_k: int) -> list[dict]: ...

    @abstractmethod
    def save(self, path: str | Path) -> None: ...

    @classmethod
    @abstractmethod
    def load(cls, path: str | Path, expected_metadata: dict | None = None) -> "VectorIndex": ...

    @abstractmethod
    def validate(self) -> dict: ...


class NumpyVectorIndex(VectorIndex):
    """One explicit SOURCE or REFERENCE space; normalized exact cosine search.

    Storage contains JSON metadata/records and a non-pickle NumPy matrix. Load
    verifies hashes and can require the caller's expected embedding fingerprint.
    """
    def __init__(self, space: str, metadata: dict | None = None):
        if space not in {"SOURCE", "REFERENCE"}:
            raise ValueError("Index space must be SOURCE or REFERENCE")
        self.space = space
        self.metadata = dict(metadata or {})
        self.records: list[dict] = []
        self.vectors = np.empty((0, 0), dtype=np.float64)

    def build(self, bundle: Any) -> None:
        metadata = dict(bundle.metadata)
        if metadata.get("source_space", self.space) != self.space:
            raise ValueError("Bundle metadata space mismatch")
        for key, value in self.metadata.items():
            if key in metadata and metadata[key] != value:
                raise ValueError(f"Incompatible index metadata: {key}")
        metadata = {**metadata, **self.metadata, "source_space": self.space}
        if any(key not in metadata or metadata[key] in (None, "") for key in FINGERPRINT_FIELDS):
            raise ValueError("Complete embedding fingerprint required")
        vectors = np.asarray(bundle.vectors, dtype=np.float64)
        records = [dict(record) for record in bundle.records]
        if vectors.ndim != 2 or vectors.shape != (len(records), metadata["dimensions"]):
            raise ValueError("Embedding matrix dimensions do not match records/metadata")
        if not np.isfinite(vectors).all():
            raise ValueError("Non-finite embedding values")
        norms = np.linalg.norm(vectors, axis=1)
        if np.any(~np.isfinite(norms)) or np.any(norms <= 0):
            raise ValueError("Zero or invalid embedding norm")
        # Check in an isolated candidate; unsuccessful builds leave this index intact.
        candidate = NumpyVectorIndex(self.space, metadata)
        candidate.records = records
        candidate.vectors = vectors / norms[:, None]
        candidate.validate()
        self.records, self.vectors, self.metadata = records, candidate.vectors, metadata

    def validate(self) -> dict:
        if any(key not in self.metadata or self.metadata[key] in (None, "") for key in FINGERPRINT_FIELDS):
            raise ValueError("Incomplete embedding fingerprint")
        dimensions = self.metadata["dimensions"]
        if not isinstance(dimensions, int) or isinstance(dimensions, bool) or dimensions <= 0:
            raise ValueError("dimensions must be a positive integer")
        if self.metadata.get("source_space", self.space) != self.space:
            raise ValueError("Metadata space mismatch")
        if self.vectors.ndim != 2 or self.vectors.shape != (len(self.records), dimensions):
            raise ValueError("Invalid index dimensions")
        if not np.isfinite(self.vectors).all():
            raise ValueError("Non-finite index values")
        if len(self.vectors) and not np.allclose(np.linalg.norm(self.vectors, axis=1), 1.0, atol=1e-9):
            raise ValueError("Index vectors must have unit norm")
        for field in ("chunk_id", "embedding_id"):
            values = [record.get(field) for record in self.records]
            if any(not isinstance(value, str) or not value for value in values) or len(set(values)) != len(values):
                raise ValueError(f"Missing or duplicate {field}")
        for record in self.records:
            if record.get("source_space") != self.space:
                raise ValueError("Embedding record crosses source spaces")
            for key in ("model", "model_version", "dimensions"):
                if record.get(key) != self.metadata[key]:
                    raise ValueError(f"Embedding record fingerprint mismatch: {key}")
            if record.get("embedding_config_hash", self.metadata["config_hash"]) != self.metadata["config_hash"]:
                raise ValueError("Embedding record configuration mismatch")
        return {"valid": True, "backend": "numpy_exact", "source_space": self.space,
                "embedding_count": len(self.records), "dimensions": dimensions}

    def search(self, query_vector: Any, top_k: int) -> list[dict]:
        self.validate()
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        query = np.asarray(query_vector, dtype=np.float64)
        if query.ndim != 1 or query.shape[0] != self.metadata["dimensions"]:
            raise ValueError("Query dimensions incompatible with index")
        norm = np.linalg.norm(query)
        if not np.isfinite(query).all() or not np.isfinite(norm) or norm <= 0:
            raise ValueError("Query embedding must be finite and nonzero")
        scores = np.clip(self.vectors @ (query / norm), -1.0, 1.0)
        order = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), self.records[i]["chunk_id"]))
        return [{"chunk_id": self.records[i]["chunk_id"], "embedding_id": self.records[i]["embedding_id"],
                 "score": float(scores[i]), "rank": rank, "source_space": self.space}
                for rank, i in enumerate(order[:top_k], 1)]

    def save(self, path: str | Path) -> None:
        self.validate()
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        vectors_path = target / "vectors.npy"
        np.save(vectors_path, self.vectors, allow_pickle=False)
        payload = {"format_version": 1, "backend": "numpy_exact", "source_space": self.space,
                   "metadata": self.metadata, "records": self.records,
                   "vectors_sha256": sha256(vectors_path.read_bytes()).hexdigest()}
        payload["payload_sha256"] = sha256(_json_bytes(payload)).hexdigest()
        (target / "index.json").write_bytes(_json_bytes(payload))

    @classmethod
    def load(cls, path: str | Path, expected_metadata: dict | None = None) -> "NumpyVectorIndex":
        target = Path(path)
        payload = json.loads((target / "index.json").read_text(encoding="utf-8"))
        checksum = payload.pop("payload_sha256", None)
        if checksum != sha256(_json_bytes(payload)).hexdigest():
            raise ValueError("Index metadata checksum mismatch")
        if payload.get("format_version") != 1 or payload.get("backend") != "numpy_exact":
            raise ValueError("Unsupported index format")
        vectors_path = target / "vectors.npy"
        if sha256(vectors_path.read_bytes()).hexdigest() != payload["vectors_sha256"]:
            raise ValueError("Index matrix checksum mismatch")
        metadata = payload["metadata"]
        for key, value in (expected_metadata or {}).items():
            if metadata.get(key) != value:
                raise ValueError(f"Index incompatible with requested metadata: {key}")
        index = cls(payload["source_space"], metadata)
        index.records = payload["records"]
        index.vectors = np.load(vectors_path, allow_pickle=False)
        index.validate()
        return index


def create_vector_index(backend: str, space: str) -> VectorIndex:
    if backend != "numpy_exact":
        raise ValueError(f"Unsupported vector backend: {backend}")
    return NumpyVectorIndex(space)
