"""OpenGWAS IDs and batches, translated through the Data API's own resolution."""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

import opengwaspy as og
from opengwaspy.client import Client
from opengwaspy.errors import UnsupportedOptionError

_LEGACY = {"UKB-a:": "ukb-a-", "UKB-b:": "ukb-b-", "UKB-c:": "ukb-c-", "IEU-a:": "ieu-a-"}

#: What a successor match means, for warnings.
SUCCESSOR = "a later release than OpenGWAS held, so the numbers may differ"


def legacy_ids(study_ids: list[str]) -> list[str]:
    """Convert legacy OpenGWAS study IDs (``UKB-a:``, ``IEU-a:``) to the newer form."""
    result = []
    for study in study_ids:
        for old, new in _LEGACY.items():
            study = study.replace(old, new)
        result.append(study)
    return result


@dataclass
class Resolved:
    """Requested IDs, resolved to Data API analysis IDs.

    Attributes:
        ids: Store-qualified analysis IDs, in the order requested, each once.
        requested: For each analysis ID, the ID it was requested by.
        opengwas: How each OpenGWAS ID was translated (``id``, ``analyses``,
            ``match``), or why it was not (``id``, ``reason``).
        info: The analyses' metadata.
    """

    ids: list[str] = field(default_factory=list)
    requested: dict[str, str] = field(default_factory=dict)
    opengwas: list[dict[str, Any]] = field(default_factory=list)
    info: pd.DataFrame = field(default_factory=pd.DataFrame)

    def label(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Add ``opengwas_id`` (the ID each row's analysis was asked for, last) and provenance."""
        if not frame.empty and "id" in frame.columns:
            frame["opengwas_id"] = [self.requested.get(i, i) for i in frame["id"]]
        frame.attrs["opengwas_ids"] = self.opengwas
        return frame


def resolve(
    ids: str | Iterable[str],
    *,
    stacklevel: int = 3,
    warn: bool = True,
    client: Client | None = None,
) -> Resolved:
    """Translate analysis IDs, OpenGWAS IDs among them, with one ``gwasinfo`` lookup.

    Store-qualified and bare Data API IDs pass through. OpenGWAS IDs become the
    analyses the API resolves them to. A successor match is used with a warning;
    an ID nothing resolves is left out, with a warning giving the API's reason.
    With ``warn=False``, the caller reports these from ``Resolved.opengwas``.
    """
    wanted = legacy_ids([ids] if isinstance(ids, str) else list(ids))
    resolved = Resolved()
    if not wanted:
        return resolved
    info = og.gwasinfo(wanted, client=client)
    resolved.info = info
    entries = {str(e.get("id")): e for e in info.attrs.get("opengwas") or []}
    rows = info.to_dict("records")
    successors: list[str] = []
    missing: list[str] = []

    def add(analysis: str, requested: str) -> None:
        if analysis not in resolved.requested:
            resolved.requested[analysis] = requested
            resolved.ids.append(analysis)

    for request in wanted:
        entry = entries.get(request)
        if entry is not None:
            analyses = [str(a) for a in entry.get("catalog_ids") or []]
            if analyses and entry.get("match"):
                for analysis in analyses:
                    add(analysis, request)
                resolved.opengwas.append(
                    {"id": request, "analyses": analyses, "match": entry["match"]}
                )
                if entry["match"] == "successor":
                    successors.append(f"{request} -> {', '.join(analyses)}")
                continue
            reason = str(entry.get("reason") or "not held by any Store")
            resolved.opengwas.append({"id": request, "reason": reason})
            missing.append(f"{request} ({reason})")
            continue
        key = "id" if ":" in request else "analysis_id"
        matched = [str(r["id"]) for r in rows if str(r.get(key)) == request]
        if matched:
            for analysis in matched:
                add(analysis, request)
        else:
            reason = "not served by the Data API"
            resolved.opengwas.append({"id": request, "reason": reason})
            missing.append(f"{request} ({reason})")
    if successors and warn:
        warnings.warn(
            "OpenGWAS IDs translated to a successor analysis, "
            + SUCCESSOR
            + ": "
            + "; ".join(successors),
            stacklevel=stacklevel,
        )
    if missing and warn:
        shown = "; ".join(missing[:10]) + (" ..." if len(missing) > 10 else "")
        warnings.warn(f"{len(missing)} IDs are left out: {shown}", stacklevel=stacklevel)
    return resolved


def resolve_batches(batch: Iterable[str], *, stacklevel: int = 3) -> list[str] | None:
    """Store IDs for ``batch``: Data API Store IDs, or OpenGWAS batches such as ``ebi-a``.

    Returns:
        The Store IDs, in order, each once; ``None`` for an empty ``batch`` (every Store).

    Raises:
        UnsupportedOptionError: A batch that is neither a served Store nor an
            OpenGWAS batch the API resolves.
    """
    wanted = list(batch)
    if not wanted:
        return None
    batches = og.batches()
    served = set(batches["store_id"]) if "store_id" in batches else set()
    opengwas = {str(b["batch"]): b for b in batches.attrs.get("opengwas_batches") or []}
    stores: list[str] = []
    successors: list[str] = []
    unknown: list[str] = []
    for name in wanted:
        if name in served:
            found = [name]
        elif name in opengwas:
            found = [str(s) for s in opengwas[name].get("store_ids") or []]
            if opengwas[name].get("match") == "successor":
                successors.append(f"{name} -> {', '.join(found)}")
        else:
            unknown.append(name)
            continue
        stores.extend(s for s in found if s not in stores)
    if unknown:
        held = ", ".join(sorted(opengwas)) or "none"
        raise UnsupportedOptionError(
            f"batch {', '.join(unknown)} is neither a Data API Store nor an OpenGWAS batch "
            f"the Data API holds. OpenGWAS batches it holds: {held}; "
            f"Stores: {', '.join(sorted(served))}"
        )
    if successors:
        warnings.warn(
            "OpenGWAS batches translated to successor Stores, "
            + SUCCESSOR
            + ": "
            + "; ".join(successors),
            stacklevel=stacklevel,
        )
    return stores
