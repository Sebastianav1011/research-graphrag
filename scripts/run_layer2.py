"""Thin Layer 2 CLI. Default configuration deliberately cannot publish yet."""
import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from layer2_knowledge.pipeline import run
from layer2_knowledge.validate_inputs import WaitingForLayer1, ConfigurationPending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/layer2.yaml')
    parser.add_argument('--mode', choices=['profile', 'validate', 'publish'], default='publish')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    try:
        result = run(ROOT, args.config, args.mode)
    except WaitingForLayer1 as exc:
        print(str(exc))
        return 2
    except ConfigurationPending as exc:
        print(str(exc))
        return 3
    except Exception as exc:
        logging.error('LAYER_2_FAILED: %s', exc)
        return 1
    print('LAYER_2_' + ('PUBLISHED' if args.mode == 'publish' else args.mode.upper() + '_FINISHED'))
    if args.mode == 'validate':
        print('Quality:', result['status'], 'reports:', result['quality']['reports'])
    return 0 if result.get('status') != 'FAIL' else 1


if __name__ == '__main__':
    raise SystemExit(main())
