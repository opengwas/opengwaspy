"""MCP data tools: top_hits, associations, region_associations, phewas, variant_info."""

from __future__ import annotations

from typing import Any

import pytest
import respx

import opengwaspy.client as client_module
from tests import test_compat_associations as fake
from tests.fakes import JobServer
from tests.mcp_fakes import BASE, call, keyed, text_of
from tests.test_compat_ids import gwasinfo as opengwas_gwasinfo

A, B = fake.A, fake.B


def hit(analysis: str, alid: str, log10_p: float, **extra: Any) -> dict[str, Any]:
    row = fake.assoc(analysis, alid, f"rs{alid.split(':')[1]}")
    row["store_id"] = analysis.split(":")[0]
    return {**row, "log10_p": log10_p, **extra}


def answer(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    if endpoint == "/api/tophits":
        rows = []
        for a in body["analyses"]:
            rows += [hit(a, f"1:{i}:A:G", -10.0 + i, clump_size=3) for i in range(1, 4)]
        return rows
    if endpoint == "/api/phewas":
        return [
            {**hit(A, "1:100:A:G", -9.0), "analysis_label": "weak"},
            {**hit(B, "1:100:A:G", -30.0), "analysis_label": "strong"},
        ]
    return fake.answer(endpoint, body)


def tophits_meta(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    if endpoint == "/api/tophits" and "clump" in body:
        return {
            "truncated": False,
            "clump": {
                "r2": 0.001,
                "kb": 3000,
                "hits": 9,
                "leads": 3,
                "absent": 2,
                "ld_stores": {"EUR": "eur"},
            },
        }
    if endpoint == "/api/tophits":
        return {"truncated": True}
    if endpoint == "/api/phewas":
        return {"total": 5000, "returned": 2, "truncated": True, "threshold": 1e-8}
    return {}


def serve() -> JobServer:
    respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=fake.gwasinfo)
    respx.get(f"{BASE}/api/ld/stores").respond(
        json={"stores": [{"ancestry": "EUR", "store": "eur"}]}
    )
    return JobServer(BASE, answer, metadata=tophits_meta)


def bodies(server: JobServer, endpoint: str) -> list[dict[str, Any]]:
    return [b for e, b in server.bodies if e == endpoint]


@respx.mock
def test_top_hits_shares_rows_between_analyses_and_labels_them() -> None:
    server = serve()
    result = call(keyed, "top_hits", {"analysis_ids": [A, B], "max_rows": 4})
    assert not result.is_error, text_of(result)
    out = result.structured_content
    assert out is not None
    assert bodies(server, "/api/tophits")[0]["analyses"] == [A, B]
    assert "clump" not in bodies(server, "/api/tophits")[0]
    assert [r["id"] for r in out["rows"]] == [A, A, B, B]
    assert out["total_rows"] == 6 and out["truncated"] is True
    assert out["summary"] == f"6 hits at p <= 5e-08 ({A}: 3; {B}: 3)."
    assert out["columns"][:4] == ["id", "rsid", "alid", "ea"]
    assert out["rows"][0]["n"] == 10 and out["rows"][0]["beta"] == pytest.approx(0.5)
    assert any("more than 1,000 hits" in n for n in out["notes"])


@respx.mock
def test_top_hits_clumped_on_the_server() -> None:
    server = serve()
    out = call(
        keyed, "top_hits", {"analysis_ids": [A], "clump": True, "kb": 500, "ancestry": "eur"}
    ).structured_content
    assert out is not None
    assert bodies(server, "/api/tophits")[0]["clump"] == {"kb": 500, "ancestry": "EUR"}
    assert "clump_size" in out["columns"]
    assert out["summary"].startswith("3 leads")
    assert out["provenance"]["clump"]["leads"] == 3
    assert any("2 hits are not in the LD panel" in n for n in out["notes"])
    plain = call(keyed, "top_hits", {"analysis_ids": [A], "clump": True}).structured_content
    assert plain is not None and bodies(server, "/api/tophits")[-1]["clump"] == {}


@respx.mock
def test_top_hits_translate_opengwas_ids() -> None:
    respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=opengwas_gwasinfo)
    server = JobServer(BASE, answer)
    out = call(keyed, "top_hits", {"analysis_ids": ["finn-b-E4", "ieu-a-2"]}).structured_content
    assert out is not None
    assert bodies(server, "/api/tophits")[0]["analyses"] == ["OGS-17:finngen-E4"]
    assert {r["opengwas_id"] for r in out["rows"]} == {"finn-b-E4"}
    assert any(n.startswith("ieu-a-2: not found") for n in out["notes"])
    assert any("later release" in n for n in out["notes"])
    nothing = call(keyed, "top_hits", {"analysis_ids": ["ieu-a-2"]})
    assert nothing.is_error and "None of the analysis IDs were found" in text_of(nothing)


@pytest.mark.parametrize(
    ("tool", "args", "message"),
    [
        ("top_hits", {"analysis_ids": [f"a{i}" for i in range(11)]}, ""),
        ("top_hits", {"analysis_ids": ["a"], "r2": 0.1}, "only with clump=true"),
        ("top_hits", {"analysis_ids": ["a"], "threshold": 0}, ""),
        ("associations", {"variants": ["rs1"] * 101, "analysis_ids": ["a"]}, ""),
        ("associations", {"variants": ["rs1"], "analysis_ids": [f"a{i}" for i in range(21)]}, ""),
        (
            "region_associations",
            {"chromosome": "1", "start": 1, "end": 1_000_001, "analysis_ids": ["a"]},
            "at most 1,000,000 bp",
        ),
        (
            "region_associations",
            {"chromosome": "1", "start": 9, "end": 1, "analysis_ids": ["a"]},
            "before start",
        ),
        (
            "region_associations",
            {"chromosome": "1", "start": 1, "end": 2, "analysis_ids": [f"a{i}" for i in range(6)]},
            "",
        ),
        ("phewas", {"variant": "rs1", "threshold": 2}, ""),
        ("variant_info", {"variants": ["APOE"]}, "not rsIDs or chromosome:position: APOE"),
        ("variant_info", {"variants": ["rs1"] * 101}, ""),
    ],
)
def test_limits_are_checked_before_any_job(tool: str, args: dict[str, Any], message: str) -> None:
    with respx.mock(assert_all_called=False) as mock:
        result = call(keyed, tool, args)
        assert not [c for c in mock.calls if c.request.method == "POST"]
    assert result.is_error
    assert message in text_of(result)


@respx.mock
def test_associations_without_proxies() -> None:
    server = serve()
    out = call(
        keyed, "associations", {"variants": ["rs500", "1:100:A:G"], "analysis_ids": [A, B]}
    ).structured_content
    assert out is not None
    assert bodies(server, "/api/associations")[0]["variants"] == ["rs500", "1:100:A:G"]
    assert [r["rsid"] for r in out["rows"]] == ["rs500", "rs500"]
    assert out["summary"] == "2 associations in 2 analyses."
    assert out["provenance"]["proxies"] is False
    assert "proxy" not in out["columns"]


@respx.mock
def test_associations_with_proxies_use_the_session_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "_default", None)
    serve()
    result = call(
        keyed, "associations", {"variants": ["1:100:A:G"], "analysis_ids": [A, B], "proxies": True}
    )
    assert not result.is_error, text_of(result)
    out = result.structured_content
    assert out is not None
    assert out["summary"] == "2 associations in 2 analyses, 2 through proxies."
    assert {"proxy", "target_snp", "proxy_snp", "proxy_r2"} <= set(out["columns"])
    assert {r["proxy_snp"] for r in out["rows"]} == {"rs300", "rs500"}
    assert any("no LD store for ancestry MID" in n for n in out["notes"])
    assert out["provenance"]["proxies"] is True and out["provenance"]["r2"] == 0.8
    assert client_module._default is None  # restored when the session ended


@respx.mock
def test_region_associations() -> None:
    server = serve()
    out = call(
        keyed,
        "region_associations",
        {"chromosome": "chr7", "start": 1, "end": 1_000_000, "analysis_ids": [A]},
    ).structured_content
    assert out is not None
    sent = bodies(server, "/api/associations/range")[0]
    assert (sent["chromosome"], sent["start"], sent["end"]) == ("7", 1, 1_000_000)
    assert out["summary"] == "1 associations in chr7:1-1000000 in 1 analyses."
    assert out["notes"] == ["Strongest: rs7 (p = 1e-06)."]


@respx.mock
def test_phewas_strongest_first_with_truncation_note() -> None:
    server = serve()
    out = call(keyed, "phewas", {"variant": "rs100", "max_rows": 1}).structured_content
    assert out is not None
    sent = bodies(server, "/api/phewas")[0]
    assert (sent["variant"], sent["threshold"], sent["limit"]) == ("rs100", 1e-8, 1000)
    assert out["rows"][0]["trait"] == "strong"
    assert out["total_rows"] == 5000 and out["summary"].startswith("5000 associations of rs100")
    assert out["notes"] and "only 2 were fetched" in out["notes"][0]
    assert out["provenance"]["threshold"] == 1e-8


@respx.mock
def test_phewas_refusal_is_a_tool_error() -> None:
    respx.post(f"{BASE}/api/phewas").respond(
        400, json={"error": "unsupported_threshold", "message": "use 5e-4 or lower"}
    )
    serve()
    result = call(keyed, "phewas", {"variant": "rs1", "threshold": 0.01})
    assert result.is_error and "use 5e-4 or lower" in text_of(result)


@respx.mock
def test_variant_info_by_rsid_and_position() -> None:
    serve()
    out = call(
        keyed, "variant_info", {"variants": ["rs100", "1:100", "rs0", "chr2:5"]}
    ).structured_content
    assert out is not None
    assert [r["alid"] for r in out["rows"]] == ["1:100:A:G", "1:100:A:C"]
    assert out["notes"] == ["rs0: no served Store holds it.", "chr2:5: no served Store holds it."]
    empty = call(keyed, "variant_info", {"variants": ["rs0"]}).structured_content
    assert empty is not None and empty["rows"] == []


@respx.mock
def test_store_counts_when_held_by_several_stores() -> None:
    def found(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"rsid": "rs1", "alid": "1:1:A:G", "store_id": r["store_id"]} for r in body["releases"]
        ]

    JobServer(BASE, found, batches=[{"store_id": s, "release_id": "r"} for s in ("S1", "S2")])
    out = call(keyed, "variant_info", {"variants": ["rs1"]}).structured_content
    assert out is not None and out["rows"][0]["stores"] == 2
