"""Pinned local Qwen tokenizer; calibrated template overhead, no model loaded."""
from functools import lru_cache
import hashlib
from pathlib import Path


@lru_cache(maxsize=2)
def load(path,digest,size,mtime):
    from tokenizers import Tokenizer
    if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise ValueError('TOKENIZER_CHANGED')
    return Tokenizer.from_file(path)


def count(prompt,descriptor):
    path=Path(descriptor['path']);stat=path.stat()
    tokenizer=load(str(path.resolve()),descriptor['sha256'],stat.st_size,stat.st_mtime_ns)
    return len(tokenizer.encode(prompt,add_special_tokens=False).ids)
