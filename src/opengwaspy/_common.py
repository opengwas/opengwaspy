"""Helpers shared by the query functions: releases, chunking, merging results."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any, TypeVar

import pandas as pd

from opengwaspy.client import Client

T = TypeVar("T")

#: A release, as the caller may name it: a Store ID (``OGS-00006``, its current
#: release), ``store/release`` text, or ``{"store_id": ..., "release_id": ...}``.
ReleaseLike = str | Mapping[str, str]


def as_list(value: str | Iterable[str] | None, name: str) -> list[str] | None:
    """A list of non-empty strings, from one string or many."""
    if value is None:
        return None
    values = [value] if isinstance(value, str) else list(value)
    if not values:
        raise ValueError(f"{name} is empty")
    if not all(isinstance(v, str) and v.strip() for v in values):
        raise ValueError(f"every item of {name} must be a non-empty string")
    return [v.strip() for v in values]


def chunks(values: Sequence[T], size: int) -> Iterator[list[T]]:
    """Consecutive slices of at most ``size`` items."""
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def resolve_releases(
    client: Client, releases: Iterable[ReleaseLike] | None
) -> list[dict[str, str]] | None:
    """Release references for a request body.

    A bare Store ID is resolved to the release the API serves for it.

    Raises:
        ValueError: A Store ID the API does not serve, or a malformed reference.
    """
    if releases is None:
        return None
    items = [releases] if isinstance(releases, (str, Mapping)) else list(releases)
    if not items:
        raise ValueError("releases is empty")
    out: list[dict[str, str]] = []
    served: dict[str, list[str]] | None = None
    for item in items:
        if isinstance(item, Mapping):
            if not item.get("store_id") or not item.get("release_id"):
                raise ValueError(f"a release needs store_id and release_id: {dict(item)!r}")
            out.append({"store_id": str(item["store_id"]), "release_id": str(item["release_id"])})
        elif "/" in item:
            store, _, release = item.partition("/")
            if not store or not release:
                raise ValueError(f"expected store/release, got {item!r}")
            out.append({"store_id": store, "release_id": release})
        else:
            if served is None:
                served = client.served_releases()
            choices = served.get(item)
            if not choices:
                raise ValueError(f"no served release of Store {item!r}; see opengwaspy.batches()")
            out.extend({"store_id": item, "release_id": r} for r in choices)
    return out


def add_p(frame: pd.DataFrame) -> pd.DataFrame:
    """Add ``p`` derived from ``log10_p`` (the API's log10 of p, never above 0)."""
    if "log10_p" in frame.columns and "p" not in frame.columns:
        position = list(frame.columns).index("log10_p") + 1
        frame.insert(position, "p", 10.0 ** frame["log10_p"].astype(float))
    return frame


def combine(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate results of several jobs, keeping each job's provenance.

    One job's frame is returned as it is. For several, ``attrs`` lists every
    ``job_id`` and ``query_hash``, the union of ``releases``, each job's
    ``metadata`` (``metadata_by_job``), and the ``image_digest``.
    """
    if len(frames) == 1:
        return frames[0]
    non_empty = [f for f in frames if not f.empty]
    combined: pd.DataFrame = (
        pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()
    )
    releases: list[Any] = []
    for frame in frames:
        for release in frame.attrs.get("releases", []):
            if release not in releases:
                releases.append(release)
    combined.attrs.clear()
    combined.attrs.update(
        job_ids=[f.attrs.get("job_id") for f in frames],
        query_hashes=[f.attrs.get("query_hash") for f in frames],
        endpoint=frames[0].attrs.get("endpoint") if frames else None,
        releases=releases,
        metadata_by_job=[f.attrs.get("metadata", {}) for f in frames],
        image_digest=frames[0].attrs.get("image_digest") if frames else None,
    )
    return combined


def run(client: Client, endpoint: str, bodies: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Run one job per body (a few at a time), and combine the results in order."""
    if len(bodies) == 1:
        return combine([client.query(endpoint, bodies[0])])
    return combine(client.query_many([(endpoint, body) for body in bodies]))


def drop_none(body: Mapping[str, Any]) -> dict[str, Any]:
    """A request body without the fields left as ``None``."""
    return {k: v for k, v in body.items() if v is not None}
