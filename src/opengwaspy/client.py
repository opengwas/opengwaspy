"""The client: one object that holds the configuration and runs queries.

Most people never build one: the module-level functions use a default client,
configured from the environment and the config file on first use. Call
:func:`configure` to change it, or build a :class:`Client` for full control
(for example, two clients against different APIs)::

    import opengwaspy as og

    og.configure(url="https://...", token="...")
    og.status()

    with og.Client(url="https://...", token="...") as client:
        client.status()
"""

from __future__ import annotations

import atexit
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from typing import Any

import pandas as pd

from opengwaspy.auth import AuthProvider
from opengwaspy.batch import Query, run_many
from opengwaspy.config import Config
from opengwaspy.errors import ProtocolError
from opengwaspy.jobs import Job
from opengwaspy.transport import Transport, json_body

__all__ = ["Client", "Limits", "configure", "get_client"]


@dataclass(frozen=True)
class Limits:
    """The API's per-query limits, used to split large requests into jobs.

    Read from ``execution.limits`` in ``/api/status`` where the API publishes
    them; the defaults below are the Data API's own defaults.

    Attributes:
        lookup_variants: Most variants in one association or variant lookup.
        lookup_analyses: Most analyses in one association lookup.
        range_span: Widest range, in base pairs, in one range query.
        range_analyses: Most analyses in one range query.
        analysis_analyses: Most whole analyses in one query.
        result_rows: Most rows in one job's result.
        ld_matrix_alids: Most ALIDs in one LD matrix.
        ld_proxies_alids: Most ALIDs in one LD proxy query.
        ld_reflookup_alids: Most ALIDs in one LD reference lookup.
        ld_clump_alids: Most ALIDs in one clump.
    """

    lookup_variants: int = 1000
    lookup_analyses: int = 100
    range_span: int = 10_000_000
    range_analyses: int = 10
    analysis_analyses: int = 10
    result_rows: int = 100_000
    ld_matrix_alids: int = 500
    ld_proxies_alids: int = 1000
    ld_reflookup_alids: int = 10_000
    ld_clump_alids: int = 300_000

    @classmethod
    def from_status(cls, status: Mapping[str, Any]) -> Limits:
        """Limits from a ``/api/status`` document, defaults where it is silent."""
        published = (status.get("execution") or {}).get("limits") or {}
        values = {
            f.name: int(published[f.name])
            for f in fields(cls)
            if isinstance(published.get(f.name), (int, float)) and published[f.name] > 0
        }
        return cls(**values)


class Client:
    """Runs queries against the OpenGWAS Data API.

    Args:
        url: The API's base URL. See :class:`~opengwaspy.config.Config`.
        token: A Data API developer key.
        jwt: An OpenGWAS token, for the Gateway.
        profile: A named base URL, such as ``gateway``.
        auth: An authentication provider, instead of ``token`` or ``jwt``.
        config: A complete configuration, instead of the arguments above.
        transport: A transport to use (for tests); overrides ``config``.
        **options: Other configuration fields, such as ``timeout``.
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        token: str | None = None,
        jwt: str | None = None,
        profile: str | None = None,
        auth: AuthProvider | None = None,
        config: Config | None = None,
        transport: Transport | None = None,
        **options: Any,
    ) -> None:
        if transport is None:
            if config is None:
                config = Config.load(
                    url, profile=profile, token=token, jwt=jwt, auth=auth, **options
                )
            transport = Transport(config)
        self.transport = transport
        self._status: dict[str, Any] | None = None
        self._releases: dict[str, list[str]] | None = None
        self._lock = threading.Lock()

    @property
    def config(self) -> Config:
        """The client's configuration."""
        return self.transport.config

    def close(self) -> None:
        """Close the client's connections."""
        self.transport.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"Client(base_url={self.config.base_url!r}, auth={self.config.auth!r})"

    # Service

    def status(self) -> dict[str, Any]:
        """The API's status: readiness, served releases, queue and limits.

        Also refreshes the limits and the ``image_digest`` this client records
        in each result's provenance.
        """
        body = json_body(self.transport.get("api/status"))
        if not isinstance(body, dict):
            raise ProtocolError("/api/status did not return an object")
        with self._lock:
            self._status = body
        return body

    def user(self) -> dict[str, Any]:
        """Who the API takes you to be: ``user``, ``role``, ``tier`` and allowance."""
        body = json_body(self.transport.get("api/user"))
        if not isinstance(body, dict):
            raise ProtocolError("/api/user did not return an object")
        return body

    def batches(self) -> pd.DataFrame:
        """The data releases (Stores) the API serves, one row each.

        ``attrs["opengwas_batches"]`` lists the OpenGWAS batches (``ebi-a``,
        ``finn-b``, ...) the API resolves, each with its ``store_ids`` and ``match``.
        """
        body = json_body(self.transport.get("api/batches"))
        rows = body.get("batches", body) if isinstance(body, dict) else body
        if not isinstance(rows, list):
            raise ProtocolError("/api/batches did not return a list of batches")
        frame: pd.DataFrame = pd.DataFrame.from_records(rows)
        opengwas = body.get("opengwas_batches") if isinstance(body, dict) else None
        frame.attrs["opengwas_batches"] = list(opengwas or [])
        return frame

    def served_releases(self) -> dict[str, list[str]]:
        """The release IDs the API serves, by Store ID (fetched once)."""
        with self._lock:
            cached = self._releases
        if cached is None:
            cached = {}
            for row in self.batches().to_dict("records"):
                cached.setdefault(str(row["store_id"]), []).append(str(row["release_id"]))
            with self._lock:
                self._releases = cached
        return cached

    @property
    def limits(self) -> Limits:
        """The API's per-query limits (fetched from ``/api/status`` once)."""
        return Limits.from_status(self._cached_status())

    @property
    def image_digest(self) -> str | None:
        """The API build that answers, from ``/api/status`` (fetched once)."""
        digest = (self._cached_status().get("execution") or {}).get("image_digest")
        return str(digest) if digest else None

    def _cached_status(self) -> dict[str, Any]:
        with self._lock:
            cached = self._status
        return cached if cached is not None else self.status()

    # Jobs

    def submit(self, endpoint: str, body: Mapping[str, Any]) -> Job:
        """Submit a query as a job and return it without waiting."""
        return Job.submit(self.transport, endpoint, body)

    def job(self, job_id: str) -> Job:
        """A job submitted earlier, by its ID."""
        return Job.from_id(self.transport, job_id)

    def query(self, endpoint: str, body: Mapping[str, Any]) -> pd.DataFrame:
        """Run one query as a job and return its result.

        Args:
            endpoint: The API path, such as ``api/tophits``.
            body: The query.

        Returns:
            The result, with provenance in ``attrs`` (including ``image_digest``).
        """
        frame = self.submit(endpoint, body).to_frame()
        frame.attrs["image_digest"] = self.image_digest
        return frame

    def query_many(
        self, queries: Iterable[Query], *, max_in_flight: int | None = None
    ) -> list[pd.DataFrame]:
        """Run several queries, a few at a time, and return their results in order.

        Raises:
            BatchError: Some queries failed; the others' results are in the error.
        """
        frames = run_many(self.transport, queries, max_in_flight=max_in_flight)
        digest = self.image_digest
        out: list[pd.DataFrame] = []
        for frame in frames:
            assert frame is not None  # run_many raises if any failed
            frame.attrs["image_digest"] = digest
            out.append(frame)
        return out


_default: Client | None = None
_default_lock = threading.Lock()


def configure(url: str | None = None, **kwargs: Any) -> Client:
    """Set up the default client used by the module-level functions.

    Takes the same arguments as :class:`Client`. Settings you do not pass still
    come from the environment and the config file.

    Returns:
        The new default client.
    """
    global _default
    client = Client(url, **kwargs)
    with _default_lock:
        old, _default = _default, client
    if old is not None:
        old.close()
    return client


@atexit.register
def _close_default() -> None:  # pragma: no cover - runs at interpreter exit
    with _default_lock:
        if _default is not None:
            _default.close()


def get_client() -> Client:
    """The default client, created from the environment and config file on first use."""
    global _default
    with _default_lock:
        if _default is None:
            _default = Client()
        return _default
