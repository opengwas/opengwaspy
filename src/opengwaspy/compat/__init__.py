"""ieugwaspy-compatible functions, on the OpenGWAS Data API.

``opengwaspy.compat`` offers ieugwaspy 1.0.6's functions with ieugwaspy's
names, arguments and defaults, so existing code needs few changes::

    import opengwaspy.compat as ieugwaspy

Differences from ieugwaspy:

* Results are pandas DataFrames, not JSON. They keep ieugwaspy's column names
  (``id``, ``trait``, ``rsid``, ``beta``, ``se``, ``p``, ``n``, ...) beside the
  Data API's own columns. Columns opengwaspy derives are listed in
  :data:`DERIVED`.
* An option that cannot be honoured exactly is refused, with an explanation,
  rather than ignored. ieugwaspy's default top-hits clumping is one: see
  :func:`tophits`.

See the migration guide for every function, and what differs.
"""

from __future__ import annotations

from opengwaspy.compat._columns import DERIVED, ieugwas_columns
from opengwaspy.compat.api import (
    get_jwt,
    gwasinfo,
    gwasinfo_files,
    legacy_ids,
    select_api,
    status,
    user,
)
from opengwaspy.compat.hits import tophits
from opengwaspy.compat.variants import phewas, variants_chrpos, variants_to_rsid

__all__ = [
    "DERIVED",
    "get_jwt",
    "gwasinfo",
    "gwasinfo_files",
    "ieugwas_columns",
    "legacy_ids",
    "phewas",
    "select_api",
    "status",
    "tophits",
    "user",
    "variants_chrpos",
    "variants_to_rsid",
]
