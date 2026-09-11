from typing import Any, Dict

import yaml


def load_config(path: str) -> Dict[str, Any]:
    """
    Load YAML file.
    """
    with open(path, "r") as f:
        return dict(yaml.safe_load(f))