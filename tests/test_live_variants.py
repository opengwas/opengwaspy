"""Live variant lookups."""

from collections.abc import Iterator

import pytest

from opengwaspy import Client
from opengwaspy.variants import variants_chrpos, variants_rsid
from tests.conftest import LiveAPI

pytestmark = pytest.mark.live


@pytest.fixture
def client(live_api: LiveAPI) -> Iterator[Client]:
    with Client(live_api.url, token=live_api.token) as client:
        yield client


def test_rsid_in_one_store(client: Client) -> None:
    frame = variants_rsid(["rs429358", "rs0"], releases="OGS-00006", client=client)
    assert list(frame["alid"]) == ["19:44908684:C:T"]


def test_chrpos_across_stores(client: Client) -> None:
    frame = variants_chrpos("chr19:44908684", client=client)
    assert set(frame["rsid"].dropna()) == {"rs429358"}
    assert frame["store_id"].nunique() >= 1
