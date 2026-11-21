from pathlib import Path
from typing import Any

import pytest
import respx

import opengwaspy.client as client_module
import opengwaspy.compat as compat
from opengwaspy.compat.hits import clump_settings_answerable
from opengwaspy.errors import UnsupportedOptionError
from tests.fakes import JobServer, fake_client

BASE = "http://api.test"
EUR = {
    "store": "eur-k10",
    "ancestry": "EUR",
    "t_far": 0.0319,
    "near_bp": 3_000_000,
    "far_bp": 10_000_000,
}
AMR = {
    "store": "amr-k10",
    "ancestry": "AMR",
    "t_far": 0.0632,
    "near_bp": 3_000_000,
    "far_bp": 10_000_000,
}
HITS = [
    {
        "store_id": "OGS-1",
        "analysis_id": "A",
        "alid": "1:100:A:G",
        "z": 9.0,
        "se": 0.1,
        "log10_p": -19.0,
        "rsid": "rs1",
    },
    {
        "store_id": "OGS-1",
        "analysis_id": "A",
        "alid": "1:200:C:T",
        "z": -8.0,
        "se": 0.1,
        "log10_p": -15.0,
        "rsid": "rs2",
    },
    {
        "store_id": "OGS-1",
        "analysis_id": "A",
        "alid": "1:900:G:T",
        "z": 6.0,
        "se": 0.1,
        "log10_p": -9.0,
        "rsid": "rs3",
    },
    {
        "store_id": "OGS-1",
        "analysis_id": "A",
        "alid": "9:9:A:C",
        "z": 7.0,
        "se": 0.1,
        "log10_p": -12.0,
        "rsid": "rs4",
    },
]


@pytest.fixture(autouse=True)
def default_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(client_module, "_default", fake_client(BASE))


LEADS = {"rs1": 2, "rs3": 1}  # the server's clumping: rs2 joins rs1; rs4 is not in the LD store


def answer(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    if not endpoint.endswith("tophits"):
        return []
    if body.get("clump") is None:
        return HITS
    return [{**h, "clump_size": LEADS[h["rsid"]]} for h in HITS if h["rsid"] in LEADS]


def meta(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"total": 4, "truncated": False}
    if body.get("clump") is not None:
        out["clump"] = {
            **body["clump"],
            "hits": 4,
            "leads": 2,
            "absent": 1,
            "ld_stores": {"EUR": "eur-k10"},
        }
    return out


def serve(truncated: bool = False) -> JobServer:
    respx.get(f"{BASE}/api/ld/stores").respond(json={"stores": [EUR, AMR]})
    respx.post(f"{BASE}/api/gwasinfo").respond(
        json={"analyses": [{"id": "OGS-1:A", "sample_size": 5000}]}
    )
    return JobServer(
        BASE, answer, metadata=(lambda e, b: {"truncated": True, "total": 4}) if truncated else meta
    )


@pytest.mark.parametrize(
    ("r2", "kb", "store", "ok"),
    [
        (0.001, 10000, EUR, False),
        (0.001, 3000, EUR, True),
        (0.05, 10000, EUR, True),
        (0.05, 10000, AMR, False),
        (0.5, 20000, EUR, False),
    ],
)
def test_answerable(r2: float, kb: float, store: dict[str, Any], ok: bool) -> None:
    assert clump_settings_answerable(r2, kb, store) is ok


@respx.mock
def test_default_clumping_is_refused_before_any_job() -> None:
    server = serve()
    with pytest.raises(UnsupportedOptionError) as info:
        compat.tophits("OGS-1:A")
    message = str(info.value)
    assert "r2=0.001 within kb=10000 cannot be done exactly" in message
    assert "tophits(..., r2=0.001, kb=3000)" in message
    assert "tophits(..., r2=0.04, kb=10000)" in message
    assert server.bodies == []


@respx.mock
def test_amr_suggests_its_own_t_far() -> None:
    serve()
    with pytest.raises(UnsupportedOptionError, match=r"r2=0.07, kb=10000"):
        compat.tophits("OGS-1:A", r2=0.05, pop="amr")


@respx.mock
def test_clumped_on_the_server_with_old_columns() -> None:
    server = serve()
    with pytest.warns(UserWarning, match="1 hits are not in the EUR LD store, so were not clumped"):
        frame = compat.tophits("OGS-1:A", r2=0.001, kb=3000)
    assert [e for e, _ in server.bodies] == ["/api/tophits"]  # one job, clumped on the server
    body = server.bodies[0][1]
    assert body["limit"] == 10_000 and body["threshold"] == 5e-8
    assert body["clump"] == {"r2": 0.001, "kb": 3000, "store": "eur-k10"}
    assert list(frame["rsid"]) == ["rs1", "rs3"] and list(frame["clump_size"]) == [2, 1]
    assert list(frame.columns[:3]) == ["id", "trait", "rsid"] or list(frame.columns[:2]) == [
        "id",
        "rsid",
    ]
    assert frame.iloc[0]["n"] == 5000 and frame.iloc[0]["beta"] == pytest.approx(0.9)
    assert frame.attrs["clump"]["leads"] == 2 and frame.attrs["clump"]["store"] == "eur-k10"


@respx.mock
def test_unclumped_and_ignored_options() -> None:
    server = serve()
    frame = compat.tophits(
        ["OGS-1:A"], clump=0, preclumped=0, bychr=1, force_server=True, pop="nowhere"
    )
    assert [e for e, _ in server.bodies] == ["/api/tophits"]
    assert server.bodies[0][1]["limit"] == 1000
    assert len(frame) == 4


@respx.mock
def test_truncation_warnings() -> None:
    serve(truncated=True)
    with pytest.warns(UserWarning, match="more than 10,000 clumped leads"):
        compat.tophits("OGS-1:A", r2=0.1, kb=1000)
    with pytest.warns(UserWarning, match="only the strongest were returned"):
        compat.tophits("OGS-1:A", clump=0)


@respx.mock
def test_unknown_pop() -> None:
    serve()
    with pytest.raises(
        UnsupportedOptionError, match="pop='legacy' has no LD store; choose one of AMR, EUR"
    ):
        compat.tophits("OGS-1:A", pop="legacy")


@respx.mock
def test_no_hits() -> None:
    respx.get(f"{BASE}/api/ld/stores").respond(json={"stores": [EUR]})
    JobServer(BASE, lambda e, b: [])
    assert compat.tophits("OGS-1:A", r2=0.1, kb=1000).empty
