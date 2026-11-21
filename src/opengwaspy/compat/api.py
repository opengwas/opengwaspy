"""ieugwaspy's service, configuration and metadata functions."""

from __future__ import annotations

import warnings
import webbrowser
from typing import Any

import pandas as pd

import opengwaspy as og
from opengwaspy.compat._ids import legacy_ids, resolve
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


def gwasinfo(id: list[str] | str | None = None) -> pd.DataFrame:
    """Metadata of analyses, as ieugwaspy's ``gwasinfo``, with a ``trait`` column.

    OpenGWAS IDs are translated by the Data API: ``ukb-b-*``, ``ebi-a-GCST*``
    and ``eqtl-a-ENSG*`` to the same analysis, and ``finn-b-*`` to its successor
    in a later FinnGen release (with a warning). Other OpenGWAS batches, such as
    ``ieu-a``, are not held by any Store.

    Args:
        id: Analysis IDs, Data API or OpenGWAS; empty or ``None`` lists every
            analysis (about 40 requests of 1,000).

    Returns:
        One row per analysis, ``id`` first and ``trait`` (the analysis label)
        second, then the Data API's metadata columns, and ``opengwas_id`` (the ID
        each analysis was asked for) last. ``attrs["opengwas_ids"]`` says how each OpenGWAS ID was
        translated, or why it was not; untranslated IDs are also printed,
        because ieugwaspy users are used to getting them silently dropped.
    """
    ids = [id] if isinstance(id, str) else list(id or [])
    if not ids:
        frame = og.gwasinfo()
        if not frame.empty:
            frame.insert(1, "trait", frame.get("analysis_label"))
        return frame
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolved = resolve(ids)
    for warning in caught:  # successors still warn; what is left out is printed below
        if "are left out" not in str(warning.message):
            warnings.warn(warning.message, warning.category, stacklevel=2)
    frame = resolved.info.copy()
    if not frame.empty:
        order = {analysis: n for n, analysis in enumerate(resolved.ids)}
        frame = frame[frame["id"].isin(order)].copy()
        frame = frame.iloc[frame["id"].map(order).argsort()].reset_index(drop=True)
        frame.attrs.update(resolved.info.attrs)
        frame = resolved.label(frame)
        frame.insert(1, "trait", frame.get("analysis_label"))
    else:
        frame.attrs["opengwas_ids"] = resolved.opengwas
    missing = [e for e in resolved.opengwas if "reason" in e]
    if missing:
        shown = ", ".join(f"{e['id']} ({e['reason']})" for e in missing[:10])
        print(
            f"{len(missing)} IDs are not served by the Data API: {shown}"
            + (" ..." if len(missing) > 10 else "")
        )
    return frame


def gwasinfo_files(id: list[str] | str) -> pd.DataFrame:
    """Source-file records of analyses' Stores (ieugwaspy returned download links).

    The Data API has no download links. This lists the source files recorded by
    the Stores holding these analyses. On 19 Nov 2026 no Store records them, so
    it raises :class:`~opengwaspy.NotImplementedByServer`.
    """
    ids = [id] if isinstance(id, str) else list(id)
    info = resolve(ids).info
    stores = sorted(set(info["store_id"])) if "store_id" in info else []
    if not stores:
        raise og.RequestError(404, "analysis_not_found", f"none of {ids} is served")
    return og.gwasinfo_files(releases=stores)
