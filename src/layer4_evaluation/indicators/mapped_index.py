"""Bounded-memory read access to a published exact NumPy index (evaluation side).

Lives outside the Knowledge code (src/layer3_graphrag/ is part of the sealed Knowledge
fingerprint), so reading an index this way never invalidates an existing Knowledge
version. Same published files and the same integrity checks as
NumpyVectorIndex.load(); nothing is copied, converted or rewritten.
"""
import json
from hashlib import sha256
from pathlib import Path

import numpy as np

from layer3_graphrag.vector_index import FINGERPRINT_FIELDS, NumpyVectorIndex, _json_bytes


def open_mapped(path: str | Path, expected_metadata: dict | None = None,
                block_rows: int = 4096) -> "NumpyVectorIndex":
    """Same published index and checks as load(), without holding the matrix in RAM.

    The original float64 file is never copied, converted or rewritten. One sequential
    pass streams its SHA-256 and validates finiteness and unit norms block by block
    (bounded memory); afterwards a read-only numpy.memmap serves only the rows that
    callers score.
    """
    target = Path(path)
    payload = json.loads((target / "index.json").read_text(encoding="utf-8"))
    checksum = payload.pop("payload_sha256", None)
    if checksum != sha256(_json_bytes(payload)).hexdigest():
        raise ValueError("Index metadata checksum mismatch")
    if payload.get("format_version") != 1 or payload.get("backend") != "numpy_exact":
        raise ValueError("Unsupported index format")
    metadata = payload["metadata"]
    for key, value in (expected_metadata or {}).items():
        if metadata.get(key) != value:
            raise ValueError(f"Index incompatible with requested metadata: {key}")
    dimensions = metadata.get("dimensions")
    if not isinstance(dimensions, int) or isinstance(dimensions, bool) or dimensions <= 0:
        raise ValueError("dimensions must be a positive integer")
    index = NumpyVectorIndex(payload["source_space"], metadata)
    if metadata.get("source_space", index.space) != index.space:
        raise ValueError("Metadata space mismatch")
    index.records = payload["records"]
    vectors_path = target / "vectors.npy"
    digest = sha256()
    with vectors_path.open("rb") as stream:
        version = np.lib.format.read_magic(stream)
        reader = (np.lib.format.read_array_header_1_0 if version == (1, 0)
                  else np.lib.format.read_array_header_2_0)
        shape, fortran, dtype = reader(stream)
        header_end = stream.tell()
        stream.seek(0)
        digest.update(stream.read(header_end))
        if (len(shape) != 2 or tuple(shape) != (len(index.records), dimensions) or fortran
                or dtype != np.dtype(np.float64)):
            raise ValueError("Invalid index dimensions")
        row_bytes = dimensions * dtype.itemsize
        while True:
            data = stream.read(block_rows * row_bytes)
            if not data:
                break
            digest.update(data)
            if len(data) % row_bytes:
                raise ValueError("Truncated index matrix")
            block = np.frombuffer(data, dtype=dtype).reshape(-1, dimensions)
            if not np.isfinite(block).all() or not np.allclose(np.linalg.norm(block, axis=1), 1.0, atol=1e-9):
                raise ValueError("Index vectors must be finite with unit norm")
    if digest.hexdigest() != payload["vectors_sha256"]:
        raise ValueError("Index matrix checksum mismatch")
    vectors = np.load(vectors_path, mmap_mode="r", allow_pickle=False)
    if vectors.shape != (len(index.records), dimensions):
        raise ValueError("Invalid index dimensions")
    index.vectors = vectors
    # Fingerprint, space and record identity checks of validate(), without a full matrix scan.
    if any(key not in metadata or metadata[key] in (None, "") for key in FINGERPRINT_FIELDS):
        raise ValueError("Incomplete embedding fingerprint")
    for field in ("chunk_id", "embedding_id"):
        values = [record.get(field) for record in index.records]
        if any(not isinstance(value, str) or not value for value in values) or len(set(values)) != len(values):
            raise ValueError(f"Missing or duplicate {field}")
    for record in index.records:
        if record.get("source_space") != index.space:
            raise ValueError("Embedding record crosses source spaces")
        for key in ("model", "model_version", "dimensions"):
            if record.get(key) != metadata[key]:
                raise ValueError(f"Embedding record fingerprint mismatch: {key}")
        if record.get("embedding_config_hash", metadata["config_hash"]) != metadata["config_hash"]:
            raise ValueError("Embedding record configuration mismatch")
    return index
