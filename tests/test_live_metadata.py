"""Live metadata checks."""

from collections.abc import Iterator

import pytest

from opengwaspy import Client, NotImplementedByServer, RequestError
from opengwaspy.metadata import gwasinfo, gwasinfo_files, gwasinfo_search
from tests.conftest import LiveAPI

pytestmark = pytest.mark.live


@pytest.fixture
def client(live_api: LiveAPI) -> Iterator[Client]:
    with Client(live_api.url, token=live_api.token) as client:
        yield client


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


def test_lookup_in_named_store(client: Client) -> None:
    found = gwasinfo("GCST90199621", releases=["OGS-00006"], client=client)
    assert list(found["id"]) == ["OGS-00006:GCST90199621"]


def test_search_contains_and_fulltext(client: Client) -> None:
    contains = gwasinfo_search("body mass index", limit=3, client=client)
    assert 0 < len(contains) <= 3 and contains.attrs["total"] >= len(contains)
    assert all("body mass index" in label.lower() for label in contains["analysis_label"])
    eur = gwasinfo_search("body mass index", assigned_ancestry="EUR", limit=3, client=client)
    assert set(eur["assigned_ancestry"]) <= {"EUR"}
    fulltext = gwasinfo_search('"body mass index"', match="fulltext", limit=3, client=client)
    assert 0 < len(fulltext) <= 3


def test_search_malformed_fulltext(client: Client) -> None:
    with pytest.raises(RequestError) as info:
        gwasinfo_search("bmi AND (", match="fulltext", limit=1, client=client)
    assert info.value.error == "invalid_query"
