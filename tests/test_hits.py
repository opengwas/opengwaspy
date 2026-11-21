from typing import Any

import pytest
import respx

from opengwaspy.client import Client
from opengwaspy.hits import phewas, tophits
from tests.fakes import JobServer, fake_client

BASE = "http://api.test"


@pytest.fixture
def client() -> Client:
    return fake_client(BASE)


def hits(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    if endpoint.endswith("tophits"):
        return [{"analysis_id": a, "z": 9.0, "log10_p": -19.0} for a in body["analyses"]]
    return [{"analysis_id": f"{r['store_id']}-x", "log10_p": -3.0} for r in body["releases"]]


def truncated_meta(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    return {"total": 5, "returned": 1, "truncated": True}


@respx.mock
def test_tophits_groups_by_result_rows(client: Client) -> None:
    server = JobServer(BASE, hits, limits={"result_rows": 2000, "lookup_analyses": 100})
    frame = tophits(["a", "b", "c"], threshold=5e-6, limit=1000, client=client)
    assert [b["analyses"] for _, b in server.bodies] == [["a", "b"], ["c"]]
    assert server.bodies[0][1] == {
        "analyses": ["a", "b"],
        "threshold": 5e-6,
        "limit": 1000,
        "observed_only": False,
    }
    assert list(frame["analysis_id"]) == ["a", "b", "c"]
    assert frame["p"].iloc[0] == pytest.approx(1e-19)
    assert frame.attrs["truncated"] is False


@respx.mock
def test_tophits_truncation_warns(client: Client) -> None:
    JobServer(BASE, hits, metadata=truncated_meta)
    with pytest.warns(UserWarning, match="more than 10 hits"):
        frame = tophits("a", limit=10, client=client)
    assert frame.attrs["truncated"] is True and frame.attrs["total"] == 5


@pytest.mark.parametrize(
    ("kw", "msg"),
    [({"threshold": 0}, "between"), ({"threshold": 1}, "between"), ({"limit": 0}, "at least")],
)
def test_tophits_validation(client: Client, kw: dict[str, Any], msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        tophits("a", client=client, **kw)


BATCHES = [
    {"store_id": f"OGS-{i}", "release_id": f"r{i}", "capabilities": {"phewas": i != 3}}
    for i in range(12)
]


@respx.mock
def test_phewas_defaults_to_capable_releases_in_groups_of_ten(client: Client) -> None:
    server = JobServer(BASE, hits, batches=BATCHES)
    frame = phewas(" rs1 ", analyses="a", client=client)
    groups = [[r["store_id"] for r in b["releases"]] for _, b in server.bodies]
    assert [len(g) for g in groups] == [10, 1]
    assert all("OGS-3" not in g for g in groups)
    body = server.bodies[0][1]
    assert body["variant"] == "rs1" and body["analyses"] == ["a"] and body["limit"] == 1000
    assert body["threshold"] == 1e-8  # the Data API's default, sent explicitly
    assert len(frame) == 11 and "p" in frame.columns
    assert frame.attrs["threshold"] == 1e-8


@respx.mock
def test_phewas_named_releases_and_truncation(client: Client) -> None:
    server = JobServer(BASE, hits, batches=BATCHES, metadata=truncated_meta)
    with pytest.warns(UserWarning, match=r"has 5 associations at p <= 1e-05; only 1 were returned"):
        frame = phewas("rs1", threshold=1e-5, releases=["OGS-1"], client=client)
    assert server.bodies[0][1]["threshold"] == 1e-5
    assert server.bodies[0][1]["releases"] == [{"store_id": "OGS-1", "release_id": "r1"}]
    assert frame.attrs["returned"] == 1


@respx.mock
def test_phewas_without_capable_release(client: Client) -> None:
    JobServer(
        BASE,
        hits,
        batches=[{"store_id": "x", "release_id": "y", "capabilities": {"phewas": False}}],
    )
    with pytest.raises(ValueError, match="no served release"):
        phewas("rs1", client=client)


@pytest.mark.parametrize(
    ("variant", "kw"),
    [("", {}), ("rs1", {"limit": 0}), ("rs1", {"threshold": 0}), ("rs1", {"threshold": 1.5})],
)
def test_phewas_validation(client: Client, variant: str, kw: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        phewas(variant, client=client, **kw)


@respx.mock
def test_phewas_threshold_from_result_metadata(client: Client) -> None:
    JobServer(BASE, hits, batches=BATCHES, metadata=lambda e, b: {"threshold": 1.0, "total": 1})
    frame = phewas("rs1", threshold=1, releases=["OGS-1"], client=client)
    assert frame.attrs["threshold"] == 1.0
