"""LD tools: proxies of variants, and the LD matrix between variants."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Annotated, Any

import pandas as pd
from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from opengwaspy.client import Client
from opengwaspy.ld import ld_matrix, ld_proxies
from opengwaspy.mcp.formatting import (
    ColumnChoice,
    MaxRows,
    Overwrite,
    SaveAs,
    TableResult,
    table_result,
)
from opengwaspy.mcp.server import (
    READ_ONLY,
    Session,
    arguments,
    deliver,
    session_of,
    watched,
)
from opengwaspy.variants import variants_rsid

__all__ = ["MATRIX_MAX", "PROXIES_MAX", "register", "to_alids"]

#: The most variants ``ld_proxies`` takes.
PROXIES_MAX = 100
#: The most variants ``ld_matrix`` takes.
MATRIX_MAX = 50

_ALID = re.compile(r"(chr)?[0-9A-Za-z]+:[0-9]+:[A-Za-z*-]+:[A-Za-z*-]+")
_RSID = re.compile(r"rs[0-9]+", re.IGNORECASE)

VARIANTS_HELP = (
    "Variants as ALIDs (chromosome:position:allele:allele, such as 19:44908684:C:T) "
    "or rsIDs (rs429358); rsIDs are translated to ALIDs first."
)
STORE_HELP = "The LD reference panel's ancestry, such as EUR, AFR or EAS (api_status lists them)."


def to_alids(
    client: Client, variants: Sequence[str]
) -> tuple[list[str], dict[str, str], list[str]]:
    """ALIDs for ALIDs and rsIDs, in order, each once.

    Returns:
        The ALIDs; the rsID each translated ALID came from; and notes on rsIDs
        that no Store holds, or that name several ALIDs.

    Raises:
        ValueError: A variant is neither an ALID nor an rsID.
    """
    values = [v.strip() for v in variants]
    bad = [v for v in values if not (_ALID.fullmatch(v) or _RSID.fullmatch(v))]
    if bad:
        raise ValueError(f"not ALIDs or rsIDs: {', '.join(bad[:5])}")
    rsids = list(dict.fromkeys(v.lower() for v in values if _RSID.fullmatch(v)))
    found: dict[str, list[str]] = {}
    if rsids:
        frame = variants_rsid(rsids, client=client)
        if not frame.empty:
            for row in frame.drop_duplicates("alid").to_dict("records"):
                found.setdefault(str(row["rsid"]).lower(), []).append(str(row["alid"]))
    alids: list[str] = []
    rsid_of: dict[str, str] = {}
    notes: list[str] = []
    for value in values:
        if not _RSID.fullmatch(value):
            if value not in alids:
                alids.append(value)
            continue
        matches = found.get(value.lower(), [])
        if not matches:
            notes.append(f"{value}: no served Store holds this rsID, so it is left out.")
        elif len(matches) > 1:
            notes.append(f"{value} names several variants: {', '.join(matches)}; all are used.")
        for alid in matches:
            if alid not in alids:
                alids.append(alid)
                rsid_of[alid] = value
    return alids, rsid_of, notes


def _ld_provenance(frame: pd.DataFrame) -> dict[str, Any]:
    keys = ("store", "ancestry", "t_far", "near_bp", "far_bp", "absent")
    return {k: frame.attrs[k] for k in keys if k in frame.attrs}


def _absent_note(frame: pd.DataFrame) -> list[str]:
    absent = frame.attrs.get("absent") or []
    if not absent:
        return []
    shown = ", ".join(absent[:10]) + (" ..." if len(absent) > 10 else "")
    return [f"{len(absent)} variants are not in the LD panel: {shown}."]


def register(server: MCPServer[Session]) -> None:
    """Add ``ld_proxies`` and ``ld_matrix``."""

    @server.tool(
        name="ld_proxies",
        title="LD proxies",
        description=(
            "Proxies of variants: other variants in linkage disequilibrium (LD) with them, "
            "from an LD reference panel. Each row gives the query variant, the proxy, the "
            "signed r, r2 and the distance in base pairs. Use proxies for variants an "
            "analysis lacks."
        ),
        annotations=READ_ONLY,
    )
    async def ld_proxies_tool(
        ctx: Context[Session],
        variants: Annotated[
            list[str],
            Field(min_length=1, max_length=PROXIES_MAX, description=VARIANTS_HELP),
        ],
        ancestry: Annotated[str, Field(min_length=1, description=STORE_HELP)] = "EUR",
        r2: Annotated[float, Field(gt=0, le=1, description="Least r2 for a proxy.")] = 0.8,
        kb: Annotated[
            float, Field(gt=0, le=10_000, description="The window either side, in kilobases.")
        ] = 3000,
        max_rows: MaxRows = 50,
        columns: ColumnChoice = "default",
        save_as: SaveAs = None,
        overwrite: Overwrite = False,
    ) -> TableResult:
        args = arguments(locals())
        session = session_of(ctx)
        client = session.require_client()

        def fetch() -> tuple[pd.DataFrame, dict[str, str], list[str]]:
            alids, rsid_of, notes = to_alids(client, variants)
            if not alids:
                return pd.DataFrame(), rsid_of, notes
            frame = ld_proxies(alids, r2=r2, kb=kb, ancestry=ancestry.upper(), client=client)
            if rsid_of and "query" in frame.columns:
                frame.insert(1, "query_rsid", [rsid_of.get(q) for q in frame["query"]])
            return frame, rsid_of, notes

        done = await watched(session, ctx, fetch, (ld_proxies_tool, args))
        if isinstance(done, TableResult):
            return session.finish(done)
        frame, rsid_of, notes = done
        default = ["query", *(["query_rsid"] if rsid_of else []), "proxy", "r", "r2", "distance"]
        if "r2" in frame.columns:
            frame = frame.sort_values(["query", "r2"], ascending=[True, False], kind="stable")
        queries = frame["query"].nunique() if "query" in frame.columns else 0
        result = table_result(
            frame,
            summary=(
                f"{len(frame)} proxies with r2 >= {r2:g} within {kb:g} kb "
                f"for {queries} variants ({ancestry.upper()})."
            ),
            max_rows=max_rows,
            columns=columns,
            default_columns=default,
            notes=[*notes, *_absent_note(frame)],
            provenance={**_ld_provenance(frame), "rsids": rsid_of},
        )
        return await deliver(session, result, frame, tool="ld_proxies", args=args)

    @server.tool(
        name="ld_matrix",
        title="LD matrix",
        description=(
            "The LD (signed r) between every pair of up to 50 variants, from an LD reference "
            "panel. One row per variant: its alid, its alleles a1 and a2 (the sign of r refers "
            "to them), then r with each variant, in the same order as the rows. Square r for r2."
        ),
        annotations=READ_ONLY,
    )
    async def ld_matrix_tool(
        ctx: Context[Session],
        variants: Annotated[
            list[str],
            Field(min_length=1, max_length=MATRIX_MAX, description=VARIANTS_HELP),
        ],
        ancestry: Annotated[str, Field(min_length=1, description=STORE_HELP)] = "EUR",
        save_as: SaveAs = None,
        overwrite: Overwrite = False,
    ) -> TableResult:
        args = arguments(locals())
        session = session_of(ctx)
        client = session.require_client()

        def fetch() -> tuple[pd.DataFrame, dict[str, str], list[str]]:
            alids, rsid_of, notes = to_alids(client, variants)
            if not alids:
                return pd.DataFrame(), rsid_of, notes
            if len(alids) > MATRIX_MAX:
                raise ValueError(
                    f"the rsIDs name {len(alids)} variants; ld_matrix takes at most {MATRIX_MAX}"
                )
            return ld_matrix(alids, ancestry=ancestry.upper(), client=client), rsid_of, notes

        done = await watched(session, ctx, fetch, (ld_matrix_tool, args))
        if isinstance(done, TableResult):
            return session.finish(done)
        square, rsid_of, notes = done
        rows = _labelled(square, rsid_of)
        result = table_result(
            rows,
            summary=f"LD matrix (signed r) of {len(rows)} variants ({ancestry.upper()}).",
            max_rows=MATRIX_MAX,
            columns="all",
            notes=[*notes, *_absent_note(square)],
            provenance={**_ld_provenance(square), "rsids": rsid_of},
        )
        return await deliver(session, result, rows, tool="ld_matrix", args=args)


def _labelled(square: pd.DataFrame, rsid_of: dict[str, str]) -> pd.DataFrame:
    """The square matrix as rows: alid, rsid (if any), a1, a2, then r rounded to 3 places."""
    if square.empty:
        empty: pd.DataFrame = pd.DataFrame(columns=["alid"])
        empty.attrs.update(square.attrs)
        return empty
    alleles = {v["alid"]: v for v in square.attrs.get("variants") or []}
    rows: pd.DataFrame = square.round(3).reset_index()
    rows.columns = pd.Index(["alid", *[str(c) for c in rows.columns[1:]]])
    position = 1
    if rsid_of:
        rows.insert(position, "rsid", [rsid_of.get(a) for a in rows["alid"]])
        position += 1
    for allele in ("a1", "a2"):
        rows.insert(position, allele, [alleles.get(a, {}).get(allele) for a in rows["alid"]])
        position += 1
    rows.attrs.update(square.attrs)
    return rows
