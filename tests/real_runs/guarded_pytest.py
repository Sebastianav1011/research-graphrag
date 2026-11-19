"""Run one pytest node under a wall-clock and free-memory guard (kills it on breach). Not a pytest module."""
import subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import evaluate_source

def main(node, seconds=60, min_free=1536):
    start = time.perf_counter(); low = 1e9
    process = subprocess.Popen([sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-x', node], cwd=ROOT,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    reason = None
    while process.poll() is None:
        free = evaluate_source.free_mib(); low = min(low, free)
        if free < min_free: reason = f'KILLED_LOW_MEMORY {free:.0f} MiB'
        elif time.perf_counter() - start > seconds: reason = f'KILLED_TIMEOUT {seconds}s'
        if reason: process.kill(); break
        time.sleep(0.5)
    out = process.communicate()[0].splitlines()
    print(node, '|', reason or (out[-1] if out else ''), f'| {time.perf_counter()-start:.1f}s | min_free {low:.0f} MiB')
    if reason is None and process.returncode: print('\n'.join(out[-40:]))

if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 60)
