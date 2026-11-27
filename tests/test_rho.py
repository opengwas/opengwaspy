from typing import Any

import numpy as np
import pytest
import respx

import opengwaspy as og
from opengwaspy.client import Client
from opengwaspy.errors import ProtocolError, RequestError
from tests.fakes import JobServer, fake_client

BASE = "http://api.test"
SETTINGS = {"method": "nulls", "z_thresh": 2.0, "min_nulls": 100, "grid_n": 10}
FULL = ["a", "b", "c"]
RHO: dict[str, list[float | None]] = {
    "a": [1.0, 0.25, None],
    "b": [0.25, 1.0, -0.5],
    "c": [None, -0.5, 1.0],
}
N_NULL: dict[str, list[int]] = {"a": [900, 800, 12], "b": [800, 950, 400], "c": [12, 400, 990]}


@pytest.fixture
def client() -> Client:
    return fake_client(BASE)


def columns(body: dict[str, Any]) -> list[str]:
    return [a.split(":")[-1] for a in body.get("analyses") or FULL]


def answer(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    cols = columns(body)
    return [
        {
            "analysis_id": a,
            "rho": [RHO[a][FULL.index(c)] for c in cols],
            "n_null": [N_NULL[a][FULL.index(c)] for c in cols],
            "store_id": "OGS-1",
            "release_id": "OGS-1-r1",
        }
        for a in cols
    ]


def metadata(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    cols = columns(body)
    return {"analyses": cols, "n_analyses": len(cols), "settings": SETTINGS}


@respx.mock
def test_rho_full_matrix(client: Client) -> None:
    server = JobServer(BASE, answer, metadata=metadata)
    matrix = og.rho("OGS-1", client=client)
    assert server.bodies == [
        ("/api/rho", {"releases": [{"store_id": "OGS-1", "release_id": "OGS-1-r1"}]})
    ]
    assert list(matrix.index) == FULL and list(matrix.columns) == FULL
    assert matrix.dtypes.unique().tolist() == [np.dtype("float32")]
    assert matrix.loc["a", "b"] == pytest.approx(0.25)
    assert np.isnan(matrix.to_numpy()[0, 2])
    assert (np.diag(matrix.to_numpy()) == 1).all()
    n_null = matrix.attrs["n_null"]
    assert n_null.loc["a", "c"] == 12 and n_null.dtypes.unique().tolist() == [np.dtype("int64")]
    assert matrix.attrs["settings"] == SETTINGS
    assert (matrix.attrs["store_id"], matrix.attrs["release_id"]) == ("OGS-1", "OGS-1-r1")
    assert matrix.attrs["image_digest"] == "sha256:test" and matrix.attrs["job_id"] == "j1"


@respx.mock
def test_rho_sub_matrix_in_the_order_asked(client: Client) -> None:
    server = JobServer(BASE, answer, metadata=metadata)
    matrix = og.rho("OGS-1/OGS-1-r1", ["OGS-1:c", "a"], client=client)
    assert server.bodies[0][1]["analyses"] == ["OGS-1:c", "a"]
    assert list(matrix.index) == ["c", "a"] and list(matrix.columns) == ["c", "a"]
    assert matrix.loc["c", "c"] == 1


@respx.mock
def test_rho_missing_n_null_stays_nan(client: Client) -> None:
    def gappy(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        rows = answer(endpoint, body)
        rows[0]["n_null"][1] = None
        return rows

    JobServer(BASE, gappy, metadata=metadata)
    n_null = og.rho("OGS-1", client=client).attrs["n_null"]
    assert np.isnan(n_null.loc["a", "b"]) and n_null.loc["b", "b"] == 950


@respx.mock
def test_rho_not_square_is_a_protocol_error(client: Client) -> None:
    def short(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        rows = answer(endpoint, body)
        rows[1]["rho"] = rows[1]["rho"][:2]
        return rows

    JobServer(BASE, short, metadata=metadata)
    with pytest.raises(ProtocolError, match="not square"):
        og.rho("OGS-1", client=client)


@respx.mock
def test_rho_unavailable_is_refused(client: Client) -> None:
    respx.post(f"{BASE}/api/rho").respond(  # before the JobServer's catch-all route
        422,
        json={"error": "rho_unavailable", "message": "OGS-1 is a Ragged Store: it has no Rho"},
    )
    JobServer(BASE, answer, metadata=metadata)
    with pytest.raises(RequestError, match="Ragged") as caught:
        og.rho("OGS-1", client=client)
    assert caught.value.error == "rho_unavailable"


@respx.mock
def test_rho_needs_one_release(client: Client) -> None:
    JobServer(
        BASE,
        answer,
        batches=[
            {"store_id": "OGS-1", "release_id": "r1"},
            {"store_id": "OGS-1", "release_id": "r2"},
        ],
    )
    with pytest.raises(ValueError, match="matches 2"):
        og.rho("OGS-1", client=client)
    with pytest.raises(ValueError, match="analyses is empty"):
        og.rho("OGS-1/r1", [], client=client)


def test_rho_values_must_be_lists() -> None:
    from opengwaspy.rho import _floats

    with pytest.raises(ProtocolError, match="not a list"):
        _floats("0.5")
