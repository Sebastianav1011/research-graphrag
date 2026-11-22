"""Sequential regression: one pytest process per module, memory checked before each.

Not a pytest module. Writes one line per module to --out (JSON lines) with passed,
failed and the failing node IDs, so the run can be resumed module by module.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

MODULES = ['tests/test_context_budget.py', 'tests/test_evidence_references.py', 'tests/test_ollama_provider.py',
    'tests/test_precision_correction_v1.py', 'tests/test_prospective_v2.py', 'tests/test_prospective_v2_closure.py',
    'tests/test_prospective_v2_decisions.py', 'tests/test_prospective_v2_pilot.py', 'tests/test_run_prospective_defaults.py',
    'tests/test_semantic_correction_v2.py', 'tests/semantic_validation', 'tests/layer5_confidence',
    'tests/test_assessment_recovery.py', 'tests/test_claude_recommendations.py', 'tests/test_scoped_identity.py',
    'tests/test_v5_articles_optimization.py', 'tests/test_pipeline_scope_fixes.py', 'tests/layer4_graphrag',
    'tests/test_thesis_output.py', 'tests/test_indicator_csv.py', 'tests/test_calibrated_context.py',
    'tests/test_resume_blocked_indicators.py', 'tests/test_token_limit_recovery.py', 'tests/test_prompt_v3_and_selection.py',
    'tests/test_evaluable_contracts.py', 'tests/test_manual_pipeline.py', 'tests/test_unified_runner.py',
    'tests/test_python_runner.py', 'tests/test_architecture_consolidation.py', 'tests/test_selection_console.py']
MIN_FREE_MIB = 1536
MODULE_SECONDS = 900


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--limit', type=int, default=0, help='modules in this batch (0 = all pending)')
    args = parser.parse_args()
    import evaluate_source
    out = Path(args.out)
    done = {json.loads(line)['module'] for line in out.read_text(encoding='utf-8').splitlines()} if out.exists() else set()
    pending = [m for m in MODULES if m not in done]
    for module in pending[:args.limit or None]:
        free = evaluate_source.free_mib()
        if free < MIN_FREE_MIB:
            print(f'STOP: memoria libre {free:.0f} MiB < {MIN_FREE_MIB} antes de {module}', flush=True)
            return 2
        start = time.perf_counter()
        # Guarded: a hanging module (e.g. an exhausted scripted menu) is killed and recorded.
        process = subprocess.Popen([sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-rf', module],
                                   cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   encoding='utf-8', errors='replace')
        import threading
        chunks = []
        reader = threading.Thread(target=lambda: chunks.extend(process.stdout), daemon=True); reader.start()
        killed, low = None, free
        while process.poll() is None:
            now = evaluate_source.free_mib(); low = min(low, now)
            if now < MIN_FREE_MIB: killed = f'KILLED_LOW_MEMORY {now:.0f} MiB'
            elif time.perf_counter() - start > MODULE_SECONDS: killed = f'KILLED_TIMEOUT {MODULE_SECONDS}s'
            if killed: process.kill(); break
            time.sleep(0.5)
        process.wait(); reader.join(5)
        process.stdout = ''.join(chunks)
        lines = process.stdout.splitlines()
        summary = killed or next((l for l in reversed(lines) if ' passed' in l or ' failed' in l or ' error' in l), lines[-1] if lines else '')
        failed = sorted({l.split(' ')[1] for l in lines if l.startswith(('FAILED ', 'ERROR '))})
        record = dict(module=module, summary=summary.strip('= '), failed=failed, exit=process.returncode,
                      seconds=round(time.perf_counter() - start, 1), free_mib_before=round(free),
                      free_mib_min=round(low), killed=killed)
        with out.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        print(module, '|', record['summary'], '| fallos', len(failed), flush=True)
        if killed and killed.startswith('KILLED_LOW_MEMORY'):
            print('STOP: memoria baja durante', module, flush=True)
            return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
