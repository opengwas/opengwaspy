"""opengwaspy: the Python client for the OpenGWAS Data API.

opengwaspy succeeds ieugwaspy. It queries OpenGWAS metadata, associations,
top hits, PheWAS, variants and LD through the job-based Data API, and returns
pandas DataFrames.

The functions at the top level use a default :class:`Client`, configured from
the environment (``OPENGWAS_URL``, ``OPENGWAS_TOKEN``) and the config file on
first use. Call :func:`configure` to change it.
"""

__version__ = "0.0.1.dev0"

from opengwaspy.associations import associations, associations_analysis, associations_range
from opengwaspy.auth import DeveloperKey, NoAuth, OpenGWASToken
from opengwaspy.batch import BatchError, run_many
from opengwaspy.client import Client, Limits, configure, get_client
from opengwaspy.config import Config, ConfigError
from opengwaspy.errors import (
    APIError,
    AuthError,
    BusyError,
    JobFailed,
    LDRefusal,
    NotImplementedByServer,
    OpenGWASError,
    RateLimitError,
    RequestError,
    UnsupportedOptionError,
)
from opengwaspy.hits import phewas, tophits
from opengwaspy.jobs import Job, JobTimeout
from opengwaspy.ld import ld_clump, ld_matrix, ld_proxies, ld_reflookup, ld_region, ld_stores
from opengwaspy.local import LocalSource, local
from opengwaspy.metadata import gwasinfo, gwasinfo_files, gwasinfo_search
from opengwaspy.rho import rho
from opengwaspy.service import batches, status, user
from opengwaspy.source import LocalUnsupported, Source
from opengwaspy.variants import variants_chrpos, variants_rsid

__all__ = [
    "APIError",
    "AuthError",
    "BatchError",
    "BusyError",
    "Client",
    "Config",
    "ConfigError",
    "DeveloperKey",
    "Job",
    "JobFailed",
    "JobTimeout",
    "LDRefusal",
    "Limits",
    "LocalSource",
    "LocalUnsupported",
    "NoAuth",
    "NotImplementedByServer",
    "OpenGWASError",
    "OpenGWASToken",
    "RateLimitError",
    "RequestError",
    "Source",
    "UnsupportedOptionError",
    "__version__",
    "associations",
    "associations_analysis",
    "associations_range",
    "batches",
    "configure",
    "get_client",
    "gwasinfo",
    "gwasinfo_files",
    "gwasinfo_search",
    "ld_clump",
    "ld_matrix",
    "ld_proxies",
    "ld_reflookup",
    "ld_region",
    "ld_stores",
    "local",
    "phewas",
    "rho",
    "run_many",
    "status",
    "tophits",
    "user",
    "variants_chrpos",
    "variants_rsid",
]
