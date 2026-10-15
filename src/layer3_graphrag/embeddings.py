"""Provider interface and lazy local adapter, fingerprints, reusable cache and checksummed embedding bundles."""

from abc import ABC, abstractmethod
import numpy as np
import json
import os
import time
from pathlib import Path
from uuid import uuid4
from .contracts import EmbeddingBundle, SPACES
from .provenance import digest, file_hash, serialize, stable_id, text_hash



# Provider-independent API; optional local adapter is loaded only on execution.
class EmbeddingProvider(ABC):
    model_name: str
    model_version: str
    dimensions: int
    batch_size: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError

    @abstractmethod
    def embed_queries(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError


class SentenceTransformersProvider(EmbeddingProvider):
    """Lazy optional adapter; local files only by default, no remote model code."""
    def __init__(self, settings):
        self.model_name = settings['model']
        self.model_version = settings['model_version']
        self.dimensions = settings['dimensions']
        self.batch_size = settings['batch_size']
        self.device = settings['device']
        self.allow_model_download = settings.get('allow_model_download', False)
        self.settings = dict(settings)
        import importlib.metadata
        self.runtime_fingerprint = {}
        for name in ('torch', 'sentence-transformers', 'transformers'):
            try:
                self.runtime_fingerprint[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                self.runtime_fingerprint[name] = 'not_installed'
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError('Optional sentence-transformers dependency is not installed') from exc
            import torch
            torch.manual_seed(0)
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
            dtype = getattr(torch, self.settings.get('dtype', 'float32'))
            location = self.settings.get('local_model_path', self.model_name)
            if self.settings.get('local_model_path'):
                from pathlib import Path
                root = Path(__file__).resolve().parents[2]
                path = (root / location).resolve()
                if not path.is_relative_to(root / 'outputs/layer3/models'):
                    raise ValueError('Local model must be inside official Layer 3 outputs')
                location = str(path)
                self.validate_model_files()
            self._model = SentenceTransformer(location, revision=self.model_version,
                device=self.device, local_files_only=not self.allow_model_download, trust_remote_code=False,
                model_kwargs={'torch_dtype': dtype, 'attn_implementation': 'sdpa'})
            if self.settings.get('max_seq_length'):
                self._model.max_seq_length = self.settings['max_seq_length']
            if next(self._model.parameters()).dtype != dtype:
                raise ValueError('Actual model dtype differs from recorded dtype')
            if self._model.get_sentence_embedding_dimension() != self.dimensions:
                self._model = None
                raise ValueError('Configured/model dimensions disagree')
        return self._model

    def validate_model_files(self):
        """Verify pinned local weights even when a full build uses only cached vectors."""
        if self.settings.get('weights_sha256'):
            from pathlib import Path
            from .provenance import file_hash
            root = Path(__file__).resolve().parents[2]
            location = (root / self.settings['local_model_path']).resolve()
            if not location.is_relative_to(root / 'outputs/layer3/models'):
                raise ValueError('Local model escapes official root')
            if file_hash(location / 'pytorch_model.bin') != self.settings['weights_sha256']:
                raise ValueError('Pinned local weights SHA-256 mismatch')

    def _encode(self, texts, kind):
        if not texts:
            return np.empty((0, self.dimensions), dtype=np.float32)
        model = self._load()
        lengths = model.tokenizer(texts, truncation=False, padding=False, return_length=True)['length']
        if any(n > model.max_seq_length for n in lengths):
            raise ValueError('Embedding input exceeds model limit; silent truncation forbidden')
        method = model.encode_document if kind == 'document' else model.encode_query
        return np.asarray(method(texts, batch_size=self.batch_size, convert_to_numpy=True,
                                 show_progress_bar=False, normalize_embeddings=False), dtype=np.float32)

    def embed_documents(self, texts):
        return self._encode(texts, 'document')

    def embed_queries(self, texts):
        return self._encode(texts, 'query')


def create_provider(settings):
    if settings.get('provider') != 'sentence_transformers':
        raise RuntimeError('Choose a provider before real embedding execution')
    if not settings.get('model') or not settings.get('model_version') or not settings.get('dimensions'):
        raise RuntimeError('Choose model, pinned model revision and dimensions before execution')
    revision = settings['model_version']
    if len(revision) not in (40, 64) or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('Real model_version must be an immutable commit/content hash')
    return SentenceTransformersProvider(settings)

# Separate spaces, deterministic cache and checksummed numeric embeddings.
def embedding_config_hash(settings, provider):
    return digest(settings | {'resolved_model': provider.model_name, 'resolved_model_version': provider.model_version,
                              'resolved_dimensions': provider.dimensions, 'encoding_api': 'document_query_v1', 'storage_dtype': 'float32',
                              'provider_runtime': getattr(provider, 'runtime_fingerprint', {})})


def cache_key(chunk, space, fingerprint):
    if space not in SPACES or chunk['chunk_hash'] != text_hash(chunk['text']):
        raise ValueError('Invalid embedding space or text hash')
    return digest({'text_hash': text_hash(chunk['text']), 'chunk_hash': chunk['chunk_hash'],
                   'source_space': space, 'embedding_config_hash': fingerprint})


def vector_hash(vector):
    values = np.asarray(vector, dtype='<f4')
    return __import__('hashlib').sha256(values.tobytes()).hexdigest()


def validate_vectors(values, count, dimensions, normalize=False):
    result = np.asarray(values, dtype=np.float32)
    if result.shape != (count, dimensions) or not np.isfinite(result).all():
        raise ValueError('Embedding shape/nonfinite error')
    if count:
        lengths = np.linalg.norm(result, axis=1)
        if (lengths <= 0).any():
            raise ValueError('Zero embedding vector')
        if normalize:
            result = result / lengths[:, None]
    return np.ascontiguousarray(result, dtype=np.float32)


class EmbeddingCache:
    def __init__(self, directory):
        self.directory = Path(directory)

    def get(self, key, dimensions):
        metadata = self.directory / (key + '.json')
        if not metadata.exists():
            return None
        meta = json.loads(metadata.read_text(encoding='utf-8'))
        path = self.directory / (key + '.npy')
        if meta.get('key') != key or meta.get('dimensions') != dimensions or file_hash(path) != meta.get('file_hash'):
            raise ValueError('Incompatible/corrupt embedding cache')
        vector = np.load(path, allow_pickle=False)
        validate_vectors(vector[None, :], 1, dimensions)
        if vector_hash(vector) != meta.get('embedding_hash'):
            raise ValueError('Cached embedding payload checksum mismatch')
        return vector

    def put(self, key, vector):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (key + '.npy')
        temporary = self.directory / (key + '.' + uuid4().hex + '.tmp')
        with temporary.open('wb') as stream:
            np.save(stream, np.asarray(vector, dtype=np.float32), allow_pickle=False)
        os.replace(temporary, path)
        meta = {'key': key, 'dimensions': len(vector), 'embedding_hash': vector_hash(vector), 'file_hash': file_hash(path)}
        temp_meta = temporary.with_suffix('.json.tmp')
        temp_meta.write_text(serialize(meta), encoding='utf-8')
        os.replace(temp_meta, self.directory / (key + '.json'))


def build_embeddings(snapshot, space, provider, settings, run_id, cache=None):
    if space not in SPACES:
        raise ValueError('Unknown embedding space')
    if provider.dimensions < 1 or provider.batch_size < 1:
        raise ValueError('Invalid embedding provider metadata')
    if any(settings.get(key) not in (None, value) for key, value in
           (('model', provider.model_name), ('model_version', provider.model_version), ('dimensions', provider.dimensions))):
        raise ValueError('Configured/provider embedding model fingerprint mismatch')
    chunks = sorted(snapshot.tables[space.lower() + '_chunks'], key=lambda row: row['chunk_id'])
    fingerprint = embedding_config_hash(settings, provider)
    vectors = np.empty((len(chunks), provider.dimensions), dtype=np.float32)
    missing, cache_hits = defaultdict_list(), 0
    for i, chunk in enumerate(chunks):
        key = cache_key(chunk, space, fingerprint)
        cached = cache.get(key, provider.dimensions) if cache else None
        if cached is None:
            missing.setdefault(key, []).append(i)
        else:
            vectors[i] = cached
            cache_hits += 1
    started = time.perf_counter()
    missing_keys = list(missing)
    for offset in range(0, len(missing_keys), provider.batch_size):
        if offset % max(provider.batch_size, 320) == 0:
            print('EMBEDDING_PROGRESS', space, offset, len(missing_keys), flush=True)
        batch = missing_keys[offset:offset + provider.batch_size]
        values = provider.embed_documents([chunks[missing[key][0]]['text'] for key in batch])
        values = validate_vectors(values, len(batch), provider.dimensions, settings['normalize_embeddings'])
        for key, vector in zip(batch, values):
            for i in missing[key]:
                vectors[i] = vector
            if cache:
                cache.put(key, vector)
    elapsed = time.perf_counter() - started
    vectors = validate_vectors(vectors, len(chunks), provider.dimensions)
    records = [{'embedding_id': stable_id('EMB', space, c['chunk_id'], fingerprint, c['chunk_hash']),
                'chunk_id': c['chunk_id'], 'source_space': space, 'model': provider.model_name,
                **{key: c[key] for key in ('section_id', 'document_id', 'source_id', 'source_type', 'field_name')},
                'embedding_model': provider.model_name, 'model_revision': provider.model_version,
                'normalized': settings['normalize_embeddings'],
                'model_version': provider.model_version, 'dimensions': provider.dimensions,
                'text_hash': text_hash(c['text']), 'chunk_hash': c['chunk_hash'],
                'embedding_hash': vector_hash(vectors[i]), 'embedding_config_hash': fingerprint,
                'layer3_run_id': run_id} for i, c in enumerate(chunks)]
    metadata = {'model': provider.model_name, 'model_version': provider.model_version, 'dimensions': provider.dimensions,
                'source_space': space, 'config_hash': fingerprint, 'embedding_config_hash': fingerprint,
                'normalize_embeddings': settings['normalize_embeddings'], 'layer2_manifest_hash': snapshot.manifest_hash,
                'cache_hits': cache_hits, 'computed_unique_texts': len(missing_keys), 'embedding_latency': elapsed}
    return EmbeddingBundle(records, vectors, metadata)


def defaultdict_list():
    # Normal dict preserves deterministic batch ordering, values are occurrence lists.
    return {}


def save_bundle(bundle, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'vectors.npy').open('wb') as stream:
        np.save(stream, bundle.vectors, allow_pickle=False)
    (directory / 'records.json').write_text(serialize(bundle.records), encoding='utf-8')
    metadata = bundle.metadata | {'file_hashes': {f: file_hash(directory / f) for f in ('vectors.npy', 'records.json')}}
    (directory / 'metadata.json').write_text(serialize(metadata), encoding='utf-8')


def load_bundle(directory):
    directory = Path(directory)
    meta = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
    for filename in ('vectors.npy', 'records.json'):
        if file_hash(directory / filename) != meta['file_hashes'][filename]:
            raise ValueError('Embedding bundle checksum mismatch')
    records = json.loads((directory / 'records.json').read_text(encoding='utf-8'))
    vectors = validate_vectors(np.load(directory / 'vectors.npy', allow_pickle=False), len(records), meta['dimensions'])
    if any(vector_hash(vectors[i]) != row['embedding_hash'] for i, row in enumerate(records)):
        raise ValueError('Embedding row checksum mismatch')
    return EmbeddingBundle(records, vectors, meta)


def reuse_bundle(directory, snapshot, space, provider, settings, run_id):
    """Reuse a checksummed published bundle only after exact content/config alignment."""
    bundle=load_bundle(directory)
    fingerprint=embedding_config_hash(settings,provider)
    chunks=sorted(snapshot.tables[space.lower()+'_chunks'],key=lambda r:r['chunk_id'])
    if bundle.metadata['embedding_config_hash']!=fingerprint or bundle.metadata['layer2_manifest_hash']!=snapshot.manifest_hash:
        return None
    if len(chunks)!=len(bundle.records) or any(r['chunk_id']!=c['chunk_id'] or r['chunk_hash']!=c['chunk_hash'] or r['text_hash']!=text_hash(c['text']) for r,c in zip(bundle.records,chunks)):
        return None
    bundle.records=[dict(r,layer3_run_id=run_id) for r in bundle.records]
    bundle.metadata.update(cache_hits=len(chunks),computed_unique_texts=0,embedding_latency=0.,reuse_origin='VERIFIED_PUBLICATION')
    return bundle
