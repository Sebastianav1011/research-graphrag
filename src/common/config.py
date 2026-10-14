from pathlib import Path
import yaml


def read_config(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        result = yaml.safe_load(stream)
    if not isinstance(result, dict):
        raise ValueError("Configuration must be a mapping")
    return result

