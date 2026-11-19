"""Linkage disequilibrium (LD) from the LD Stores.

Each LD Store holds the LD of one ancestry's reference panel (HGDP + 1000
Genomes). Name a store by ``ancestry`` (``EUR``, ``AFR``, ``AMR``, ``EAS``,
``SAS``) or by ``store`` (see :func:`ld_stores`).

Variants are given as ALIDs (``chromosome:position:allele:allele``). Use
:func:`~opengwaspy.variants_rsid` to find a variant's ALID.

**What a store holds.** Within ``near_bp`` (3 Mb) of a variant, every r is held.
From there to ``far_bp`` (10 Mb), only r² ≥ ``t_far`` (about 0.03; 0.063 for AMR)
is held. A pair the store does not hold is missing (``NaN``), never 0, unless
you pass ``fill``. A request that cannot be answered exactly is refused with
:class:`~opengwaspy.LDRefusal`, which says what the store can answer instead.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd

from opengwaspy._common import as_list, chunks, drop_none, run
from opengwaspy.client import Client, get_client
from opengwaspy.errors import ProtocolError
from opengwaspy.transport import json_body

__all__ = ["ld_clump", "ld_matrix", "ld_proxies", "ld_reflookup", "ld_region", "ld_stores"]


def _store(ancestry: str | None, store: str | None) -> dict[str, str]:
    if (ancestry is None) == (store is None):
        raise ValueError("name exactly one LD store: ancestry= or store=")
    return {"ancestry": ancestry.upper()} if ancestry is not None else {"store": str(store)}


def _alids(alids: str | Iterable[str], *, distinct: bool) -> list[str]:
    values = as_list(alids, "alids") or []
    if distinct and len(set(values)) != len(values):
        dupes = sorted(v for v, n in Counter(values).items() if n > 1)
        raise ValueError(f"alids must be distinct; repeated: {', '.join(dupes[:5])}")
    return values


def _square(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows of ``alid`` and ``r`` (a list) as a square matrix of r, NaN where not held."""
    attrs = dict(frame.attrs)
    if frame.empty:
        square: pd.DataFrame = pd.DataFrame()
    else:
        alids = list(frame["alid"])
        values = np.array(
            [[np.nan if r is None else float(r) for r in row] for row in frame["r"]], dtype=float
        )
        if values.shape != (len(alids), len(alids)):
            raise ProtocolError(f"LD matrix rows are not square: {values.shape}")
        square = pd.DataFrame(values, index=pd.Index(alids, name="alid"), columns=alids)
    attrs["variants"] = frame.drop(columns=["r"], errors="ignore").to_dict("records")
    square.attrs.update(attrs)
    return square


def _lift_metadata(frame: pd.DataFrame, keys: Sequence[str] = ("absent",)) -> pd.DataFrame:
    per_job = frame.attrs.get("metadata_by_job") or [frame.attrs.get("metadata") or {}]
    first = per_job[0] if per_job else {}
    for key in ("store", "ancestry", "t_far", "near_bp", "far_bp"):
        if key in first:
            frame.attrs[key] = first[key]
    for key in keys:
        merged: list[Any] = []
        for meta in per_job:
            merged.extend(meta.get(key) or [])
        frame.attrs[key] = merged
    return frame


def ld_stores(*, client: Client | None = None) -> pd.DataFrame:
    """The LD Stores served: ancestry, panel size, ``t_far``, ``near_bp``, ``far_bp``.

    Args:
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.
    """
    client = client or get_client()
    body = json_body(client.transport.get("api/ld/stores"))
    stores = body.get("stores") if isinstance(body, dict) else None
    if not isinstance(stores, list):
        raise ProtocolError("/api/ld/stores did not return a list of stores")
    frame: pd.DataFrame = pd.DataFrame.from_records(stores)
    return frame


def ld_matrix(
    alids: str | Iterable[str],
    *,
    ancestry: str | None = None,
    store: str | None = None,
    fill: float | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """The LD (signed r) between every pair of some variants.

    Args:
        alids: Up to 500 distinct ALIDs. The matrix is never split across jobs,
            because the pairs between the parts would be missing.
        ancestry: The LD store's ancestry, such as ``EUR``.
        store: The LD store's name, instead of ``ancestry``.
        fill: A number to give pairs the store does not hold, instead of NaN.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        A square DataFrame of r, indexed and labelled by ALID, for the variants
        the store holds. ``attrs["absent"]`` lists ALIDs it does not hold, and
        ``attrs["variants"]`` the alleles (``a1``, ``a2``) the signs refer to.
    """
    client = client or get_client()
    values = _alids(alids, distinct=True)
    cap = client.limits.ld_matrix_alids
    if len(values) > cap:
        raise ValueError(f"an LD matrix takes at most {cap} ALIDs; got {len(values)}")
    body = drop_none({**_store(ancestry, store), "alids": values, "fill": fill})
    return _square(_lift_metadata(run(client, "api/ld/matrix", [body])))


def ld_region(
    chromosome: str | int,
    centre: int,
    radius: int,
    *,
    ancestry: str | None = None,
    store: str | None = None,
    fill: float | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """The LD matrix of every variant the store holds within ``radius`` of ``centre``.

    Args:
        chromosome: Chromosome name.
        centre: Centre position.
        radius: Distance either side, in base pairs. A region of more than
            2,000 variants fails (``result_too_large``); narrow it.
        ancestry: The LD store's ancestry.
        store: The LD store's name, instead of ``ancestry``.
        fill: A number to give pairs the store does not hold, instead of NaN.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        A square DataFrame of r, as :func:`ld_matrix` returns.
    """
    client = client or get_client()
    if centre < 1 or radius < 0:
        raise ValueError("centre must be positive and radius not negative")
    body = drop_none(
        {
            **_store(ancestry, store),
            "chromosome": str(chromosome).removeprefix("chr"),
            "centre": centre,
            "radius": radius,
            "fill": fill,
        }
    )
    return _square(_lift_metadata(run(client, "api/ld/region", [body])))


def ld_clump(
    alids: str | Iterable[str],
    scores: Iterable[float],
    *,
    r2: float,
    kb: float,
    ancestry: str | None = None,
    store: str | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """Clump variants: keep the strongest of each group of variants in LD.

    Greedily, the highest-scoring variant becomes a lead, and every variant
    within ``kb`` with r² ≥ ``r2`` joins its clump.

    ``r2`` and ``kb`` are required: there are no defaults. Not every setting is
    answerable. Beyond ``near_bp`` the store holds only r² ≥ ``t_far``, so
    ``r2`` below ``t_far`` with ``kb`` beyond ``near_bp`` is refused with
    :class:`~opengwaspy.LDRefusal`. ieugwasr's default (r² 0.001 within
    10,000 kb) is refused for that reason.

    Args:
        alids: Distinct ALIDs. Never split across jobs.
        scores: One score per ALID, finite and ≥ 0, higher meaning stronger,
            such as absolute z or -log10(p).
        r2: The r² threshold for joining a clump.
        kb: The window, in kilobases.
        ancestry: The LD store's ancestry.
        store: The LD store's name, instead of ``ancestry``.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        One row per variant the store holds, in the order given: ``alid``,
        ``chromosome``, ``position``, ``score``, ``lead`` (its clump's lead), and
        ``r`` with the lead (1 for a lead). ``frame[frame.alid == frame.lead]``
        are the leads. ``attrs["absent"]`` lists ALIDs the store does not hold:
        they belong to no clump.
    """
    client = client or get_client()
    values = _alids(alids, distinct=True)
    score_list = [float(s) for s in scores]
    if len(score_list) != len(values):
        raise ValueError(f"need one score per ALID: {len(values)} ALIDs, {len(score_list)} scores")
    if any(not np.isfinite(s) or s < 0 for s in score_list):
        raise ValueError("scores must be finite and not negative")
    cap = client.limits.ld_clump_alids
    if len(values) > cap:
        raise ValueError(f"a clump takes at most {cap:,} ALIDs; got {len(values):,}")
    body = {**_store(ancestry, store), "alids": values, "scores": score_list, "r2": r2, "kb": kb}
    return _lift_metadata(run(client, "api/ld/clump", [body]))


def ld_proxies(
    alids: str | Iterable[str],
    *,
    r2: float = 0.8,
    kb: float = 10_000,
    ancestry: str | None = None,
    store: str | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """Proxies of variants: other variants in LD with them.

    Args:
        alids: ALIDs, split into jobs of up to 1,000.
        r2: Least r² for a proxy.
        kb: The window, in kilobases.
        ancestry: The LD store's ancestry.
        store: The LD store's name, instead of ``ancestry``.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        One row per proxy: ``query``, ``proxy``, ``r``, ``r2`` and ``distance``.
        ``attrs["absent"]`` lists ALIDs the store does not hold.
    """
    client = client or get_client()
    values = _alids(alids, distinct=True)
    selection = _store(ancestry, store)
    bodies = [
        {**selection, "alids": group, "r2": r2, "kb": kb}
        for group in chunks(values, client.limits.ld_proxies_alids)
    ]
    return _lift_metadata(run(client, "api/ld/proxies", bodies))


def ld_reflookup(
    alids: str | Iterable[str],
    *,
    ancestry: str | None = None,
    store: str | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """Whether the LD store holds each variant.

    Args:
        alids: ALIDs, split into jobs of up to 10,000.
        ancestry: The LD store's ancestry.
        store: The LD store's name, instead of ``ancestry``.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        One row per ALID, in order: ``alid`` and ``present``.
    """
    client = client or get_client()
    values = _alids(alids, distinct=True)
    selection = _store(ancestry, store)
    bodies = [
        {**selection, "alids": group} for group in chunks(values, client.limits.ld_reflookup_alids)
    ]
    return _lift_metadata(run(client, "api/ld/reflookup", bodies))
