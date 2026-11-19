"""Associations: effect estimates of variants in analyses.

Every association row has the analysis (``analysis_id``, ``analysis_label``),
the variant (``alid``, ``chromosome``, ``position``, ``rsid``,
``effect_allele``, ``other_allele``), and the estimate (``eaf``, ``se``, ``z``,
``log10_p``, and ``p``, which opengwaspy derives as ``10 ** log10_p``), with
``association_status`` (observed or imputed) and the Store release.

Large requests are split into jobs within the API's limits and run a few at a
time; the rows come back in a stable order.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from opengwaspy._common import ReleaseLike, add_p, as_list, chunks, drop_none, resolve_releases, run
from opengwaspy.client import Client, get_client

__all__ = ["associations", "associations_analysis", "associations_range"]


def associations(
    variants: str | Iterable[str],
    analyses: str | Iterable[str],
    *,
    observed_only: bool = True,
    releases: Iterable[ReleaseLike] | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """Associations of some variants in some analyses.

    Variants absent from an analysis give no row: there are no LD proxies here.
    (The ieugwaspy-compatible layer offers proxies.)

    Args:
        variants: rsIDs (``rs1205``) or ALIDs (``7:105561135:A:G``).
        analyses: Analysis IDs, bare or Store-qualified.
        observed_only: Leave out imputed associations.
        releases: Only these Stores' releases (Store IDs, ``store/release``, or dicts).
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        One row per association found, with ``p`` derived from ``log10_p``. Rows
        are grouped by chunk of analyses, then by chunk of variants; within a
        job they are ordered by Store, analysis and position.
    """
    client = client or get_client()
    variant_list = as_list(variants, "variants") or []
    analysis_list = as_list(analyses, "analyses") or []
    limits = client.limits
    release_refs = resolve_releases(client, releases)
    bodies = [
        drop_none(
            {
                "variants": vs,
                "analyses": an,
                "observed_only": observed_only,
                "releases": release_refs,
            }
        )
        for an in chunks(analysis_list, limits.lookup_analyses)
        for vs in chunks(variant_list, limits.lookup_variants)
    ]
    return add_p(run(client, "api/associations", bodies))


def associations_range(
    chromosome: str | int,
    start: int,
    end: int,
    analyses: str | Iterable[str] | None = None,
    *,
    observed_only: bool = True,
    releases: Iterable[ReleaseLike] | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """Every association in a genomic range.

    The range is split into windows of at most the API's ``range_span``
    (10 Mb), and the analyses into groups of ``range_analyses`` (10).

    Args:
        chromosome: Chromosome name, such as ``7`` or ``X``.
        start: First position, one-based, inclusive.
        end: Last position, inclusive.
        analyses: Analysis IDs. ``None`` means every analysis of ``releases``.
        observed_only: Leave out imputed associations.
        releases: Only these Stores' releases.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        The associations, by group of analyses, then window, with ``p`` added.
    """
    client = client or get_client()
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not (isinstance(start, int) and isinstance(end, int))
    ):
        raise TypeError("start and end must be integers")
    if start < 1 or end < start:
        raise ValueError(f"need 1 <= start <= end, got {start}..{end}")
    chromosome = str(chromosome).strip()
    if chromosome.lower().startswith("chr"):
        chromosome = chromosome[3:]
    if not chromosome:
        raise ValueError("chromosome is empty")
    limits = client.limits
    analysis_list = as_list(analyses, "analyses")
    groups: list[list[str] | None] = (
        list(chunks(analysis_list, limits.range_analyses)) if analysis_list else [None]
    )
    release_refs = resolve_releases(client, releases)
    bodies = []
    for group in groups:
        for window_start in range(start, end + 1, limits.range_span):
            window_end = min(window_start + limits.range_span - 1, end)
            bodies.append(
                drop_none(
                    {
                        "chromosome": chromosome,
                        "start": window_start,
                        "end": window_end,
                        "analyses": group,
                        "observed_only": observed_only,
                        "releases": release_refs,
                    }
                )
            )
    return add_p(run(client, "api/associations/range", bodies))


def associations_analysis(
    analyses: str | Iterable[str],
    *,
    observed_only: bool = True,
    releases: Iterable[ReleaseLike] | None = None,
    client: Client | None = None,
) -> pd.DataFrame:
    """Every association of whole analyses.

    This suits Ragged Stores (signals-only and cis-eQTL analyses, up to tens of
    thousands of rows each). A whole Dense or Hybrid analysis is too large for
    one job: the API refuses it with ``413 request_too_large``. Fetch it with
    :func:`associations_range` instead.

    Args:
        analyses: Analysis IDs, in groups of the API's ``analysis_analyses`` (10).
        observed_only: Leave out imputed associations.
        releases: Only these Stores' releases.
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.
    """
    client = client or get_client()
    analysis_list = as_list(analyses, "analyses") or []
    release_refs = resolve_releases(client, releases)
    bodies = [
        drop_none({"analyses": group, "observed_only": observed_only, "releases": release_refs})
        for group in chunks(analysis_list, client.limits.analysis_analyses)
    ]
    return add_p(run(client, "api/associations/analysis", bodies))
