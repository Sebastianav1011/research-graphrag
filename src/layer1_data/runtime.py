"""Layer1 operational configuration, filesystem boundary and diagnostic logger."""

from pathlib import Path
import yaml
import logging



# Read Layer1 YAML configuration without inferred settings.
def read_config(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        result = yaml.safe_load(stream)
    if not isinstance(result, dict):
        raise ValueError("Configuration must be a mapping")
    return result

# Resolve Layer1 inputs and constrain publication paths to the workspace.
ROOT = Path(__file__).resolve().parents[2]


def resolve_input(root, value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else Path(root) / path).resolve()


def output_path(root, value):
    root = Path(root).resolve()
    path = resolve_input(root, value)
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Output must be strictly inside the project root")
    return path

# Configure the Layer1 diagnostic logger without duplicate handlers.
def get_logger():
    logger = logging.getLogger("layer1")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger
