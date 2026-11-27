"""Service calls on the default client: who you are, and what the API serves."""

from __future__ import annotations

from typing import Any

import pandas as pd

from opengwaspy.client import Client, get_client
from opengwaspy.source import require_api

__all__ = ["batches", "status", "user"]


def status(*, client: Client | None = None) -> dict[str, Any]:
    """The API's status: readiness, served releases, queue state and limits.

    Args:
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.

    Returns:
        The status document.
    """
    return require_api(client or get_client(), "opengwaspy.status").status()


def user(*, client: Client | None = None) -> dict[str, Any]:
    """Who the API takes you to be (``user``, ``role``, ``tier``) and your allowance.

    Args:
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.
    """
    return require_api(client or get_client(), "opengwaspy.user").user()


def batches(*, client: Client | None = None) -> pd.DataFrame:
    """The data releases (Stores) the API serves, one row each.

    In OpenGWAS, a batch was an ID prefix such as ``ieu-a``. In the Data API, a
    batch is a Store release, with its ``store_id``, ``release_id``, analysis
    count and capabilities. ``attrs["opengwas_batches"]`` maps the OpenGWAS
    batches the API resolves (``ukb-b``, ``ebi-a``, ``eqtl-a``, ``finn-b``) to
    the Stores they reach.

    Args:
        client: The client to use; defaults to :func:`~opengwaspy.get_client`.
    """
    return require_api(client or get_client(), "opengwaspy.batches").batches()
