"""ieugwaspy's ``associations``, with LD proxies looked up through the LD stores."""

from __future__ import annotations

import re
import warnings
from collections.abc import Iterable
from typing import Any, cast

import pandas as pd

import opengwaspy as og
from opengwaspy.compat._columns import ieugwas_columns
from opengwaspy.compat._ids import resolve

__all__ = ["associations"]

_RANGE = re.compile(r"^(?:chr)?([0-9A-Za-z_.]+):([0-9]+)-([0-9]+)$", re.IGNORECASE)
_CHRPOS = re.compile(r"^(?:chr)?[0-9A-Za-z_.]+:[0-9]+$", re.IGNORECASE)
_ALID = re.compile(r"^[0-9A-Za-z_.]+:[0-9]+:[A-Za-z*-]+:[A-Za-z*-]+$")
PALINDROMES = {frozenset("AT"), frozenset("CG")}
#: Ancestry used for proxies when an analysis's ancestry has no LD store.
FALLBACK_ANCESTRY = "EUR"
PROXY_COLUMNS = [
    "proxy",
    "target_snp",
    "proxy_snp",
    "proxy_r2",
    "target_a1",
    "target_a2",
    "proxy_a1",
    "proxy_a2",
]


def associations(
    variant: str | Iterable[str],
    id: str | Iterable[str],
    proxies: int = 1,
    r2: float = 0.8,
    align_alleles: int = 1,
    palindromes: int = 1,
    maf_threshold: float = 0.3,
) -> pd.DataFrame:
    """Associations of variants in analyses, with LD proxies, as ieugwaspy's ``associations``.

    With ``proxies=1`` (the default), a variant missing from an analysis is
    replaced by its best proxy that the analysis holds: the variant in highest
    LD (r² ≥ ``r2``) in the LD store of the analysis's ancestry (EUR if that
    ancestry has no store, with a warning).

    Args:
        variant: rsIDs, ALIDs, ``chr:pos`` positions, or ``chr:start-end`` ranges.
            Ranges are not given proxies.
        id: Analysis IDs.
        proxies: ``1`` to look for proxies, ``0`` not to.
        r2: Least r² for a proxy.
        align_alleles: ``1`` to report a proxy's effect against the target's
            alleles (``ea``, ``nea``), through the sign of their LD; ``0`` to
            report the proxy's own alleles.
        palindromes: ``1`` to allow a palindromic proxy (A/T or C/G) when its
            minor allele frequency is below ``maf_threshold``; ``0`` never to
            use one.
        maf_threshold: See ``palindromes``.

    Returns:
        The associations, ieugwaspy's column names first. Proxy rows have
        ``proxy`` true, and ``target_snp``, ``proxy_snp``, ``proxy_r2``,
        ``target_a1``, ``target_a2``, ``proxy_a1`` and ``proxy_a2``. Their
        ``rsid``, ``alid``, ``chr`` and ``position`` are the proxy's.
    """
    variants = [variant] if isinstance(variant, str) else list(variant)
    resolved = resolve(id)
    ids = resolved.ids
    if not ids:
        empty: pd.DataFrame = pd.DataFrame()
        empty.attrs["opengwas_ids"] = resolved.opengwas
        return empty
    frames: list[pd.DataFrame] = []
    points: list[str] = []
    for v in variants:
        match = _RANGE.match(v)
        if match:
            chrom, start, end = match.group(1), int(match.group(2)), int(match.group(3))
            frames.append(og.associations_range(chrom, start, end, ids))
        elif _CHRPOS.match(v):
            found = og.variants_chrpos(v)
            alids = list(dict.fromkeys(found["alid"])) if "alid" in found else []
            if not alids:
                warnings.warn(f"no variant is held at {v}", stacklevel=2)
            points.extend(alids)
        else:
            points.append(v)
    points = list(dict.fromkeys(points))
    direct = og.associations(points, ids) if points else pd.DataFrame()
    frames.insert(0, direct)
    if proxies and points:
        frames.append(
            _proxy_rows(
                points, ids, direct, r2, bool(align_alleles), bool(palindromes), maf_threshold
            )
        )
    non_empty = [f for f in frames if not f.empty]
    frame = pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()
    if frame.empty:
        frame.attrs["opengwas_ids"] = resolved.opengwas
        return frame
    frame["proxy"] = frame["proxy"].fillna(False).astype(bool) if "proxy" in frame else False
    info = resolved.info
    sizes = dict(zip(info.get("id", []), info.get("sample_size", []), strict=False))
    return resolved.label(ieugwas_columns(frame, sizes))


def _found(direct: pd.DataFrame) -> set[tuple[str, str]]:
    """(qualified analysis, variant) pairs present, by rsID and by ALID."""
    pairs: set[tuple[str, str]] = set()
    if direct.empty:
        return pairs
    for row in direct.to_dict("records"):
        analysis = f"{row['store_id']}:{row['analysis_id']}"
        for key in (row.get("alid"), row.get("rsid")):
            if isinstance(key, str):
                pairs.add((analysis, key))
    return pairs


def _target_alids(queries: list[str]) -> dict[str, str]:
    """Each query's ALID: itself if it is one, else looked up by rsID."""
    alids = {q: q for q in queries if _ALID.match(q)}
    rsids = [q for q in queries if q not in alids]
    if rsids:
        found = og.variants_rsid(rsids)
        for rsid in rsids:
            matches = (
                list(dict.fromkeys(found.loc[found["rsid"] == rsid, "alid"]))
                if not found.empty
                else []
            )
            if len(matches) > 1:
                warnings.warn(
                    f"{rsid} has {len(matches)} variants; proxies are for {matches[0]}",
                    stacklevel=4,
                )
            if matches:
                alids[rsid] = str(matches[0])
    return alids


def _ancestries(ids: list[str]) -> dict[str, str]:
    """Qualified analysis ID to the ancestry of the LD store used for its proxies."""
    info = og.gwasinfo(ids)
    served = set(og.ld_stores()["ancestry"].str.upper())
    ancestry: dict[str, str] = {}
    unmatched: set[str] = set()
    for row in info.to_dict("records"):
        wanted = str(row.get("assigned_ancestry") or "").upper()
        if wanted not in served:
            unmatched.add(wanted or "unknown")
            wanted = FALLBACK_ANCESTRY
        ancestry[str(row["id"])] = wanted
    if unmatched:
        warnings.warn(
            f"no LD store for ancestry {', '.join(sorted(unmatched))}; "
            f"proxies for those analyses come from the {FALLBACK_ANCESTRY} store",
            stacklevel=4,
        )
    return ancestry


def _alleles(alid: str) -> tuple[str, str]:
    parts = alid.split(":")
    return parts[2], parts[3]


def _usable(row: dict[str, Any], palindromes: bool, maf_threshold: float) -> bool:
    a1, a2 = _alleles(str(row["alid"]))
    if frozenset((a1.upper(), a2.upper())) not in PALINDROMES:
        return True
    if not palindromes:
        return False
    eaf = row.get("eaf")
    if eaf is None or pd.isna(eaf):
        return False
    return min(float(eaf), 1 - float(eaf)) < maf_threshold


def _proxy_rows(
    queries: list[str],
    ids: list[str],
    direct: pd.DataFrame,
    r2: float,
    align: bool,
    palindromes: bool,
    maf_threshold: float,
) -> pd.DataFrame:
    ancestry = _ancestries(ids)
    found = _found(direct)
    missing = [(a, q) for a in ancestry for q in queries if (a, q) not in found]
    if not missing:
        return _frame([])
    targets = _target_alids(sorted({q for _, q in missing}))
    rows: list[dict[str, Any]] = []
    for anc in sorted(set(ancestry.values())):
        analyses = [a for a in ancestry if ancestry[a] == anc]
        wanted = [(a, q) for a, q in missing if a in analyses and q in targets]
        if not wanted:
            continue
        target_alids = sorted({targets[q] for _, q in wanted})
        candidates = og.ld_proxies(target_alids, r2=r2, ancestry=anc)
        if candidates.empty:
            continue
        candidates = candidates.sort_values(["r2", "distance"], ascending=[False, True])
        lookup = og.associations(list(dict.fromkeys(candidates["proxy"])), analyses)
        records = cast("list[dict[str, Any]]", lookup.to_dict("records"))
        held = {(f"{r['store_id']}:{r['analysis_id']}", r["alid"]): r for r in records}
        for analysis, query in wanted:
            target = targets[query]
            options = candidates[candidates["query"] == target].to_dict("records")
            for proxy in cast("list[dict[str, Any]]", options):
                row = held.get((analysis, proxy["proxy"]))
                if row is not None and _usable(row, palindromes, maf_threshold):
                    rows.append(_as_proxy(row, query, target, proxy, align))
                    break
    return _frame(rows)


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame: pd.DataFrame = pd.DataFrame.from_records(rows) if rows else pd.DataFrame()
    return frame


def _as_proxy(
    row: dict[str, Any], query: str, target: str, proxy: dict[str, Any], align: bool
) -> dict[str, Any]:
    t1, t2 = _alleles(target)
    p1, p2 = _alleles(str(proxy["proxy"]))
    out = dict(row)
    out.update(
        proxy=True,
        target_snp=query,
        proxy_snp=row.get("rsid") or row["alid"],
        proxy_r2=float(proxy["r2"]),
        target_a1=t1,
        target_a2=t2,
        proxy_a1=p1,
        proxy_a2=p2,
    )
    if align:
        # Positive r pairs the first alleles of the two ALIDs; negative r crosses them.
        tags_first = (row["effect_allele"] == p1) == (float(proxy["r"]) > 0)
        tagged = t1 if tags_first else t2
        out["effect_allele"] = tagged
        out["other_allele"] = t2 if tagged == t1 else t1
    return out
