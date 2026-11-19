import json

import httpx
import pytest
import respx

from opengwaspy.auth import DeveloperKey
from opengwaspy.client import Client
from opengwaspy.config import Config
from opengwaspy.errors import NotImplementedByServer, ProtocolError, RequestError
from opengwaspy.metadata import gwasinfo, gwasinfo_files
from opengwaspy.transport import Transport

BASE = "http://api.test"


@pytest.fixture
def client() -> Client:
    return Client(
        transport=Transport(Config(base_url=BASE, auth=DeveloperKey("k")), client=httpx.Client())
    )


def listing(ids: list[str], next_after: str | None, total: int = 3) -> dict[str, object]:
    return {
        "release_id": "r",
        "catalog_version": "cv1",
        "total": total,
        "next_after": next_after,
        "analyses": [{"id": i, "trait": f"t{i}"} for i in ids],
    }


@respx.mock
def test_list_pages_with_after(client: Client) -> None:
    route = respx.get(f"{BASE}/api/gwasinfo").mock(
        side_effect=[
            httpx.Response(200, json=listing(["a", "b"], "b")),
            httpx.Response(200, json=listing(["c"], None)),
        ]
    )
    frame = gwasinfo(client=client, release_set="all_configured_releases")
    assert list(frame["id"]) == ["a", "b", "c"]
    assert frame.attrs == {"release_id": "r", "catalog_version": "cv1", "total": 3}
    first, second = (c.request.url.params for c in route.calls)
    assert first["limit"] == "1000" and "after" not in first
    assert first["release_set"] == "all_configured_releases"
    assert second["after"] == "b"


@respx.mock
def test_list_with_limit(client: Client) -> None:
    route = respx.get(f"{BASE}/api/gwasinfo").mock(
        side_effect=[
            httpx.Response(200, json=listing(["a", "b"], "b")),
            httpx.Response(200, json=listing(["c"], "c")),
        ]
    )
    frame = gwasinfo(limit=3, client=client)
    assert len(frame) == 3
    assert [c.request.url.params["limit"] for c in route.calls] == ["3", "1"]


@respx.mock
def test_list_stops_on_empty_page_and_warns_when_large(client: Client) -> None:
    respx.get(f"{BASE}/api/gwasinfo").mock(
        side_effect=[
            httpx.Response(200, json=listing(["a"], "a", total=50_000)),
            httpx.Response(200, json=listing([], "z", total=50_000)),
        ]
    )
    with pytest.warns(UserWarning, match="listing all 50,000"):
        frame = gwasinfo(client=client)
    assert len(frame) == 1


@respx.mock
def test_lookup_in_order_with_not_found(client: Client) -> None:
    route = respx.post(f"{BASE}/api/gwasinfo").respond(
        json={
            "release_id": "r",
            "catalog_version": "cv",
            "analyses": [{"id": "x"}],
            "not_found": ["nope"],
            "retired": [],
        }
    )
    frame = gwasinfo(["x", "nope"], releases=["OGS-1/r1"], client=client)
    assert json.loads(route.calls.last.request.content) == {
        "id": ["x", "nope"],
        "releases": [{"store_id": "OGS-1", "release_id": "r1"}],
    }
    assert list(frame["id"]) == ["x"]
    assert frame.attrs["not_found"] == ["nope"]
    with pytest.raises(RequestError, match="1 analyses not found and 0 retired: nope") as info:
        gwasinfo("x", strict=True, client=client)
    assert info.value.extra["not_found"] == ["nope"]


@respx.mock
def test_lookup_chunks_at_1000(client: Client) -> None:
    route = respx.post(f"{BASE}/api/gwasinfo").mock(
        side_effect=lambda request: httpx.Response(
            200, json={"analyses": [{"id": i} for i in json.loads(request.content)["id"]]}
        )
    )
    ids = [f"a{i}" for i in range(2500)]
    frame = gwasinfo(ids, client=client)
    assert list(frame["id"]) == ids
    assert [len(json.loads(c.request.content)["id"]) for c in route.calls] == [1000, 1000, 500]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"ids": []}, "empty"),
        ({"ids": ["ok", ""]}, "non-empty"),
        ({"ids": "x", "releases": ["r"], "release_set": "s"}, "not both"),
        ({"limit": 0}, "at least 1"),
        ({"releases": ["r"]}, "release_set, not releases"),
    ],
)
def test_bad_arguments(client: Client, args: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        gwasinfo(client=client, **args)  # type: ignore[arg-type]


@respx.mock
def test_malformed_answer(client: Client) -> None:
    respx.get(f"{BASE}/api/gwasinfo").respond(json={"analyses": "nope"})
    with pytest.raises(ProtocolError):
        gwasinfo(client=client)


@respx.mock
def test_files(client: Client) -> None:
    route = respx.post(f"{BASE}/api/gwasinfo/files").mock(
        side_effect=[
            httpx.Response(200, json={"files": [{"source_file": "f.tsv.gz"}], "next_after": "a"}),
            httpx.Response(200, json=[{"source_file": "g"}]),
            httpx.Response(200, json={"oops": 1}),
            httpx.Response(501, text="Not yet implemented"),
        ]
    )
    frame = gwasinfo_files(release_set="s", after="z", client=client)
    assert json.loads(route.calls.last.request.content) == {
        "limit": 100,
        "release_set": "s",
        "after": "z",
    }
    assert frame.attrs == {"next_after": "a"} and len(frame) == 1
    assert len(gwasinfo_files(client=client)) == 1
    with pytest.raises(ProtocolError):
        gwasinfo_files(client=client)
    with pytest.raises(NotImplementedByServer):
        gwasinfo_files(client=client)
