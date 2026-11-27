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


def clump_meta(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    n = len(body["analyses"])
    return {
        "total": n,
        "truncated": False,
        "clump": {
            "r2": body["clump"].get("r2", 0.001),
            "kb": body["clump"].get("kb", 3000.0),
            "hits": 100 * n,
            "leads": n,
            "absent": 7,
            "ld_stores": {"EUR": "eur-k10"} if body["analyses"][0] == "a" else {"AFR": "afr-k10"},
        },
    }


@respx.mock
def test_tophits_clump_defaults_sent_and_metadata_combined(client: Client) -> None:
    server = JobServer(
        BASE, hits, metadata=clump_meta, limits={"result_rows": 2000, "lookup_analyses": 100}
    )
    frame = tophits(["a", "b", "c"], clump=True, client=client)
    assert [b["clump"] for _, b in server.bodies] == [{}, {}]  # the server's defaults
    assert frame.attrs["clump"] == {
        "r2": 0.001,
        "kb": 3000.0,
        "hits": 300,
        "leads": 3,
        "absent": 14,
        "ld_stores": {"EUR": "eur-k10", "AFR": "afr-k10"},
        "source": "computed",
    }


STORED_CONFIGURATION = {"configuration": "k10", "threshold": 5e-8, "kb": 10000}


def stored_part(release: str, hits: int) -> dict[str, Any]:
    return {
        release: {
            "configuration": STORED_CONFIGURATION,
            "hits": hits,
            "leads": 2,
            "absent": 1,
            "imputed": 3,
            "ambiguous": 0,
            "not_clumped": 0,
        }
    }


def mixed_meta(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    """Job 1 (a, b): every release stored. Job 2 (c): one stored, one computed."""
    if body["analyses"] == ["a", "b"]:
        clump: dict[str, Any] = {
            "source": "stored",
            "r2": None,
            "kb": None,
            "hits": 0,
            "leads": 0,
            "absent": 0,
            "ld_stores": {},
            "stored": stored_part("OGS-1/r1", 50),
        }
    else:
        clump = {
            "source": "mixed",
            "r2": 0.001,
            "kb": 3000,
            "hits": 20,
            "leads": 4,
            "absent": 2,
            "ld_stores": {"EUR": "eur-k10"},
            "stored": stored_part("OGS-2/r1", 30),
        }
    return {"total": 2, "truncated": False, "clump": clump}


@respx.mock
def test_tophits_clump_merges_stored_and_computed_jobs(client: Client) -> None:
    JobServer(BASE, hits, metadata=mixed_meta, limits={"result_rows": 2000, "lookup_analyses": 100})
    frame = tophits(["a", "b", "c"], clump=True, client=client)
    summary = frame.attrs["clump"]
    assert summary["source"] == "mixed"
    assert (summary["r2"], summary["kb"]) == (0.001, 3000)  # not the stored job's None
    assert (summary["hits"], summary["leads"], summary["absent"]) == (100, 8, 4)
    assert (summary["imputed"], summary["ambiguous"], summary["not_clumped"]) == (6, 0, 0)
    assert set(summary["stored"]) == {"OGS-1/r1", "OGS-2/r1"}
    assert summary["stored"]["OGS-1/r1"]["configuration"] == STORED_CONFIGURATION
    assert summary["ld_stores"] == {"EUR": "eur-k10"}


@respx.mock
def test_tophits_clump_all_stored(client: Client) -> None:
    JobServer(BASE, hits, metadata=mixed_meta)
    frame = tophits(["a", "b"], clump=True, client=client)
    summary = frame.attrs["clump"]
    assert summary["source"] == "stored"
    assert summary["r2"] is None and summary["kb"] is None
    assert (summary["hits"], summary["leads"], summary["imputed"]) == (50, 2, 3)


@respx.mock
def test_tophits_clump_settings(client: Client) -> None:
    server = JobServer(BASE, hits, metadata=clump_meta)
    frame = tophits(
        "a", clump={"r2": 0.01, "kb": 1000, "ancestry": "EUR", "store": None}, client=client
    )
    assert server.bodies[0][1]["clump"] == {"r2": 0.01, "kb": 1000, "ancestry": "EUR"}
    assert frame.attrs["clump"]["r2"] == 0.01


@respx.mock
def test_tophits_without_clump_sends_none(client: Client) -> None:
    server = JobServer(BASE, hits)
    frame = tophits("a", client=client)
    assert "clump" not in server.bodies[0][1] and "clump" not in frame.attrs


@respx.mock
def test_tophits_clumped_truncation_says_leads(client: Client) -> None:
    JobServer(BASE, hits, metadata=truncated_meta)
    with pytest.warns(UserWarning, match="more than 10 clumped leads"):
        tophits("a", limit=10, clump=True, client=client)


@pytest.mark.parametrize(
    ("clump", "msg"),
    [
        ({"r2": 0.1, "window": 5}, "unknown clump settings window"),
        ({"ancestry": "EUR", "store": "x"}, "not both"),
        ("yes", "clump must be"),
    ],
)
def test_tophits_clump_validation(client: Client, clump: Any, msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        tophits("a", clump=clump, client=client)


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
