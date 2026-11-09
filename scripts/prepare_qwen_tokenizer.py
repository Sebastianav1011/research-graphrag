"""Download only the pinned tokenizer, never model weights or inference."""
import hashlib
import json
from pathlib import Path
from huggingface_hub import hf_hub_download

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    config=json.loads((ROOT/'config/qwen_tokenizer.json').read_text(encoding='utf-8'))
    path=Path(hf_hub_download(config['repository'],'tokenizer.json',revision=config['revision'],token=False,
                            local_dir=str((ROOT/config['path']).parent)))
    if hashlib.sha256(path.read_bytes()).hexdigest()!=config['sha256']:raise ValueError('Tokenizer SHA256 mismatch')
    print('Tokenizer verificado; sin pesos, dependencias adicionales ni inferencias: '+str(path))
