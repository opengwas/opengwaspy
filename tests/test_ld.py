import math
from typing import Any

import httpx
import pytest
import respx

from opengwaspy.client import Client
from opengwaspy.errors import LDRefusal, ProtocolError, error_from_response
from opengwaspy.ld import ld_clump, ld_matrix, ld_proxies, ld_reflookup, ld_region, ld_stores
from tests.fakes import JobServer, fake_client

BASE = "http://api.test"
STORE_META = {
    "store": "eur",
    "ancestry": "EUR",
    "t_far": 0.03,
    "near_bp": 3_000_000,
    "far_bp": 10_000_000,
}


@pytest.fixture
def client() -> Client:
    return fake_client(BASE)


def answer(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    if endpoint.endswith(("matrix", "region")):
        alids = body.get("alids", ["1:1:A:G", "1:2:C:T"])
        held = [a for a in alids if not a.startswith("9:")]
        n = len(held)
        return [
            {
                "alid": a,
                "a1": "A",
                "a2": "G",
                "r": [1.0 if i == j else (None if i + j == 1 else 0.5) for j in range(n)],
            }
            for i, a in enumerate(held)
        ]
    if endpoint.endswith("proxies"):
        return [
            {"query": a, "proxy": "p", "r": 0.9, "r2": 0.81, "distance": 5} for a in body["alids"]
        ]
    if endpoint.endswith("reflookup"):
        return [{"alid": a, "present": not a.startswith("9:")} for a in body["alids"]]
    return [
        {"alid": a, "lead": body["alids"][0], "r": 1.0, "score": s}
        for a, s in zip(body["alids"], body["scores"], strict=True)
    ]


def meta(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    return {**STORE_META, "absent": [a for a in body.get("alids", []) if a.startswith("9:")]}


@respx.mock
def test_matrix_is_square_with_nan_for_unheld_pairs(client: Client) -> None:
    server = JobServer(BASE, answer, metadata=meta)
    m = ld_matrix(["1:1:A:G", "1:2:C:T", "9:9:A:C"], ancestry="eur", client=client)
    assert server.bodies[0][1] == {"ancestry": "EUR", "alids": ["1:1:A:G", "1:2:C:T", "9:9:A:C"]}
    assert list(m.index) == ["1:1:A:G", "1:2:C:T"] and list(m.columns) == ["1:1:A:G", "1:2:C:T"]
    assert m.loc["1:1:A:G", "1:1:A:G"] == 1.0 and math.isnan(m.to_numpy()[0, 1])
    assert m.attrs["absent"] == ["9:9:A:C"]
    assert m.attrs["t_far"] == 0.03 and m.attrs["store"] == "eur"
    assert m.attrs["variants"][0] == {"alid": "1:1:A:G", "a1": "A", "a2": "G"}


@respx.mock
def test_matrix_fill_store_and_limits(client: Client) -> None:
    server = JobServer(BASE, answer, metadata=meta, limits={"ld_matrix_alids": 2})
    ld_matrix(["1:1:A:G", "1:2:C:T"], store="s1", fill=0.0, client=client)
    assert server.bodies[0][1] == {"store": "s1", "alids": ["1:1:A:G", "1:2:C:T"], "fill": 0.0}
    with pytest.raises(ValueError, match="at most 2 ALIDs"):
        ld_matrix(["1:1:A:G", "1:2:C:T", "1:3:A:T"], ancestry="EUR", client=client)
    with pytest.raises(ValueError, match="distinct; repeated: 1:1:A:G"):
        ld_matrix(["1:1:A:G", "1:1:A:G"], ancestry="EUR", client=client)


@pytest.mark.parametrize("kw", [{}, {"ancestry": "EUR", "store": "s"}])
def test_exactly_one_store(client: Client, kw: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="exactly one LD store"):
        ld_reflookup("1:1:A:G", client=client, **kw)


@respx.mock
def test_empty_matrix_and_malformed_rows(client: Client) -> None:
    JobServer(
        BASE,
        lambda e, b: [] if b["alids"] == ["9:9:A:C"] else [{"alid": "1:1:A:G", "r": [1.0, 0.2]}],
        metadata=meta,
    )
    empty = ld_matrix(["9:9:A:C"], ancestry="EUR", client=client)
    assert empty.empty and empty.attrs["absent"] == ["9:9:A:C"]
    with pytest.raises(ProtocolError, match="not square"):
        ld_matrix(["1:1:A:G"], ancestry="EUR", client=client)


@respx.mock
def test_region(client: Client) -> None:
    server = JobServer(BASE, answer, metadata=meta)
    m = ld_region("chr10", 100, 50, ancestry="EUR", client=client)
    assert server.bodies[0][1] == {
        "ancestry": "EUR",
        "chromosome": "10",
        "centre": 100,
        "radius": 50,
    }
    assert m.shape == (2, 2)
    with pytest.raises(ValueError):
        ld_region(10, 0, 5, ancestry="EUR", client=client)


@respx.mock
def test_clump(client: Client) -> None:
    server = JobServer(BASE, answer, metadata=meta)
    frame = ld_clump(
        ["1:1:A:G", "1:2:C:T"], [5.0, 3.0], r2=0.1, kb=1000, ancestry="EUR", client=client
    )
    assert server.bodies[0][1] == {
        "ancestry": "EUR",
        "alids": ["1:1:A:G", "1:2:C:T"],
        "scores": [5.0, 3.0],
        "r2": 0.1,
        "kb": 1000,
    }
    assert list(frame["lead"]) == ["1:1:A:G", "1:1:A:G"]


@pytest.mark.parametrize(
    ("scores", "msg"),
    [([1.0], "one score per ALID"), ([1.0, -1.0], "not negative"), ([1.0, float("nan")], "finite")],
)
def test_clump_validation(client: Client, scores: list[float], msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        ld_clump(["1:1:A:G", "1:2:C:T"], scores, r2=0.1, kb=10, ancestry="EUR", client=client)


@respx.mock
def test_clump_cap(client: Client) -> None:
    JobServer(BASE, answer, limits={"ld_clump_alids": 1})
    with pytest.raises(ValueError, match="at most 1 ALIDs"):
        ld_clump(["1:1:A:G", "1:2:C:T"], [1, 2], r2=0.1, kb=10, ancestry="EUR", client=client)


@respx.mock
def test_proxies_and_reflookup_chunk_and_merge_absent(client: Client) -> None:
    server = JobServer(
        BASE, answer, metadata=meta, limits={"ld_proxies_alids": 2, "ld_reflookup_alids": 2}
    )
    alids = ["1:1:A:G", "9:9:A:C", "1:3:A:T", "9:8:A:C"]
    proxies = ld_proxies(alids, ancestry="EUR", client=client)
    assert [b["alids"] for _, b in server.bodies] == [alids[:2], alids[2:]]
    assert server.bodies[0][1]["r2"] == 0.8 and server.bodies[0][1]["kb"] == 10_000
    assert proxies.attrs["absent"] == ["9:9:A:C", "9:8:A:C"]
    ref = ld_reflookup(alids, ancestry="EUR", client=client)
    assert list(ref["present"]) == [True, False, True, False]


@respx.mock
def test_stores(client: Client) -> None:
    respx.get(f"{BASE}/api/ld/stores").mock(
        side_effect=[
            httpx.Response(200, json={"stores": [STORE_META]}),
            httpx.Response(200, json={"x": 1}),
        ]
    )
    assert list(ld_stores(client=client)["ancestry"]) == ["EUR"]
    with pytest.raises(ProtocolError):
        ld_stores(client=client)


def test_refusal_says_what_is_answerable() -> None:
    body = {
        "error": "ld_refusal",
        "message": "r2=0.001 is below t_far",
        "reason": "threshold_below_t_far",
        **STORE_META,
    }
    error = error_from_response(
        httpx.Response(422, json=body, request=httpx.Request("POST", "http://x/"))
    )
    assert isinstance(error, LDRefusal)
    assert "answers r2 >= 0.03 with kb up to 10,000, or any r2 with kb up to 3,000" in str(error)
    bare = error_from_response(
        httpx.Response(
            422,
            json={"error": "ld_refusal", "message": "m"},
            request=httpx.Request("POST", "http://x/"),
        )
    )
    assert isinstance(bare, LDRefusal) and bare.answerable is None
