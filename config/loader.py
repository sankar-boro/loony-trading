import os
import re
import yaml
from pathlib import Path
from typing import Any


def _expand_env_vars(obj: Any) -> Any:
    if isinstance(obj, str):
        return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(i) for i in obj]
    return obj


class Settings:
    def __init__(self, path: str | None = None):
        base = Path(__file__).parent
        cfg_path = Path(path) if path else base / "settings.yaml"
        with open(cfg_path) as f:
            raw = yaml.safe_load(f)
        self._data = _expand_env_vars(raw)

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        node = self._data
        for k in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(k)
            if node is None:
                return default
        return node

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        val = self._data.get(name)
        if val is None:
            raise AttributeError(f"Setting '{name}' not found")
        return val

    def as_dict(self) -> dict:
        return self._data


settings = Settings()


def get_setting(key: str, default: Any = None) -> Any:
    return settings.get(key, default)
