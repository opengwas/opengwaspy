"""The MCP server, driven through the SDK's in-memory client against fake APIs."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import respx
from mcp import Client as MCPClient
from mcp.types import CallToolResult

from opengwaspy.auth import NoAuth, OpenGWASToken
from opengwaspy.client import Client
from opengwaspy.config import Config, ConfigError
from opengwaspy.mcp import create_server
from opengwaspy.mcp.__main__ import main
from opengwaspy.mcp.server import NO_CREDENTIAL, Session, profile_name, scrub
from opengwaspy.transport import Transport
from tests.fakes import FakeClock, JobServer

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


def serve(*, user: Any = None, user_status: int = 200) -> respx.Route:
    JobServer(
        BASE,
        lambda e, b: [],
        opengwas_batches=[{"batch": "ukb-b", "store_ids": ["OGS-00009"], "match": "exact"}],
    )
    route = respx.get(f"{BASE}/api/user").respond(
        user_status, json=user if user is not None else {"user": "u1", "role": "user"}
    )
    respx.get(f"{BASE}/api/ld/stores").respond(
        json={"stores": [{"store": "s-EUR", "ancestry": "EUR", "n": 665, "t_far": 0.03}]}
    )
    return route


@respx.mock
def test_lists_api_status_with_annotations_and_instructions() -> None:
    serve()

    async def body(mcp: MCPClient) -> Any:
        return await mcp.list_tools(), mcp.instructions, mcp.server_info

    tools, instructions, info = run(client_with(OpenGWASToken(SECRET)), body)
    by_name = {t.name: t for t in tools.tools}
    tool = by_name["api_status"]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.open_world_hint is True
    assert tool.input_schema["properties"] == {}
    assert instructions is not None and "read-only" in instructions
    assert info is not None and info.name == "opengwas"


@respx.mock
def test_api_status_reports_api_auth_kind_user_stores_and_batches() -> None:
    serve()
    result = call(client_with(OpenGWASToken(SECRET)), "api_status")
    assert not result.is_error
    out = result.structured_content
    assert out is not None
    assert out["api"] == {
        "url": BASE,
        "profile": "custom",
        "ready": True,
        "image_digest": "sha256:test",
        "release_ids": None,
    }
    assert out["auth"] == {"kind": "OpenGWAS token", "user": {"user": "u1", "role": "user"}}
    assert out["ld_stores"] == [{"store": "s-EUR", "ancestry": "EUR", "n": 665}]
    assert out["batches"]["releases"] == [{"store_id": "OGS-1", "release_id": "OGS-1-r1"}]
    assert out["batches"]["opengwas_batches"][0]["batch"] == "ukb-b"
    assert SECRET not in text_of(result) and SECRET not in json.dumps(out)


@respx.mock
def test_no_credential_still_starts_and_says_how_to_configure() -> None:
    user = serve()
    result = call(client_with(NoAuth()), "api_status")
    assert not result.is_error
    out = result.structured_content
    assert out is not None
    assert out["auth"]["kind"] == "none"
    assert "OPENGWAS_JWT" in out["auth"]["note"]
    assert "user" not in out["auth"]
    assert not user.called


@respx.mock
def test_refused_credential_explains_renewal_and_hides_the_token() -> None:
    serve(user={"error": f"bad token {SECRET}", "code": "unauthorised"}, user_status=401)
    result = call(client_with(OpenGWASToken(SECRET)), "api_status")
    out = result.structured_content
    assert out is not None
    message = out["auth"]["user"]["error"]
    assert "14 days" in message and "OPENGWAS_JWT" in message
    assert SECRET not in json.dumps(out) and SECRET not in text_of(result)


@respx.mock
def test_status_failure_is_reported_not_raised() -> None:
    respx.get(f"{BASE}/api/status").respond(404, json={"error": "nope"})
    result = call(client_with(OpenGWASToken(SECRET)), "api_status")
    out = result.structured_content
    assert out is not None and "error" in out["api"]
    assert "auth" in out and "user" not in out["auth"]


def test_invalid_configuration_still_starts() -> None:
    def broken() -> Client:
        raise ConfigError("unknown profile 'nope'")

    result = call(broken, "api_status")
    assert result.structured_content == {"configured": False, "error": "unknown profile 'nope'"}


def test_session_require_client_and_auth_kinds() -> None:
    session = Session(None, "bad")
    with pytest.raises(Exception, match="invalid: bad"):
        session.require_client()
    assert session.auth_kind == "none"
    no_auth = Session(client_with(NoAuth())())
    with pytest.raises(Exception, match="No OpenGWAS credential"):
        no_auth.require_client()
    assert NO_CREDENTIAL.startswith("No OpenGWAS credential")
    keyed = Session(client_with(OpenGWASToken(SECRET))())
    assert keyed.require_client() is keyed.client


def test_scrub_hides_secrets_at_any_depth() -> None:
    value = {"a": [f"x {SECRET} y", ("t", SECRET)], SECRET: 1, "n": 2}
    assert scrub(value, [SECRET]) == {
        "a": ["x <hidden> y", ("t", "<hidden>")],
        "<hidden>": 1,
        "n": 2,
    }
    assert scrub(value, []) is value


def test_profile_name() -> None:
    assert profile_name("https://api.opengwas.io/ogdb") == "gateway"
    assert profile_name("http://elsewhere") == "custom"


def test_main_runs_stdio_server(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_create(**kwargs: Any) -> Any:
        seen.update(kwargs)

        class Fake:
            def run(self, transport: str) -> None:
                seen["transport"] = transport

        return Fake()

    monkeypatch.setattr("opengwaspy.mcp.server.create_server", fake_create)
    main(["--profile", "gateway"])
    assert seen == {"url": None, "profile": "gateway", "transport": "stdio"}


def test_main_never_takes_a_credential() -> None:
    with pytest.raises(SystemExit):
        main(["--token", "x"])


def test_default_factory_reads_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENGWAS_CONFIG", str(tmp_path / "none.toml"))
    monkeypatch.delenv("OPENGWAS_TOKEN", raising=False)
    monkeypatch.setenv("OPENGWAS_JWT", SECRET)
    server = create_server(url=BASE)

    async def main_() -> Any:
        async with MCPClient(server) as mcp:
            return await mcp.call_tool("api_status", {})

    with respx.mock:
        serve()
        result = anyio.run(main_)
    assert result.structured_content["auth"]["kind"] == "OpenGWAS token"
    assert SECRET not in text_of(result)
