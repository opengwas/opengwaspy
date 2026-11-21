import json
from typing import Any

import httpx
import pytest
import respx

import opengwaspy.client as client_module
import opengwaspy.compat as compat
from opengwaspy.compat._ids import resolve, resolve_batches
from opengwaspy.errors import UnsupportedOptionError
from tests.fakes import JobServer, fake_client

BASE = "http://api.test"

ANALYSES = {
    "OGS-9:ukb-b-1": {"id": "OGS-9:ukb-b-1", "store_id": "OGS-9", "analysis_id": "ukb-b-1"},
    "OGS-11:GCST1": {"id": "OGS-11:GCST1", "store_id": "OGS-11", "analysis_id": "GCST1"},
    "OGS-12:GCST1": {"id": "OGS-12:GCST1", "store_id": "OGS-12", "analysis_id": "GCST1"},
    "OGS-17:finngen-E4": {
        "id": "OGS-17:finngen-E4",
        "store_id": "OGS-17",
        "analysis_id": "finngen-E4",
    },
}
OPENGWAS = {
    "ebi-a-GCST1": {
        "id": "ebi-a-GCST1",
        "batch": "ebi-a",
        "match": "exact",
        "catalog_ids": ["OGS-11:GCST1", "OGS-12:GCST1"],
    },
    "finn-b-E4": {
        "id": "finn-b-E4",
        "batch": "finn-b",
        "match": "successor",
        "catalog_ids": ["OGS-17:finngen-E4"],
    },
    "ieu-a-2": {
        "id": "ieu-a-2",
        "batch": "ieu-a",
        "catalog_ids": [],
        "reason": "OpenGWAS batch ieu-a is not held by any Store",
    },
}


def gwasinfo(request: httpx.Request) -> httpx.Response:
    """The Data API's lookup: Data API IDs directly, OpenGWAS IDs through their resolution."""
    rows: list[dict[str, Any]] = []
    opengwas, not_found = [], []
    for i in json.loads(request.content)["id"]:
        if i in OPENGWAS:
            opengwas.append(OPENGWAS[i])
            rows.extend(ANALYSES[a] for a in OPENGWAS[i]["catalog_ids"])
            if not OPENGWAS[i]["catalog_ids"]:
                not_found.append(i)
            continue
        found = [r for r in ANALYSES.values() if i in (r["id"], r["analysis_id"])]
        rows.extend(found)
        if not found:
            not_found.append(i)
    return httpx.Response(
        200, json={"analyses": rows, "not_found": not_found, "opengwas": opengwas}
    )


BATCHES: dict[str, list[dict[str, Any]]] = {
    "batches": [
        {"store_id": s, "release_id": f"{s}-r"} for s in ("OGS-9", "OGS-11", "OGS-12", "OGS-17")
    ],
    "opengwas_batches": [
        {"batch": "ukb-b", "match": "exact", "store_ids": ["OGS-9"]},
        {"batch": "ebi-a", "match": "exact", "store_ids": ["OGS-11", "OGS-12"]},
        {"batch": "finn-b", "match": "successor", "store_ids": ["OGS-17"]},
    ],
}


@pytest.fixture(autouse=True)
def default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "_default", fake_client(BASE))


@respx.mock
def test_resolve_translates_reports_and_keeps_order() -> None:
    respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=gwasinfo)
    with pytest.warns(UserWarning) as caught:
        resolved = resolve(
            ["UKB-b:1", "ebi-a-GCST1", "finn-b-E4", "ieu-a-2", "nope", "ebi-a-GCST1"]
        )
    messages = [str(w.message) for w in caught]
    assert any("successor" in m and "finn-b-E4 -> OGS-17:finngen-E4" in m for m in messages)
    assert any(
        "2 IDs are left out: ieu-a-2 (OpenGWAS batch ieu-a is not held by any Store); "
        "nope (not served by the Data API)" in m
        for m in messages
    )
    assert resolved.ids == ["OGS-9:ukb-b-1", "OGS-11:GCST1", "OGS-12:GCST1", "OGS-17:finngen-E4"]
    assert resolved.requested["OGS-12:GCST1"] == "ebi-a-GCST1"
    assert resolved.requested["OGS-9:ukb-b-1"] == "ukb-b-1"  # the legacy form, converted
    assert {
        "id": "finn-b-E4",
        "analyses": ["OGS-17:finngen-E4"],
        "match": "successor",
    } in resolved.opengwas
    assert {"id": "nope", "reason": "not served by the Data API"} in resolved.opengwas


def test_resolve_nothing() -> None:
    assert resolve([]).ids == []


@respx.mock
def test_resolve_batches() -> None:
    respx.get(f"{BASE}/api/batches").respond(json=BATCHES)
    assert resolve_batches([]) is None
    assert resolve_batches(["OGS-9", "ebi-a", "OGS-11"]) == ["OGS-9", "OGS-11", "OGS-12"]
    with pytest.warns(UserWarning, match="finn-b -> OGS-17"):
        assert resolve_batches(["finn-b"]) == ["OGS-17"]
    with pytest.raises(
        UnsupportedOptionError, match="OpenGWAS batches it holds: ebi-a, finn-b, ukb-b"
    ):
        resolve_batches(["ieu-a"])


def tophits(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "store_id": a.split(":")[0],
            "analysis_id": a.split(":")[1],
            "alid": "1:1:A:G",
            "rsid": "rs1",
            "z": 9.0,
            "se": 0.1,
            "log10_p": -19.0,
        }
        for a in body["analyses"]
    ]


@respx.mock
def test_tophits_by_opengwas_ids() -> None:
    respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=gwasinfo)
    server = JobServer(BASE, tophits)
    with pytest.warns(UserWarning, match="successor"):
        frame = compat.tophits(["ebi-a-GCST1", "finn-b-E4"], clump=0)
    assert server.bodies[0][1]["analyses"] == ["OGS-11:GCST1", "OGS-12:GCST1", "OGS-17:finngen-E4"]
    assert list(frame["opengwas_id"]) == ["ebi-a-GCST1", "ebi-a-GCST1", "finn-b-E4"]
    assert [e["id"] for e in frame.attrs["opengwas_ids"]] == ["ebi-a-GCST1", "finn-b-E4"]


@respx.mock
def test_nothing_resolved_gives_empty_results() -> None:
    respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=gwasinfo)
    with pytest.warns(UserWarning, match="left out"):
        frame = compat.tophits("ieu-a-2", clump=0)
    assert frame.empty and frame.attrs["opengwas_ids"][0]["id"] == "ieu-a-2"
    with pytest.warns(UserWarning, match="left out"):
        frame = compat.associations("rs1", "ieu-a-2")
    assert frame.empty and frame.attrs["opengwas_ids"][0]["id"] == "ieu-a-2"


@respx.mock
def test_gwasinfo_with_opengwas_ids(capsys: pytest.CaptureFixture[str]) -> None:
    respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=gwasinfo)
    with pytest.warns(UserWarning, match="successor"):
        frame = compat.gwasinfo(["finn-b-E4", "ieu-a-2", "OGS-11:GCST1"])
    assert list(frame["id"]) == ["OGS-17:finngen-E4", "OGS-11:GCST1"]
    assert list(frame.columns[:2]) == ["id", "trait"]
    assert list(frame["opengwas_id"]) == ["finn-b-E4", "OGS-11:GCST1"]
    assert "ieu-a-2 (OpenGWAS batch ieu-a is not held by any Store)" in capsys.readouterr().out
    empty = compat.gwasinfo(["ieu-a-2"])
    assert empty.empty and empty.attrs["opengwas_ids"][0]["id"] == "ieu-a-2"


@respx.mock
def test_phewas_batch_by_opengwas_batch() -> None:
    respx.post(f"{BASE}/api/gwasinfo").respond(json={"analyses": []})
    server = JobServer(
        BASE,
        lambda e, b: [],
        batches=BATCHES["batches"],
        opengwas_batches=BATCHES["opengwas_batches"],
    )
    compat.phewas("rs1", batch=["ebi-a"])
    releases = [b["releases"] for e, b in server.bodies if e.endswith("phewas")]
    assert [r["store_id"] for r in releases[0]] == ["OGS-11", "OGS-12"]
