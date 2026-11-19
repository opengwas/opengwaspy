"""Live association queries."""

import pytest

from opengwaspy import Client
from opengwaspy.associations import associations, associations_range
from tests.conftest import LiveAPI

pytestmark = pytest.mark.live

ANALYSIS = "OGS-00006:GCST90199621"  # Carnitine levels


@pytest.fixture
def client(live_api: LiveAPI) -> Client:
    return Client(live_api.url, token=live_api.token)


def test_by_rsid_and_alid(client: Client) -> None:
    frame = associations(["rs1171617", "rs0000000"], ANALYSIS, client=client)
    assert list(frame["rsid"]) == ["rs1171617"]  # an absent variant gives no row
    by_alid = associations(list(frame["alid"]), ANALYSIS, client=client)
    assert list(by_alid["rsid"]) == ["rs1171617"]
    top = frame.iloc[0]
    assert top["p"] == pytest.approx(10 ** top["log10_p"])
    assert top["p"] < 5e-8


def test_range(client: Client) -> None:
    frame = associations_range(10, 59_700_000, 59_710_000, ANALYSIS, client=client)
    assert len(frame) > 0
    assert frame["position"].between(59_700_000, 59_710_000).all()
    assert set(frame["chromosome"].astype(str)) == {"10"}
