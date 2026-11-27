"""Saving full results as CSV, with a provenance sidecar, into one set folder.

The folder is ``OPENGWAS_MCP_OUTPUT_DIR`` (default ``./opengwas-results``,
relative to the server's working directory), created on demand. Nothing is
written outside it: names are reduced to ``[A-Za-z0-9._-]``, absolute paths,
``..`` and path separators are refused, a symbolic link is never written
through, and an existing file is replaced only with ``overwrite``.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

__all__ = ["DEFAULT_OUTPUT_DIR", "SavedFile", "output_dir", "safe_target", "save_frame"]

DEFAULT_OUTPUT_DIR = "opengwas-results"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class SavedFile(BaseModel):
    """Where a full result was saved."""

    path: str = Field(description="The CSV file, with every row and column.")
    provenance_path: str = Field(description="A JSON file of where the result came from.")
    rows: int
    bytes: int


def output_dir(environ: Mapping[str, str] | None = None) -> Path:
    """The folder results are saved in (not created here)."""
    env = os.environ if environ is None else environ
    return Path(env.get("OPENGWAS_MCP_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR).expanduser().absolute()


def safe_target(name: str, folder: Path, *, overwrite: bool = False) -> Path:
    """The CSV path for ``name`` in ``folder``, if it is safe to write.

    Raises:
        ValueError: The name is empty, absolute, holds a path, would leave the
            folder, names a symbolic link, or names an existing file without
            ``overwrite``.
    """
    raw = name.strip()
    if not raw:
        raise ValueError("save_as is empty")
    if raw.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", raw):
        raise ValueError(f"save_as must be a file name, not a path: {name!r}")
    if "/" in raw or "\\" in raw or ".." in raw:
        raise ValueError(f"save_as must be a plain file name, without folders or '..': {name!r}")
    clean = _UNSAFE.sub("_", raw).lstrip(".")
    if not clean or clean in {".csv"}:
        raise ValueError(f"save_as has no usable characters: {name!r}")
    if not clean.lower().endswith(".csv"):
        clean += ".csv"
    folder.mkdir(parents=True, exist_ok=True)
    real = folder.resolve()
    target = real / clean
    for path in (target, target.with_suffix(".json")):
        if path.is_symlink():
            raise ValueError(f"{path.name} is a symbolic link; it will not be written through")
        if path.exists() and not overwrite:
            raise ValueError(
                f"{path.name} already exists in {real}; choose another name, or pass overwrite=true"
            )
    if target.resolve().parent != real:
        raise ValueError(f"save_as would leave {real}: {name!r}")
    return target


def _write(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` through a temporary file, never following a link."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o644)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(temporary, path)  # replaces a link itself, never its target
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def save_frame(
    frame: pd.DataFrame,
    name: str,
    provenance: Mapping[str, Any],
    *,
    overwrite: bool = False,
    folder: Path | None = None,
) -> SavedFile:
    """Save ``frame`` as CSV, with ``provenance`` in a JSON file beside it.

    Raises:
        ValueError: ``name`` is not safe (see :func:`safe_target`).
    """
    target = safe_target(name, folder or output_dir(), overwrite=overwrite)
    data = frame.to_csv(index=False).encode("utf-8")
    sidecar = target.with_suffix(".json")
    _write(target, data)
    _write(
        sidecar,
        json.dumps(
            {"file": target.name, "rows": len(frame), **provenance}, indent=2, default=str
        ).encode("utf-8"),
    )
    return SavedFile(
        path=str(target), provenance_path=str(sidecar), rows=len(frame), bytes=len(data)
    )
