"""Data tools: top hits, associations, regions, PheWAS and variant lookups."""

from __future__ import annotations

import math
import re
from typing import Annotated, Any

import pandas as pd
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from opengwaspy import compat
from opengwaspy.associations import associations, associations_range
from opengwaspy.compat._columns import ieugwas_columns
from opengwaspy.compat._ids import Resolved, resolve
from opengwaspy.hits import phewas, tophits
from opengwaspy.mcp.formatting import (
    ColumnChoice,
    MaxRows,
    Overwrite,
    SaveAs,
    TableResult,
    table_result,
)
from opengwaspy.mcp.metadata import resolution_notes
from opengwaspy.mcp.server import (
    READ_ONLY,
    Session,
    arguments,
    capture_warnings,
    deliver,
    session_of,
    watched,
)
from opengwaspy.variants import variants_chrpos, variants_rsid

__all__ = ["ASSOCIATION_COLUMNS", "REGION_MAX_BP", "register"]

#: Association columns shown by default (ieugwaspy's names, plus alid and log10_p).
ASSOCIATION_COLUMNS = (
    "id",
    "trait",
    "rsid",
    "alid",
    "ea",
    "nea",
    "eaf",
    "beta",
    "se",
    "p",
    "log10_p",
    "n",
)
#: The widest region ``region_associations`` returns, in base pairs.
REGION_MAX_BP = 1_000_000
#: The widest region with ``save_as``: the API's window for one range job.
REGION_SAVED_MAX_BP = 10_000_000

TOPHITS_ANALYSES = 10
LOOKUP_VARIANTS = 100
LOOKUP_ANALYSES = 20
REGION_ANALYSES = 5
#: Most top hits fetched per analysis.
TOPHITS_LIMIT = 1000
#: Most PheWAS rows fetched per job (each job covers up to 10 releases).
PHEWAS_LIMIT = 1000
#: Most PheWAS rows per job with ``save_as`` (the API's maximum).
PHEWAS_SAVED_LIMIT = 10_000

_RSID = re.compile(r"rs[0-9]+", re.IGNORECASE)
_CHRPOS = re.compile(r"(chr)?[0-9A-Za-z]+:[0-9]+", re.IGNORECASE)

AnalysisIds = Annotated[
    list[str],
    Field(
        min_length=1,
        description=(
            "Analysis IDs: Data API IDs (OGS-00006:GCST90199621, or bare GCST90199621) or "
            "OpenGWAS IDs (ieu-a-2, ukb-b-19953), as search_analyses and get_analyses give."
        ),
    ),
]
VARIANTS_HELP = "Variants as rsIDs (rs1205) or ALIDs (chromosome:position:allele:allele)."


def _resolve(client: Any, ids: list[str]) -> Resolved:
    resolved = resolve(ids, warn=False, client=client)
    return resolved


def _association_frame(frame: pd.DataFrame, resolved: Resolved | None) -> pd.DataFrame:
    """Ieugwaspy's column names, the analyses' labels and sample sizes, and opengwas_id."""
    if frame.empty:
        return frame
    attrs = dict(frame.attrs)
    info = resolved.info if resolved is not None else pd.DataFrame()
    sizes: dict[str, Any] = {}
    labels: dict[str, Any] = {}
    if not info.empty and "id" in info.columns:
        if "sample_size" in info.columns:
            sizes = dict(zip(info["id"], info["sample_size"], strict=True))
        if "analysis_label" in info.columns:
            labels = dict(zip(info["id"], info["analysis_label"], strict=True))
    frame = ieugwas_columns(frame, sizes or None)
    if "trait" not in frame.columns and labels and "id" in frame.columns:
        frame.insert(1, "trait", [labels.get(i) for i in frame["id"]])
    if resolved is not None and any(e.get("analyses") for e in resolved.opengwas):
        frame = resolved.label(frame)
    frame.attrs.update(attrs)
    return frame


def _defaults(*extra: str) -> list[str]:
    return [*ASSOCIATION_COLUMNS, *extra, "opengwas_id"]


def _per_analysis(frame: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    """At most ``max_rows`` rows, shared fairly between analyses, keeping each one's order."""
    if frame.empty or "id" not in frame.columns or len(frame) <= max_rows:
        return frame
    groups = frame["id"].nunique()
    per = max(1, math.floor(max_rows / groups))
    trimmed = frame.groupby("id", sort=False).head(per)
    trimmed.attrs.update(frame.attrs)
    return trimmed


def _no_analyses(notes: list[str]) -> ToolError:
    return ToolError("None of the analysis IDs were found. " + " ".join(notes))


def register(server: MCPServer[Session]) -> None:
    """Add the data tools: top hits, associations, regions, PheWAS and variant lookups."""

    @server.tool(
        name="top_hits",
        title="Top hits of analyses",
        description=(
            "The strongest associations (top hits) of up to 10 analyses at p <= threshold, "
            "strongest first. With clump=true, the server LD-clumps every hit and returns only "
            "the independent leads, each with clump_size (r2 0.001 within 3,000 kb in the "
            "analysis's own ancestry by default)."
        ),
        annotations=READ_ONLY,
    )
    async def top_hits(
        ctx: Context[Session],
        analysis_ids: Annotated[AnalysisIds, Field(max_length=TOPHITS_ANALYSES)],
        threshold: Annotated[
            float,
            Field(gt=0, le=1, description="Largest p-value. Stores index down to about 5e-4."),
        ] = 5e-8,
        clump: Annotated[bool, Field(description="LD-clump the hits on the server.")] = False,
        r2: Annotated[
            float | None, Field(gt=0, le=1, description="Clumping r2 (default 0.001).")
        ] = None,
        kb: Annotated[
            float | None, Field(gt=0, le=10_000, description="Clumping window (default 3000).")
        ] = None,
        ancestry: Annotated[
            str | None, Field(description="Clump every analysis in this LD panel, such as EUR.")
        ] = None,
        max_rows: MaxRows = 50,
        columns: ColumnChoice = "default",
        save_as: SaveAs = None,
        overwrite: Overwrite = False,
    ) -> TableResult:
        args = arguments(locals())
        session = session_of(ctx)
        client = session.require_client()
        if not clump and (r2 is not None or kb is not None or ancestry is not None):
            raise ToolError("r2, kb and ancestry apply only with clump=true")
        settings = {
            k: v for k, v in {"r2": r2, "kb": kb, "ancestry": ancestry}.items() if v is not None
        }
        if isinstance(settings.get("ancestry"), str):
            settings["ancestry"] = str(settings["ancestry"]).upper()

        def fetch() -> tuple[pd.DataFrame, Resolved]:
            resolved = _resolve(client, analysis_ids)
            if not resolved.ids:
                return pd.DataFrame(), resolved
            frame = tophits(
                resolved.ids,
                threshold=threshold,
                limit=TOPHITS_LIMIT,
                clump=settings or clump,
                client=client,
            )
            return _association_frame(frame, resolved), resolved

        done = await watched(session, ctx, fetch, (top_hits, args))
        if isinstance(done, TableResult):
            return session.finish(done)
        frame, resolved = done
        notes, _ = resolution_notes(resolved)
        if not resolved.ids:
            raise _no_analyses(notes)
        if frame.attrs.get("truncated"):
            notes.append(
                f"Some analyses have more than {TOPHITS_LIMIT:,} hits at p <= {threshold:g}; "
                f"only the strongest {TOPHITS_LIMIT:,} of each were fetched."
            )
        counts = frame["id"].value_counts().to_dict() if "id" in frame.columns else {}
        kind = "leads" if clump else "hits"
        per = "; ".join(f"{i}: {counts.get(i, 0)}" for i in resolved.ids)
        prov: dict[str, Any] = {"threshold": threshold, "opengwas_ids": resolved.opengwas}
        clumped = frame.attrs.get("clump")
        if clumped:
            prov["clump"] = clumped
            if clumped.get("absent"):
                notes.append(
                    f"{clumped['absent']} hits are not in the LD panel, so were neither clumped "
                    "nor returned."
                )
        result = table_result(
            _per_analysis(frame, max_rows),
            summary=f"{len(frame)} {kind} at p <= {threshold:g} ({per}).",
            max_rows=max_rows,
            columns=columns,
            default_columns=_defaults(*(["clump_size"] if clump else [])),
            total=len(frame),
            notes=notes,
            provenance=prov,
        )
        return await deliver(session, result, frame, tool="top_hits", args=args)

    @server.tool(
        name="associations",
        title="Associations of variants",
        description=(
            "The associations of up to 100 variants in up to 20 analyses. A variant an "
            "analysis lacks gives no row, unless proxies=true: then its best LD proxy that the "
            "analysis holds (r2 >= r2, in the analysis's ancestry's LD panel) is used, with "
            "the effect aligned to the target variant's alleles."
        ),
        annotations=READ_ONLY,
    )
    async def associations_tool(
        ctx: Context[Session],
        variants: Annotated[
            list[str],
            Field(min_length=1, max_length=LOOKUP_VARIANTS, description=VARIANTS_HELP),
        ],
        analysis_ids: Annotated[AnalysisIds, Field(max_length=LOOKUP_ANALYSES)],
        proxies: Annotated[bool, Field(description="Use LD proxies for missing variants.")] = False,
        r2: Annotated[float, Field(gt=0, le=1, description="Least r2 for a proxy.")] = 0.8,
        max_rows: MaxRows = 50,
        columns: ColumnChoice = "default",
        save_as: SaveAs = None,
        overwrite: Overwrite = False,
    ) -> TableResult:
        args = arguments(locals())
        session = session_of(ctx)
        client = session.require_client()
        if not proxies:

            def fetch() -> tuple[pd.DataFrame, Resolved]:
                resolved = _resolve(client, analysis_ids)
                if not resolved.ids:
                    return pd.DataFrame(), resolved
                frame = associations(variants, resolved.ids, client=client)
                return _association_frame(frame, resolved), resolved

            done = await watched(session, ctx, fetch, (associations_tool, args))
            if isinstance(done, TableResult):
                return session.finish(done)
            frame, resolved = done
            notes, _ = resolution_notes(resolved)
            if not resolved.ids:
                raise _no_analyses(notes)
            prov: dict[str, Any] = {"opengwas_ids": resolved.opengwas, "proxies": False}
            extra: list[str] = []
        else:
            noted = await watched(
                session,
                ctx,
                capture_warnings(
                    lambda: compat.associations(variants, analysis_ids, proxies=1, r2=r2)
                ),
                (associations_tool, args),
            )
            if isinstance(noted, TableResult):
                return session.finish(noted)
            frame, notes = noted
            prov = {"opengwas_ids": frame.attrs.get("opengwas_ids"), "proxies": True, "r2": r2}
            extra = ["proxy", "target_snp", "proxy_snp", "proxy_r2"]
        found = frame["id"].nunique() if "id" in frame.columns else 0
        summary = f"{len(frame)} associations in {found} analyses"
        if proxies and "proxy" in frame.columns:
            summary += f", {int(frame['proxy'].fillna(False).astype(bool).sum())} through proxies"
        result = table_result(
            frame,
            summary=summary + ".",
            max_rows=max_rows,
            columns=columns,
            default_columns=_defaults(*extra),
            notes=notes,
            provenance=prov,
        )
        return await deliver(session, result, frame, tool="associations", args=args)

    @server.tool(
        name="region_associations",
        title="Associations in a region",
        description=(
            f"Every association in a genomic region of up to {REGION_MAX_BP // 1000:,} kb "
            f"({REGION_SAVED_MAX_BP // 1000:,} kb with save_as), in "
            f"up to {REGION_ANALYSES} analyses, in position order. Positions are one-based and "
            "inclusive, on the analyses' genome build (GRCh38 in most Stores)."
        ),
        annotations=READ_ONLY,
    )
    async def region_associations(
        ctx: Context[Session],
        chromosome: Annotated[str, Field(min_length=1, description="Such as 7, X or chr7.")],
        start: Annotated[int, Field(ge=1, description="First position.")],
        end: Annotated[int, Field(ge=1, description="Last position.")],
        analysis_ids: Annotated[AnalysisIds, Field(max_length=REGION_ANALYSES)],
        max_rows: MaxRows = 50,
        columns: ColumnChoice = "default",
        save_as: SaveAs = None,
        overwrite: Overwrite = False,
    ) -> TableResult:
        args = arguments(locals())
        session = session_of(ctx)
        client = session.require_client()
        if end < start:
            raise ToolError(f"end ({end}) is before start ({start})")
        widest = REGION_SAVED_MAX_BP if save_as else REGION_MAX_BP
        if end - start + 1 > widest:
            raise ToolError(
                f"the region is {end - start + 1:,} bp; this tool returns at most "
                f"{REGION_MAX_BP:,} bp, or {REGION_SAVED_MAX_BP:,} bp with save_as. "
                "Ask for a narrower region, or several."
            )

        def fetch() -> tuple[pd.DataFrame, Resolved]:
            resolved = _resolve(client, analysis_ids)
            if not resolved.ids:
                return pd.DataFrame(), resolved
            frame = associations_range(chromosome, start, end, resolved.ids, client=client)
            return _association_frame(frame, resolved), resolved

        done = await watched(session, ctx, fetch, (region_associations, args))
        if isinstance(done, TableResult):
            return session.finish(done)
        frame, resolved = done
        notes, _ = resolution_notes(resolved)
        if not resolved.ids:
            raise _no_analyses(notes)
        if not frame.empty and "p" in frame.columns:
            best = frame.sort_values("p", kind="stable").to_dict("records")[0]
            name = best.get("rsid") or best.get("alid")
            notes.append(f"Strongest: {name} (p = {float(best['p']):.3g}).")
        result = table_result(
            frame,
            summary=(
                f"{len(frame)} associations in {chromosome}:{start}-{end} "
                f"in {len(resolved.ids)} analyses."
            ),
            max_rows=max_rows,
            columns=columns,
            default_columns=_defaults("chr", "position"),
            notes=notes,
            provenance={"opengwas_ids": resolved.opengwas},
        )
        return await deliver(session, result, frame, tool="region_associations", args=args)

    @server.tool(
        name="phewas",
        title="PheWAS of a variant",
        description=(
            "The associations of one variant across every analysis that can answer (a PheWAS), "
            "at p <= threshold (default 1e-8), strongest first."
        ),
        annotations=READ_ONLY,
    )
    async def phewas_tool(
        ctx: Context[Session],
        variant: Annotated[str, Field(min_length=1, description="One rsID or ALID.")],
        threshold: Annotated[
            float, Field(gt=0, le=1, description="Largest p-value (1 for every association).")
        ] = 1e-8,
        max_rows: MaxRows = 50,
        columns: ColumnChoice = "default",
        save_as: SaveAs = None,
        overwrite: Overwrite = False,
    ) -> TableResult:
        args = arguments(locals())
        session = session_of(ctx)
        client = session.require_client()

        def fetch() -> pd.DataFrame:
            limit = PHEWAS_SAVED_LIMIT if save_as else PHEWAS_LIMIT
            frame = phewas(variant, threshold=threshold, limit=limit, client=client)
            if "log10_p" in frame.columns:
                frame = frame.sort_values("log10_p", kind="stable")
            return _association_frame(frame, None)

        done = await watched(session, ctx, fetch, (phewas_tool, args))
        if isinstance(done, TableResult):
            return session.finish(done)
        frame = done
        total = frame.attrs.get("total")
        total = int(total) if total is not None else len(frame)
        notes = []
        if frame.attrs.get("truncated"):
            notes.append(
                f"{total:,} associations pass p <= {threshold:g}, but only {len(frame):,} were "
                "fetched; the rows shown are the strongest of those. Lower the threshold to "
                "see fewer, stronger associations."
            )
        result = table_result(
            frame,
            summary=f"{total} associations of {variant} at p <= {threshold:g}.",
            max_rows=max_rows,
            columns=columns,
            default_columns=ASSOCIATION_COLUMNS,
            total=total,
            notes=notes,
            provenance={"threshold": frame.attrs.get("threshold", threshold)},
        )
        return await deliver(session, result, frame, tool="phewas", args=args)

    @server.tool(
        name="variant_info",
        title="Look up variants",
        description=(
            "Find variants by rsID (rs429358) or position (19:44908684, or chr19:44908684): "
            "their ALID (chromosome:position:allele:allele), rsID, position and alleles, in the "
            "served Stores."
        ),
        annotations=READ_ONLY,
    )
    async def variant_info(
        ctx: Context[Session],
        variants: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=LOOKUP_VARIANTS,
                description="rsIDs or chromosome:position, mixed as you like.",
            ),
        ],
        max_rows: MaxRows = 50,
        columns: ColumnChoice = "default",
        save_as: SaveAs = None,
        overwrite: Overwrite = False,
    ) -> TableResult:
        args = arguments(locals())
        session = session_of(ctx)
        client = session.require_client()
        values = [v.strip() for v in variants]
        bad = [v for v in values if not (_RSID.fullmatch(v) or _CHRPOS.fullmatch(v))]
        if bad:
            raise ToolError(f"not rsIDs or chromosome:position: {', '.join(bad[:5])}")
        rsids = [v for v in values if _RSID.fullmatch(v)]
        positions = [v for v in values if not _RSID.fullmatch(v)]

        def fetch() -> pd.DataFrame:
            frames: list[pd.DataFrame] = []
            if rsids:
                frames.append(variants_rsid(rsids, client=client))
            if positions:
                frames.append(variants_chrpos(positions, client=client))
            frames = [f for f in frames if not f.empty]
            frame: pd.DataFrame = pd.DataFrame()
            if not frames:
                return frame
            frame = pd.concat(frames, ignore_index=True)
            stores = frame.groupby("alid")["store_id"].nunique() if "store_id" in frame else None
            frame = frame.drop_duplicates("alid").reset_index(drop=True)
            if stores is not None:
                frame["stores"] = [int(stores[a]) for a in frame["alid"]]
            return frame

        done = await watched(session, ctx, fetch, (variant_info, args))
        if isinstance(done, TableResult):
            return session.finish(done)
        frame = done
        notes = _not_found(values, frame)
        result = table_result(
            frame,
            summary=(
                f"{len(frame)} variants for {len(values) - len(notes)} of {len(values)} queries."
            ),
            max_rows=max_rows,
            columns=columns,
            default_columns=(
                "query",
                "rsid",
                "alid",
                "chromosome",
                "position",
                "effect_allele",
                "other_allele",
                "stores",
            ),
            notes=notes,
        )
        return await deliver(session, result, frame, tool="variant_info", args=args)


def _not_found(values: list[str], frame: pd.DataFrame) -> list[str]:
    """A note for each query no served Store holds."""
    held: set[str] = set()
    if "rsid" in frame.columns:
        held |= {str(v).lower() for v in frame["rsid"]}
    if "alid" in frame.columns:
        held |= {":".join(str(a).split(":")[:2]).lower() for a in frame["alid"]}
    notes = []
    for value in values:
        key = value.lower()
        key = key[3:] if key.startswith("chr") else key
        if key not in held:
            notes.append(f"{value}: no served Store holds it.")
    return notes
