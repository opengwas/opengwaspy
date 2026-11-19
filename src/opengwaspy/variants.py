"""Variants: look variants up by rsID or by position in the Stores' variant tables.

Each row is one variant in one Store: ``alid`` (``chromosome:position:allele:allele``),
``chromosome``, ``position``, ``effect_allele``, ``other_allele``, ``rsid``,
``store_id`` and ``release_id``. A variant held by several Stores gives one row
per Store; a multi-allelic rsID gives one row per allele pair. These are the
Stores' own variants, not dbSNP records.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import pandas as pd

from opengwaspy._common import ReleaseLike, as_list, chunks, resolve_releases, run
from opengwaspy.client import Client, get_client

__all__ = ["variants_chrpos", "variants_rsid"]

#: Most releases one variant lookup may name.
RELEASES_PER_JOB = 10
_POSITION = re.compile(r"^(?:chr)?([0-9A-Za-z_.]+):([0-9]+)$", re.IGNORECASE)


def _all_releases(client: Client) -> list[dict[str, str]]:
    return [
        {"store_id": store, "release_id": release}
        for store, releases in client.served_releases().items()
        for release in releases
    ]


def _lookup(
    client: Client,
    endpoint: str,
    field: str,
    values: list[str],
    releases: Iterable[ReleaseLike] | None,
) -> pd.DataFrame:
    release_refs = resolve_releases(client, releases) or _all_releases(client)
    bodies = [
        {field: group, "releases": release_group}
        for release_group in chunks(release_refs, RELEASES_PER_JOB)
        for group in chunks(values, client.limits.lookup_variants)
    ]
    return run(client, endpoint, bodies)


def variants_rsid(
    rsids: str | Iterable[str],
    *,
    releases: Iterable[ReleaseLike] | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """Look variants up by rsID.

    Args:
        rsids: rsIDs, such as ``rs429358``.
        releases: The Stores to search; by default every served release.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        One row per variant per Store. An rsID no Store holds gives no row. For
        one row per variant, use ``frame.drop_duplicates("alid")``.
    """
    client = client or get_client()
    values = as_list(rsids, "rsids") or []
    bad = [v for v in values if not re.fullmatch(r"rs[0-9]+", v, re.IGNORECASE)]
    if bad:
        raise ValueError(f"not rsIDs: {', '.join(bad[:5])}")
    return _lookup(client, "api/variants/rsid", "rsids", values, releases)


def variants_chrpos(
    positions: str | Iterable[str],
    *,
    releases: Iterable[ReleaseLike] | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """Look variants up by exact position.

    Args:
        positions: ``chromosome:position`` values, such as ``19:44908684``; a
            ``chr`` prefix is allowed. Exact positions only: there is no radius.
        releases: The Stores to search; by default every served release.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        One row per variant per Store at those positions.
    """
    client = client or get_client()
    values = as_list(positions, "positions") or []
    bad = [v for v in values if not _POSITION.match(v)]
    if bad:
        raise ValueError(f"expected chromosome:position, got {', '.join(bad[:5])}")
    return _lookup(client, "api/variants/chrpos", "positions", values, releases)
