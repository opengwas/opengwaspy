"""The Local Source: Store Releases opened with ogquery, answering API requests in process."""

from __future__ import annotations

import functools
import importlib
import math
import re
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from opengwaspy.client import Limits
from opengwaspy.errors import OpenGWASError, RequestError
from opengwaspy.source import LocalUnsupported

if TYPE_CHECKING:
    from opengwaspy.batch import Query

__all__ = ["LocalExtraMissing", "LocalRelease", "LocalSource", "local"]

#: The ogquery versions this opengwaspy reads with (below 1.0 a minor version may break).
OGQUERY_SPEC = ">=0.5,<0.6"
#: Store format versions a Local Source reads.
READABLE_FORMAT = "0.3"
#: Far above any request: a Local Source splits nothing.
_UNBOUNDED = 10**12

#: An OpenGWAS ID, such as ``ieu-a-2`` or ``ukb-b-19953``.
_OPENGWAS_ID = re.compile(r"^[a-z0-9]+-[a-z]-[A-Za-z0-9_]+$")

_ASSOCIATIONS = ("api/associations", "api/associations/range", "api/associations/analysis")


class LocalExtraMissing(OpenGWASError, ImportError):
    """ogquery, which a Local Source reads with, is not installed."""


class LocalSourceError(OpenGWASError, ValueError):
    """A path cannot be opened as a Store Release for a Local Source."""


def _ogquery(module: str = "ogquery") -> Any:
    """Import an ogquery module, or say how to install it."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        version = ".".join(map(str, sys.version_info[:2]))
        hint = (
            'pip install "opengwaspy[local]"'
            if sys.version_info >= (3, 12)
            else f'Python 3.12 or later (this is {version}), then pip install "opengwaspy[local]"'
        )
        raise LocalExtraMissing(
            f"a Local Source reads Store Releases with ogquery{OGQUERY_SPEC}, which is not "
            f"installed: {hint}"
        ) from exc


@dataclass
class LocalRelease:
    """One Store Release opened for a Local Source.

    Attributes:
        store_id: The GWAS Store, such as ``OGS-00006``.
        release_id: The release, from its manifest.
        path: Where it is on disk.
        format_version: Its Store format version.
        layout: ``dense``, ``ragged`` or ``hybrid``.
        completion_state: Observed-Only or Reference-Completed.
    """

    store_id: str
    release_id: str
    path: Path
    format_version: str
    layout: str
    completion_state: str
    query: Any = field(repr=False)
    analyses: dict[str, dict[str, Any]] = field(repr=False, default_factory=dict)

    def close(self) -> None:
        """Close the release's reader, letting go of its files."""
        self.query.close()


def _open(path: str | Path) -> LocalRelease:
    release_module = _ogquery("ogquery.release")
    facade = _ogquery("ogquery.facade")
    where = Path(path).expanduser()
    if not where.exists():
        raise LocalSourceError(f"no Store Release at {where}")
    try:
        release = release_module.open_release(where)
    except Exception as exc:
        raise LocalSourceError(f"{where} cannot be opened as a Store Release: {exc}") from exc
    manifest = release.manifest
    version = str(manifest.format_version)
    if not version.startswith(READABLE_FORMAT + "."):
        remedy = (
            "rewrite it with `ogdb rewrite-release` (opengwasdb)"
            if version == "0.2.3"
            else "download or rebuild it at format 0.3.0"
        )
        raise LocalSourceError(
            f"{where} is format {version}; a Local Source reads format {READABLE_FORMAT}.x: "
            f"{remedy}"
        )
    query = facade.query_release(release)
    analyses = {str(row["analysis_id"]): row for row in query.analyses_table().values()}
    return LocalRelease(
        store_id=str(manifest.store_id),
        release_id=str(manifest.release_id),
        path=where,
        format_version=version,
        layout=str(manifest.primary_layout),
        completion_state=str(manifest.completion_state),
        query=query,
        analyses=analyses,
    )


def local(paths: str | Path | Iterable[str | Path]) -> LocalSource:
    """Open downloaded Store Releases as a Local Source.

    Args:
        paths: The full path of each Store Release (the directory holding its
            ``manifest.json``), at most one release per GWAS Store.

    Returns:
        A :class:`LocalSource`, to pass as ``client`` to the query functions.
        Close it (or use it in a ``with`` block) to let go of its files.

    Raises:
        LocalExtraMissing: ogquery is not installed.
        LocalSourceError: A path is not a readable format 0.3 Store Release, or
            two paths are releases of the same Store.
    """
    items = [paths] if isinstance(paths, (str, Path)) else list(paths)
    if not items:
        raise ValueError("paths is empty: name at least one Store Release")
    return LocalSource(items)


class LocalSource:
    """Downloaded Store Releases, answering the Data API's requests in process.

    Build one with :func:`local`. It holds at most one release per GWAS Store,
    so no query ever chooses between releases. Analyses are named as with the
    API: ``store_id:analysis_id``, or a bare analysis ID that only one of the
    releases holds. OpenGWAS IDs (``ieu-a-2``) are not translated locally.

    An operation it cannot answer raises :class:`~opengwaspy.local.LocalUnsupported`;
    it never asks the Data API instead.
    """

    #: Marks a Local Source to functions that need the API.
    is_local = True

    def __init__(self, paths: Sequence[str | Path]) -> None:
        self.releases: list[LocalRelease] = []
        try:
            for path in paths:
                opened = _open(path)
                same = next((r for r in self.releases if r.store_id == opened.store_id), None)
                if same is not None:
                    opened.close()
                    raise LocalSourceError(
                        f"two releases of Store {opened.store_id}: {same.path} and {opened.path}; "
                        "a Local Source holds one release per Store"
                    )
                self.releases.append(opened)
        except BaseException:
            self.close()
            raise
        self.ogquery_version = str(getattr(_ogquery(), "__version__", "unknown"))

    def __repr__(self) -> str:
        names = ", ".join(f"{r.store_id}/{r.release_id}" for r in self.releases)
        return f"LocalSource({names})"

    def __enter__(self) -> LocalSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close every release, letting go of their files."""
        for release in self.releases:
            release.close()

    # What the query functions need (opengwaspy.source.Source)

    @property
    def limits(self) -> Limits:
        """No per-request limits: a Local Source answers each request whole."""
        return Limits(**{name: _UNBOUNDED for name in Limits.__dataclass_fields__})

    @property
    def image_digest(self) -> str | None:
        """``None``: no API build answers a Local Source."""
        return None

    def served_releases(self) -> dict[str, list[str]]:
        """The open release, by Store ID."""
        return {r.store_id: [r.release_id] for r in self.releases}

    def query(self, endpoint: str, body: Mapping[str, Any]) -> pd.DataFrame:
        """Answer one Data API request from the open releases.

        Args:
            endpoint: The API path, such as ``api/associations``.
            body: The request, as the query functions build it.

        Returns:
            The rows the API would return, in its order, with provenance in
            ``attrs`` (``source`` is ``"local"``; there is no ``job_id``).
        """
        name = endpoint.strip("/")
        if name not in _ASSOCIATIONS:
            raise LocalUnsupported(f"{name} is not available on a Local Source yet")
        releases = self._select(body)
        rows = _translated(lambda: self._associations(name, body, releases))
        rows.sort(key=_row_key)
        frame: pd.DataFrame = pd.DataFrame.from_records(rows) if rows else pd.DataFrame()
        frame.attrs.update(self._provenance(name, [r for r, _ in releases]))
        return frame

    def query_many(
        self, queries: Iterable[Query], *, max_in_flight: int | None = None
    ) -> list[pd.DataFrame]:
        """Answer several requests, one after another, in order."""
        del max_in_flight  # nothing runs in parallel locally
        return [self.query(endpoint, body) for endpoint, body in queries]

    # Answering

    def _select(self, body: Mapping[str, Any]) -> list[tuple[LocalRelease, list[str] | None]]:
        """The releases a request reads, each with its own analysis IDs (``None``: all)."""
        candidates = self.releases
        named = body.get("releases")
        if named:
            candidates = []
            for ref in named:
                match = next(
                    (
                        r
                        for r in self.releases
                        if r.store_id == ref.get("store_id")
                        and r.release_id == ref.get("release_id")
                    ),
                    None,
                )
                if match is None:
                    raise RequestError(
                        404,
                        "release_not_found",
                        f"{ref.get('store_id')}/{ref.get('release_id')} is not open in this "
                        f"Local Source ({self!r})",
                    )
                candidates.append(match)
        requested = body.get("analyses")
        if not requested:
            return [(r, None) for r in candidates]
        wanted: dict[str, list[str]] = {}
        for value in requested:
            release, analysis = self._analysis(str(value), candidates)
            ids = wanted.setdefault(release.store_id, [])
            if analysis not in ids:
                ids.append(analysis)
        return [(r, wanted[r.store_id]) for r in candidates if r.store_id in wanted]

    def _analysis(self, value: str, candidates: Sequence[LocalRelease]) -> tuple[LocalRelease, str]:
        store, sep, bare = value.partition(":")
        if sep:
            release = next((r for r in candidates if r.store_id == store), None)
            if release is not None and bare in release.analyses:
                return release, bare
            raise RequestError(404, "analysis_not_found", f"{value} is not in {self!r}")
        holders = [r for r in candidates if value in r.analyses]
        if len(holders) == 1:
            return holders[0], value
        if holders:
            names = ", ".join(f"{r.store_id}:{value}" for r in holders)
            raise RequestError(
                409, "ambiguous_analysis", f"{value} is in several Stores; use one of {names}"
            )
        hint = (
            "; OpenGWAS IDs are not translated locally: translate it with "
            "opengwaspy.gwasinfo([...]) on the Data API, then use its store_id:analysis_id"
            if _OPENGWAS_ID.match(value)
            else ""
        )
        raise RequestError(404, "analysis_not_found", f"{value} is not in {self!r}{hint}")

    def _associations(
        self,
        endpoint: str,
        body: Mapping[str, Any],
        releases: Sequence[tuple[LocalRelease, list[str] | None]],
    ) -> list[dict[str, Any]]:
        observed_only = bool(body.get("observed_only", True))
        rows: list[dict[str, Any]] = []
        for release, analyses in releases:
            query = release.query
            if endpoint == "api/associations":
                identifiers = list(body.get("variants") or body.get("rsids") or [])
                ids = analyses if analyses is not None else list(release.analyses)
                raw = query.lookup(identifiers, ids, observed_only=observed_only)
                found = query.resolve(raw, include_variant_info=True)
            elif endpoint == "api/associations/analysis":
                if analyses is None:
                    raise RequestError(400, "invalid_query", "analyses is required")
                found = []
                for analysis in analyses:
                    raw = query.analysis(analysis, observed_only=observed_only)
                    found.extend(query.resolve(raw, include_variant_info=True))
            else:
                raw = query.range_phewas(
                    str(body["chromosome"]),
                    int(body["start"]),
                    int(body["end"]),
                    observed_only=observed_only,
                )
                found = query.resolve(raw, include_variant_info=True)
                if analyses is not None:
                    keep = set(analyses)
                    found = (row for row in found if row.get("analysis_id") in keep)
            rows.extend(
                {
                    **_json_values(row),
                    "store_id": release.store_id,
                    "release_id": release.release_id,
                }
                for row in found
            )
        return rows

    def _provenance(self, endpoint: str, releases: Sequence[LocalRelease]) -> dict[str, Any]:
        return {
            "source": "local",
            "job_id": None,
            "query_hash": None,
            "endpoint": endpoint,
            "release_id": releases[0].release_id if len(releases) == 1 else None,
            "releases": [{"store_id": r.store_id, "release_id": r.release_id} for r in releases],
            "metadata": {},
            "compute": {},
            "retrieved": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ogquery_version": self.ogquery_version,
            "paths": [str(r.path) for r in releases],
            "image_digest": None,
        }


def _json_values(row: Mapping[str, Any]) -> dict[str, Any]:
    """A row as the API writes it: NaN and infinities are ``null`` (ogdb-api#193)."""
    return {k: None if isinstance(v, float) and not math.isfinite(v) else v for k, v in row.items()}


@functools.cache
def _chromosome_rank(chromosome: Any) -> tuple[int, str]:
    """The reader's chromosome order (1-22, X, Y, MT, then others); unknown last."""
    try:
        key = _ogquery("ogquery.identity").chromosome_sort_key(str(chromosome))
    except ValueError:
        return (10**9, "")
    return (int(key[0]), str(key[1]))


def _row_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """The API's row order: Store, release, analysis, then genome order (ogdb-api#62)."""
    position = row.get("position")
    return (
        str(row.get("store_id", "")),
        str(row.get("release_id", "")),
        str(row.get("analysis_id", "")),
        _chromosome_rank(row.get("chromosome")),
        int(position) if isinstance(position, int) else -1,
        str(row.get("alid", "")),
    )


def _translated(answer: Any) -> list[dict[str, Any]]:
    """Run ``answer()``, turning ogquery's refusals into opengwaspy's typed errors."""
    analyses = _ogquery("ogquery.analyses")
    identity = _ogquery("ogquery.identity")
    try:
        return list(answer())
    except analyses.UnknownAnalysisError as exc:
        raise RequestError(404, "analysis_not_found", str(exc)) from exc
    except identity.VariantNormalisationError as exc:
        raise RequestError(400, "invalid_query", str(exc)) from exc
