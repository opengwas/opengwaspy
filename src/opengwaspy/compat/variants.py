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

    ``pval`` is sent to the Data API as its PheWAS ``threshold``, so the server
    returns only the associations that pass it. ieugwaspy's default, 1e-3, is
    sent explicitly: the Data API's own default is 1e-8. If more than 10,000
    associations of one variant pass in one query (of up to 10 Stores), the
    result would be incomplete, so it is refused.

    Args:
        variant: rsIDs, ALIDs, or ``chr:pos`` values (looked up first).
        pval: Largest p-value to keep, above 0 and at most 1.
        batch: Stores to search, by Store ID (see :func:`opengwaspy.batches`).
            Empty searches every Store. OpenGWAS batches such as ``ieu-a`` are
            not Data API Stores, and are refused.

    Returns:
        The associations, with ieugwaspy's column names first. ``attrs`` has
        the ``threshold`` applied.

    Raises:
        UnsupportedOptionError: A ``batch`` that is not a served Store, or more
            associations at ``pval`` than one query returns.
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
        frame.attrs["threshold"] = pval
        return frame
    ids = sorted({f"{s}:{a}" for s, a in zip(frame["store_id"], frame["analysis_id"], strict=True)})
    info = og.gwasinfo(ids)
    sizes = dict(zip(info.get("id", []), info.get("sample_size", []), strict=False))
    result = ieugwas_columns(frame, sizes)
    result.attrs["threshold"] = pval
    return result


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
        warnings.simplefilter("ignore")  # truncation is refused below
        frame = og.phewas(variant, threshold=pval, releases=releases, limit=PHEWAS_MAX_LIMIT)
    if frame.attrs.get("truncated"):
        raise UnsupportedOptionError(
            f"the PheWAS of {variant} has {frame.attrs.get('total', 0):,} associations at "
            f"p <= {pval:g}, more than the API returns in one query ({PHEWAS_MAX_LIMIT:,}). "
            "Use a smaller pval, or choose Stores with batch"
        )
    return frame
