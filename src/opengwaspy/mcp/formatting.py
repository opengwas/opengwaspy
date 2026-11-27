"""Results sized for a model: a summary, chosen columns, a few rows, and provenance."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

__all__ = [
    "MAX_ROWS",
    "METADATA_COLUMNS",
    "PROVENANCE_KEYS",
    "TableResult",
    "table_result",
]

#: The most rows a tool returns, unless the caller asks for fewer.
MAX_ROWS = 100

#: Columns of analysis metadata shown by default.
METADATA_COLUMNS = (
    "id",
    "analysis_label",
    "assigned_ancestry",
    "sample_size",
    "n_cases",
    "n_controls",
    "outcome_type",
    "trait_class",
    "first_author",
    "publication_pmid",
    "store_id",
)

#: ``attrs`` keys copied into a result's provenance, when present.
PROVENANCE_KEYS = (
    "release_id",
    "catalog_version",
    "releases",
    "job_id",
    "job_ids",
    "image_digest",
)

Columns = Literal["default", "all"]


class TableResult(BaseModel):
    """A table, trimmed for a model, with what was left out and where it came from."""

    summary: str = Field(description="One line on what was found.")
    total_rows: int | None = Field(
        description="Rows in the full answer, when known; may exceed the rows returned."
    )
    rows_returned: int = Field(description="Rows in `rows`.")
    truncated: bool = Field(description="True if `rows` holds fewer rows than the full answer.")
    columns: list[str] = Field(description="The columns of each row.")
    rows: list[dict[str, Any]] = Field(description="The rows, as column: value.")
    notes: list[str] = Field(
        default_factory=list, description="Warnings and translations to pass on to the user."
    )
    provenance: dict[str, Any] = Field(
        default_factory=dict,
        description="Where the answer came from: releases, catalog version, jobs, API build.",
    )


def _json_safe(value: Any) -> Any:
    """``value`` as plain JSON types: NaN becomes None, and unknown types text."""
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):  # numpy scalars
        return _json_safe(value.item())
    return str(value)


def table_result(
    frame: pd.DataFrame,
    *,
    summary: str,
    max_rows: int,
    columns: Columns | Sequence[str] = "default",
    default_columns: Iterable[str] = (),
    total: int | None = None,
    notes: Iterable[str] = (),
    provenance: Mapping[str, Any] | None = None,
) -> TableResult:
    """Trim a result for a model.

    Args:
        frame: The full result.
        summary: One line on what was found.
        max_rows: The most rows to return.
        columns: ``"default"`` for ``default_columns`` (those present), ``"all"``
            for every column, or a list of column names (those present).
        default_columns: The columns shown by default; every column if empty.
        total: Rows in the full answer, if more than ``frame`` holds.
        notes: Warnings to pass on.
        provenance: Extra provenance, added to :data:`PROVENANCE_KEYS` from ``attrs``.
    """
    if columns == "all":
        keep = list(frame.columns)
    else:
        wanted = list(default_columns) if columns == "default" else list(columns)
        keep = [c for c in wanted if c in frame.columns] if wanted else list(frame.columns)
    shown = frame.loc[:, keep].head(max_rows)
    rows = json.loads(shown.to_json(orient="records", date_format="iso")) if keep else []
    if not keep:
        rows = [{} for _ in range(len(shown))]
    total_rows = len(frame) if total is None else max(total, len(frame))
    prov = {k: frame.attrs[k] for k in PROVENANCE_KEYS if frame.attrs.get(k) is not None}
    prov.update(provenance or {})
    return TableResult(
        summary=summary,
        total_rows=total_rows,
        rows_returned=len(rows),
        truncated=len(rows) < total_rows,
        columns=[str(c) for c in keep],
        rows=rows,
        notes=list(notes),
        provenance=_json_safe(prov),
    )
