"""Live metadata checks."""

import pytest

from opengwaspy import Client, NotImplementedByServer
from opengwaspy.metadata import gwasinfo, gwasinfo_files
from tests.conftest import LiveAPI

pytestmark = pytest.mark.live


@pytest.fixture
def client(live_api: LiveAPI) -> Client:
    return Client(live_api.url, token=live_api.token)


def test_listing_and_lookup(client: Client) -> None:
    listed = gwasinfo(limit=5, client=client)
    assert len(listed) == 5
    assert listed.attrs["total"] > 5
    ids = list(listed["id"])
    found = gwasinfo([ids[2], "no-such-analysis", ids[0]], client=client)
    assert list(found["id"]) == [ids[2], ids[0]]
    assert found.attrs["not_found"] == ["no-such-analysis"]
    assert {"analysis_label", "sample_size", "assigned_ancestry"} <= set(found.columns)


def test_files_not_yet_served(client: Client) -> None:
    with pytest.raises(NotImplementedByServer):
        gwasinfo_files(client=client)
