import json

import httpx
import pytest
import respx

from opengwaspy import __version__
from opengwaspy.auth import DeveloperKey
from opengwaspy.config import Config
from opengwaspy.errors import (
    AuthError,
    BusyError,
    NotImplementedByServer,
    ProtocolError,
    RateLimitError,
    RequestError,
    ServerError,
    TransportError,
)
from opengwaspy.transport import Transport, json_body
from tests.fakes import FakeClock

BASE = "http://api.test"


def make(clock: FakeClock, **options: object) -> Transport:
    config = Config(base_url=BASE, auth=DeveloperKey("k3y"), **options)  # type: ignore[arg-type]
    return Transport(
        config,
        client=httpx.Client(),
        sleep=clock.sleep,
        clock=clock.monotonic,
        wall_clock=clock.time,
        jitter=lambda: 0.5,
    )


def err(status: int, code: str, **headers: str) -> httpx.Response:
    return httpx.Response(status, json={"error": code, "message": code}, headers=headers)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@respx.mock
def test_headers_and_json(clock: FakeClock) -> None:
    route = respx.post(f"{BASE}/api/tophits").respond(202, json={"job_id": "j"})
    with make(clock) as transport:
        response = transport.post("api/tophits", {"analyses": ["a"]})
    assert json_body(response) == {"job_id": "j"}
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer k3y"
    assert sent.headers["X-API-Source"] == f"opengwaspy/{__version__}"
    assert sent.headers["User-Agent"].startswith(f"opengwaspy/{__version__}")
    assert len(sent.headers["X-Request-ID"]) == 32
    assert json.loads(sent.content) == {"analyses": ["a"]}
    assert clock.sleeps == []


@respx.mock
def test_get_params_and_delete(clock: FakeClock) -> None:
    get = respx.get(f"{BASE}/api/gwasinfo", params={"limit": "2"}).respond(200, json={})
    delete = respx.delete(f"{BASE}/api/jobs/j").respond(200, json={})
    transport = make(clock)
    transport.get("api/gwasinfo", params={"limit": 2})
    transport.delete("/api/jobs/j")
    assert get.called and delete.called


@respx.mock
def test_retry_after_is_honoured_with_same_request_id(clock: FakeClock) -> None:
    route = respx.post(f"{BASE}/api/jobs").mock(
        side_effect=[
            err(429, "server_busy", **{"Retry-After": "3"}),
            err(503, "intake_paused", **{"Retry-After": "0"}),
            httpx.Response(202, json={}),
        ]
    )
    make(clock).post("api/jobs", {})
    assert clock.sleeps == [3.0, 1.0]  # a zero Retry-After still waits a second
    ids = {call.request.headers["X-Request-ID"] for call in route.calls}
    assert len(ids) == 1


@respx.mock
def test_retry_after_budget(clock: FakeClock) -> None:
    respx.post(f"{BASE}/api/jobs").mock(
        return_value=err(429, "queue_wait_too_long", **{"Retry-After": "40"})
    )
    with pytest.raises(RateLimitError) as info:
        make(clock, max_retry_wait=100).post("api/jobs", {})
    assert clock.sleeps == [40.0, 40.0]
    assert info.value.retry_after == 40.0


@respx.mock
def test_backoff_on_server_errors(clock: FakeClock) -> None:
    route = respx.get(f"{BASE}/api/status").mock(
        side_effect=[err(500, "boom"), err(502, "bad"), httpx.Response(200, json={})]
    )
    make(clock).get("api/status")
    assert route.call_count == 3
    assert clock.sleeps == [0.75, 1.5]  # delay/2 + 0.5 * delay/2


@respx.mock
def test_busy_without_retry_after_backs_off_then_raises(clock: FakeClock) -> None:
    respx.get(f"{BASE}/api/status").mock(return_value=err(503, "release_unavailable"))
    with pytest.raises(BusyError):
        make(clock, max_attempts=3).get("api/status")
    assert len(clock.sleeps) == 2


@respx.mock
def test_backoff_is_capped(clock: FakeClock) -> None:
    respx.get(f"{BASE}/api/status").mock(return_value=err(500, "boom"))
    with pytest.raises(ServerError):
        make(clock, max_attempts=9).get("api/status")
    assert max(clock.sleeps) == pytest.approx(22.5)  # 30 * 0.75


@respx.mock
def test_transport_errors_retry_then_raise(clock: FakeClock) -> None:
    route = respx.get(f"{BASE}/api/status").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(TransportError, match="after 2 attempts"):
        make(clock, max_attempts=2).get("api/status")
    assert route.call_count == 2


@respx.mock
def test_transport_error_then_success(clock: FakeClock) -> None:
    respx.get(f"{BASE}/api/status").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json={"ok": 1})]
    )
    assert json_body(make(clock).get("api/status")) == {"ok": 1}


@respx.mock
@pytest.mark.parametrize("status", [400, 404, 409, 413, 422])
def test_request_errors_are_not_retried(clock: FakeClock, status: int) -> None:
    route = respx.post(f"{BASE}/api/x").mock(return_value=err(status, "bad"))
    with pytest.raises(RequestError):
        make(clock).post("api/x", {})
    assert route.call_count == 1


@respx.mock
def test_501_is_not_retried(clock: FakeClock) -> None:
    route = respx.get(f"{BASE}/api/variants/gene/APOE").respond(501, text="Not yet implemented")
    with pytest.raises(NotImplementedByServer):
        make(clock).get("api/variants/gene/APOE")
    assert route.call_count == 1


class Refreshing(DeveloperKey):
    def __init__(self) -> None:
        super().__init__("old")
        self.refreshes = 0

    def refresh(self) -> bool:
        self.refreshes += 1
        self._token = "new"
        return True


@respx.mock
def test_401_refreshes_once(clock: FakeClock) -> None:
    route = respx.get(f"{BASE}/api/user").mock(
        side_effect=[err(401, "unauthorized"), httpx.Response(200, json={})]
    )
    auth = Refreshing()
    transport = Transport(
        Config(base_url=BASE, auth=auth), client=httpx.Client(), sleep=clock.sleep
    )
    transport.get("api/user")
    assert auth.refreshes == 1
    assert route.calls.last.request.headers["Authorization"] == "Bearer new"


@respx.mock
def test_401_raises_after_one_refresh(clock: FakeClock) -> None:
    respx.get(f"{BASE}/api/user").mock(return_value=err(401, "unauthorized"))
    auth = Refreshing()
    transport = Transport(
        Config(base_url=BASE, auth=auth), client=httpx.Client(), sleep=clock.sleep
    )
    with pytest.raises(AuthError):
        transport.get("api/user")
    assert auth.refreshes == 1


@respx.mock
def test_401_with_fixed_token_raises(clock: FakeClock) -> None:
    route = respx.get(f"{BASE}/api/user").mock(return_value=err(401, "unauthorized"))
    with pytest.raises(AuthError):
        make(clock).get("api/user")
    assert route.call_count == 1


@respx.mock
def test_allowance_waits_until_reset(clock: FakeClock) -> None:
    reset = clock.wall + 30
    route = respx.get(f"{BASE}/api/status").mock(
        side_effect=[
            httpx.Response(
                200,
                json={},
                headers={"X-Allowance-Remaining": "0", "X-Allowance-Reset": str(reset)},
            ),
            httpx.Response(200, json={}, headers={"X-Allowance-Remaining": "9"}),
            httpx.Response(200, json={}),
        ]
    )
    transport = make(clock)
    transport.get("api/status")
    transport.get("api/status")
    assert clock.sleeps == [30.0]
    transport.get("api/status")  # reset has passed: no more waiting
    assert clock.sleeps == [30.0]
    assert route.call_count == 3


@respx.mock
def test_allowance_beyond_budget_fails_fast(clock: FakeClock) -> None:
    respx.get(f"{BASE}/api/status").mock(
        return_value=httpx.Response(
            200,
            json={},
            headers={"X-Allowance-Remaining": "0", "X-Allowance-Reset": str(clock.wall + 7200)},
        )
    )
    transport = make(clock)
    transport.get("api/status")
    with pytest.raises(RateLimitError, match="allowance is used up"):
        transport.get("api/status")
    assert clock.sleeps == []


@respx.mock
def test_allowance_without_reset_uses_retry_after(clock: FakeClock) -> None:
    respx.get(f"{BASE}/api/status").mock(
        side_effect=[
            httpx.Response(
                200, json={}, headers={"X-Allowance-Remaining": "0", "Retry-After": "12"}
            ),
            httpx.Response(200, json={}),
            httpx.Response(
                200, json={}, headers={"X-Allowance-Remaining": "0", "Retry-After": "soon"}
            ),
            httpx.Response(200, json={}),
        ]
    )
    transport = make(clock)
    transport.get("api/status")
    transport.get("api/status")
    transport.get("api/status")
    transport.get("api/status")
    assert clock.sleeps == [12.0, 60.0]


@respx.mock
def test_absolute_paths_keep_gateway_prefix(clock: FakeClock) -> None:
    route = respx.get("https://gw.test/ogdb/api/jobs/j").respond(200, json={})
    transport = Transport(
        Config(base_url="https://gw.test/ogdb"), client=httpx.Client(), sleep=clock.sleep
    )
    transport.get("/ogdb/api/jobs/j")
    assert route.called


def test_json_body_rejects_non_json() -> None:
    response = httpx.Response(200, text="<html>", request=httpx.Request("GET", "http://x/y"))
    with pytest.raises(ProtocolError, match="expected JSON"):
        json_body(response)


def test_default_config_and_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGWAS_URL", "http://env.test")
    monkeypatch.setenv("OPENGWAS_TOKEN", "secret-key")
    transport = Transport()
    assert transport.config.base_url == "http://env.test"
    assert "secret" not in repr(transport)
    transport.close()
