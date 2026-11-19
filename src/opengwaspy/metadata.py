"""Analysis metadata: what each GWAS is, and where it comes from.

These calls answer at once; they are not jobs.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Mapping
from typing import Any, Literal

import pandas as pd

from opengwaspy._common import ReleaseLike, resolve_releases
from opengwaspy.client import Client, get_client
from opengwaspy.errors import ProtocolError, RequestError
from opengwaspy.transport import json_body

__all__ = ["gwasinfo", "gwasinfo_files", "gwasinfo_search"]

#: Most analyses the API returns in one page or one lookup.
PAGE = 1000
#: Listing more analyses than this warns that it will take a while.
LARGE_LISTING = 10_000
#: Furthest a full-text search pages: its largest ``offset``.
FULLTEXT_MAX_OFFSET = 10_000
#: Longest search text the API takes.
MAX_QUERY = 500


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


def gwasinfo_search(
    q: str,
    *,
    match: Literal["contains", "fulltext"] = "contains",
    limit: int | None = 100,
    store_id: str | None = None,
    assigned_ancestry: str | None = None,
    ancestry_category: str | None = None,
    outcome_type: str | None = None,
    trait_class: str | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """Find analyses by their label, or by a full-text query.

    With ``match="contains"`` (the default), finds analyses whose label holds
    ``q`` anywhere, ignoring case. The text is literal: no wildcards. Rows come
    in label order.

    With ``match="fulltext"``, ``q`` is a boolean full-text query over the
    label, trait, consortium, first author and IDs: ``AND``, ``OR``, ``NOT``,
    parentheses, ``"phrases"``, ``prefix*`` and ``column:term`` (for example
    ``first_author:locke``). It matches whole words (``bmi*`` also matches
    BMI1), and returns the best match first. Put an ID with hyphens in double
    quotes. The API pages a full-text search only up to 10,000 matches.

    Each filter keeps only analyses whose field equals it exactly.

    Args:
        q: The text to find, or the full-text query; at most 500 characters.
        match: ``"contains"`` or ``"fulltext"``.
        limit: The most analyses to return. ``None`` returns every match: a
            full-text search then stops at the API's 10,000 limit, with a warning.
        store_id: Only this served Store's analyses, such as ``OGS-00006``.
        assigned_ancestry: Only this ancestry, such as ``EUR``.
        ancestry_category: Only this ancestry category.
        outcome_type: ``binary`` or ``continuous``.
        trait_class: Only this trait class.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        One row per analysis, with the columns of :func:`gwasinfo`. ``attrs``
        holds ``q``, ``match``, ``filters``, ``total`` (every match, including
        those not returned), ``release_id`` and ``catalog_version``.

    Raises:
        ValueError: ``q`` is blank or too long, ``match`` is unknown, or
            ``limit`` is below 1.
        RequestError: The API refused the search: ``invalid_query`` (a malformed
            full-text query), ``query_too_broad`` (narrow it with a longer ``q``
            or a filter), or ``release_not_found`` (``store_id`` is not served).
        NotImplementedByServer: The API does not offer this kind of search.

    Example:
        ```python
        import opengwaspy as og

        bmi = og.gwasinfo_search("body mass index", assigned_ancestry="EUR")
        locke = og.gwasinfo_search("bmi* AND first_author:locke", match="fulltext")
        ```
    """
    if not isinstance(q, str) or not q.strip():
        raise ValueError("q must be non-empty text")
    if len(q) > MAX_QUERY:
        raise ValueError(f"q is {len(q)} characters; the API takes at most {MAX_QUERY}")
    if match not in ("contains", "fulltext"):
        raise ValueError(f"match must be 'contains' or 'fulltext', not {match!r}")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    client = client or get_client()
    fulltext = match == "fulltext"
    filters = {
        name: value
        for name, value in (
            ("store_id", store_id),
            ("assigned_ancestry", assigned_ancestry),
            ("ancestry_category", ancestry_category),
            ("outcome_type", outcome_type),
            ("trait_class", trait_class),
        )
        if value is not None
    }
    rows: list[dict[str, Any]] = []
    cursor: str | int | None = None
    meta: Mapping[str, Any] = {}
    warned = False
    while True:
        size = PAGE if limit is None else min(PAGE, limit - len(rows))
        body: dict[str, Any] = {"q": q, "match": match, "limit": size, **filters}
        if cursor is not None:
            body["offset" if fulltext else "after"] = cursor
        path = "/api/gwasinfo/search"
        meta = _object(json_body(client.transport.post("api/gwasinfo/search", body)), path)
        rows.extend(meta["analyses"])
        total = meta.get("total")
        wanted = total if limit is None or not isinstance(total, int) else min(limit, total)
        if not warned and isinstance(wanted, int) and wanted > LARGE_LISTING:
            warnings.warn(
                f"fetching {wanted:,} of {total:,} matching analyses, {PAGE:,} per request; "
                "narrow the search, or pass a smaller limit",
                stacklevel=2,
            )
            warned = True
        cursor = meta.get("next_offset" if fulltext else "next_after")
        if cursor is None or not meta["analyses"] or (limit is not None and len(rows) >= limit):
            break
    total = meta.get("total")
    # Past its offset cap the API gives no next_offset, so full-text results can end short.
    capped = fulltext and cursor is None and isinstance(total, int) and len(rows) < total
    if capped and (limit is None or len(rows) < limit):
        warnings.warn(
            f"returned {len(rows):,} of {total:,} matching analyses: the API pages a "
            f"full-text search only to {FULLTEXT_MAX_OFFSET:,}; narrow the query",
            stacklevel=2,
        )
    frame = _frame(rows)
    frame.attrs.update(
        q=q,
        match=match,
        filters=dict(meta.get("filters") or filters),
        total=total,
        release_id=meta.get("release_id"),
        catalog_version=meta.get("catalog_version"),
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
