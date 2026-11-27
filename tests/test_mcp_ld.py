"""MCP LD tools: ld_proxies and ld_matrix."""

from __future__ import annotations

from typing import Any

import pytest
import respx

from opengwaspy.mcp.ld import to_alids
from tests.fakes import JobServer
from tests.mcp_fakes import BASE, call, keyed, text_of

STORE = {
    "store": "eur-k10",
    "ancestry": "EUR",
    "t_far": 0.03,
    "near_bp": 3_000_000,
    "far_bp": 10**7,
}
RSIDS = {"rs1": ["1:100:A:G"], "rs2": ["1:200:C:T", "1:200:C:G"]}


def answer(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    if endpoint.endswith("variants/rsid"):
        return [
            {"rsid": r, "alid": a, "store_id": s["store_id"]}
            for s in body["releases"]
            for r in body["rsids"]
            for a in RSIDS.get(r, [])
        ]
    held = [a for a in body["alids"] if not a.startswith("9:")]
    if endpoint.endswith("proxies"):
        return [
            row
            for a in held
            for row in (
                {"query": a, "proxy": f"{a}-p1", "r": 0.9, "r2": 0.81, "distance": 5},
                {"query": a, "proxy": f"{a}-p2", "r": -0.99, "r2": 0.98, "distance": 9},
            )
        ]
    return [
        {
            "alid": a,
            "a1": "A",
            "a2": "G",
            "r": [1.0 if i == j else 0.12345 for j in range(len(held))],
        }
        for i, a in enumerate(held)
    ]


def meta(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    return {**STORE, "absent": [a for a in body.get("alids", []) if a.startswith("9:")]}


@respx.mock
def test_proxies_translate_rsids_and_sort_strongest_first() -> None:
    server = JobServer(BASE, answer, metadata=meta)
    result = call(
        keyed, "ld_proxies", {"variants": ["rs1", "9:9:A:C", "rs404"], "r2": 0.5, "kb": 500}
    )
    assert not result.is_error, text_of(result)
    out = result.structured_content
    assert out is not None
    ld_body = next(b for e, b in server.bodies if e.endswith("proxies"))
    assert ld_body == {"ancestry": "EUR", "alids": ["1:100:A:G", "9:9:A:C"], "r2": 0.5, "kb": 500}
    assert out["columns"] == ["query", "query_rsid", "proxy", "r", "r2", "distance"]
    assert [r["proxy"] for r in out["rows"]] == ["1:100:A:G-p2", "1:100:A:G-p1"]
    assert out["rows"][0]["query_rsid"] == "rs1"
    assert out["summary"] == "2 proxies with r2 >= 0.5 within 500 kb for 1 variants (EUR)."
    assert "rs404: no served Store holds this rsID, so it is left out." in out["notes"]
    assert "1 variants are not in the LD panel: 9:9:A:C." in out["notes"]
    assert out["provenance"]["store"] == "eur-k10" and out["provenance"]["rsids"] == {
        "1:100:A:G": "rs1"
    }


@respx.mock
def test_proxies_of_alids_only_and_nothing_left() -> None:
    JobServer(BASE, answer, metadata=meta)
    out = call(keyed, "ld_proxies", {"variants": ["1:5:A:G"], "max_rows": 1}).structured_content
    assert out is not None
    assert out["columns"] == ["query", "proxy", "r", "r2", "distance"]
    assert out["rows_returned"] == 1 and out["truncated"] is True
    empty = call(keyed, "ld_proxies", {"variants": ["rs404"]}).structured_content
    assert empty is not None and empty["rows"] == [] and empty["notes"]


@respx.mock
def test_matrix_is_labelled_rows_rounded() -> None:
    JobServer(BASE, answer, metadata=meta)
    result = call(keyed, "ld_matrix", {"variants": ["rs2", "1:5:A:G", "9:9:A:C"]})
    assert not result.is_error, text_of(result)
    out = result.structured_content
    assert out is not None
    assert out["columns"] == ["alid", "rsid", "a1", "a2", "1:200:C:T", "1:200:C:G", "1:5:A:G"]
    assert out["rows"][0] == {
        "alid": "1:200:C:T",
        "rsid": "rs2",
        "a1": "A",
        "a2": "G",
        "1:200:C:T": 1.0,
        "1:200:C:G": 0.123,
        "1:5:A:G": 0.123,
    }
    assert out["rows"][2]["rsid"] is None
    assert any("rs2 names several variants" in n for n in out["notes"])
    assert any("9:9:A:C" in n for n in out["notes"])


@respx.mock
def test_matrix_of_alids_and_empty() -> None:
    JobServer(BASE, answer, metadata=meta)
    out = call(keyed, "ld_matrix", {"variants": ["1:5:A:G", "1:6:A:G"]}).structured_content
    assert out is not None and out["columns"] == ["alid", "a1", "a2", "1:5:A:G", "1:6:A:G"]
    absent = call(keyed, "ld_matrix", {"variants": ["9:9:A:C"]}).structured_content
    assert absent is not None and absent["rows"] == [] and absent["notes"]
    nothing = call(keyed, "ld_matrix", {"variants": ["rs404"]}).structured_content
    assert nothing is not None and nothing["rows"] == []


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("ld_proxies", {"variants": [f"1:{i}:A:G" for i in range(101)]}),
        ("ld_matrix", {"variants": [f"1:{i}:A:G" for i in range(51)]}),
        ("ld_proxies", {"variants": ["1:1:A:G"], "r2": 0}),
        ("ld_proxies", {"variants": ["1:1:A:G"], "kb": 20_000}),
        ("ld_proxies", {"variants": []}),
        ("ld_matrix", {"variants": ["APOE"]}),
    ],
)
def test_limits_and_bad_variants_refused_before_any_job(tool: str, args: dict[str, Any]) -> None:
    with respx.mock(assert_all_called=False) as mock:
        result = call(keyed, tool, args)
        assert not [c for c in mock.calls if c.request.method == "POST"]
    assert result.is_error


@respx.mock
def test_rsids_naming_too_many_variants_are_refused() -> None:
    many = {f"rs{i}": [f"1:{i}:A:G", f"1:{i}:A:C"] for i in range(30)}
    RSIDS.update(many)
    try:
        JobServer(BASE, answer, metadata=meta)
        result = call(keyed, "ld_matrix", {"variants": list(many)})
    finally:
        for key in many:
            RSIDS.pop(key)
    assert result.is_error and "at most 50" in text_of(result)


@respx.mock
def test_ld_refusal_passes_on_what_is_answerable() -> None:
    respx.post(f"{BASE}/api/ld/proxies").respond(
        422,
        json={
            "error": "ld_refusal",
            "message": "r2=0.001 is below t_far",
            "reason": "threshold_below_t_far",
            **STORE,
        },
    )
    JobServer(BASE, answer, metadata=meta)
    result = call(keyed, "ld_proxies", {"variants": ["1:1:A:G"], "r2": 0.001, "kb": 5000})
    assert result.is_error
    assert "answers r2 >= 0.03 with kb up to 10,000" in text_of(result)


@respx.mock
def test_unknown_ancestry_passes_on_the_api_message() -> None:
    respx.post(f"{BASE}/api/ld/matrix").respond(
        404, json={"error": "ld_store_not_found", "message": "no LD store for ancestry XYZ"}
    )
    JobServer(BASE, answer, metadata=meta)
    result = call(keyed, "ld_matrix", {"variants": ["1:1:A:G"], "ancestry": "xyz"})
    assert result.is_error and "no LD store for ancestry XYZ" in text_of(result)


def test_to_alids_rejects_other_text() -> None:
    with pytest.raises(ValueError, match="not ALIDs or rsIDs: APOE"):
        to_alids(keyed(), ["APOE"])
