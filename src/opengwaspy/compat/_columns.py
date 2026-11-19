"""ieugwaspy's column names, added beside the Data API's own columns."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

__all__ = ["DERIVED", "ieugwas_columns"]

#: Columns opengwaspy derives, and how. Everything else is copied or renamed.
DERIVED: dict[str, str] = {
    "beta": "z * se: the effect on the analysis's stored_effect_scale (see gwasinfo)",
    "p": "10 ** log10_p",
    "n": "sample_size of the analysis, from gwasinfo",
}

#: ieugwaspy name: Data API name, for columns copied as they are.
RENAMED: dict[str, str] = {
    "trait": "analysis_label",
    "chr": "chromosome",
    "ea": "effect_allele",
    "nea": "other_allele",
}


def _qualified_id(row: Mapping[str, Any]) -> Any:
    store, analysis = row.get("store_id"), row.get("analysis_id")
    if isinstance(store, str) and isinstance(analysis, str):
        return f"{store}:{analysis}"
    return row.get("id")


def ieugwas_columns(
    frame: pd.DataFrame, sample_sizes: Mapping[str, Any] | None = None
) -> pd.DataFrame:
    """Add ieugwaspy's column names to a Data API result, keeping its own columns.

    The ieugwaspy columns come first: ``id``, ``trait``, ``rsid``, ``chr``,
    ``position``, ``ea``, ``nea``, ``eaf``, ``beta``, ``se``, ``p``, ``n``, where
    the result has what they need. ``id`` is the Store-qualified analysis ID.

    Args:
        frame: A Data API result.
        sample_sizes: Sample size by qualified analysis ID, for ``n``.

    Returns:
        The same frame, with the extra columns.
    """
    if frame.empty:
        return frame
    added: dict[str, Any] = {}
    if "analysis_id" in frame.columns and "store_id" in frame.columns:
        columns = [c for c in ("store_id", "analysis_id", "id") if c in frame.columns]
        added["id"] = [_qualified_id(r) for r in frame[columns].to_dict("records")]
    for old, new in RENAMED.items():
        if new in frame.columns and old not in frame.columns:
            added[old] = frame[new]
    if {"z", "se"} <= set(frame.columns) and "beta" not in frame.columns:
        added["beta"] = frame["z"].astype(float) * frame["se"].astype(float)
    if "log10_p" in frame.columns and "p" not in frame.columns:
        added["p"] = 10.0 ** frame["log10_p"].astype(float)
    if sample_sizes is not None and "id" in added:
        added["n"] = [sample_sizes.get(i, np.nan) for i in added["id"]]
    order = ["id", "trait", "rsid", "chr", "position", "ea", "nea", "eaf", "beta", "se", "p", "n"]
    for name in reversed(order):
        if name in added:
            if name in frame.columns:
                frame = frame.drop(columns=[name])
            frame.insert(0, name, added[name])
        elif name in frame.columns:
            frame.insert(0, name, frame.pop(name))
    return frame
