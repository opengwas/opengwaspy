"""Clumped top hits on a Local Source: stored Clumps, or clumping on the fly in an LD Store.

Ports ogdb-api's ``stored_clumps.py`` (``read_facts``, ``answers``, ``stored_leads``),
``main.clump_plan`` and ``ld_clump.clump_hits`` (ogdb-api#146, #197), so the leads, their
``clump_size`` and ``clump_source``, and ``metadata.clump`` are the API's:

- ``clump: {}`` at 5e-8 answers from a release's stored Clumps, in the release's own
  configuration; an explicit ``r2`` or ``kb`` uses them only on an exact match;
- any other request, and a release without stored Clumps, clumps on the fly (r² 0.001
  within 3,000 kb by default) in an open LD Store: the one the request names, else the
  analysis's ``assigned_ancestry``, else EUR.
"""

from __future__ import annotations

import functools
import importlib
import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from opengwaspy.errors import LDRefusal, RequestError

if TYPE_CHECKING:
    from opengwaspy.local._ld import LocalLDStore
    from opengwaspy.local._source import LocalRelease

__all__ = ["clump_answer"]

#: The tier stored Clumps are made for (Store spec §18.1).
STORED_THRESHOLD = 5e-8
#: The configuration fields every provenance carries, from the ``clumps`` attribute.
CONFIGURATION_KEYS = (
    "configuration",
    "threshold",
    "score",
    "ties",
    "kb",
    "join",
    "opengwasdb",
    "created_at",
)
#: Each LD resource's fields kept (the attribute's ``ld_stores`` entries).
RESOURCE_KEYS = (
    "name",
    "kind",
    "format_version",
    "samples_sha256",
    "k",
    "r2",
    "t_far",
    "t_partner",
    "near_bp",
    "far_bp",
    "reference_assembly",
    "n",
)
MARKERS = {-1: "absent", -2: "imputed", -3: "ambiguous", -4: "not_clumped"}
R2_TOLERANCE = 1e-9
DEFAULT_R2 = 0.001
DEFAULT_KB = 3000.0

Rows = list[dict[str, Any]]


def _components(release: LocalRelease) -> list[tuple[str, Any]]:
    """The parts of a release that carry a Top-Hit tier: a Hybrid's two, else itself."""
    store = release.store
    if release.layout.lower().endswith("hybrid"):
        return [("dense", store.dense_component()), ("overflow", store)]
    return [("store", store)]


def stored_facts(release: LocalRelease) -> dict[str, Any] | None:
    """The release's stored-Clumps configuration, or None where it has none.

    Malformed Clumps count as none, so the hits are clumped on the fly rather than
    refused, as the API does.
    """
    try:
        if not release.store.manifest.clumps:
            return None
        configurations = []
        for name, component in _components(release):
            tier = component.top_hit_tiers().tier(STORED_THRESHOLD)
            if tier is None or not tier.clumps_declared:
                return None
            stored = tier.clumps(-1)  # an empty slice: the configuration's attribute alone
            if stored is None:
                return None
            configurations.append((name, dict(stored.attribute)))
    except Exception:  # MalformedClumps, or a tier the reader cannot open
        return None
    attribute = configurations[0][1]
    facts: dict[str, Any] = {key: attribute.get(key) for key in CONFIGURATION_KEYS}
    facts["ld_stores"] = {
        ancestry: {key: entry.get(key) for key in RESOURCE_KEYS}
        for ancestry, entry in sorted((attribute.get("ld_stores") or {}).items())
    }
    facts["components"] = [name for name, _ in configurations]
    return facts


def _answers(
    facts: Mapping[str, Any] | None,
    clump: Mapping[str, Any],
    r2: float,
    kb: float,
    threshold: float,
    ancestries: set[str],
    named: LocalLDStore | None,
) -> bool:
    """Whether stored Clumps answer this request for a release (the owner's rule, ogdb-api#197)."""
    if not facts or not math.isclose(
        float(threshold), float(facts.get("threshold") or 0), rel_tol=1e-12
    ):
        return False
    resources = facts.get("ld_stores") or {}
    if named is not None:
        entry = resources.get(named.ancestry)
        panel = named.provenance.get("panel") or {}
        k = (named.provenance.get("adjustment") or {}).get("k")
        if entry is None or entry.get("samples_sha256") != panel.get("samples_sha256"):
            return False
        if entry.get("k") != k:
            return False
    if not {"r2", "kb"} & set(clump):
        return True
    if float(kb) != float(facts.get("kb") or -1):
        return False
    for ancestry in ancestries:
        entry = resources.get(ancestry)
        if entry is None or entry.get("r2") is None:
            return False
        if not math.isclose(float(r2), float(entry["r2"]), rel_tol=R2_TOLERANCE):
            return False
    return True


def _strength(row: Mapping[str, Any]) -> float:
    z = row.get("z")
    if not isinstance(z, (int, float)) or not math.isfinite(z):
        return -1.0
    return abs(float(z))


def _lead_key(row: Mapping[str, Any]) -> tuple[float, str, int]:
    return (-_strength(row), str(row.get("chromosome")), int(row.get("position") or 0))


def _lead_of(release: LocalRelease, analysis_id: str) -> dict[str, str]:
    """Each tier row's ALID → its lead's ALID, or its marker's name, for one Analysis."""
    import numpy as np

    row = release.analyses.get(analysis_id)
    if row is None:
        return {}
    analysis_index = int(row["analysis_index"])
    alids: list[str] = []
    leads: list[int] = []
    for _, component in _components(release):
        tier = component.top_hit_tiers().tier(STORED_THRESHOLD)
        stored = tier.clumps(analysis_index)
        variant_index = np.asarray(tier.read(analysis_index).variant_index)
        if len(stored.lead) != len(variant_index):
            raise RequestError(
                500,
                "stored_clumps",
                f"stored Clumps of {release.path} do not cover the tier's rows",
            )
        axis = component.variant_axis(aliases=False)
        try:
            alids.extend(str(a) for a in axis.identity_by_indices(variant_index)["alid"])
        finally:
            axis.close()
        leads.extend(int(lead) for lead in stored.lead)
    return {
        alid: (alids[lead] if lead >= 0 else MARKERS.get(lead, "not_clumped"))
        for alid, lead in zip(alids, leads, strict=True)
    }


def _stored_leads(
    release: LocalRelease,
    raw: Any,
    analysis_id: str,
    limit: int,
    resolve: Callable[[Any], Rows],
) -> tuple[Rows, dict[str, Any]]:
    """An Analysis's hits at 5e-8 cut to its stored Clumps' leads, strongest first."""
    import numpy as np

    lead_of = _lead_of(release, analysis_id)
    axis = release.store.variant_axis(aliases=False)
    try:
        alids = [str(a) for a in axis.identity_by_indices(np.asarray(raw["variant_index"]))["alid"]]
    finally:
        axis.close()
    keep = np.array([i for i, a in enumerate(alids) if lead_of.get(a) == a], dtype=np.int64)
    rows = resolve(raw.take(keep)) if len(keep) else []
    sizes = Counter(lead for lead in lead_of.values() if lead not in MARKERS.values())
    marked = Counter(lead for lead in lead_of.values() if lead in MARKERS.values())
    rows.sort(key=_lead_key)
    counts: dict[str, Any] = {
        "hits": len(alids),
        "leads": len(rows),
        "truncated": len(rows) > limit,
        **{name: marked.get(name, 0) for name in MARKERS.values()},
    }
    out = [{**r, "clump_size": sizes[r["alid"]], "clump_source": "stored"} for r in rows[:limit]]
    return out, counts


def _clump_rows(
    store: LocalLDStore, rows: Rows, r2: float, kb: float, limit: int
) -> tuple[Rows, int, int, bool]:
    """One analysis's hits clumped in ``store``.

    Returns its leads (with ``clump_size``), the leads found, the hits absent from
    the store, and whether ``limit`` cut the leads.
    """
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        if _strength(row) >= 0 and (
            row["alid"] not in best or _strength(row) > _strength(best[row["alid"]])
        ):
            best[row["alid"]] = row
    if not best:
        return [], 0, 0, False
    ld = importlib.import_module("ogquery.ld")
    alids = list(best)
    try:
        result = store.store.clump(alids, [_strength(best[a]) for a in alids], r2=r2, kb=kb)
    except ld.Refusal as exc:
        raise LDRefusal(
            422,
            "ld_refusal",
            f"ld_refusal ({exc.reason.value}): {exc.detail}",
            extra={"reason": exc.reason.value, **store.facts()},
        ) from exc
    lead_of = {str(a): str(lead) for a, lead in zip(result.alid, result.lead, strict=True)}
    sizes = Counter(lead_of.values())
    leads = [best[a] for a in alids if lead_of.get(a) == a]
    leads.sort(key=_lead_key)
    out = [
        {**row, "clump_size": sizes[row["alid"]], "clump_source": "computed"}
        for row in leads[:limit]
    ]
    return out, len(leads), len(result.absent), len(leads) > limit


def clump_answer(
    body: Mapping[str, Any],
    releases: Sequence[tuple[LocalRelease, list[str] | None]],
    ld_stores: Sequence[LocalLDStore],
    hits_of: Callable[[LocalRelease, str, float, bool], Any],
    resolve: Callable[[LocalRelease, Any], Rows],
) -> tuple[Rows, dict[str, Any]]:
    """Clumped top hits, as the API answers ``/api/tophits`` with ``clump``.

    ``hits_of(release, analysis, threshold, observed_only)`` reads an analysis's hits
    at exactly ``threshold`` (the reader's arrays), and ``resolve`` turns them into API rows.
    """
    from opengwaspy.local._ld import choose

    clump = dict(body.get("clump") or {})
    threshold = float(body.get("threshold", 5e-8))
    limit = int(body.get("limit", 1000))
    observed_only = bool(body.get("observed_only", False))
    r2 = float(clump.get("r2", DEFAULT_R2))
    kb = float(clump.get("kb", DEFAULT_KB))
    if any(analyses is None for _, analyses in releases):
        raise RequestError(400, "invalid_query", "analyses is required with clump")
    named = None
    if clump.get("store") is not None or clump.get("ancestry") is not None:
        named = choose(ld_stores, clump)
    served = {s.ancestry for s in ld_stores}
    fallback = named.ancestry if named is not None else "EUR"

    def ancestry_of(release: LocalRelease, analysis: str) -> str:
        if named is not None:
            return named.ancestry
        assigned = str(release.analyses.get(analysis, {}).get("assigned_ancestry") or "")
        return assigned if assigned in served else fallback

    stored_rows: Rows = []
    stored_releases: dict[str, Any] = {}
    computed: list[tuple[LocalRelease, list[str]]] = []
    for release, analyses in releases:
        ids = list(analyses or [])
        ancestries = {ancestry_of(release, a) for a in ids} or {fallback}
        facts = stored_facts(release)
        if _answers(facts, clump, r2, kb, threshold, ancestries, named):
            counts: dict[str, int] = {}
            truncated = False
            for analysis in ids:
                raw = hits_of(release, analysis, threshold, observed_only)
                found, tally = _stored_leads(
                    release, raw, analysis, limit, functools.partial(resolve, release)
                )
                stored_rows.extend(found)
                truncated = truncated or bool(tally.pop("truncated"))
                for name, value in tally.items():
                    counts[name] = counts.get(name, 0) + int(value)
            key = f"{release.store_id}/{release.release_id}"
            assert facts is not None
            stored_releases[key] = {
                "configuration": {
                    k: facts.get(k) for k in (*CONFIGURATION_KEYS, "components", "ld_stores")
                },
                **counts,
                "truncated": truncated,
            }
        else:
            computed.append((release, ids))

    computed_rows: Rows = []
    hits = leads_found = absent = 0
    truncated = False
    used: dict[str, str] = {}
    for release, ids in computed:
        for analysis in ids:
            ancestry = ancestry_of(release, analysis)
            store = named if named is not None else _store_for(ld_stores, ancestry)
            rows = resolve(release, hits_of(release, analysis, threshold, observed_only))
            hits += len(rows)
            leads, n_leads, n_absent, cut = _clump_rows(store, rows, r2, kb, limit)
            if rows:
                used[store.ancestry] = store.name
            computed_rows.extend(leads)
            leads_found += n_leads
            absent += n_absent
            truncated = truncated or cut

    source = "stored" if not computed else ("mixed" if stored_releases else "computed")
    truncated = truncated or any(item["truncated"] for item in stored_releases.values())
    clump_meta: dict[str, Any] = {
        "source": source,
        "r2": r2 if computed else None,
        "kb": kb if computed else None,
        "hits": hits,
        "leads": leads_found,
        "absent": absent,
        "ld_stores": dict(sorted(used.items())),
        "stored": {
            key: {k: v for k, v in item.items() if k != "truncated"}
            for key, item in stored_releases.items()
        },
    }
    rows = computed_rows + stored_rows
    meta = {
        "threshold": threshold,
        "observed_only": observed_only,
        "total": len(rows),
        "truncated": truncated,
        "clump": clump_meta,
    }
    return rows, meta


def _store_for(ld_stores: Sequence[LocalLDStore], ancestry: str) -> LocalLDStore:
    """The one open LD Store of ``ancestry``, to clump an analysis in on the fly."""
    match = [s for s in ld_stores if s.ancestry == ancestry]
    if len(match) == 1:
        return match[0]
    if match:
        names = ", ".join(s.name for s in match)
        raise RequestError(
            409,
            "ambiguous_ld_store",
            f"several open LD Stores are {ancestry} ({names}); name one in clump (store=)",
        )
    raise RequestError(
        404,
        "ld_store_not_found",
        f"no LD Store is open for {ancestry}, the ancestry to clump in: open one with "
        "og.local(..., ld=[...]), or name one in clump",
    )
