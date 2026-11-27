"""The MCP server with OpenGWAS tokens (JWT) through the Gateway, against Gateway fakes."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import respx
from mcp import Client as MCPClient
from mcp.types import CallToolResult

from opengwaspy.auth import DeveloperKey, NoAuth, OpenGWASToken
from opengwaspy.config import ConfigError
from opengwaspy.mcp import create_server
from opengwaspy.mcp.credentials import ReloadingAuth

GATEWAY = "https://api.opengwas.io/ogdb"
OLD, NEW = "old.jwt.token-1111", "new.jwt.token-2222"
RESET = int(time.time()) + 3600


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.toml"
    monkeypatch.setenv("OPENGWAS_CONFIG", str(path))
    for name in ("OPENGWAS_JWT", "OPENGWAS_TOKEN", "OPENGWAS_URL", "OPENGWAS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    return path


def save(path: Path, token: str) -> None:
    path.write_text(f'profile = "gateway"\njwt = "{token}"\n')
    path.chmod(0o600)


def allowance(remaining: int) -> dict[str, str]:
    return {
        "X-Allowance-Limit": "100000",
        "X-Allowance-Remaining": str(remaining),
        "X-Allowance-Reset": str(RESET),
    }


def gateway(valid: set[str], *, remaining: int = 99_000) -> respx.Route:
    """A Gateway that accepts tokens in ``valid`` and adds X-Allowance-* to every answer."""

    def search(request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in valid:
            return httpx.Response(
                401, json={"error": "unauthorized", "message": f"token {token} revoked"}
            )
        return httpx.Response(
            200,
            headers=allowance(remaining),
            json={"total": 1, "release_id": "r", "analyses": [{"id": "OGS-1:A"}]},
        )

    respx.get(f"{GATEWAY}/api/status").respond(json={"ready": True, "execution": {}})
    return respx.post(f"{GATEWAY}/api/gwasinfo/search").mock(side_effect=search)


def session(*steps: Any, **server: Any) -> list[CallToolResult]:
    """Run tool calls (or plain callables, between them) in one server session."""
    mcp_server = create_server(**server)

    async def main() -> list[CallToolResult]:
        out = []
        async with MCPClient(mcp_server) as client:
            for step in steps:
                if callable(step):
                    step()
                else:
                    out.append(await client.call_tool(*step))
        return out

    results: list[CallToolResult] = anyio.run(main)
    return results


def text(result: CallToolResult) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.content)


SEARCH = ("search_analyses", {"q": "bmi"})


@respx.mock
def test_jwt_through_the_gateway_prefix_with_allowance(config_file: Path) -> None:
    save(config_file, OLD)
    route = gateway({OLD})
    (result,) = session(SEARCH)
    assert not result.is_error, text(result)
    request = route.calls[0].request
    assert str(request.url) == f"{GATEWAY}/api/gwasinfo/search"
    assert request.headers["Authorization"] == f"Bearer {OLD}"
    out = result.structured_content
    assert out is not None
    assert out["provenance"]["allowance"]["remaining"] == 99_000
    assert out["provenance"]["allowance"]["limit"] == 100_000
    assert "Allowance left: 99,000 of 100,000, until" in out["summary"]
    assert OLD not in text(result) and OLD not in json.dumps(out)


@respx.mock
def test_a_renewed_token_in_the_config_file_is_used_without_restart(config_file: Path) -> None:
    save(config_file, OLD)
    route = gateway({NEW})
    first, second = session(SEARCH, lambda: save(config_file, NEW), SEARCH)
    assert first.is_error
    message = text(first)
    assert "14 days" in message and "config file" in message and "OPENGWAS_JWT" in message
    assert OLD not in message
    assert not second.is_error, text(second)
    assert route.calls[-1].request.headers["Authorization"] == f"Bearer {NEW}"


@respx.mock
def test_a_token_in_the_environment_cannot_change(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENGWAS_JWT", OLD)
    monkeypatch.setenv("OPENGWAS_PROFILE", "gateway")
    gateway({NEW})
    (result,) = session(SEARCH)
    assert result.is_error and "restart the server" in text(result)
    assert OLD not in text(result)


@respx.mock
def test_a_token_saved_after_start_is_picked_up(config_file: Path) -> None:
    config_file.write_text('profile = "gateway"\n')
    gateway({NEW})
    first, second = session(SEARCH, lambda: save(config_file, NEW), SEARCH)
    assert first.is_error and "No OpenGWAS credential" in text(first)
    assert not second.is_error, text(second)


@respx.mock
def test_api_status_shows_allowance_and_kind_never_the_token(config_file: Path) -> None:
    save(config_file, OLD)
    gateway({OLD})
    respx.get(f"{GATEWAY}/api/user").respond(
        json={"user": "u@example.org", "role": "user"}, headers=allowance(500)
    )
    respx.get(f"{GATEWAY}/api/ld/stores").respond(json={"stores": []}, headers=allowance(499))
    respx.get(f"{GATEWAY}/api/batches").respond(json={"batches": []}, headers=allowance(498))
    (result,) = session(("api_status", {}))
    out = result.structured_content
    assert out is not None
    assert out["api"]["profile"] == "gateway"
    assert out["auth"]["kind"] == "OpenGWAS token"
    assert out["auth"]["allowance"]["remaining"] == 498
    assert OLD not in json.dumps(out)


@respx.mock
def test_allowance_429_fails_fast_with_the_reset_time(config_file: Path) -> None:
    save(config_file, OLD)
    respx.get(f"{GATEWAY}/api/status").respond(json={"ready": True, "execution": {}})
    respx.post(f"{GATEWAY}/api/gwasinfo/search").respond(
        429,
        headers={**allowance(0), "Retry-After": "3600"},
        json={"error": "allowance_exhausted", "message": "allowance used up"},
    )
    started = time.monotonic()
    (result,) = session(SEARCH)
    assert time.monotonic() - started < 10
    assert result.is_error
    assert "Your OpenGWAS allowance is used up until" in text(result)
    assert time.strftime("%Y-%m-%d", time.localtime(RESET)) in text(result)


def test_reloading_auth() -> None:
    providers: list[Any] = [NoAuth(), DeveloperKey("k1234"), DeveloperKey("k1234")]

    def load() -> Any:
        provider = providers.pop(0)
        if isinstance(provider, Exception):
            raise provider
        return provider

    auth = ReloadingAuth(load)
    assert auth.headers() == {} and "NoAuth" in repr(auth)
    assert auth.refresh() is True and auth.headers() == {"Authorization": "Bearer k1234"}
    assert auth.refresh() is False
    providers.append(ConfigError("bad"))
    assert auth.refresh() is False
    assert isinstance(auth.current, DeveloperKey)
    assert "k1234" not in repr(auth)
    assert isinstance(OpenGWASToken("t1234"), OpenGWASToken)
