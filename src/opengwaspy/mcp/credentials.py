"""A credential the MCP server re-reads when the API refuses it.

OpenGWAS tokens last 14 days, and getting a new one revokes the old. A server
started by an AI assistant may run for longer than that. On a 401, or when no
credential was configured, :class:`ReloadingAuth` reads the configuration again,
so a token saved to the opengwaspy config file (for example by
``opengwaspy.compat.get_jwt()``) is used on the next call, with no restart.
An ``OPENGWAS_JWT`` in the server's environment cannot change while it runs:
the assistant's settings must be updated, and the server restarted.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from opengwaspy.auth import AuthProvider
from opengwaspy.config import ConfigError

__all__ = ["ReloadingAuth"]

log = logging.getLogger(__name__)


class ReloadingAuth:
    """An auth provider that reloads its credential from the configuration.

    Args:
        load: Returns the configured provider (it reads the environment and
            the config file each time).
    """

    def __init__(self, load: Callable[[], AuthProvider]) -> None:
        self._load = load
        self._lock = threading.Lock()
        self._current = load()

    @property
    def current(self) -> AuthProvider:
        """The provider in use."""
        with self._lock:
            return self._current

    def headers(self) -> dict[str, str]:
        """The current provider's headers."""
        return self.current.headers()

    def refresh(self) -> bool:
        """Reload the configuration; True if the credential changed."""
        try:
            fresh = self._load()
        except (ConfigError, ValueError) as exc:
            log.warning("cannot reload the opengwaspy configuration: %s", exc)
            return False
        with self._lock:
            if fresh == self._current:
                return False
            self._current = fresh
        log.warning("loaded a new credential from the configuration")
        return True

    def __repr__(self) -> str:
        return f"ReloadingAuth({self.current!r})"
