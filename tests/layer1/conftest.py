from copy import deepcopy
from pathlib import Path
import shutil
import pytest
import yaml
from common.config import read_config

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def settings():
    return deepcopy(read_config(ROOT / "config/layer1.yaml"))


@pytest.fixture
def workspace(tmp_path):
    for folder in ("config", "data/samples/synthetic"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "data/samples/synthetic", tmp_path / "data/samples/synthetic", dirs_exist_ok=True)
    shutil.copy(ROOT / "config/sources.synthetic.yaml", tmp_path / "config/sources.yaml")
    shutil.copy(ROOT / "config/layer1.yaml", tmp_path / "config/layer1.yaml")
    return tmp_path


def record(row_no=2, **values):
    return {"_file": "synthetic.csv", "_row": row_no, "_raw": values.copy(), "_source_id": None,
            "_mapping": {}, **values}

