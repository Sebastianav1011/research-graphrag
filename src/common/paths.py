from pathlib import Path

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

