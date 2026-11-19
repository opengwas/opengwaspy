import httpx
import pytest
import respx

import opengwaspy.client as client_module
from opengwaspy.auth import DeveloperKey
from opengwaspy.batch import BatchError
from opengwaspy.client import Client, Limits, configure, get_client
from opengwaspy.config import Config
from opengwaspy.errors import ProtocolError
from opengwaspy.transport import Transport
from tests.fakes import FakeClock, accepted, page, status

BASE = "http://api.test"
STATUS = {
    "status": "ok",
    "ready": True,
    "execution": {
        "image_digest": "sha256:abc",
        "limits": {
            "lookup_variants": 500,
            "range_span": 5_000_000,
            "result_rows": "x",
            "range_analyses": 0,
        },
    },
}


@pytest.fixture
def client() -> Client:
    clock = FakeClock()
    transport = Transport(
        Config(base_url=BASE, auth=DeveloperKey("k")),
        client=httpx.Client(),
        sleep=clock.sleep,
        clock=clock.monotonic,
        wall_clock=clock.time,
    )
    return Client(transport=transport)


def test_limits_from_status() -> None:
    limits = Limits.from_status(STATUS)
    assert limits.lookup_variants == 500
    assert limits.range_span == 5_000_000
    assert limits.result_rows == 100_000  # not a number: default kept
    assert limits.range_analyses == 10  # not positive: default kept
    assert Limits.from_status({}) == Limits()


@respx.mock
def test_status_is_cached_for_limits_and_digest(client: Client) -> None:
    route = respx.get(f"{BASE}/api/status").respond(json=STATUS)
    assert client.limits.lookup_variants == 500
    assert client.image_digest == "sha256:abc"
    assert route.call_count == 1
    client.status()
    assert route.call_count == 2


@respx.mock
def test_status_without_digest(client: Client) -> None:
    respx.get(f"{BASE}/api/status").respond(json={"ready": True})
    assert client.image_digest is None


@respx.mock
def test_user_and_batches(client: Client) -> None:
    respx.get(f"{BASE}/api/user").respond(json={"user": "developer:x", "role": "developer"})
    respx.get(f"{BASE}/api/batches").respond(
        json={"batches": [{"store_id": "OGS-1"}, {"store_id": "OGS-2"}]}
    )
    assert client.user()["role"] == "developer"
    assert list(client.batches()["store_id"]) == ["OGS-1", "OGS-2"]


@respx.mock
@pytest.mark.parametrize(
    ("path", "body"), [("status", []), ("user", "x"), ("batches", {"batches": 3})]
)
def test_malformed_service_answers(client: Client, path: str, body: object) -> None:
    respx.get(f"{BASE}/api/{path}").respond(json=body)
    with pytest.raises(ProtocolError):
        getattr(client, path)()


@respx.mock
def test_query_adds_image_digest(client: Client) -> None:
    respx.get(f"{BASE}/api/status").respond(json=STATUS)
    respx.post(f"{BASE}/api/tophits").respond(202, json=accepted("j1", poll_after=0))
    respx.get(f"{BASE}/api/jobs/j1").respond(json=status("j1", "succeeded"))
    respx.get(f"{BASE}/api/jobs/j1/result").respond(json=page([{"z": 1.0}]))
    frame = client.query("api/tophits", {"analyses": ["a"]})
    assert frame.attrs["image_digest"] == "sha256:abc"
    assert frame.attrs["job_id"] == "j1"
    assert client.job("j1").job_id == "j1"


@respx.mock
def test_query_many(client: Client) -> None:
    respx.get(f"{BASE}/api/status").respond(json=STATUS)
    respx.post(f"{BASE}/api/tophits").mock(
        side_effect=[
            httpx.Response(202, json=accepted("j1", poll_after=0)),
            httpx.Response(202, json=accepted("j2", poll_after=0)),
        ]
    )
    for j in ("j1", "j2"):
        respx.get(f"{BASE}/api/jobs/{j}").respond(json=status(j, "succeeded"))
        respx.get(f"{BASE}/api/jobs/{j}/result").respond(json=page([{"job": j}]))
    frames = client.query_many([("api/tophits", {"a": 1}), ("api/tophits", {"a": 2})])
    assert [f.iloc[0]["job"] for f in frames] == ["j1", "j2"]
    assert all(f.attrs["image_digest"] == "sha256:abc" for f in frames)


@respx.mock
def test_query_many_raises_batch_error(client: Client) -> None:
    respx.post(f"{BASE}/api/tophits").respond(
        404, json={"error": "analysis_not_found", "message": "x"}
    )
    with pytest.raises(BatchError):
        client.query_many([("api/tophits", {})])


def test_construction_and_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGWAS_CONFIG", "/nonexistent/config.toml")
    for key in ("OPENGWAS_URL", "OPENGWAS_PROFILE", "OPENGWAS_TOKEN", "OPENGWAS_JWT"):
        monkeypatch.delenv(key, raising=False)
    with Client("http://x.test", token="secret", timeout=5) as c:
        assert c.config.base_url == "http://x.test"
        assert c.config.timeout == 5
        assert "secret" not in repr(c)
    with Client(config=Config(base_url="http://y.test")) as c:
        assert c.config.base_url == "http://y.test"


def test_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "_default", None)
    monkeypatch.setenv("OPENGWAS_CONFIG", "/nonexistent/config.toml")
    monkeypatch.setenv("OPENGWAS_URL", "http://env.test")
    monkeypatch.delenv("OPENGWAS_PROFILE", raising=False)
    first = get_client()
    assert first is get_client()
    assert first.config.base_url == "http://env.test"
    second = configure("http://other.test")
    assert get_client() is second
    third = configure()
    assert third.config.base_url == "http://env.test"


@respx.mock
def test_module_level_service_calls(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    import opengwaspy as og

    monkeypatch.setattr(client_module, "_default", client)
    respx.get(f"{BASE}/api/status").respond(json=STATUS)
    respx.get(f"{BASE}/api/user").respond(json={"role": "developer"})
    respx.get(f"{BASE}/api/batches").respond(json={"batches": [{"store_id": "OGS-1"}]})
    assert og.status()["ready"] is True
    assert og.user()["role"] == "developer"
    assert len(og.batches()) == 1
    assert og.status(client=client)["ready"] is True
