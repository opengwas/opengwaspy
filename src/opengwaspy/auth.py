"""Authentication providers.

A provider supplies the headers that authenticate a request. The Data API and
the Gateway both take a bearer token today, but the Gateway's final user login
flow is not settled, so callers depend only on the :class:`AuthProvider`
protocol. A new flow (for example an OAuth device login with token refresh)
becomes a new provider, with no change to callers' code.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["AuthProvider", "DeveloperKey", "NoAuth", "OpenGWASToken"]


@runtime_checkable
class AuthProvider(Protocol):
    """Supplies authentication headers, and may refresh its credential."""

    def headers(self) -> dict[str, str]:
        """Headers to add to every request."""
        ...

    def refresh(self) -> bool:
        """Try to renew the credential after a 401.

        Returns:
            True if the credential changed and the request is worth retrying.
        """
        ...


class _Bearer:
    """A fixed bearer token. Never shown in ``repr`` or ``str``."""

    kind = "token"

    def __init__(self, token: str) -> None:
        token = token.strip()
        if not token:
            raise ValueError(f"empty {self.kind}")
        if any(c.isspace() for c in token):
            raise ValueError(f"{self.kind} contains whitespace")
        self._token = token

    def headers(self) -> dict[str, str]:
        """The ``Authorization: Bearer`` header."""
        return {"Authorization": f"Bearer {self._token}"}

    def refresh(self) -> bool:
        """A fixed token cannot be renewed."""
        return False

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<hidden>)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return (
            type(other) is type(self) and isinstance(other, _Bearer) and other._token == self._token
        )

    def __hash__(self) -> int:
        return hash((type(self), self._token))


class DeveloperKey(_Bearer):
    """A Data API developer key, for calling the Data API directly.

    Developer keys are issued by the Data API's operators. Each acts as one
    developer, with its own share of the queue.
    """

    kind = "developer key"


class OpenGWASToken(_Bearer):
    """An OpenGWAS token (JWT), for calling OpenGWAS through the Gateway.

    Today a token is issued on your OpenGWAS profile page and lasts 14 days.
    Issuing a new one revokes the old one.
    """

    kind = "OpenGWAS token"


class NoAuth:
    """No credential. Only public routes (such as ``/api/status``) will answer."""

    def headers(self) -> dict[str, str]:
        """No headers."""
        return {}

    def refresh(self) -> bool:
        """Nothing to refresh."""
        return False

    def __repr__(self) -> str:
        return "NoAuth()"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, NoAuth)

    def __hash__(self) -> int:
        return hash(NoAuth)
