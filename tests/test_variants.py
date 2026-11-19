from typing import Any

import pytest
import respx

from opengwaspy.client import Client
from opengwaspy.variants import variants_chrpos, variants_rsid
from tests.fakes import JobServer, fake_client

BASE = "http://api.test"
BATCHES = [{"store_id": f"OGS-{i}", "release_id": f"r{i}"} for i in range(12)]


@pytest.fixture
def client() -> Client:
    return fake_client(BASE)


def found(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    values = body.get("rsids") or body.get("positions") or []
    return [{"query": v, "store_id": r["store_id"]} for r in body["releases"] for v in values]


@respx.mock
def test_rsid_searches_every_release_in_groups(client: Client) -> None:
    server = JobServer(BASE, found, batches=BATCHES, limits={"lookup_variants": 2})
    frame = variants_rsid(["rs1", "RS2", "rs3"], client=client)
    shapes = [(len(b["releases"]), b["rsids"]) for _, b in server.bodies]
    assert shapes == [(10, ["rs1", "RS2"]), (10, ["rs3"]), (2, ["rs1", "RS2"]), (2, ["rs3"])]
    assert len(frame) == 36
    assert all(e == "/api/variants/rsid" for e, _ in server.bodies)


@respx.mock
def test_chrpos_named_release(client: Client) -> None:
    server = JobServer(BASE, found, batches=BATCHES)
    frame = variants_chrpos(["chr19:44908684", "X:100"], releases="OGS-3", client=client)
    assert server.bodies == [
        (
            "/api/variants/chrpos",
            {
                "positions": ["chr19:44908684", "X:100"],
                "releases": [{"store_id": "OGS-3", "release_id": "r3"}],
            },
        )
    ]
    assert len(frame) == 2


@pytest.mark.parametrize(
    ("func", "values"),
    [
        (variants_rsid, ["rs1", "1:100"]),
        (variants_chrpos, ["rs1"]),
        (variants_chrpos, ["19:44908684-44908700"]),
    ],
)
def test_validation(client: Client, func: Any, values: list[str]) -> None:
    with pytest.raises(ValueError):
        func(values, client=client)
