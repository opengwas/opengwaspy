"""Query downloaded Store Releases on your own machine, through ogquery.

A Local Source answers the same requests as the Data API, with the same rows,
from Store Releases you have downloaded. Pass it as ``client`` to the query
functions::

    import opengwaspy as og

    with og.local(["/data/OGS-00006/<release_id>"]) as source:
        og.associations(["rs1205"], ["OGS-00006:GCST90199621"], client=source)

It needs the ``local`` extra (``pip install "opengwaspy[local]"``, Python 3.12
or later), which installs `ogquery <https://github.com/opengwas/ogquery>`_, the
Store Reader the Data API itself reads Stores with.
"""

from __future__ import annotations

from opengwaspy.local._ld import LocalLDError, LocalLDStore
from opengwaspy.local._source import (
    LocalExtraMissing,
    LocalRelease,
    LocalSource,
    LocalSourceError,
    local,
)
from opengwaspy.source import LocalUnsupported

__all__ = [
    "LocalExtraMissing",
    "LocalLDError",
    "LocalLDStore",
    "LocalRelease",
    "LocalSource",
    "LocalSourceError",
    "LocalUnsupported",
    "local",
]
