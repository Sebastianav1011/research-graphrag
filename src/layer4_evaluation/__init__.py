"""Layer 4: independent indicator assessment and territorial characterization."""
import json
from pathlib import Path


def load_schema(root, name):
    """Load the existing consumer contract without changing its published path."""
    return json.loads((Path(root)/'schemas/layer4_assessment'/(name+'.schema.json')).read_text(encoding='utf-8'))
