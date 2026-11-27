"""An MCP server, so AI assistants can query OpenGWAS through opengwaspy.

Install the extra and run the server over stdio::

    pip install "opengwaspy[mcp]"
    opengwaspy-mcp

The server reads the usual configuration (see :mod:`opengwaspy.config`). Users
sign in with an OpenGWAS token (``OPENGWAS_JWT``) through the Gateway;
developers may use a developer key. No tool takes or returns a credential.
"""

from __future__ import annotations

try:
    import mcp.server.mcpserver  # noqa: F401
except ImportError as exc:  # pragma: no cover - depends on the environment
    raise ImportError(
        'the MCP server needs the "mcp" extra: pip install "opengwaspy[mcp]"'
    ) from exc

from opengwaspy.mcp.server import create_server

__all__ = ["create_server"]
