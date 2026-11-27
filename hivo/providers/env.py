"""Zero-dependency .env loader and secret-safe API key resolution."""

from __future__ import annotations

import os
from pathlib import Path

from .types import ProviderConfigError


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_dotenv(
    path: str | Path | None = None,
    *,
    override: bool = False,
) -> dict[str, bool]:
    """Load KEY=VALUE pairs from a local .env file into ``os.environ``.

    Returns a mapping of loaded variable names to ``True`` without ever
    returning or logging secret values.
    """
    env_path = Path(path) if path is not None else Path.cwd() / ".env"
    if not env_path.is_file():
        return {}

    loaded: dict[str, bool] = {}
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, raw_val = line.split("=", 1)
        key = key.strip()
        if not key or any(ch.isspace() for ch in key):
            continue
        val = raw_val.strip()
        # Strip unquoted inline comments (e.g. KEY=value # comment).
        if val and val[0] not in {"'", '"'} and " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        val = _strip_quotes(val)
        if not val:
            continue
        if override or not os.environ.get(key):
            os.environ[key] = val
            loaded[key] = True
    return loaded


def resolve_api_key(
    api_key_env: str | None,
    *,
    dotenv_path: str | Path | None = None,
) -> str:
    """Resolve an API key from ``os.environ`` (with lazy ``.env`` fallback).

    Never embeds secret values in error messages.
    """
    if not api_key_env or not api_key_env.strip():
        return ""
    env_name = api_key_env.strip()
    existing = os.environ.get(env_name, "").strip()
    if existing:
        return existing

    load_dotenv(dotenv_path, override=False)
    resolved = os.environ.get(env_name, "").strip()
    if not resolved:
        raise ProviderConfigError(
            f"Missing API key in environment variable '{env_name}'. "
            f"Set '{env_name}' in your environment or local gitignored .env file."
        )
    return resolved
