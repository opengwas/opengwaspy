"""Analysis metadata: what each GWAS is, and where it comes from.

These calls answer at once; they are not jobs.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from opengwaspy._common import ReleaseLike, resolve_releases
from opengwaspy.client import Client, get_client
from opengwaspy.errors import ProtocolError, RequestError
from opengwaspy.transport import json_body

__all__ = ["gwasinfo", "gwasinfo_files"]

#: Most analyses the API returns in one page or one lookup.
PAGE = 1000
#: Listing more analyses than this warns that it will take a while.
LARGE_LISTING = 10_000


def _frame(rows: Any) -> pd.DataFrame:
    frame: pd.DataFrame = pd.DataFrame.from_records(rows)
    return frame


def _as_list(ids: str | Iterable[str]) -> list[str]:
    values = [ids] if isinstance(ids, str) else list(ids)
    if not values:
        raise ValueError("ids is empty; pass None to list every analysis")
    if not all(isinstance(v, str) and v.strip() for v in values):
        raise ValueError("every analysis ID must be a non-empty string")
    return [v.strip() for v in values]


def _selection(
    client: Client, releases: Iterable[ReleaseLike] | None, release_set: str | None
) -> dict[str, Any]:
    if releases is not None and release_set is not None:
        raise ValueError("give releases or release_set, not both")
    selection: dict[str, Any] = {}
    if releases is not None:
        selection["releases"] = resolve_releases(client, releases)
    if release_set is not None:
        selection["release_set"] = release_set
    return selection


def _object(body: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(body, Mapping) or not isinstance(body.get("analyses"), list):
        raise ProtocolError(f"{path} did not return a list of analyses")
    return body


def gwasinfo(
    ids: str | Iterable[str] | None = None,
    *,
    releases: Iterable[ReleaseLike] | None = None,
    release_set: str | None = None,
    limit: int | None = None,
    strict: bool = False,
    client: Client | None = None,
) -> pd.DataFrame:
    """Metadata of analyses: trait, ancestry, sample size, effect scale, and more.

    With ``ids``, returns those analyses, in the order given. A bare ID held by
    several Stores returns one row from each; a Store-qualified ID
    (``OGS-00006:GCST90199621``) returns one.

    Without ``ids``, lists the served analyses, page by page.

    Args:
        ids: Analysis IDs, bare or Store-qualified. ``None`` lists every analysis.
        releases: Only these Stores' releases.
        release_set: A named set of releases, such as ``all_configured_releases``.
        limit: When listing, stop after this many analyses.
        strict: With ``ids``, raise if any ID is not served (or is retired)
            instead of noting it in ``attrs``.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        One row per analysis. ``attrs`` holds ``release_id``,
        ``catalog_version``, and either ``not_found`` and ``retired`` (lookup)
        or ``total`` (listing).

    Raises:
        RequestError: With ``strict``, some IDs were not found or are retired.
    """
    client = client or get_client()
    if ids is None:
        if releases is not None:
            raise ValueError(
                "listing takes release_set, not releases; pass ids to look up analyses"
            )
        return _list(client, _selection(client, None, release_set), limit)
    selection = _selection(client, releases, release_set)
    wanted = _as_list(ids)
    rows: list[dict[str, Any]] = []
    not_found: list[str] = []
    retired: list[Any] = []
    meta: Mapping[str, Any] = {}
    for start in range(0, len(wanted), PAGE):
        chunk = wanted[start : start + PAGE]
        meta = _object(
            json_body(client.transport.post("api/gwasinfo", {"id": chunk, **selection})),
            "/api/gwasinfo",
        )
        rows.extend(meta["analyses"])
        not_found.extend(meta.get("not_found") or [])
        retired.extend(meta.get("retired") or [])
    if strict and (not_found or retired):
        missing = ", ".join([*not_found, *(str(r) for r in retired)][:10])
        raise RequestError(
            404,
            "analysis_not_found",
            f"{len(not_found)} analyses not found and {len(retired)} retired: {missing}",
            extra={"not_found": not_found, "retired": retired},
        )
    frame = _frame(rows)
    frame.attrs.update(
        release_id=meta.get("release_id"),
        catalog_version=meta.get("catalog_version"),
        not_found=not_found,
        retired=retired,
    )
    return frame


def _list(client: Client, selection: Mapping[str, Any], limit: int | None) -> pd.DataFrame:
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    params: dict[str, Any] = dict(selection)
    rows: list[dict[str, Any]] = []
    after: str | None = None
    meta: Mapping[str, Any] = {}
    warned = False
    while True:
        size = PAGE if limit is None else min(PAGE, limit - len(rows))
        page_params = {**params, "limit": size, **({"after": after} if after else {})}
        meta = _object(
            json_body(client.transport.get("api/gwasinfo", params=page_params)), "/api/gwasinfo"
        )
        rows.extend(meta["analyses"])
        total = meta.get("total")
        if not warned and limit is None and isinstance(total, int) and total > LARGE_LISTING:
            warnings.warn(
                f"listing all {total:,} analyses, {PAGE:,} per request; "
                "pass ids, or limit, to fetch fewer",
                stacklevel=3,
            )
            warned = True
        after = meta.get("next_after")
        if not after or not meta["analyses"] or (limit is not None and len(rows) >= limit):
            break
    frame = _frame(rows)
    frame.attrs.update(
        release_id=meta.get("release_id"),
        catalog_version=meta.get("catalog_version"),
        total=meta.get("total"),
    )
    return frame


def gwasinfo_files(
    *,
    releases: Iterable[ReleaseLike] | None = None,
    release_set: str | None = None,
    limit: int = 100,
    after: str | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """The source files a page of analyses was built from: name, checksum, size.

    ieugwaspy's ``gwasinfo_files`` returned download links; the Data API has
    none, and lists the files' records instead. Stores that do not record their
    source files answer ``501``.

    Args:
        releases: Only these Stores' releases.
        release_set: A named set of releases.
        limit: Analyses in the page.
        after: The previous page's last analysis ID.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Raises:
        NotImplementedByServer: The selected Stores do not record source files.
    """
    client = client or get_client()
    body: dict[str, Any] = {"limit": limit, **_selection(client, releases, release_set)}
    if after:
        body["after"] = after
    answer = json_body(client.transport.post("api/gwasinfo/files", body))
    rows = answer
    if isinstance(answer, Mapping):
        rows = answer.get("files", answer.get("analyses"))
    if not isinstance(rows, list):
        raise ProtocolError("/api/gwasinfo/files did not return a list of files")
    frame = _frame(rows)
    if isinstance(answer, Mapping):
        frame.attrs.update({k: v for k, v in answer.items() if k not in ("files", "analyses")})
    return frame
