"""CLI-owned credential store.

`px login` persists the platform URL + token here; every platform command reads
it and injects it into the prometheux_chain SDK config at runtime. Environment
variables (``PMTX_TOKEN`` / ``JARVISPY_URL``) always win, so CI needs no file.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Optional

DEFAULT_URL = "http://localhost:8000"

ENV_TOKEN = "PMTX_TOKEN"
ENV_URL = "JARVISPY_URL"


def config_path() -> Path:
    """Location of the credential file (override dir with ``PROMETHEUX_HOME``)."""
    home = os.environ.get("PROMETHEUX_HOME")
    base = Path(home) if home else Path.home() / ".prometheux"
    return base / "config.json"


def load() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save(url: str, token: str) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"url": url, "token": token}, indent=2), "utf-8")
    # Best-effort tighten permissions (POSIX only; harmless/no-op on Windows).
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except (OSError, NotImplementedError):
        pass
    return path


def resolve_url() -> str:
    return os.environ.get(ENV_URL) or load().get("url") or DEFAULT_URL


def resolve_token() -> Optional[str]:
    return os.environ.get(ENV_TOKEN) or load().get("token")
