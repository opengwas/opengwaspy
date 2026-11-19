"""ieugwaspy's service, configuration and metadata functions."""

from __future__ import annotations

import webbrowser
from typing import Any

import pandas as pd

import opengwaspy as og
from opengwaspy.config import PROFILES, save_setting

__all__ = [
    "get_jwt",
    "gwasinfo",
    "gwasinfo_files",
    "legacy_ids",
    "select_api",
    "status",
    "user",
]

#: Where an OpenGWAS token is issued.
URL_OBTAIN_JWT = "https://api.opengwas.io/profile/"

#: ieugwaspy's API keys, as opengwaspy profiles.
API_KEYS: dict[str, str] = {
    "public": "gateway",
    "dev": "local",
    "local": "local",
    "gateway": "gateway",
}


def status() -> dict[str, Any]:
    """The API's status (as ieugwaspy's ``status``)."""
    return og.status()


def user() -> dict[str, Any]:
    """Who the API takes you to be (as ieugwaspy's ``user``)."""
    return og.user()


def select_api(key: str = "public") -> dict[str, Any] | None:
    """Choose which API to use, as ieugwaspy's ``select_api`` did.

    ``public`` is the OpenGWAS Gateway; ``dev`` (or ``local``) a Data API on this
    machine. A full URL is also accepted. Credentials still come from the
    environment and config file.

    Args:
        key: ``public``, ``dev``, ``local``, ``gateway``, or a URL.

    Returns:
        The new API's status, or ``None`` if ``key`` is unknown (the choices
        are printed, as ieugwaspy did).
    """
    if key.startswith(("http://", "https://")):
        client = og.configure(url=key)
    elif key in API_KEYS:
        client = og.configure(profile=API_KEYS[key])
    else:
        choices = "\n".join(f"{k} - {PROFILES[v]}" for k, v in API_KEYS.items())
        print("Please select one from the following: \n" + choices)
        return None
    print("API server is now: " + client.config.base_url)
    return client.status()


def get_jwt() -> None:
    """Get an OpenGWAS token and save it, as ieugwaspy's ``get_jwt`` did.

    Opens the OpenGWAS profile page, asks you to paste the token, and saves it
    as ``jwt`` in your user config file (mode 0600). ieugwaspy saved it to
    ``.ieugwaspy.json`` in the working directory instead.
    """
    webbrowser.open(URL_OBTAIN_JWT)
    token = input("Paste your token (JWT) like ey****.******.******:\n").strip()
    if not token:
        print("No token given; nothing saved.")
        return
    path = save_setting("jwt", token)
    og.configure(jwt=token)
    print(f"\nYour token has been saved to {path}")


def legacy_ids(study_ids: list[str]) -> list[str]:
    """Convert legacy OpenGWAS study IDs (``UKB-a:``, ``IEU-a:``) to the newer form.

    Kept from ieugwaspy for old code. OpenGWAS IDs such as ``ieu-a-2`` are not
    Data API analysis IDs: look analyses up with :func:`gwasinfo`.
    """
    substitutions = {"UKB-a:": "ukb-a-", "UKB-b:": "ukb-b-", "UKB-c:": "ukb-c-", "IEU-a:": "ieu-a-"}
    result = []
    for study in study_ids:
        for old, new in substitutions.items():
            study = study.replace(old, new)
        result.append(study)
    return result


def gwasinfo(id: list[str] | str | None = None) -> pd.DataFrame:
    """Metadata of analyses, as ieugwaspy's ``gwasinfo``, with a ``trait`` column.

    Args:
        id: Analysis IDs; empty or ``None`` lists every analysis (about 40
            requests of 1,000).

    Returns:
        One row per analysis, ``id`` first and ``trait`` (the analysis label)
        second, then the Data API's metadata columns. IDs not served are in
        ``attrs["not_found"]``, and are also printed, because ieugwaspy users
        are used to getting them silently dropped.
    """
    ids = [id] if isinstance(id, str) else list(id or [])
    frame = og.gwasinfo(legacy_ids(ids)) if ids else og.gwasinfo()
    if not frame.empty:
        frame.insert(1, "trait", frame.get("analysis_label"))
    missing = frame.attrs.get("not_found") or []
    if missing:
        shown = ", ".join(missing[:10]) + (" ..." if len(missing) > 10 else "")
        print(f"{len(missing)} IDs are not served by the Data API: {shown}")
    return frame


def gwasinfo_files(id: list[str] | str) -> pd.DataFrame:
    """Source-file records of analyses' Stores (ieugwaspy returned download links).

    The Data API has no download links. This lists the source files recorded by
    the Stores holding these analyses. On 19 Nov 2026 no Store records them, so
    it raises :class:`~opengwaspy.NotImplementedByServer`.
    """
    ids = [id] if isinstance(id, str) else list(id)
    info = og.gwasinfo(legacy_ids(ids))
    stores = sorted(set(info["store_id"])) if "store_id" in info else []
    if not stores:
        raise og.RequestError(404, "analysis_not_found", f"none of {ids} is served")
    return og.gwasinfo_files(releases=stores)
