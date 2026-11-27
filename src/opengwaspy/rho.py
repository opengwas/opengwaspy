"""A GWAS Store's Rho Matrix: the null correlation between its analyses.

The Rho Matrix holds, for each pair of a Store's analyses, the correlation of
their null z-scores: phenotypic correlation times sample overlap. Methods that
combine analyses need it. It was estimated when the Store was built, from its
Dense grid, so Dense Stores and Hybrid Stores' Dense Components carry one; a
Ragged Store has none.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd

from opengwaspy._common import ReleaseLike, as_list, drop_none, resolve_releases
from opengwaspy.client import Client, get_client
from opengwaspy.errors import ProtocolError

__all__ = ["rho"]


def rho(
    release: ReleaseLike,
    analyses: str | Iterable[str] | None = None,
    *,
    client: Client | None = None,
) -> pd.DataFrame:
    """A GWAS Store's Rho Matrix, or the sub-matrix of some of its analyses.

    The full matrix of a large Store is large: OGS-00017's 2,754 analyses are
    132 MB from the API (about 30 s to read), and it counts against your share
    of the API's results cache until read. Ask for ``analyses`` when you need
    only some.

    Args:
        release: One Store Release: a Store ID (the release the API serves),
            ``"store_id/release_id"``, or a mapping of ``store_id`` and
            ``release_id``.
        analyses: Analysis IDs of that Store (bare, or ``store_id:analysis_id``):
            the sub-matrix of these, rows and columns in this order. Default:
            every analysis the matrix holds, in the Store's order.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        A square DataFrame of Rho, indexed and labelled by analysis ID, with 1
        on the diagonal and NaN for a pair with too few shared null variants
        to estimate it. ``attrs`` holds ``n_null`` (a square DataFrame of the
        shared null variants behind each pair), ``settings`` (how it was
        estimated: ``method``, ``z_thresh``, ``min_nulls``, ``grid_n``,
        ``window_bp`` and ``n_variants_used``), ``store_id``, ``release_id``,
        and the job's provenance.

    Raises:
        ValueError: ``release`` names no single served release.
        RequestError: ``rho_unavailable`` if the release has no Rho Matrix (a
            Ragged Store, for example); the message says why.
    """
    client = client or get_client()
    refs = resolve_releases(client, [release])
    if not refs or len(refs) != 1:
        raise ValueError(f"name one Store Release; {release!r} matches {len(refs or [])}")
    analysis_list = as_list(analyses, "analyses")
    if analysis_list is not None and not analysis_list:
        raise ValueError("analyses is empty")
    body = drop_none({"releases": refs, "analyses": analysis_list})
    job = client.submit("api/rho", body)
    ids: list[str] = []
    rho_rows: list[np.ndarray] = []
    null_rows: list[np.ndarray] = []
    for row in job.rows():
        ids.append(str(row["analysis_id"]))
        rho_rows.append(np.asarray(_floats(row.get("rho")), dtype=np.float32))
        null_rows.append(np.asarray(_floats(row.get("n_null")), dtype=np.float64))
    attrs = job.provenance()
    metadata = attrs.get("metadata") or {}
    columns = [str(a) for a in metadata.get("analyses") or ids]
    if columns != ids or any(len(r) != len(columns) for r in (*rho_rows, *null_rows)):
        raise ProtocolError(
            f"job {job.job_id}: the Rho Matrix is not square over metadata.analyses"
        )
    index = pd.Index(ids, name="analysis_id")
    matrix: pd.DataFrame = pd.DataFrame(_stack(rho_rows, np.float32), index=index, columns=columns)
    n_null = pd.DataFrame(_counts(null_rows), index=index, columns=columns)
    ref = refs[0]
    matrix.attrs.update(attrs)
    matrix.attrs.update(
        store_id=ref["store_id"],
        release_id=ref["release_id"],
        settings=dict(metadata.get("settings") or {}),
        n_null=n_null,
        image_digest=client.image_digest,
    )
    return matrix


def _floats(values: Any) -> list[float]:
    """A row's list of numbers, with ``null`` as NaN."""
    if not isinstance(values, list):
        raise ProtocolError(f"a Rho row's values are not a list: {type(values).__name__}")
    return [np.nan if v is None else float(v) for v in values]


def _stack(rows: Sequence[np.ndarray], dtype: type[np.floating[Any]]) -> np.ndarray:
    return np.vstack(rows).astype(dtype, copy=False) if rows else np.empty((0, 0), dtype=dtype)


def _counts(rows: Sequence[np.ndarray]) -> np.ndarray:
    """``n_null`` as integers, unless some are missing (then floats, with NaN)."""
    stacked = _stack(rows, np.float64)
    return stacked if np.isnan(stacked).any() else stacked.astype(np.int64)
