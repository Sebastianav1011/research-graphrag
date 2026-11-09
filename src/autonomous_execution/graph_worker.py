"""Short-lived authorized GraphRAG builder: process exit releases BGE resources."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT))


def main():
    from autonomous_execution import lifecycle as l, store as s
    from scripts import pipeline_coordinator as coordinator
    from layer4_evaluation.indicators.performance import run_session
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-path',required=True)
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--prepare-discovery',action='store_true')
    args=parser.parse_args()
    run=(ROOT/args.run_path).resolve();l.safe_id(run.name)
    if Path(args.run_path).is_absolute() or not run.is_relative_to(ROOT/'outputs/runs'):
        raise ValueError('Ruta de ejecucion fuera de outputs/runs')
    if args.prepare_discovery:
        if args.manifest_sha256 or (l.folder(run)/'manifest.json').exists():
            raise ValueError('Preparacion de descubrimiento solo antes de revisar/autorizar el manifiesto')
        from autonomous_execution.discovery import build
        with run_session(run,included_in_parent=True), coordinator.lock(run):
            audit=build(ROOT,run)
        print(json.dumps(dict(status='DISCOVERY_PREPARED',inference_calls=0,
            candidates={pid:len(ids) for pid,ids in audit['project_indicators'].items()})))
        return
    if not args.manifest_sha256:raise ValueError('Falta SHA-256 autorizado')
    l.verify(ROOT,run)
    if s.sha(l.folder(run)/'manifest.json')!=args.manifest_sha256:
        raise ValueError('Manifest distinto del autorizado')
    l.graph_policy(run)
    with run_session(run,included_in_parent=True), coordinator.lock(l.folder(run)/'graph_build_lock'):
        coordinator.graph(ROOT,run,build=True)
    print(json.dumps(dict(status='COMPLETE',stage='graphrag')))


if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)  # Private run log; no prompts are printed.
        print(json.dumps(dict(status='GRAPH_BUILD_FAILED',error_type=type(exc).__name__,error_message=str(exc))),file=sys.stderr)
        raise SystemExit(2)
