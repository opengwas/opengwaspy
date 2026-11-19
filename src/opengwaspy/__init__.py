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
from opengwaspy.jobs import Job, JobTimeout
from opengwaspy.metadata import gwasinfo, gwasinfo_files
from opengwaspy.service import batches, status, user

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
    "NoAuth",
    "NotImplementedByServer",
    "OpenGWASError",
    "OpenGWASToken",
    "RateLimitError",
    "RequestError",
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
    "run_many",
    "status",
    "user",
]
