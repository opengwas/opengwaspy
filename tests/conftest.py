"""Shared fixtures.

Unit tests never touch the network. Tests marked ``live`` run against the API
named by ``OPENGWAS_URL`` with ``OPENGWAS_TOKEN``. They are deselected by
default (``-m "not live"`` in pyproject) and selected with ``pytest -m live``.
Credentials come from the environment, or else from the project's ``.env``,
which is read for live tests only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
LIVE_KEYS = ("OPENGWAS_URL", "OPENGWAS_TOKEN")


@dataclass(frozen=True)
class LiveAPI:
    url: str
    token: str = ""

    def __repr__(self) -> str:  # never show the token
        return f"LiveAPI(url={self.url!r})"


def read_env_file(path: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE lines, ignoring comments and blanks."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def live_settings(environ: dict[str, str], env_file: Path) -> LiveAPI | None:
    """Credentials for live tests, from the environment first, then the .env file."""
    file_values = read_env_file(env_file)
    found = {k: environ.get(k) or file_values.get(k, "") for k in LIVE_KEYS}
    if not all(found.values()):
        return None
    return LiveAPI(url=found["OPENGWAS_URL"].rstrip("/"), token=found["OPENGWAS_TOKEN"])


@pytest.fixture(scope="session")
def live_api() -> LiveAPI:
    settings = live_settings(dict(os.environ), ENV_FILE)
    if settings is None:
        pytest.skip("live API not configured: set OPENGWAS_URL and OPENGWAS_TOKEN or create .env")
    return settings
