"""Metadata tools: find analyses, and look them up by ID."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from opengwaspy.compat._ids import resolve
from opengwaspy.mcp.formatting import (
    METADATA_COLUMNS,
    ColumnChoice,
    MaxRows,
    TableResult,
    table_result,
)
from opengwaspy.mcp.server import READ_ONLY, Session, call, session_of
from opengwaspy.metadata import gwasinfo_search

__all__ = ["register"]


def register(server: MCPServer[Session]) -> None:
    """Add ``search_analyses`` and ``get_analyses``."""

    @server.tool(
        name="search_analyses",
        title="Search OpenGWAS analyses",
        description=(
            "Find GWAS analyses (studies) by their label, or by a full-text query. "
            'match="contains" finds labels holding q anywhere (literal text, any case). '
            'match="fulltext" takes a boolean query over label, trait, consortium, first '
            'author and IDs: AND, OR, NOT, "phrases", prefix*, column:term (for example '
            "first_author:locke); best match first. Filters keep exact matches only. "
            "Returns analysis IDs to use with the other tools."
        ),
        annotations=READ_ONLY,
    )
    async def search_analyses(
        ctx: Context[Session],
        q: Annotated[str, Field(min_length=1, max_length=500, description="The text or query.")],
        match: Literal["contains", "fulltext"] = "contains",
        store_id: Annotated[
            str | None, Field(description="Only this Store, such as OGS-00006.")
        ] = None,
        assigned_ancestry: Annotated[
            str | None, Field(description="Only this ancestry, such as EUR.")
        ] = None,
        ancestry_category: str | None = None,
        outcome_type: Literal["binary", "continuous"] | None = None,
        trait_class: str | None = None,
        max_rows: MaxRows = 50,
        columns: ColumnChoice = "default",
    ) -> TableResult:
        session = session_of(ctx)
        client = session.require_client()
        filters = {
            "store_id": store_id,
            "assigned_ancestry": assigned_ancestry,
            "ancestry_category": ancestry_category,
            "outcome_type": outcome_type,
            "trait_class": trait_class,
        }
        frame = await call(
            session,
            lambda: gwasinfo_search(q, match=match, limit=max_rows, client=client, **filters),
        )
        total = frame.attrs.get("total")
        total = int(total) if total is not None else len(frame)
        result = table_result(
            frame,
            summary=f"{total} analyses match {q!r} ({match}); {min(total, len(frame))} shown.",
            max_rows=max_rows,
            columns=columns,
            default_columns=METADATA_COLUMNS,
            total=total,
            provenance={
                "q": q,
                "match": match,
                "filters": {k: v for k, v in filters.items() if v is not None},
            },
        )
        return session.scrub(result)

    @server.tool(
        name="get_analyses",
        title="Look up OpenGWAS analyses",
        description=(
            "Metadata of analyses by ID: trait, ancestry, sample size, cases and controls, "
            "author, PubMed ID and Store. Takes Data API IDs (OGS-00006:GCST90199621, or bare "
            "GCST90199621) and OpenGWAS IDs (ieu-a-2, ukb-b-19953, ebi-a-GCST006802, finn-b-...). "
            "Each OpenGWAS ID is translated to the analyses holding it, or the reason it is "
            "not held is given."
        ),
        annotations=READ_ONLY,
    )
    async def get_analyses(
        ctx: Context[Session],
        ids: Annotated[
            list[str],
            Field(min_length=1, max_length=100, description="Up to 100 analysis IDs."),
        ],
        max_rows: MaxRows = 50,
        columns: ColumnChoice = "default",
    ) -> TableResult:
        session = session_of(ctx)
        client = session.require_client()
        resolved = await call(session, lambda: resolve(ids, warn=False, client=client))
        frame = resolved.label(resolved.info)
        notes: list[str] = []
        unresolved = 0
        for entry in resolved.opengwas:
            if "reason" in entry:
                unresolved += 1
                notes.append(f"{entry['id']}: not found ({entry['reason']}).")
            elif entry.get("match") == "successor":
                notes.append(
                    f"{entry['id']} was translated to {', '.join(entry['analyses'])}, a later "
                    "release than OpenGWAS held, so the numbers may differ."
                )
        translated = any(e.get("analyses") for e in resolved.opengwas)
        default = [*METADATA_COLUMNS, "opengwas_id"] if translated else METADATA_COLUMNS
        found = len(ids) - unresolved
        summary = f"{len(frame)} analyses for {found} of {len(ids)} IDs"
        result = table_result(
            frame,
            summary=summary + (f"; {unresolved} not found." if unresolved else "."),
            max_rows=max_rows,
            columns=columns,
            default_columns=default,
            notes=notes,
            provenance={"opengwas_ids": resolved.opengwas},
        )
        return session.scrub(result)
