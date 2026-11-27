"""Helpers for driving the MCP server through the SDK's in-memory client."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import httpx
from mcp import Client as MCPClient
from mcp.types import CallToolResult

from opengwaspy.auth import DeveloperKey
from opengwaspy.client import Client
from opengwaspy.config import Config
from opengwaspy.mcp import create_server
from opengwaspy.transport import Transport
from tests.fakes import FakeClock

BASE = "http://api.test"
SECRET = "sekrit-token-value-123"


def client_with(auth: Any) -> Callable[[], Client]:
    def make() -> Client:
        clock = FakeClock()
        transport = Transport(
            Config(base_url=BASE, auth=auth),
            client=httpx.Client(),
            sleep=clock.sleep,
            clock=clock.monotonic,
            wall_clock=clock.time,
        )
        return Client(transport=transport)

    return make


def run(factory: Callable[[], Client], body: Callable[[MCPClient], Awaitable[Any]]) -> Any:
    server = create_server(client_factory=factory)

    async def main_() -> Any:
        async with MCPClient(server) as mcp:
            return await body(mcp)

    return anyio.run(main_)


def call(
    factory: Callable[[], Client], tool: str, args: dict[str, Any] | None = None
) -> CallToolResult:
    async def body(mcp: MCPClient) -> CallToolResult:
        return await mcp.call_tool(tool, args or {})

    result: CallToolResult = run(factory, body)
    return result


def text_of(result: CallToolResult) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.content)


def keyed() -> Client:
    """A client with a developer key, against the fake API."""
    return client_with(DeveloperKey(SECRET))()
