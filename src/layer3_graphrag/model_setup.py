"""Pinned local dense BGE-M3 download, full token census and measured GPU batch."""
import os
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['HF_HUB_DISABLE_XET'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
import json
import ssl
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
import yaml
from huggingface_hub import snapshot_download
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from .provenance import file_hash
from .embeddings import SentenceTransformersProvider

REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
REPORTS = ROOT / 'outputs/layer3/reports'


def ps(script):
    return json.loads(subprocess.check_output(['powershell', '-NoProfile', '-Command', script + ' | ConvertTo-Json -Compress'], text=True))


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    approved = json.loads((REPORTS/'input_validation.json').read_text(encoding='utf-8'))
    original_manifest_hash = approved['layer2_manifest_hash']
    if file_hash(ROOT/'outputs/layer2/knowledge/_manifest.json') != original_manifest_hash:
        raise RuntimeError('Manifest changed since physical approval; aborting')
    # Honor Windows' trusted CA store (e.g. local HTTPS inspection), never disable TLS.
    import certifi
    ca_bundle = REPORTS / 'download_trusted_ca.pem'
    ca_bundle.write_text(Path(certifi.where()).read_text(encoding='ascii') + '\n' +
        '\n'.join(ssl.DER_cert_to_PEM_cert(cert) for cert in ssl.create_default_context().get_ca_certs(binary_form=True)),
        encoding='ascii')
    os.environ['REQUESTS_CA_BUNDLE'] = str(ca_bundle)
    hardware = {'cpu': ps('Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors'),
        'ram': ps('Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory'),
        'cuda_available': torch.cuda.is_available(), 'torch': torch.__version__, 'cuda_runtime': torch.version.cuda}
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable; local BGE-M3 GPU execution needs review')
    properties = torch.cuda.get_device_properties(0)
    hardware.update(gpu=properties.name, vram_bytes=properties.total_memory,
        cuda_free_bytes=torch.cuda.mem_get_info()[0], dtype='float16', device='cuda')
    (REPORTS / 'hardware.json').write_text(json.dumps(hardware, indent=2), encoding='utf-8')
    model_dir = ROOT / 'outputs/layer3/models/bge-m3' / REVISION
    print('DOWNLOADING_PINNED_LOCAL_MODEL', REVISION, flush=True)
    snapshot_download('BAAI/bge-m3', revision=REVISION, local_dir=model_dir,
        allow_patterns=['config.json', 'config_sentence_transformers.json', 'modules.json',
            '1_Pooling/config.json', 'sentence_bert_config.json',
            'sentencepiece.bpe.model', 'special_tokens_map.json', 'tokenizer.json', 'tokenizer_config.json'], max_workers=2)
    download_weights(model_dir)
    if file_hash(ROOT/'outputs/layer2/knowledge/_manifest.json') != original_manifest_hash:
        raise RuntimeError('Manifest changed while obtaining model; aborting')
    (REPORTS / 'model_files.json').write_text(json.dumps({p.relative_to(model_dir).as_posix(): file_hash(p)
        for p in model_dir.rglob('*') if p.is_file() and '.cache' not in p.parts and not any('download_parts' in x for x in p.parts)}, indent=2), encoding='utf-8')
    # Download is complete; all subsequent inference is local and offline.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    settings = {'model': 'BAAI/bge-m3', 'model_version': REVISION, 'dimensions': 1024,
        'batch_size': 1, 'device': 'cuda', 'dtype': 'float16', 'max_seq_length': 8192,
        'local_model_path': str(model_dir), 'allow_model_download': False,
        'weights_sha256': 'b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38'}
    provider = SentenceTransformersProvider(settings)
    print('LOADING_LOCAL_DENSE_MODEL', flush=True)
    model = provider._load()
    if next(model.parameters()).dtype != torch.float16:
        raise RuntimeError('Actual model dtype does not match calibrated float16 configuration')
    census, all_texts, all_lengths = {}, [], []
    expected = json.loads((ROOT / 'outputs/layer2/knowledge/_manifest.json').read_text(encoding='utf-8'))
    manifest_hash = file_hash(ROOT / 'outputs/layer2/knowledge/_manifest.json')
    if manifest_hash != original_manifest_hash:
        raise RuntimeError('Manifest changed during local model preparation; aborting')
    for space in ('SOURCE', 'REFERENCE'):
        path = ROOT / ('outputs/layer2/knowledge/' + space.lower() + '_chunks.parquet')
        if file_hash(path) != expected['output_hashes'][space.lower() + '_chunks']:
            raise RuntimeError('Approved chunks changed')
        texts = pq.read_table(path, columns=['text']).column('text').to_pylist()
        lengths = []
        for offset in range(0, len(texts), 256):
            lengths.extend(model.tokenizer(texts[offset:offset+256], padding=False, truncation=False,
                return_length=True)['length'])
        census[space] = {'count': len(lengths), 'min': min(lengths), 'max': max(lengths),
            **{f'p{p}': float(np.percentile(lengths, p)) for p in (50, 90, 95, 99)},
            'chunks_above_model_limit': sum(n > 8192 for n in lengths)}
        all_texts.extend(texts)
        all_lengths.extend(lengths)
    (REPORTS / 'token_profile.json').write_text(json.dumps(census, indent=2), encoding='utf-8')
    print('TOKEN_CENSUS', json.dumps(census), flush=True)
    if any(row['chunks_above_model_limit'] for row in census.values()):
        raise RuntimeError('Over-limit inputs require explicit strategy; no rechunking/truncation')
    longest = all_texts[int(np.argmax(all_lengths))]
    measurements, selected = [], None
    for batch in (1, 2, 4, 8, 16, 32, 64, 128, 256):
        provider.batch_size = batch
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        try:
            result = provider.embed_documents([longest] * batch)
            torch.cuda.synchronize()
            free, total = torch.cuda.mem_get_info()
            peak = torch.cuda.max_memory_allocated()
            row = {'batch_size': batch, 'peak_allocated_bytes': peak, 'free_bytes_after': free,
                'seconds': time.perf_counter()-started, 'shape': list(result.shape),
                'safe': peak < total * .8 and free >= 1024**3}
            if row['safe']:
                selected = batch
            measurements.append(row)
            print('BATCH_CALIBRATION', json.dumps(row), flush=True)
            if not row['safe']:
                break
        except torch.cuda.OutOfMemoryError:
            measurements.append({'batch_size': batch, 'safe': False, 'error': 'CUDA_OUT_OF_MEMORY'})
            torch.cuda.empty_cache()
            break
    if selected is None:
        raise RuntimeError('No safe GPU batch fits with memory headroom')
    calibration = {'batch_size': selected, 'policy': 'Largest tested batch with >=1GiB free and peak <80% total VRAM, longest real chunk',
        'measurements': measurements, 'max_tokens': max(all_lengths)}
    (REPORTS / 'batch_calibration.json').write_text(json.dumps(calibration, indent=2), encoding='utf-8')
    config_path = ROOT / 'config/layer3.yaml'
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    config['readiness'] = {'layer2_status': 'FINAL_PROJECT_LAYER_2_READY',
        'approved_layer2_manifest_sha256': manifest_hash}
    config['execution']['allow_real_build'] = True
    config['embeddings'].update(settings | {'provider': 'sentence_transformers', 'batch_size': selected,
        'local_model_path': model_dir.relative_to(ROOT).as_posix(), 'normalize_embeddings': True})
    if file_hash(ROOT / 'outputs/layer2/knowledge/_manifest.json') != manifest_hash:
        raise RuntimeError('Layer2 manifest changed during preflight')
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf-8')
    (REPORTS / 'model_preflight_result.json').write_text(json.dumps({'status': 'PASS',
        'model': settings['model'], 'revision': REVISION, 'dimensions': 1024, 'hardware': hardware,
        'tokens': census, 'calibration': calibration}, indent=2), encoding='utf-8')
    print('LOCAL_BGE_M3_PREFLIGHT_PASS', flush=True)


def download_weights(model_dir):
    """Bounded HTTP range transfer, pinned LFS hash; useful behind HTTPS scanners."""
    import requests
    import threading
    from concurrent.futures import ThreadPoolExecutor
    expected_hash = 'b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38'
    target = model_dir / 'pytorch_model.bin'
    if target.exists() and file_hash(target) == expected_hash:
        return
    url = 'https://modelscope.cn/models/BAAI/bge-m3/resolve/master/pytorch_model.bin'
    total = 2271145830
    step = 1024**2
    parts = model_dir / 'download_parts_verified_1mb'
    parts.mkdir(exist_ok=True)
    thread_local = threading.local()
    def fetch(n):
        start, end = n * step, min(total, (n+1)*step)-1
        part = parts / f'{n:04d}.part'
        if part.exists() and part.stat().st_size == end-start+1:
            return part
        for cache_dir in ('download_parts_modelscope_8mb', 'download_parts_native_8mb', 'download_parts'):
            cached = model_dir / cache_dir / f'{n//8:04d}.part'
            expected = min(8*1024**2, total-(n//8)*8*1024**2)
            if cached.exists() and cached.stat().st_size == expected:
                with cached.open('rb') as stream:
                    stream.seek((n%8)*1024**2)
                    part.write_bytes(stream.read(end-start+1))
                return part
        cached = model_dir / 'download_parts_1mb' / f'{n:04d}.part'
        if cached.exists() and cached.stat().st_size == end-start+1:
            import shutil
            shutil.copyfile(cached,part)
            return part
        # A continuous native transfer can also supply an already received prefix.
        prefix = model_dir / 'pytorch_model.mirror.candidate'
        if prefix.exists() and prefix.stat().st_size >= end+1:
            with prefix.open('rb') as stream:
                stream.seek(start)
                part.write_bytes(stream.read(end-start+1))
            return part
        previous = model_dir / 'download_parts' / f'{n:04d}.part'
        native_previous = model_dir / 'download_parts_native_8mb' / f'{n:04d}.part'
        if native_previous.exists() and native_previous.stat().st_size == end-start+1:
            import shutil
            shutil.copyfile(native_previous, part)
            return part
        if previous.exists() and previous.stat().st_size == end-start+1:
            import shutil
            shutil.copyfile(previous, part)
            return part
        small_parts = [model_dir / 'download_parts_1mb' / f'{i:04d}.part' for i in range(start//1024**2, (end+1024**2)//1024**2)]
        if all(p.exists() and p.stat().st_size == min(1024**2, total - int(p.stem)*1024**2) for p in small_parts):
            with part.open('wb') as output:
                for p in small_parts:
                    output.write(p.read_bytes())
            return part
        if not hasattr(thread_local, 'session'):
            thread_local.session = requests.Session()
        for attempt in range(20):
            try:
                headers = part.with_suffix('.headers')
                origin = url if attempt % 2 == 0 else 'https://huggingface.co/BAAI/bge-m3/resolve/' + REVISION + '/pytorch_model.bin'
                result = subprocess.run(['curl.exe', '--location', '--fail', '--silent', '--show-error',
                    '--range', f'{start}-{end}', '--connect-timeout', '10', '--max-time', '30', '--output', str(part),
                    '--dump-header', str(headers), origin + f'?verified_part={n}&part_size={step}&attempt={attempt}'],
                    capture_output=True, text=True)
                if result.returncode:
                    raise RuntimeError('Native HTTPS transfer failed: ' + result.stderr.strip())
                header_lines = headers.read_text(encoding='latin-1').splitlines()
                actual_ranges = [line.split(':',1)[1].strip().split('/')[0] for line in header_lines if line.lower().startswith('content-range:')]
                if not actual_ranges or actual_ranges[-1] != f'bytes {start}-{end}':
                    raise RuntimeError('Unexpected weights byte range')
                if part.stat().st_size != end-start+1:
                    raise RuntimeError('Incomplete range')
                return part
            except Exception:
                print('WEIGHTS_RANGE_RETRY', n, attempt + 1, flush=True)
                if attempt == 19:
                    raise
    with ThreadPoolExecutor(max_workers=8) as pool:
        chunks = []
        for n, part in enumerate(pool.map(fetch, range((total+step-1)//step), buffersize=16), 1):
            chunks.append(part)
            if n % 64 == 0:
                print('WEIGHTS_DOWNLOAD', min(total,n*step), total, flush=True)
    import shutil
    temporary = model_dir / 'pytorch_model.bin.candidate'
    with temporary.open('wb') as output:
        for part in chunks:
            with part.open('rb') as stream:
                shutil.copyfileobj(stream, output, 1024**2)
    if file_hash(temporary) != expected_hash:
        raise RuntimeError('Pinned weights SHA-256 mismatch')
    temporary.replace(target)
    (REPORTS / 'weights_download.json').write_text(json.dumps({'origin': 'ModelScope BAAI/bge-m3 mirror plus cached HF ranges',
        'authoritative_model': 'BAAI/bge-m3', 'authoritative_revision': REVISION,
        'weights_sha256': expected_hash, 'verified': True, 'bytes': total}), encoding='utf-8')
    # Keep transfer pieces out of artifact inventories. They remain private recovery files.



def setup(root):
    global ROOT, REPORTS
    ROOT=Path(root).resolve()
    REPORTS=ROOT/"outputs/layer3/reports"
    from .pipeline import run
    run(ROOT,mode='validate')
    main()
    return {"status":"PASS","model":"BAAI/bge-m3","revision":REVISION}
