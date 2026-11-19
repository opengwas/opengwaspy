from typing import Any

import pytest
import respx

import opengwaspy.client as client_module
import opengwaspy.compat as compat
from opengwaspy.errors import UnsupportedOptionError
from tests.fakes import JobServer, fake_client

BASE = "http://api.test"
BATCHES = [{"store_id": "OGS-1", "release_id": "r1"}, {"store_id": "OGS-2", "release_id": "r2"}]


@pytest.fixture(autouse=True)
def default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "_default", fake_client(BASE))


def row(analysis: str, log10_p: float, **extra: Any) -> dict[str, Any]:
    return {
        "store_id": "OGS-1",
        "analysis_id": analysis,
        "z": 3.0,
        "se": 0.1,
        "log10_p": log10_p,
        **extra,
    }


def answer(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    if endpoint.endswith("chrpos"):
        position = body["positions"][0]
        if position == "1:1":
            return []
        if position == "2:2":
            return [
                {"alid": "2:2:A:G", "rsid": "rs2"},
                {"alid": "2:2:A:T", "rsid": "rs2b"},
                {"alid": "2:2:A:G", "rsid": "rs2"},
            ]
        return [{"alid": "7:5:C:T", "rsid": "rs7"}]
    if endpoint.endswith("phewas"):
        if body["variant"] == "rs0":
            return []
        return [row("A", -5.0, rsid="q"), row("B", -2.0, rsid="q")]
    return []


def truncation(limit_ok: int | None) -> Any:
    def meta(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        if not endpoint.endswith("phewas"):
            return {}
        per_store = len(body["releases"]) == 1
        truncated = limit_ok is None or body["limit"] < limit_ok or not per_store
        if limit_ok == 0:
            truncated = False
        return {"total": 20_000, "returned": body["limit"], "truncated": truncated}

    return meta


def serve(meta: Any = None) -> JobServer:
    respx.post(f"{BASE}/api/gwasinfo").respond(
        json={
            "analyses": [
                {"id": "OGS-1:A", "sample_size": 100},
                {"id": "OGS-1:B", "sample_size": 200},
            ]
        }
    )
    return JobServer(BASE, answer, batches=BATCHES, metadata=meta or truncation(0))


@respx.mock
def test_variants_chrpos_and_to_rsid() -> None:
    serve()
    assert compat.variants_chrpos("7:5") == "rs7"
    with pytest.warns(UserWarning, match="2:2 has 2 rsIDs"):
        assert compat.variants_chrpos("2:2") == "rs2"
    assert compat.variants_chrpos("1:1") is None
    original = ["rs9", "7:5", "1:1"]
    with pytest.warns(UserWarning, match="no rsID found at 1:1"):
        assert compat.variants_to_rsid(original) == ["rs9", "rs7", "1:1"]
    assert original == ["rs9", "7:5", "1:1"]


@respx.mock
def test_phewas_filters_by_pval_with_old_columns() -> None:
    server = serve()
    frame = compat.phewas(["rs1", "7:5"], pval=1e-3)
    phewas_bodies = [b for e, b in server.bodies if e.endswith("phewas")]
    assert [b["variant"] for b in phewas_bodies] == ["rs1", "7:5:C:T"]
    assert list(frame["id"]) == ["OGS-1:A", "OGS-1:A"]
    assert (frame["p"] <= 1e-3).all() and list(frame["n"]) == [100, 100]


@respx.mock
def test_phewas_reruns_with_largest_limit_when_truncated() -> None:
    server = serve(truncation(10_000))
    frame = compat.phewas("rs1", pval=0.5)
    calls = [
        (b["limit"], [r["store_id"] for r in b["releases"]])
        for e, b in server.bodies
        if e.endswith("phewas")
    ]
    assert calls == [(1000, ["OGS-1", "OGS-2"]), (10_000, ["OGS-1"]), (10_000, ["OGS-2"])]
    assert len(frame) == 4


@respx.mock
def test_phewas_refuses_when_still_truncated() -> None:
    serve(truncation(None))
    with pytest.raises(UnsupportedOptionError, match="in Store OGS-1 has 20,000 associations"):
        compat.phewas("rs1")


@respx.mock
def test_phewas_batch_and_skips() -> None:
    server = serve()
    with pytest.warns(UserWarning, match="1:1 is not a variant"):
        frame = compat.phewas(["1:1"], batch=["OGS-2"])
    assert frame.empty
    compat.phewas("rs1", batch=["OGS-2"])
    releases = [b["releases"] for e, b in server.bodies if e.endswith("phewas")]
    assert releases == [[{"store_id": "OGS-2", "release_id": "r2"}]]
    with pytest.raises(UnsupportedOptionError, match="ieu-a is not a Data API Store"):
        compat.phewas("rs1", batch=["ieu-a"])


@respx.mock
def test_phewas_ambiguous_position_and_empty_result() -> None:
    serve()
    with pytest.warns(UserWarning, match="2:2 holds 2 variants"):
        compat.phewas("2:2", pval=1e-9)


@respx.mock
def test_phewas_variant_with_no_associations() -> None:
    serve()
    assert compat.phewas("rs0").empty


@respx.mock
def test_per_store_rerun_with_no_rows() -> None:
    respx.post(f"{BASE}/api/gwasinfo").respond(json={"analyses": []})
    JobServer(
        BASE,
        lambda e, b: [],
        batches=BATCHES,
        metadata=lambda e, b: {"truncated": len(b["releases"]) > 1},
    )
    assert compat.phewas("rs1").empty
