"""ieugwaspy's ``phewas`` and variant helpers."""

from __future__ import annotations

import re
import warnings
from collections.abc import Iterable

import pandas as pd

import opengwaspy as og
from opengwaspy.compat._columns import ieugwas_columns
from opengwaspy.errors import UnsupportedOptionError

__all__ = ["phewas", "variants_chrpos", "variants_to_rsid"]

#: The API's largest PheWAS ``limit``.
PHEWAS_MAX_LIMIT = 10_000
_CHRPOS = re.compile(r"^(?:chr)?[0-9A-Za-z_.]+:[0-9]+$", re.IGNORECASE)


def variants_chrpos(chrpos: str) -> str | None:
    """The rsID at a ``chr:pos`` position, as ieugwaspy's ``variants_chrpos``.

    Only the first rsID is returned, as ieugwaspy did. A warning says when the
    position has several.

    Returns:
        The rsID, or ``None`` if no served Store has a variant with an rsID there.
    """
    found = og.variants_chrpos(chrpos)
    rsids = list(dict.fromkeys(found["rsid"].dropna())) if "rsid" in found else []
    if len(rsids) > 1:
        warnings.warn(
            f"{chrpos} has {len(rsids)} rsIDs ({', '.join(rsids)}); returning the first",
            stacklevel=2,
        )
    return rsids[0] if rsids else None


def variants_to_rsid(variants: list[str]) -> list[str]:
    """Replace ``chr:pos`` values with rsIDs, leaving rsIDs as they are.

    Unlike ieugwaspy, the list passed in is not changed: a new list is returned.
    A position with no rsID is kept as it is, with a warning.
    """
    result = []
    for variant in variants:
        if _CHRPOS.match(variant):
            rsid = variants_chrpos(variant)
            if rsid is None:
                warnings.warn(f"no rsID found at {variant}; kept as it is", stacklevel=2)
                rsid = variant
            result.append(rsid)
        else:
            result.append(variant)
    return result


def phewas(
    variant: str | Iterable[str],
    pval: float = 1e-3,
    batch: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Every association of variants with ``p <= pval``, as ieugwaspy's ``phewas``.

    The Data API has no p-value filter, so each variant's PheWAS is fetched in
    full and filtered here. If a result is cut short at the API's limit, the
    query is rerun one Store at a time with the largest limit (10,000 rows). If
    a Store's result is still cut short, the filter could miss associations, so
    it is refused.

    Args:
        variant: rsIDs, ALIDs, or ``chr:pos`` values (looked up first).
        pval: Largest p-value to keep.
        batch: Stores to search, by Store ID (see :func:`opengwaspy.batches`).
            Empty searches every Store. OpenGWAS batches such as ``ieu-a`` are
            not Data API Stores, and are refused.

    Returns:
        The associations, with ieugwaspy's column names first.

    Raises:
        UnsupportedOptionError: A ``batch`` that is not a served Store, or a
            result too large to filter completely.
    """
    variants = [variant] if isinstance(variant, str) else list(variant)
    queries = [_as_query(v) for v in variants]
    releases = _releases(list(batch or []))
    frames = []
    for original, query in zip(variants, queries, strict=True):
        if query is None:
            warnings.warn(f"{original} is not a variant any Store holds; skipped", stacklevel=2)
            continue
        frames.append(_filtered(query, pval, releases))
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if frame.empty:
        return frame
    ids = sorted({f"{s}:{a}" for s, a in zip(frame["store_id"], frame["analysis_id"], strict=True)})
    info = og.gwasinfo(ids)
    sizes = dict(zip(info.get("id", []), info.get("sample_size", []), strict=False))
    return ieugwas_columns(frame, sizes)


def _as_query(variant: str) -> str | None:
    if _CHRPOS.match(variant):
        found = og.variants_chrpos(variant)
        alids = list(dict.fromkeys(found["alid"])) if "alid" in found else []
        if not alids:
            return None
        if len(alids) > 1:
            warnings.warn(
                f"{variant} holds {len(alids)} variants ({', '.join(alids)}); using {alids[0]}",
                stacklevel=3,
            )
        return str(alids[0])
    return variant


def _releases(batch: list[str]) -> list[str] | None:
    if not batch:
        return None
    served = og.get_client().served_releases()
    unknown = [b for b in batch if b not in served]
    if unknown:
        raise UnsupportedOptionError(
            f"batch {', '.join(unknown)} is not a Data API Store. OpenGWAS batches such as "
            f"ieu-a are not Stores; choose from {', '.join(sorted(served))}, or leave batch empty"
        )
    return batch


def _filtered(variant: str, pval: float, releases: list[str] | None) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # truncation is handled here
        frame = og.phewas(variant, releases=releases)
        if frame.attrs.get("truncated"):
            frame = _per_store(variant, releases)
    if frame.empty:
        return frame
    kept: pd.DataFrame = frame[frame["p"] <= pval].reset_index(drop=True)
    kept.attrs.update(frame.attrs)
    return kept


def _per_store(variant: str, releases: list[str] | None) -> pd.DataFrame:
    """Rerun a truncated PheWAS one Store at a time, at the API's largest limit."""
    stores = releases or sorted(og.get_client().served_releases())
    frames = []
    for store in stores:
        frame = og.phewas(variant, releases=[store], limit=PHEWAS_MAX_LIMIT)
        if frame.attrs.get("truncated"):
            raise UnsupportedOptionError(
                f"the PheWAS of {variant} in Store {store} has "
                f"{frame.attrs.get('total', 0):,} associations, more than the API returns "
                f"in one query ({PHEWAS_MAX_LIMIT:,}), so filtering by p-value could miss "
                "some. Use opengwaspy.phewas with analyses= to search fewer analyses"
            )
        frames.append(frame)
    non_empty = [f for f in frames if not f.empty]
    return pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()
