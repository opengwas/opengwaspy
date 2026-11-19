import math
from typing import Any

import pandas as pd
import pytest
import respx

from opengwaspy._common import as_list, combine, resolve_releases
from opengwaspy.associations import associations, associations_analysis, associations_range
from opengwaspy.client import Client
from tests.fakes import JobServer, fake_client

BASE = "http://api.test"


def rows_for(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    if endpoint.endswith("/range"):
        return [
            {"analysis_id": a, "position": body["start"], "log10_p": -2.0}
            for a in body.get("analyses") or ["all"]
        ]
    return [
        {"analysis_id": a, "alid": v, "log10_p": -8.0}
        for a in body["analyses"]
        for v in body.get("variants", ["*"])
    ]


@pytest.fixture
def client() -> Client:
    return fake_client(BASE)


@respx.mock
def test_single_job_adds_p(client: Client) -> None:
    server = JobServer(BASE, rows_for)
    frame = associations(["rs1", "rs2"], "OGS-1:A", client=client)
    assert server.bodies == [
        (
            "/api/associations",
            {"variants": ["rs1", "rs2"], "analyses": ["OGS-1:A"], "observed_only": True},
        )
    ]
    assert list(frame.columns) == ["analysis_id", "alid", "log10_p", "p"]
    assert frame["p"].iloc[0] == pytest.approx(1e-8)
    assert frame.attrs["job_id"] == "j1"
    assert frame.attrs["image_digest"] == "sha256:test"


@respx.mock
def test_chunking_follows_server_limits_and_keeps_order(client: Client) -> None:
    server = JobServer(BASE, rows_for, limits={"lookup_variants": 2, "lookup_analyses": 1})
    frame = associations(["v1", "v2", "v3"], ["a1", "a2"], observed_only=False, client=client)
    assert [b["analyses"] for _, b in server.bodies] == [["a1"], ["a1"], ["a2"], ["a2"]]
    assert [b["variants"] for _, b in server.bodies] == [["v1", "v2"], ["v3"], ["v1", "v2"], ["v3"]]
    assert list(zip(frame["analysis_id"], frame["alid"], strict=True)) == [
        ("a1", "v1"),
        ("a1", "v2"),
        ("a1", "v3"),
        ("a2", "v1"),
        ("a2", "v2"),
        ("a2", "v3"),
    ]
    assert frame.attrs["job_ids"] == ["j1", "j2", "j3", "j4"]
    assert all(b["observed_only"] is False for _, b in server.bodies)


@respx.mock
def test_releases_are_resolved(client: Client) -> None:
    server = JobServer(
        BASE,
        rows_for,
        batches=[
            {"store_id": "OGS-1", "release_id": "r1"},
            {"store_id": "OGS-2", "release_id": "r2"},
        ],
    )
    associations(
        "rs1",
        "a",
        releases=["OGS-2", "OGS-1/old", {"store_id": "OGS-3", "release_id": "r3"}],
        client=client,
    )
    assert server.bodies[0][1]["releases"] == [
        {"store_id": "OGS-2", "release_id": "r2"},
        {"store_id": "OGS-1", "release_id": "old"},
        {"store_id": "OGS-3", "release_id": "r3"},
    ]
    with pytest.raises(ValueError, match="no served release of Store 'OGS-9'"):
        associations("rs1", "a", releases="OGS-9", client=client)


@pytest.mark.parametrize("releases", [[], [{"store_id": "x"}], ["/r"], ["s/"]])
def test_bad_releases(client: Client, releases: list[object]) -> None:
    with pytest.raises(ValueError):
        resolve_releases(client, releases)  # type: ignore[arg-type]


@respx.mock
def test_range_windows_and_groups(client: Client) -> None:
    server = JobServer(BASE, rows_for, limits={"range_span": 1_000_000, "range_analyses": 2})
    frame = associations_range("chr7", 500_000, 2_600_000, ["a", "b", "c"], client=client)
    windows = [(b["start"], b["end"]) for _, b in server.bodies]
    assert windows == [(500_000, 1_499_999), (1_500_000, 2_499_999), (2_500_000, 2_600_000)] * 2
    assert [b["analyses"] for _, b in server.bodies] == [["a", "b"]] * 3 + [["c"]] * 3
    assert {b["chromosome"] for _, b in server.bodies} == {"7"}
    assert len(frame) == 9 and "p" in frame.columns


@respx.mock
def test_range_without_analyses(client: Client) -> None:
    server = JobServer(BASE, rows_for)
    associations_range(22, 1, 100, releases="OGS-1", client=client)
    assert server.bodies[0][1] == {
        "chromosome": "22",
        "start": 1,
        "end": 100,
        "observed_only": True,
        "releases": [{"store_id": "OGS-1", "release_id": "OGS-1-r1"}],
    }


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (("7", 10, 5), ValueError),
        (("7", 0, 5), ValueError),
        (("7", 1.5, 5), TypeError),
        (("7", True, 5), TypeError),
        (("chr", 1, 5), ValueError),
    ],
)
def test_range_validation(
    client: Client, args: tuple[object, object, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        associations_range(*args, client=client)  # type: ignore[arg-type]


@respx.mock
def test_whole_analyses_in_groups(client: Client) -> None:
    server = JobServer(BASE, rows_for, limits={"analysis_analyses": 2})
    frame = associations_analysis(["a", "b", "c"], client=client)
    assert [b["analyses"] for _, b in server.bodies] == [["a", "b"], ["c"]]
    assert list(frame["analysis_id"]) == ["a", "b", "c"]


def test_as_list() -> None:
    assert as_list(" x ", "v") == ["x"]
    assert as_list(None, "v") is None
    with pytest.raises(ValueError, match="empty"):
        as_list([], "v")
    with pytest.raises(ValueError, match="non-empty"):
        as_list(["a", 3], "v")  # type: ignore[list-item]


def test_combine_empty_frames() -> None:
    a, b = pd.DataFrame(), pd.DataFrame()
    a.attrs.update(job_id="1", releases=[{"s": 1}])
    b.attrs.update(job_id="2", releases=[{"s": 1}])
    out = combine([a, b])
    assert out.empty and out.attrs["job_ids"] == ["1", "2"] and out.attrs["releases"] == [{"s": 1}]
    assert not math.isnan(len(out))
