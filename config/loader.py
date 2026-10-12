import os
import re
import yaml
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from the project's .env into os.environ, without
    overriding variables already set in the real environment. Runs before
    settings.yaml is expanded, so "${UPSTOX_API_KEY}"-style values resolve for
    every entry point (main.py, scripts, the dashboard, the scheduler)."""
    path = path or _ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value[:1] in ('"', "'") and value[0] in value[1:]:
            value = value[1:value.index(value[0], 1)]       # quoted: keep as-is
        else:
            value = value.split(" #")[0].strip()            # unquoted: drop "  # comment"
        if key and key not in os.environ:
            os.environ[key] = value


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
        load_dotenv()
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
