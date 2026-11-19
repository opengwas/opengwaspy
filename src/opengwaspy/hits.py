"""Top hits and PheWAS.

* :func:`tophits`: each analysis's strongest associations, at or below a
  p-value threshold. They are **not LD-clumped**: neighbouring variants of
  one signal all appear. (Clumping is offered by the ieugwaspy-compatible
  layer, through the LD operations.)
* :func:`phewas`: every association of one variant, across analyses.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from typing import Any

import pandas as pd

from opengwaspy._common import ReleaseLike, add_p, as_list, chunks, drop_none, resolve_releases, run
from opengwaspy.client import Client, get_client

__all__ = ["phewas", "tophits"]

#: Most releases one PheWAS job may name.
PHEWAS_RELEASES = 10


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


def tophits(
    analyses: str | Iterable[str],
    *,
    threshold: float = 5e-8,
    limit: int = 1000,
    observed_only: bool = False,
    releases: Iterable[ReleaseLike] | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """Each analysis's associations at or below a p-value threshold, strongest first.

    The hits are not LD-clumped.

    Args:
        analyses: Analysis IDs.
        threshold: Largest two-sided p-value. It is exact up to the loosest tier
            the Store's index holds (usually 5e-4); a looser one is refused.
        limit: Most hits per analysis, keeping the largest absolute z.
        observed_only: Leave out imputed associations.
        releases: Only these Stores' releases.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        The hits, by analysis, strongest first, with ``p`` derived from
        ``log10_p``. ``attrs["truncated"]`` is true if any analysis had more
        than ``limit`` hits.

    Raises:
        RequestError: ``unsupported_threshold`` if ``threshold`` is looser than
            the Store indexes; the message and ``extra["indexed_thresholds"]``
            give the thresholds it holds.
    """
    client = client or get_client()
    if not 0 < threshold < 1:
        raise ValueError("threshold must be between 0 and 1")
    if limit < 1:
        raise ValueError("limit must be at least 1")
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
            }
        )
        for group in chunks(analysis_list, per_job)
    ]
    frame = add_p(run(client, "api/tophits", bodies))
    _summarise(frame, ("total",))
    if frame.attrs["truncated"]:
        warnings.warn(
            f"some analyses have more than {limit} hits at p <= {threshold:g}; "
            "only the strongest were returned (raise limit for more)",
            stacklevel=2,
        )
    return frame


def phewas(
    variant: str,
    *,
    releases: Iterable[ReleaseLike] | None = None,
    analyses: str | Iterable[str] | None = None,
    limit: int = 1000,
    observed_only: bool = True,
    client: Client | None = None,
) -> pd.DataFrame:
    """Every association of one variant, across analyses (a PheWAS).

    There is no p-value filter on the server: filter the result yourself, for
    example ``frame[frame.p < 1e-5]``. Check ``attrs["truncated"]`` first.

    Args:
        variant: One rsID or ALID.
        releases: The Stores to search. By default, every served release whose
            Store can answer PheWAS.
        analyses: Only these analyses.
        limit: Most rows per job (each job covers up to 10 releases).
        observed_only: Leave out imputed associations.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        The associations, with ``p``. ``attrs`` has ``total`` (rows that
        qualified), ``returned`` and ``truncated``.
    """
    client = client or get_client()
    if not isinstance(variant, str) or not variant.strip():
        raise ValueError("variant must be one rsID or ALID")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    release_refs = resolve_releases(client, releases)
    if release_refs is None:
        release_refs = _phewas_releases(client)
    analysis_list = as_list(analyses, "analyses")
    bodies = [
        drop_none(
            {
                "variant": variant.strip(),
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
    if frame.attrs["truncated"]:
        warnings.warn(
            f"the PheWAS of {variant} has {frame.attrs.get('total', 'more')} associations; "
            f"only {len(frame)} were returned (raise limit for more)",
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
