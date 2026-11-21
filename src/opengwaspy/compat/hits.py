"""ieugwaspy's ``tophits`` and ``phewas``, honoured on the Data API or refused."""

from __future__ import annotations

import math
import warnings
from collections.abc import Iterable
from typing import Any

import pandas as pd

import opengwaspy as og
from opengwaspy.compat._columns import ieugwas_columns
from opengwaspy.compat._ids import resolve
from opengwaspy.errors import UnsupportedOptionError

__all__ = ["clump_settings_answerable", "tophits"]

#: Most leads per analysis, when clumping: the API's largest top-hits limit.
CLUMP_LEADS = 10_000


def _store(pop: str) -> dict[str, Any]:
    stores = og.ld_stores()
    match = stores[stores["ancestry"].str.upper() == pop.upper()]
    if match.empty:
        served = ", ".join(sorted(stores["ancestry"]))
        raise UnsupportedOptionError(f"pop={pop!r} has no LD store; choose one of {served}")
    store: dict[str, Any] = match.iloc[0].to_dict()
    return store


def clump_settings_answerable(r2: float, kb: float, store: dict[str, Any]) -> bool:
    """Whether an LD store can clump exactly at ``r2`` within ``kb``.

    The store holds every r within ``near_bp``, and only r² ≥ ``t_far`` up to
    ``far_bp``.
    """
    window = kb * 1000
    if window <= store["near_bp"]:
        return True
    return bool(r2 >= store["t_far"] and window <= store["far_bp"])


def _refusal(r2: float, kb: float, pop: str, store: dict[str, Any]) -> UnsupportedOptionError:
    near_kb = int(store["near_bp"] // 1000)
    far_kb = int(store["far_bp"] // 1000)
    t_far = float(store["t_far"])
    suggested_r2 = math.ceil(t_far * 100) / 100
    return UnsupportedOptionError(
        f"clumping at r2={r2:g} within kb={kb:g} cannot be done exactly with the {pop} LD "
        f"store ({store['store']}). Beyond {near_kb:,} kb it holds only pairs with "
        f"r2 >= {t_far:.3g}, so it cannot tell whether a more distant pair has r2 >= {r2:g}. "
        f"Choose one of:\n"
        f"  tophits(..., r2={r2:g}, kb={near_kb})   # your r2, within {near_kb:,} kb\n"
        f"  tophits(..., r2={suggested_r2:g}, kb={min(kb, far_kb):g})   # r2 above the store's "
        f"t_far, up to {far_kb:,} kb\n"
        f"or clump=0 for the unclumped hits. (ieugwaspy's default, r2=0.001 within 10,000 kb, "
        f"relied on a full reference panel.)"
    )


def tophits(
    id: str | Iterable[str],
    pval: float = 5e-8,
    preclumped: int = 1,
    clump: int = 1,
    bychr: int = 0,
    r2: float = 0.001,
    kb: int = 10000,
    pop: str = "EUR",
    force_server: bool = False,
) -> pd.DataFrame:
    """Top hits, clumped by default, as ieugwaspy's ``tophits``.

    With ``clump=1``, the Data API clumps every hit of each analysis at
    ``p <= pval`` in the ``pop`` LD Store, on the server, and only each clump's
    lead is returned, with ``clump_size``.

    **ieugwaspy's default clumping (r2=0.001 within kb=10000) is refused**,
    because the LD stores cannot answer it exactly. The error suggests settings
    they can: your ``r2`` within 3,000 kb, or an ``r2`` above the store's
    ``t_far`` (about 0.03; 0.063 for AMR) within 10,000 kb. Answerable settings
    are honoured.

    Hits the LD store does not hold cannot be clumped, and are dropped with a
    warning, as ieugwasr's clumping drops variants missing from its reference.

    Args:
        id: Analysis IDs.
        pval: Largest p-value; at most 5e-4, the loosest the index holds.
        preclumped: Accepted for compatibility; has no effect.
        clump: ``1`` to clump, ``0`` for every hit.
        bychr: Accepted for compatibility; has no effect.
        r2: Clumping r² threshold.
        kb: Clumping window, in kilobases.
        pop: Ancestry of the LD store: ``EUR``, ``AFR``, ``AMR``, ``EAS`` or ``SAS``.
        force_server: Accepted for compatibility; has no effect.

    Returns:
        The hits (the leads, when clumped), with ieugwaspy's column names first.
        When clumped, ``attrs["clump"]`` has the settings, the counts of
        ``hits``, ``leads`` and ``absent``, and the LD Store used.

    Raises:
        UnsupportedOptionError: The clumping settings cannot be answered exactly, or
            ``pop`` has no LD store.
    """
    del preclumped, bychr, force_server  # no effect on the Data API (documented)
    resolved = resolve(id)
    ids = resolved.ids
    store = _store(pop) if clump else None
    if not ids:
        return resolved.label(pd.DataFrame())
    if store is not None and not clump_settings_answerable(r2, kb, store):
        raise _refusal(r2, kb, pop, store)
    settings = {"r2": r2, "kb": kb, "store": store["store"]} if store is not None else False
    limit = CLUMP_LEADS if clump else 1000
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        hits = og.tophits(ids, threshold=pval, limit=limit, clump=settings)
    for warning in caught:  # replace the native truncation warning with our own
        if not str(warning.message).startswith("some analyses have more than"):
            warnings.warn(warning.message, warning.category, stacklevel=2)
    if hits.attrs.get("truncated"):
        what = "clumped leads" if clump else "hits"
        warnings.warn(
            f"some analyses have more than {limit:,} {what} at p <= {pval:g}; "
            "only the strongest were returned",
            stacklevel=2,
        )
    absent = (hits.attrs.get("clump") or {}).get("absent") or 0
    if store is not None and absent:
        warnings.warn(
            f"{absent:,} hits are not in the {store['ancestry']} LD store, so were not "
            "clumped or returned",
            stacklevel=2,
        )
    attrs = dict(hits.attrs)
    info = resolved.info
    sizes = dict(zip(info.get("id", []), info.get("sample_size", []), strict=False))
    result = ieugwas_columns(hits, sizes)
    result.attrs.update(attrs)
    return resolved.label(result)
