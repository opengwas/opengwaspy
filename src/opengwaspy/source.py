"""Where queries are answered: the Data API, or downloaded Store Releases.

A :class:`~opengwaspy.Client` reaches the Data API; a
:class:`~opengwaspy.local.LocalSource` reads downloaded Store Releases.

The query functions that run through jobs (associations, top hits, PheWAS,
variants) take either as ``client``: both answer the same requests with the
same rows. Functions that need the API itself (metadata search, LD from the
API's LD Stores, service status) take a :class:`~opengwaspy.Client` only, and
refuse a Local Source by name.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import pandas as pd

from opengwaspy.errors import OpenGWASError

if TYPE_CHECKING:
    from opengwaspy.batch import Query
    from opengwaspy.client import Client, Limits

__all__ = ["LocalUnsupported", "Source", "require_api"]


@runtime_checkable
class Source(Protocol):
    """What the job-based query functions need of a source of answers."""

    @property
    def limits(self) -> Limits:
        """Per-request limits, used to split large requests."""
        ...

    @property
    def image_digest(self) -> str | None:
        """The API build that answers, or ``None`` for a Local Source."""
        ...

    def batches(self) -> pd.DataFrame:
        """The releases answered, one row each, with their ``capabilities``."""
        ...

    def served_releases(self) -> dict[str, list[str]]:
        """The release IDs answered, by Store ID."""
        ...

    def query(self, endpoint: str, body: Mapping[str, Any]) -> pd.DataFrame:
        """Answer one request, with its provenance in ``attrs``."""
        ...

    def query_many(
        self, queries: Iterable[Query], *, max_in_flight: int | None = None
    ) -> list[pd.DataFrame]:
        """Answer several requests, in order."""
        ...


class LocalUnsupported(OpenGWASError, NotImplementedError):
    """A Local Source cannot answer this: it needs the Data API, or is not built yet.

    A Local Source never falls back to the API: pass the API client for this call.
    """


def require_api(client: Any, operation: str) -> Client:
    """``client``, if it reaches the Data API.

    Raises:
        LocalUnsupported: ``client`` is a Local Source; the message names ``operation``.
    """
    if getattr(client, "is_local", False):
        raise LocalUnsupported(
            f"{operation} needs the Data API: a Local Source cannot answer it. "
            "Pass the API client (or no client) for this call."
        )
    return client  # type: ignore[no-any-return]
