"""The Local Source: Store Releases opened with ogquery, answering API requests in process."""

from __future__ import annotations

import functools
import importlib
import math
import re
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import pandas as pd

from opengwaspy.client import Limits
from opengwaspy.errors import OpenGWASError, RequestError
from opengwaspy.local._clumps import clump_answer
from opengwaspy.local._ld import (
    LD_ENDPOINTS,
    LocalLDError,
    LocalLDStore,
    answer_ld,
    choose,
    open_ld,
)
from opengwaspy.source import LocalUnsupported

if TYPE_CHECKING:
    from opengwaspy.batch import Query

__all__ = ["LocalExtraMissing", "LocalRelease", "LocalSource", "local"]

T = TypeVar("T")

#: The ogquery versions this opengwaspy reads with (below 1.0 a minor version may break).
OGQUERY_SPEC = ">=0.5,<0.6"
#: Store format versions a Local Source reads.
READABLE_FORMAT = "0.3"
#: Far above any request: a Local Source splits nothing.
_UNBOUNDED = 10**12

#: An OpenGWAS ID, such as ``ieu-a-2`` or ``ukb-b-19953``.
_OPENGWAS_ID = re.compile(r"^[a-z0-9]+-[a-z]-[A-Za-z0-9_]+$")

_ASSOCIATIONS = ("api/associations", "api/associations/range", "api/associations/analysis")
#: The Rho Matrix's estimation settings, as its group's attributes name them (ogdb-api rho.py).
_RHO_SETTINGS = (
    "method",
    "z_thresh",
    "min_nulls",
    "grid_n",
    "window_bp",
    "n_variants_used",
    "observed_only",
    "n_analyses",
)
_VARIANTS = {"api/variants/rsid": "rsids", "api/variants/chrpos": "positions"}
#: The variant fields of a variant lookup's rows, as the API gives them.
_VARIANT_FIELDS = ("alid", "chromosome", "position", "effect_allele", "other_allele", "rsid")


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
    store: Any = field(repr=False, default=None)
    top_hit_thresholds: tuple[float, ...] = ()
    phewas: bool = False
    variants_rsid: bool = False

    @property
    def capabilities(self) -> dict[str, Any]:
        """What the release answers, in the API's ``capabilities`` terms."""
        return {
            "gwasinfo": bool(self.analyses),
            "associations": True,
            "top_hits": bool(self.top_hit_thresholds),
            "top_hit_thresholds": list(self.top_hit_thresholds),
            "variants_rsid": self.variants_rsid,
            "variants_chrpos": True,
            "phewas": self.phewas,
        }

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
    top_hits = _ogquery("ogquery.top_hits")
    tiers = where / "data.zarr" / top_hits.TOP_HIT_GROUP
    axis = release.variant_axis(aliases=False)
    try:
        rsid_lookup = axis.rsid_index is not None
    finally:
        axis.close()
    return LocalRelease(
        store_id=str(manifest.store_id),
        release_id=str(manifest.release_id),
        path=where,
        format_version=version,
        layout=str(manifest.primary_layout),
        completion_state=str(manifest.completion_state),
        query=query,
        analyses=analyses,
        store=release,
        top_hit_thresholds=tuple(
            t for t in top_hits.TOP_HIT_THRESHOLDS if (tiers / top_hits.threshold_key(t)).is_dir()
        ),
        phewas=_phewas_indexed(where),
        variants_rsid=rsid_lookup,
    )


def _phewas_indexed(path: Path) -> bool:
    """Whether a variant can be read across every Analysis without a scan (as the API decides)."""
    if not (path / "data.zarr").is_dir():
        return False
    if not (path / _ogquery("ogquery.csr").RAGGED_ZARR_PATH).is_dir():
        return True
    return bool(_ogquery("ogquery.by_variant").has_variant_index(path))


def local(
    paths: str | Path | Iterable[str | Path] | None = None,
    *,
    ld: str | Path | Iterable[str | Path] | None = None,
) -> LocalSource:
    """Open downloaded Store Releases, and LD Stores, as a Local Source.

    Args:
        paths: The full path of each Store Release (the directory holding its
            ``manifest.json``), at most one release per GWAS Store.
        ld: The full path of each LD Store or Genotype Store (the ``.store``
            directory), for the LD functions. Each is named by its directory,
            and its ancestry comes from its provenance. With several stores of
            one ancestry, name the store (``store=``) rather than the ancestry.

    Returns:
        A :class:`LocalSource`, to pass as ``client`` to the query functions.
        Close it (or use it in a ``with`` block) to let go of its files.

    Raises:
        LocalExtraMissing: ogquery is not installed.
        LocalSourceError: A path is not a readable format 0.3 Store Release, or
            two paths are releases of the same Store.
        LocalLDError: An ``ld`` path is not a readable LD Store, or two have one name.
    """
    items = _paths(paths)
    stores = _paths(ld)
    if not items and not stores:
        raise ValueError("paths is empty: name at least one Store Release or LD Store")
    return LocalSource(items, ld=stores)


def _paths(value: str | Path | Iterable[str | Path] | None) -> list[str | Path]:
    if value is None:
        return []
    return [value] if isinstance(value, (str, Path)) else list(value)


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

    def __init__(self, paths: Sequence[str | Path], *, ld: Sequence[str | Path] = ()) -> None:
        self.releases: list[LocalRelease] = []
        self.ld_stores: list[LocalLDStore] = []
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
            if ld:
                _ogquery()  # the extra's message, before any LD Store is read
            for path in ld:
                store = open_ld(path)
                if any(s.name == store.name for s in self.ld_stores):
                    store.close()
                    raise LocalLDError(f"two LD Stores are named {store.name}; rename one")
                self.ld_stores.append(store)
        except BaseException:
            self.close()
            raise
        self.ogquery_version = str(getattr(_ogquery(), "__version__", "unknown"))

    def __repr__(self) -> str:
        names = [f"{r.store_id}/{r.release_id}" for r in self.releases]
        names += [f"LD {s.name}" for s in self.ld_stores]
        return f"LocalSource({', '.join(names)})"

    def __enter__(self) -> LocalSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close every release and LD Store, letting go of their files."""
        for release in self.releases:
            release.close()
        for store in self.ld_stores:
            store.close()

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
        metadata: dict[str, Any] = {}
        rows: list[dict[str, Any]]
        if name in _ASSOCIATIONS:
            releases = self._select(body)
            rows = _translated(lambda: self._associations(name, body, releases))
            rows.sort(key=_row_key)
        elif name == "api/tophits":
            releases = self._select(body)
            if body.get("clump") is not None:
                rows, metadata = _translated(
                    lambda: clump_answer(
                        body, releases, self.ld_stores, self._hits_at, self._resolved
                    )
                )
            else:
                rows, metadata = _translated(lambda: self._top_hits(body, releases))
        elif name == "api/phewas":
            releases = self._select(body)
            rows, metadata = _translated(lambda: self._phewas(body, releases))
        elif name in _VARIANTS:
            releases = self._select(body)
            rows = _translated(lambda: self._variants(name, body, releases))
        elif name in LD_ENDPOINTS:
            releases = []
            rows, metadata = answer_ld(choose(self.ld_stores, body), name, body)
        else:
            raise LocalUnsupported(f"{name} is not available on a Local Source")
        frame: pd.DataFrame = pd.DataFrame.from_records(rows) if rows else pd.DataFrame()
        frame.attrs.update(self._provenance(name, [r for r, _ in releases]))
        frame.attrs["metadata"] = metadata
        return frame

    def batches(self) -> pd.DataFrame:
        """The open releases, one row each, as the API's ``batches()`` lists them.

        Each row has ``store_id``, ``release_id``, ``analysis_count`` and
        ``capabilities``, and, locally, ``format_version``, ``layout``,
        ``completion_state`` and ``path``.
        """
        frame: pd.DataFrame = pd.DataFrame.from_records(
            [
                {
                    "release_id": r.release_id,
                    "store_id": r.store_id,
                    "analysis_count": len(r.analyses),
                    "capabilities": r.capabilities,
                    "format_version": r.format_version,
                    "layout": r.layout,
                    "completion_state": r.completion_state,
                    "path": str(r.path),
                }
                for r in self.releases
            ]
        )
        frame.attrs["opengwas_batches"] = []
        return frame

    def rho(self, ref: Mapping[str, str], analyses: Sequence[str] | None) -> dict[str, Any]:
        """A release's Rho Matrix, or the sub-matrix of ``analyses`` (as ``opengwaspy.rho``)."""
        [release] = self._releases_named([ref])
        group = _rho_group(release)
        if group is None:
            raise RequestError(
                422,
                "rho_unavailable",
                f"{release.store_id} holds no Rho Matrix. One is estimated from a Dense grid (a "
                f"Dense Store, or a Hybrid's Dense Component), and this {release.layout} Store "
                "Release carries none",
            )
        ids = None
        if analyses is not None:
            ids = [self._analysis(str(a), [release])[1] for a in analyses]
        answer = _translated(lambda: release.query.rho_matrix(ids))
        attributes = dict(group.attrs)
        return {
            "analysis_id": [str(a) for a in answer["analysis_id"]],
            "rho": answer["rho"],
            "n_null": answer["n_null"],
            "settings": {k: attributes[k] for k in _RHO_SETTINGS if k in attributes},
            "provenance": self._provenance("api/rho", [release]),
        }

    def ld_listing(self) -> list[dict[str, Any]]:
        """The open LD Stores, as ``ld_stores()`` lists them."""
        return [store.listing() for store in self.ld_stores]

    def gwasinfo(
        self,
        ids: Sequence[str] | None = None,
        *,
        releases: Sequence[Mapping[str, str]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Analyses' ``analyses.tsv`` rows, as the API's ``gwasinfo`` rows, and IDs not found.

        Without ``ids``, every analysis of the (selected) releases, by Store.
        A bare ID held by several releases gives each one's row, as the API does.
        """
        candidates = self._releases_named(releases)
        if ids is None:
            return [_analysis_row(r, a) for r in candidates for a in r.analyses.values()], []
        rows: list[dict[str, Any]] = []
        not_found: list[str] = []
        for value in dict.fromkeys(ids):
            store, sep, bare = value.partition(":")
            found = [r for r in candidates if value in r.analyses]
            key = value
            if not found and sep:
                found = [r for r in candidates if r.store_id == store and bare in r.analyses]
                key = bare
            if not found:
                not_found.append(value)
            rows.extend(_analysis_row(r, r.analyses[key]) for r in found)
        return rows, not_found

    def query_many(
        self, queries: Iterable[Query], *, max_in_flight: int | None = None
    ) -> list[pd.DataFrame]:
        """Answer several requests, one after another, in order."""
        del max_in_flight  # nothing runs in parallel locally
        return [self.query(endpoint, body) for endpoint, body in queries]

    # Answering

    def _select(self, body: Mapping[str, Any]) -> list[tuple[LocalRelease, list[str] | None]]:
        """The releases a request reads, each with its own analysis IDs (``None``: all)."""
        candidates = self._releases_named(body.get("releases"))
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

    def _releases_named(self, named: Sequence[Mapping[str, Any]] | None) -> list[LocalRelease]:
        """The open releases ``named`` refers to (every one if ``None``)."""
        if not named:
            return list(self.releases)
        chosen: list[LocalRelease] = []
        for ref in named:
            match = next(
                (
                    r
                    for r in self.releases
                    if r.store_id == ref.get("store_id") and r.release_id == ref.get("release_id")
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
            chosen.append(match)
        return chosen

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
            rows.extend(_rows(release, found))
        return rows

    def _top_hits(
        self, body: Mapping[str, Any], releases: Sequence[tuple[LocalRelease, list[str] | None]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Each analysis's hits at ``threshold``, strongest ``limit`` first (ogdb-api#24, #61)."""
        threshold = float(body.get("threshold", 5e-8))
        limit = int(body.get("limit", 1000))
        observed_only = bool(body.get("observed_only", False))
        rows: list[dict[str, Any]] = []
        capped = False
        for release, analyses in releases:
            tier = _index_tier(threshold, release.top_hit_thresholds)
            if tier is None:
                raise _unsupported_threshold(release)
            for analysis in analyses if analyses is not None else [None]:
                raw = release.query.top_hits(
                    analysis_id=analysis, threshold=tier, observed_only=observed_only
                )
                kept, cut = _rank_per_analysis(_at_threshold(raw, threshold, tier), limit)
                capped = capped or cut
                rows.extend(_rows(release, release.query.resolve(kept, include_variant_info=True)))
        rows.sort(key=lambda r: (*_row_key(r)[:3], -_strength(r), *_row_key(r)[3:]))
        meta = {
            "threshold": threshold,
            "observed_only": observed_only,
            "total": len(rows),
            "truncated": capped,
        }
        return rows, meta

    def _hits_at(
        self, release: LocalRelease, analysis: str, threshold: float, observed_only: bool
    ) -> Any:
        """An analysis's hits at exactly ``threshold``, from the tier at or above it."""
        tier = _index_tier(threshold, release.top_hit_thresholds)
        if tier is None:
            raise _unsupported_threshold(release)
        raw = release.query.top_hits(
            analysis_id=analysis, threshold=tier, observed_only=observed_only
        )
        return _at_threshold(raw, threshold, tier)

    @staticmethod
    def _resolved(release: LocalRelease, raw: Any) -> list[dict[str, Any]]:
        return _rows(release, release.query.resolve(raw, include_variant_info=True))

    def _phewas(
        self, body: Mapping[str, Any], releases: Sequence[tuple[LocalRelease, list[str] | None]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """One variant across the releases' analyses, cut at ``threshold`` before resolving."""
        variant = str(body["variant"])
        threshold = float(body.get("threshold", 1e-8))
        limit = int(body.get("limit", 1000))
        observed_only = bool(body.get("observed_only", True))
        rows: list[dict[str, Any]] = []
        total = 0
        for release, analyses in releases:
            if not release.phewas:
                continue  # as the API, which offers PheWAS only on indexed releases
            raw = _significant(
                release.query.phewas(variant, observed_only=observed_only), threshold
            )
            found = _rows(release, release.query.resolve(raw, include_variant_info=True))
            if analyses is not None:
                keep = set(analyses)
                found = [row for row in found if row.get("analysis_id") in keep]
            total += len(found)
            rows.extend(found[:limit])
        rows.sort(key=_row_key)
        rows = rows[:limit]
        meta = {
            "variant": variant,
            "threshold": threshold,
            "observed_only": observed_only,
            "total": total,
            "returned": len(rows),
            "truncated": total > len(rows),
        }
        return rows, meta

    def _variants(
        self,
        endpoint: str,
        body: Mapping[str, Any],
        releases: Sequence[tuple[LocalRelease, list[str] | None]],
    ) -> list[dict[str, Any]]:
        """Variants by rsID or ``chromosome:position``, as the API's lookups filter them."""
        values = [str(v) for v in body.get(_VARIANTS[endpoint]) or []]
        rows: list[dict[str, Any]] = []
        for release, _ in releases:
            query = release.query
            if endpoint == "api/variants/rsid":
                if not release.variants_rsid:
                    continue
                wanted = set(values)
                found = query.variants(sorted(wanted))
                keep = [r for _, r in sorted(found.items()) if r.get("rsid") in wanted]
            else:
                wanted = {v.removeprefix("chr") for v in values}
                found = {}
                for value in sorted(wanted):
                    chromosome, _, position = value.rpartition(":")
                    if chromosome and position.isdigit():
                        found.update(
                            query.variants_in_range(chromosome, int(position), int(position))
                        )
                keep = [
                    r
                    for _, r in sorted(found.items())
                    if f"{r['chromosome']}:{r['position']}" in wanted
                ]
            rows.extend(
                {
                    **{name: r.get(name) for name in _VARIANT_FIELDS},
                    "store_id": release.store_id,
                    "release_id": release.release_id,
                }
                for r in keep
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


def _translated(answer: Callable[[], T]) -> T:
    """Run ``answer()``, turning ogquery's refusals into opengwaspy's typed errors."""
    analyses = _ogquery("ogquery.analyses")
    identity = _ogquery("ogquery.identity")
    try:
        return answer()
    except analyses.UnknownAnalysisError as exc:
        raise RequestError(404, "analysis_not_found", str(exc)) from exc
    except identity.VariantNormalisationError as exc:
        raise RequestError(400, "invalid_query", str(exc)) from exc
    except _ogquery("ogquery.rho").OverflowOnlyAnalysisError as exc:
        raise RequestError(422, "rho_unavailable", str(exc)) from exc


def _rows(release: LocalRelease, found: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Resolved reader rows as API rows: JSON values, then the Store and release."""
    return [
        {**_json_values(row), "store_id": release.store_id, "release_id": release.release_id}
        for row in found
    ]


def _strength(row: Mapping[str, Any]) -> float:
    """|z|, for ranking; a missing z ranks last."""
    z = row.get("z")
    return abs(float(z)) if isinstance(z, (int, float)) and math.isfinite(z) else -1.0


def _unsupported_threshold(release: LocalRelease) -> RequestError:
    indexed = list(release.top_hit_thresholds)
    loosest = f"{max(indexed):g}" if indexed else "none: it has no Top-Hit Index"
    return RequestError(
        400,
        "unsupported_threshold",
        f"threshold must be at most the loosest p-value the Top-Hit Index of "
        f"{release.store_id} holds ({loosest})",
        extra={"indexed_thresholds": indexed},
    )


def _index_tier(threshold: float, indexed: Sequence[float]) -> float | None:
    """The tightest indexed tier at or above ``threshold`` (ogdb-api#61)."""
    looser = [tier for tier in indexed if tier >= threshold]
    return min(looser) if looser else None


def _z_cut(record: Any, threshold: float) -> Any:
    """``record``'s associations with two-sided p <= ``threshold``: |z| >= z_critical."""
    import numpy as np

    z_critical = _ogquery("ogquery.stats").z_critical
    strength = np.abs(np.asarray(record["z"], dtype=np.float64))
    return record.take(np.flatnonzero(strength >= z_critical(threshold)))


def _at_threshold(record: Any, threshold: float, tier: float) -> Any:
    """The hits of a ``tier`` read with p <= ``threshold``."""
    if threshold == tier or len(record["z"]) == 0:
        return record
    return _z_cut(record, threshold)


def _significant(record: Any, threshold: float) -> Any:
    """A PheWAS read cut at ``threshold`` before resolving; 1 keeps everything (ogdb-api#145)."""
    if threshold >= 1 or len(record["z"]) == 0:
        return record
    return _z_cut(record, threshold)


def _rank_per_analysis(record: Any, limit: int) -> tuple[Any, bool]:
    """Each analysis's ``limit`` hits with the largest |z|, ties in genome order.

    Also whether any analysis had more than ``limit`` (ogdb-api#24).
    """
    import numpy as np

    count = len(record["z"])
    if count == 0:
        return record, False
    analysis = np.asarray(record["analysis_index"])
    strength = np.abs(np.asarray(record["z"], dtype=np.float64))
    strength = np.where(np.isnan(strength), -1.0, strength)
    order = np.lexsort((np.asarray(record["variant_index"]), -strength, analysis))
    grouped = analysis[order]
    starts = np.r_[0, np.flatnonzero(grouped[1:] != grouped[:-1]) + 1]
    sizes = np.diff(np.r_[starts, count])
    rank = np.arange(count) - np.repeat(starts, sizes)
    return record.take(order[rank < limit]), bool((sizes > limit).any())


def _number(text: str) -> Any:
    """An ``analyses.tsv`` value: a number where it is one, ``None`` where it is empty."""
    if text == "":
        return None
    try:
        value = float(text)
    except ValueError:
        return text
    if not math.isfinite(value):
        return text
    integral = value.is_integer() and "." not in text and "e" not in text.lower()
    return int(value) if integral else value


def _analysis_row(release: LocalRelease, row: Mapping[str, Any]) -> dict[str, Any]:
    """An ``analyses.tsv`` row as a ``gwasinfo`` row (the API's rows without a catalog)."""
    values = {k: _number(v) if isinstance(v, str) else v for k, v in row.items()}
    values.pop("analysis_index", None)
    analysis = str(row["analysis_id"])
    return {
        "id": f"{release.store_id}:{analysis}",
        **values,
        "analysis_id": analysis,
        "store_id": release.store_id,
        "release_id": release.release_id,
    }


def _rho_group(release: LocalRelease) -> Any:
    """The release's Rho Matrix group (a Hybrid's is its Dense Component's), or None."""
    store = release.store
    try:
        if release.layout.lower().endswith("hybrid"):
            store = store.dense_component()
        root = store.arrays()
    except Exception:  # a layout without a Dense grid
        return None
    return root["rho"] if "rho" in root else None  # noqa: SIM401  (a zarr group, not a dict)
