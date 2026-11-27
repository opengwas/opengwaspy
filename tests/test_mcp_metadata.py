"""MCP metadata tools: search_analyses and get_analyses."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pandas as pd
import pytest
import respx

from opengwaspy.auth import NoAuth
from opengwaspy.mcp.formatting import table_result
from tests.mcp_fakes import BASE, SECRET, call, client_with, keyed, text_of
from tests.test_compat_ids import gwasinfo as fake_gwasinfo


def found(ids: list[str], *, total: int) -> dict[str, Any]:
    return {
        "q": "x",
        "release_id": "r1",
        "catalog_version": "cv1",
        "filters": {},
        "total": total,
        "next_after": None,
        "next_offset": None,
        "analyses": [
            {"id": i, "analysis_label": f"label {i}", "sample_size": 10.0, "extra": "e"}
            for i in ids
        ],
    }


def status() -> None:
    respx.get(f"{BASE}/api/status").respond(json={"ready": True, "execution": {}})


@respx.mock
def test_search_trims_rows_and_columns_and_records_provenance() -> None:
    status()
    route = respx.post(f"{BASE}/api/gwasinfo/search").respond(json=found(["a", "b"], total=40))
    result = call(
        keyed,
        "search_analyses",
        {"q": "body mass", "assigned_ancestry": "EUR", "max_rows": 2},
    )
    assert not result.is_error, text_of(result)
    out = result.structured_content
    assert out is not None
    sent = json.loads(route.calls[0].request.content)
    assert sent == {"q": "body mass", "match": "contains", "limit": 2, "assigned_ancestry": "EUR"}
    assert out["summary"] == "40 analyses match 'body mass' (contains); 2 shown."
    assert out["total_rows"] == 40 and out["rows_returned"] == 2 and out["truncated"] is True
    assert out["columns"] == ["id", "analysis_label", "sample_size"]
    assert out["rows"][0] == {"id": "a", "analysis_label": "label a", "sample_size": 10.0}
    assert out["provenance"]["release_id"] == "r1"
    assert out["provenance"]["filters"] == {"assigned_ancestry": "EUR"}
    assert SECRET not in text_of(result)


@respx.mock
def test_search_all_columns_and_empty() -> None:
    status()
    respx.post(f"{BASE}/api/gwasinfo/search").respond(json=found([], total=0))
    out = call(keyed, "search_analyses", {"q": "zzz", "columns": "all"}).structured_content
    assert out is not None
    assert out["rows"] == [] and out["total_rows"] == 0 and out["truncated"] is False


@pytest.mark.parametrize("code", ["query_too_broad", "invalid_query"])
@respx.mock
def test_search_refusals_are_tool_errors(code: str) -> None:
    status()
    respx.post(f"{BASE}/api/gwasinfo/search").respond(
        400, json={"error": code, "message": "narrow it with a longer q or a filter"}
    )
    result = call(keyed, "search_analyses", {"q": "a", "match": "fulltext"})
    assert result.is_error
    assert "narrow it" in text_of(result)


@pytest.mark.parametrize(
    ("args"),
    [{"q": "a", "max_rows": 101}, {"q": "a", "max_rows": 0}, {"q": ""}, {"q": "a", "match": "x"}],
)
def test_search_arguments_are_checked_before_any_request(args: dict[str, Any]) -> None:
    with respx.mock(assert_all_called=False) as mock:
        result = call(keyed, "search_analyses", args)
        assert not mock.calls
    assert result.is_error


def test_tools_need_a_credential() -> None:
    result = call(client_with(NoAuth()), "search_analyses", {"q": "bmi"})
    assert result.is_error and "OPENGWAS_JWT" in text_of(result)


@respx.mock
def test_get_analyses_translates_opengwas_ids() -> None:
    status()
    respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=fake_gwasinfo)
    result = call(
        keyed, "get_analyses", {"ids": ["ebi-a-GCST1", "finn-b-E4", "ieu-a-2", "UKB-b:1"]}
    )
    assert not result.is_error, text_of(result)
    out = result.structured_content
    assert out is not None
    assert [r["id"] for r in out["rows"]] == [
        "OGS-11:GCST1",
        "OGS-12:GCST1",
        "OGS-17:finngen-E4",
        "OGS-9:ukb-b-1",
    ]
    assert out["columns"][-1] == "opengwas_id"
    assert [r["opengwas_id"] for r in out["rows"]] == [
        "ebi-a-GCST1",
        "ebi-a-GCST1",
        "finn-b-E4",
        "ukb-b-1",
    ]
    assert out["summary"] == "4 analyses for 3 of 4 IDs; 1 not found."
    assert any("finn-b-E4 was translated to OGS-17:finngen-E4" in n for n in out["notes"])
    assert any(n.startswith("ieu-a-2: not found (OpenGWAS batch ieu-a") for n in out["notes"])
    assert out["provenance"]["opengwas_ids"][0] == {
        "id": "ebi-a-GCST1",
        "analyses": ["OGS-11:GCST1", "OGS-12:GCST1"],
        "match": "exact",
    }


@respx.mock
def test_get_analyses_data_api_ids_and_caps() -> None:
    status()
    respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=fake_gwasinfo)
    out = call(keyed, "get_analyses", {"ids": ["OGS-11:GCST1"], "max_rows": 1}).structured_content
    assert out is not None
    assert "opengwas_id" not in out["columns"]
    assert out["summary"] == "1 analyses for 1 of 1 IDs."
    too_many = call(keyed, "get_analyses", {"ids": [f"x{i}" for i in range(101)]})
    assert too_many.is_error


def test_table_result_handles_nan_numpy_and_missing_columns() -> None:
    frame = pd.DataFrame({"a": [1, 2, 3], "b": [float("nan"), 2.5, 3.0]})
    frame.attrs.update(release_id="r", job_ids=["j1"], other="x", image_digest=None)
    result = table_result(
        frame,
        summary="s",
        max_rows=2,
        columns=["b", "nope"],
        provenance={"n": pd.Series([1]).iloc[0], "nan": float("nan"), "obj": object},
    )
    assert result.columns == ["b"]
    assert result.rows == [{"b": None}, {"b": 2.5}]
    assert result.truncated is True and result.total_rows == 3
    assert result.provenance["release_id"] == "r" and result.provenance["n"] == 1
    assert result.provenance["nan"] is None and "other" not in result.provenance
    assert result.provenance["obj"].startswith("<class")
    no_columns = table_result(frame, summary="s", max_rows=5, columns=["nope"])
    assert no_columns.rows == [{}, {}, {}]
    every = table_result(frame, summary="s", max_rows=5)
    assert every.columns == ["a", "b"] and every.truncated is False


def test_server_errors_keep_their_message() -> None:
    with respx.mock:
        status()
        respx.post(f"{BASE}/api/gwasinfo").mock(return_value=httpx.Response(404, json={}))
        result = call(keyed, "get_analyses", {"ids": ["x"]})
    assert result.is_error
