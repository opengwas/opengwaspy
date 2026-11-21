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
        # The server applies the threshold.
        rows = [row("A", -5.0, rsid="q"), row("B", -2.0, rsid="q")]
        return [r for r in rows if 10 ** r["log10_p"] <= body["threshold"]]
    return []


def truncation(truncated: bool) -> Any:
    def meta(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        if not endpoint.endswith("phewas"):
            return {}
        return {
            "threshold": body["threshold"],
            "total": 20_000,
            "returned": body["limit"],
            "truncated": truncated,
        }

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
    return JobServer(BASE, answer, batches=BATCHES, metadata=meta or truncation(False))


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
def test_phewas_sends_pval_as_threshold_with_old_columns() -> None:
    server = serve()
    frame = compat.phewas(["rs1", "7:5"], pval=1e-3)
    phewas_bodies = [b for e, b in server.bodies if e.endswith("phewas")]
    assert [b["variant"] for b in phewas_bodies] == ["rs1", "7:5:C:T"]
    assert {(b["threshold"], b["limit"]) for b in phewas_bodies} == {(1e-3, 10_000)}
    assert list(frame["id"]) == ["OGS-1:A", "OGS-1:A"]
    assert (frame["p"] <= 1e-3).all() and list(frame["n"]) == [100, 100]
    assert frame.attrs["threshold"] == 1e-3


@respx.mock
def test_phewas_sends_ieugwaspy_default_explicitly() -> None:
    server = serve()
    compat.phewas("rs1")
    assert [b["threshold"] for e, b in server.bodies if e.endswith("phewas")] == [1e-3]


@respx.mock
def test_phewas_refuses_when_truncated() -> None:
    serve(truncation(True))
    with pytest.raises(UnsupportedOptionError, match=r"rs1 has 20,000 associations at p <= 0\.001"):
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
    with pytest.raises(
        UnsupportedOptionError,
        match="batch ieu-a is neither a Data API Store nor an OpenGWAS batch",
    ):
        compat.phewas("rs1", batch=["ieu-a"])


@respx.mock
def test_phewas_ambiguous_position_and_empty_result() -> None:
    serve()
    with pytest.warns(UserWarning, match="2:2 holds 2 variants"):
        compat.phewas("2:2", pval=1e-9)


@respx.mock
def test_phewas_variant_with_no_associations() -> None:
    serve()
    frame = compat.phewas("rs0")
    assert frame.empty and frame.attrs["threshold"] == 1e-3
