"""Run `run.py` itself (same main, same CLI arguments) when no interactive terminal exists.

Only the terminal check and the answers are scripted: 'S' exclusively to the single
run authorization '¿Iniciar ejecución?'; 'N' to every other question (for example a
Knowledge rebuild). Every prompt is logged. Not a pytest module.

  uv run python tests/real_runs/run_py_scripted.py run --source base ... (run.py arguments)
"""
import builtins
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT), str(ROOT / 'scripts')]


def main():
    import run
    prompts = []

    def answer(prompt=''):
        reply = 'S' if prompt.strip().startswith('¿Iniciar ejecución?') else 'N'
        prompts.append(dict(prompt=prompt.strip(), answer=reply))
        print(f'[respuesta guionizada] {prompt.strip()} -> {reply}', flush=True)
        return reply

    builtins.input = answer
    sys.stdin.isatty = lambda: True
    try:
        return run.main(sys.argv[1:])
    finally:
        print(json.dumps(dict(prompts=prompts), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
