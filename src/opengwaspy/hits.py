"""Top hits and PheWAS.

* :func:`tophits`: each analysis's strongest associations, at or below a
  p-value threshold. By default they are not LD-clumped, so neighbouring
  variants of one signal all appear; with ``clump``, the server clumps every
  hit and returns only the leads.
* :func:`phewas`: the associations of one variant across analyses, at or below
  a p-value threshold (1e-8 by default).
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from opengwaspy._common import ReleaseLike, add_p, as_list, chunks, drop_none, resolve_releases, run
from opengwaspy.client import Client, get_client

__all__ = ["phewas", "tophits"]

#: Most releases one PheWAS job may name.
PHEWAS_RELEASES = 10
#: The Data API's default PheWAS p-value threshold.
DEFAULT_PHEWAS_THRESHOLD = 1e-8


def _summarise(frame: pd.DataFrame, keys: tuple[str, ...]) -> None:
    """Put the jobs' result metadata in ``attrs``, summed across jobs."""
    per_job: list[dict[str, Any]] = frame.attrs.get("metadata_by_job") or [
        frame.attrs.get("metadata") or {}
    ]
    frame.attrs["truncated"] = any(bool(m.get("truncated")) for m in per_job)
    for key in keys:
        values = [m[key] for m in per_job if isinstance(m.get(key), (int, float))]
        if values:
            frame.attrs[key] = sum(values)


def _first(frame: pd.DataFrame, key: str, default: Any) -> Any:
    """A metadata value that is the same for every job, such as the threshold applied."""
    per_job: list[dict[str, Any]] = frame.attrs.get("metadata_by_job") or [
        frame.attrs.get("metadata") or {}
    ]
    return next((m[key] for m in per_job if m.get(key) is not None), default)


def tophits(
    analyses: str | Iterable[str],
    *,
    threshold: float = 5e-8,
    limit: int = 1000,
    clump: bool | Mapping[str, Any] = False,
    observed_only: bool = False,
    releases: Iterable[ReleaseLike] | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """Each analysis's associations at or below a p-value threshold, strongest first.

    Without ``clump``, the hits are not LD-clumped. With ``clump``, the server
    clumps **every** hit of each analysis at the threshold in an LD Store, and
    returns only the leads, strongest first, each with ``clump_size``. Hits the
    LD Store does not hold are neither clumped nor returned (counted in
    ``attrs["clump"]["absent"]``).

    Args:
        analyses: Analysis IDs.
        threshold: Largest two-sided p-value. It is exact up to the loosest tier
            the Store's index holds (usually 5e-4); a looser one is refused.
        limit: Most hits per analysis, keeping the largest absolute z; with
            ``clump``, most leads per analysis.
        clump: ``True`` to clump with the server's defaults (r² 0.001 within
            3,000 kb, in each analysis's own ancestry's LD Store, or EUR), or a
            mapping of any of ``r2``, ``kb``, ``ancestry`` (one LD Store for every
            analysis) or ``store`` (an LD Store's name).
        observed_only: Leave out imputed associations.
        releases: Only these Stores' releases.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        The hits (or leads), by analysis, strongest first, with ``p`` derived
        from ``log10_p``. ``attrs["truncated"]`` is true if any analysis had more
        than ``limit``. With ``clump``, ``attrs["clump"]`` has the settings and
        the counts of ``hits``, ``leads`` and ``absent``, and the ``ld_stores`` used.

    Raises:
        RequestError: ``unsupported_threshold`` if ``threshold`` is looser than
            the Store indexes; the message and ``extra["indexed_thresholds"]``
            give the thresholds it holds.
        LDRefusal: The LD Store cannot clump exactly at these settings, such as
            r² 0.001 beyond 3,000 kb. The message says what it can answer.
    """
    client = client or get_client()
    if not 0 < threshold < 1:
        raise ValueError("threshold must be between 0 and 1")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    clump_body = _clump_body(clump)
    analysis_list = as_list(analyses, "analyses") or []
    limits = client.limits
    per_job = max(1, min(limits.lookup_analyses, limits.result_rows // limit))
    release_refs = resolve_releases(client, releases)
    bodies = [
        drop_none(
            {
                "analyses": group,
                "threshold": threshold,
                "limit": limit,
                "observed_only": observed_only,
                "releases": release_refs,
                "clump": clump_body,
            }
        )
        for group in chunks(analysis_list, per_job)
    ]
    frame = add_p(run(client, "api/tophits", bodies))
    _summarise(frame, ("total",))
    if clump_body is not None:
        frame.attrs["clump"] = _clump_summary(frame)
    if frame.attrs["truncated"]:
        what = "clumped leads" if clump_body is not None else "hits"
        warnings.warn(
            f"some analyses have more than {limit} {what} at p <= {threshold:g}; "
            "only the strongest were returned (raise limit for more)",
            stacklevel=2,
        )
    return frame


_CLUMP_KEYS = ("r2", "kb", "ancestry", "store")


def _clump_body(clump: bool | Mapping[str, Any]) -> dict[str, Any] | None:
    if clump is False or clump is None:
        return None
    if clump is True:
        return {}
    if not isinstance(clump, Mapping):
        raise ValueError("clump must be True, False, or a mapping of r2, kb, ancestry or store")
    unknown = sorted(set(clump) - set(_CLUMP_KEYS))
    if unknown:
        raise ValueError(
            f"unknown clump settings {', '.join(unknown)}; use {', '.join(_CLUMP_KEYS)}"
        )
    if clump.get("ancestry") is not None and clump.get("store") is not None:
        raise ValueError("give clump ancestry or store, not both")
    return {k: v for k, v in clump.items() if v is not None}


def _clump_summary(frame: pd.DataFrame) -> dict[str, Any]:
    """The jobs' clump metadata, with the counts summed and the LD Stores merged."""
    per_job: list[dict[str, Any]] = frame.attrs.get("metadata_by_job") or [
        frame.attrs.get("metadata") or {}
    ]
    clumps = [m["clump"] for m in per_job if isinstance(m.get("clump"), Mapping)]
    summary: dict[str, Any] = {}
    for clump in clumps:
        for key, value in clump.items():
            if key in ("hits", "leads", "absent") and isinstance(value, (int, float)):
                summary[key] = summary.get(key, 0) + value
            elif key == "ld_stores" and isinstance(value, Mapping):
                summary.setdefault("ld_stores", {}).update(value)
            else:
                summary.setdefault(key, value)
    return summary


def phewas(
    variant: str,
    *,
    threshold: float = DEFAULT_PHEWAS_THRESHOLD,
    releases: Iterable[ReleaseLike] | None = None,
    analyses: str | Iterable[str] | None = None,
    limit: int = 1000,
    observed_only: bool = True,
    client: Client | None = None,
) -> pd.DataFrame:
    """The associations of one variant across analyses (a PheWAS), at p ≤ ``threshold``.

    The server applies ``threshold`` before it builds any row, so ``total``,
    ``limit`` and truncation count only associations that pass it. The default,
    1e-8, is the Data API's. Pass ``threshold=1`` for every association.

    Args:
        variant: One rsID or ALID.
        threshold: The largest two-sided p-value to return, above 0 and at most 1.
        releases: The Stores to search. By default, every served release whose
            Store can answer PheWAS.
        analyses: Only these analyses.
        limit: Most rows per job (each job covers up to 10 releases; at most 10,000).
        observed_only: Leave out imputed associations.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        The associations, with ``p``. ``attrs`` has ``threshold``, ``total``
        (rows that passed it), ``returned`` and ``truncated``.
    """
    client = client or get_client()
    if not isinstance(variant, str) or not variant.strip():
        raise ValueError("variant must be one rsID or ALID")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be above 0 and at most 1")
    release_refs = resolve_releases(client, releases)
    if release_refs is None:
        release_refs = _phewas_releases(client)
    analysis_list = as_list(analyses, "analyses")
    bodies = [
        drop_none(
            {
                "variant": variant.strip(),
                "threshold": threshold,
                "releases": group,
                "analyses": analysis_list,
                "limit": limit,
                "observed_only": observed_only,
            }
        )
        for group in chunks(release_refs, PHEWAS_RELEASES)
    ]
    frame = add_p(run(client, "api/phewas", bodies))
    _summarise(frame, ("total", "returned"))
    frame.attrs["threshold"] = _first(frame, "threshold", threshold)
    if frame.attrs["truncated"]:
        warnings.warn(
            f"the PheWAS of {variant} has {frame.attrs.get('total', 'more')} associations at "
            f"p <= {threshold:g}; only {len(frame)} were returned (raise limit, up to 10,000 "
            "per job, or lower threshold)",
            stacklevel=2,
        )
    return frame


def _phewas_releases(client: Client) -> list[dict[str, str]]:
    batches = client.batches()
    refs = []
    for row in batches.to_dict("records"):
        capabilities = row.get("capabilities")
        if isinstance(capabilities, dict) and not capabilities.get("phewas"):
            continue
        refs.append({"store_id": str(row["store_id"]), "release_id": str(row["release_id"])})
    if not refs:
        raise ValueError("no served release can answer PheWAS")
    return refs
