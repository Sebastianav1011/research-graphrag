"""Provider-independent API; optional local adapter is loaded only on execution."""
from abc import ABC, abstractmethod

import numpy as np


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
