"""The ``opengwaspy-mcp`` command: run the MCP server over stdio."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from opengwaspy import __version__
from opengwaspy.config import PROFILES


def main(argv: Sequence[str] | None = None) -> None:
    """Run the OpenGWAS MCP server over stdio.

    Credentials are never taken on the command line, where other users of the
    machine could see them: set ``OPENGWAS_JWT`` (or, for developers,
    ``OPENGWAS_TOKEN``) or use the config file.
    """
    parser = argparse.ArgumentParser(
        prog="opengwaspy-mcp",
        description="Run the OpenGWAS MCP server over stdio, for AI assistants.",
        epilog="Credentials come from OPENGWAS_JWT (users) or OPENGWAS_TOKEN (developers), "
        "or the opengwaspy config file; never from the command line.",
    )
    parser.add_argument("--url", help="the API's base URL (else OPENGWAS_URL or the config file)")
    parser.add_argument("--profile", choices=sorted(PROFILES), help="a named base URL")
    parser.add_argument("--version", action="version", version=f"opengwaspy {__version__}")
    args = parser.parse_args(argv)

    # stdout carries the protocol; logs go to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    from opengwaspy.mcp.server import create_server

    create_server(url=args.url, profile=args.profile).run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
