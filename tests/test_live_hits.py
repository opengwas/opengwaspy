"""Live top hits and PheWAS."""

from collections.abc import Iterator

import pytest

from opengwaspy import Client, RequestError
from opengwaspy.hits import phewas, tophits
from tests.conftest import LiveAPI

pytestmark = pytest.mark.live

ANALYSIS = "OGS-00006:GCST90199621"


@pytest.fixture
def client(live_api: LiveAPI) -> Iterator[Client]:
    with Client(live_api.url, token=live_api.token) as client:
        yield client


def test_tophits(client: Client) -> None:
    with pytest.warns(UserWarning, match="more than 5 hits"):
        frame = tophits(ANALYSIS, limit=5, client=client)
    assert len(frame) == 5
    assert (frame["p"] <= 5e-8).all()
    assert frame["z"].abs().is_monotonic_decreasing
    assert frame.attrs["truncated"] is True


def test_unsupported_threshold(client: Client) -> None:
    with pytest.raises(RequestError) as info:
        tophits(ANALYSIS, threshold=0.01, client=client)
    assert info.value.error == "unsupported_threshold"
    assert 5e-4 in info.value.extra["indexed_thresholds"]


def test_phewas_in_named_store(client: Client) -> None:
    with pytest.warns(UserWarning, match="only 20 were returned"):
        frame = phewas("rs1171617", releases=["OGS-00006"], limit=20, client=client)
    assert len(frame) == 20
    assert frame.attrs["truncated"] is True and frame.attrs["total"] > 20
    assert set(frame["rsid"]) == {"rs1171617"}
    assert "total" in frame.attrs


def test_phewas_threshold_on_the_server(client: Client) -> None:
    # rs429358 (APOE): the server cuts at the threshold before building rows, so every
    # association at p <= 1e-8 fits in one result.
    frame = phewas("rs429358", client=client, limit=10_000)
    assert frame.attrs["threshold"] == 1e-8 and frame.attrs["truncated"] is False
    assert len(frame) == frame.attrs["total"] > 100
    assert (frame["p"] <= 1e-8).all()
    stricter = phewas("rs429358", threshold=1e-50, client=client, limit=10_000)
    assert 0 < len(stricter) < len(frame) and (stricter["p"] <= 1e-50).all()
