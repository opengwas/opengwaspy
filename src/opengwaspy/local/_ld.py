"""Downloaded LD Stores and Genotype Stores in a Local Source, read with ``ogquery.ld``.

The operations port ogdb-api's ``ld_operations.py``, so their rows and metadata
are the Data API's: a pair a store does not hold is ``None`` (never 0) unless
the caller passes ``fill``, and a request a store cannot answer exactly is
refused with :class:`~opengwaspy.LDRefusal`, naming its reason.
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opengwaspy.errors import LDRefusal, OpenGWASError, RequestError

__all__ = ["LD_ENDPOINTS", "LocalLDStore", "answer_ld", "choose", "open_ld"]

LD_ENDPOINTS = (
    "api/ld/matrix",
    "api/ld/region",
    "api/ld/clump",
    "api/ld/proxies",
    "api/ld/reflookup",
)


class LocalLDError(OpenGWASError, ValueError):
    """A path cannot be opened as an LD Store or Genotype Store."""


@dataclass
class LocalLDStore:
    """One LD Store or Genotype Store opened for a Local Source.

    Attributes:
        name: Its directory's name, without ``.store`` (as the API names stores).
        path: Where it is on disk.
        ancestry: Its panel's ancestry, from its provenance.
        kind: ``ld_store`` or ``genotype_store``.
    """

    name: str
    path: Path
    ancestry: str
    kind: str
    provenance: dict[str, Any] = field(repr=False)
    store: Any = field(repr=False)
    reader_version: str = field(repr=False, default="")

    def close(self) -> None:
        """Let go of the store's files."""
        close = getattr(self.store, "close", None)
        if close is not None:
            close()

    def facts(self) -> dict[str, Any]:
        """The store facts every LD result and refusal carries, as the API gives them."""
        p = self.provenance
        return {
            "store": self.name,
            "ancestry": self.ancestry,
            "t_far": float(p["t_far"]),
            "t_partner": float(p["t_partner"]) if p.get("t_partner") is not None else None,
            "near_bp": int(p["near_bp"]),
            "far_bp": int(p["far_bp"]),
        }

    def listing(self) -> dict[str, Any]:
        """The store as ``ld_stores()`` lists it."""
        p = self.provenance
        panel = p["panel"]
        return {
            "store": self.name,
            "ancestry": self.ancestry,
            "ready": True,
            "panel": str(panel["id"]),
            "n": int(panel["n"]),
            "k": int(p["adjustment"]["k"]),
            "t_far": float(p["t_far"]),
            "near_bp": int(p["near_bp"]),
            "far_bp": int(p["far_bp"]),
            "n_variants": int(p["n_variants"]),
            "format_version": str(p["format_version"]),
            "encoding": dict(p["encoding"]),
            "kind": self.kind,
            "t_partner": float(p["t_partner"]) if p.get("t_partner") is not None else None,
            "reader_version": self.reader_version,
            "path": str(self.path),
        }


def open_ld(path: str | Path) -> LocalLDStore:
    """Open an LD Store or Genotype Store from a local path."""
    ld = importlib.import_module("ogquery.ld")
    opening = importlib.import_module("ogquery.opening")
    version = str(getattr(importlib.import_module("ogquery"), "__version__", ""))
    where = Path(path).expanduser()
    if not where.exists():
        raise LocalLDError(f"no LD Store at {where}")
    try:
        store = ld.open(str(where), cache_bytes=None)
    except opening.GenotypeExtraMissing as exc:
        raise LocalLDError(
            f"{where} is a Genotype Store, read with ogquery's genotype extra (pgenlib; Linux "
            f'and macOS): pip install "opengwaspy[local-genotype]" ({exc})'
        ) from exc
    except ld.InputError as exc:
        raise LocalLDError(
            f"{where} cannot be opened: {exc}. A Genotype Store pins its pgen files' size, "
            "checksum and modification time: unpack them keeping their times (tar keeps them)"
        ) from exc
    except Exception as exc:
        raise LocalLDError(f"{where} cannot be opened as an LD Store: {exc}") from exc
    provenance = dict(store.provenance)
    return LocalLDStore(
        name=where.name.removesuffix(".store"),
        path=where,
        ancestry=str(provenance["panel"]["ancestry"]),
        kind="genotype_store" if "filesets" in provenance else "ld_store",
        provenance=provenance,
        store=store,
        reader_version=version,
    )


def choose(stores: Sequence[LocalLDStore], body: Mapping[str, Any]) -> LocalLDStore:
    """The store a request names, by ``store`` (its name) or ``ancestry``."""
    if body.get("store") is not None:
        name = str(body["store"])
        match = [s for s in stores if s.name == name]
        if match:
            return match[0]
        raise RequestError(404, "ld_store_not_found", f"no LD Store named {name} is open")
    ancestry = str(body.get("ancestry") or "").upper()
    match = [s for s in stores if s.ancestry.upper() == ancestry]
    if len(match) == 1:
        return match[0]
    if match:
        names = ", ".join(s.name for s in match)
        raise RequestError(
            409,
            "ambiguous_ld_store",
            f"several open LD Stores are {ancestry} ({names}); name one with store=",
        )
    served = ", ".join(sorted({s.ancestry for s in stores})) or "none"
    raise RequestError(
        404, "ld_store_not_found", f"no open LD Store is {ancestry or '?'} (open: {served})"
    )


def answer_ld(
    store: LocalLDStore, endpoint: str, body: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run one LD request on ``store``: the API's rows and metadata, with the store's facts."""
    ld = importlib.import_module("ogquery.ld")
    alid = importlib.import_module("ogquery.alid")
    operation = _OPERATIONS[endpoint]
    try:
        rows, meta = operation(store.store, body)
    except ld.Refusal as exc:
        raise LDRefusal(
            422,
            "ld_refusal",
            f"ld_refusal ({exc.reason.value}): {exc.detail}",
            extra={"reason": exc.reason.value, **store.facts()},
        ) from exc
    except (ld.InputError, alid.ReferenceFirstIndel) as exc:
        raise RequestError(400, "invalid_query", str(exc)) from exc
    return rows, {**meta, **store.facts()}


def _r(value: float) -> float | None:
    return None if math.isnan(value) else float(value)


def _matrix_rows(result: Any) -> list[dict[str, Any]]:
    v = result.variants
    return [
        {
            "alid": str(v.alid[i]),
            "chromosome": str(v.chrom[i]),
            "position": int(v.position[i]),
            "a1": str(v.a1[i]),
            "a2": str(v.a2[i]),
            "r": [_r(value) for value in result.r[i]],
        }
        for i in range(len(v.alid))
    ]


def _matrix_meta(result: Any) -> dict[str, Any]:
    return {
        "absent": list(result.absent),
        "fill": result.fill,
        "variants": len(result.variants.alid),
    }


def _matrix(store: Any, body: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result = store.matrix(list(body["alids"]), fill=body.get("fill"))
    return _matrix_rows(result), _matrix_meta(result)


def _region(store: Any, body: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalise = importlib.import_module("ogquery.identity").normalise_chromosome
    result = store.region(
        normalise(str(body["chromosome"])),
        int(body["centre"]),
        int(body["radius"]),
        fill=body.get("fill"),
    )
    return _matrix_rows(result), _matrix_meta(result)


def _clump(store: Any, body: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    r2, kb = float(body["r2"]), float(body["kb"])
    result = store.clump(list(body["alids"]), list(body["scores"]), r2=r2, kb=kb)
    rows = [
        {
            "alid": str(result.alid[i]),
            "chromosome": str(result.chrom[i]),
            "position": int(result.position[i]),
            "score": float(result.score[i]),
            "lead": str(result.lead[i]),
            "r": _r(result.r[i]),
        }
        for i in range(len(result.alid))
    ]
    leads = sum(1 for row in rows if row["lead"] == row["alid"])
    meta = {
        "absent": list(result.absent),
        "r2": r2,
        "kb": kb,
        "window_bp": float(result.window_bp),
        "leads": leads,
        "variants": len(rows),
    }
    return rows, meta


def _proxies(store: Any, body: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    alids = list(body["alids"])
    result = store.proxies(alids, r2=float(body.get("r2", 0.8)), kb=float(body.get("kb", 10_000)))
    rows = [
        {
            "query": str(result.query[i]),
            "proxy": str(result.proxy[i]),
            "r": float(result.r[i]),
            "r2": float(result.r2[i]),
            "distance": int(result.distance[i]),
        }
        for i in range(len(result))
    ]
    meta = {
        "absent": list(result.absent),
        "r2": float(result.r2_min),
        "window_bp": float(result.window_bp),
        "variants": len(alids) - len(result.absent),
    }
    return rows, meta


def _reflookup(store: Any, body: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    alids = list(body["alids"])
    found = store.has(alids)
    rows = [{"alid": a, "present": bool(present)} for a, present in zip(alids, found, strict=True)]
    meta = {
        "absent": [row["alid"] for row in rows if not row["present"]],
        "variants": sum(row["present"] for row in rows),
    }
    return rows, meta


_OPERATIONS = {
    "api/ld/matrix": _matrix,
    "api/ld/region": _region,
    "api/ld/clump": _clump,
    "api/ld/proxies": _proxies,
    "api/ld/reflookup": _reflookup,
}
