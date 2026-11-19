"""A small job end to end on the live API."""

import pytest

from opengwaspy.auth import DeveloperKey
from opengwaspy.config import Config
from opengwaspy.jobs import Job
from opengwaspy.transport import Transport, json_body
from tests.conftest import LiveAPI

pytestmark = pytest.mark.live


def test_tophits_job_end_to_end(live_api: LiveAPI, request: pytest.FixtureRequest) -> None:
    transport = Transport(Config(base_url=live_api.url, auth=DeveloperKey(live_api.token)))
    request.addfinalizer(transport.close)
    analysis = json_body(transport.get("api/gwasinfo", params={"limit": 1}))["analyses"][0]["id"]
    job = Job.submit(transport, "api/tophits", {"analyses": [analysis], "limit": 5})
    frame = job.to_frame()
    assert 0 < len(frame) <= 5
    assert {"alid", "z", "log10_p"} <= set(frame.columns)
    assert frame.attrs["job_id"] == job.job_id
    assert frame.attrs["query_hash"].startswith("sha256:")
    assert "truncated" in frame.attrs["metadata"]
    # Resubmitting the same query returns the same job.
    again = Job.submit(transport, "api/tophits", {"analyses": [analysis], "limit": 5})
    assert again.query_hash == job.query_hash


def test_run_many_in_order(live_api: LiveAPI, request: pytest.FixtureRequest) -> None:
    from opengwaspy.batch import run_many

    transport = Transport(Config(base_url=live_api.url, auth=DeveloperKey(live_api.token)))
    request.addfinalizer(transport.close)
    analyses = json_body(transport.get("api/gwasinfo", params={"limit": 3}))["analyses"]
    ids = [a["id"] for a in analyses]
    frames = run_many(
        transport,
        [("api/tophits", {"analyses": [i], "limit": 3}) for i in ids],
        max_in_flight=2,
    )
    assert len(frames) == len(ids)
    for analysis_id, frame in zip(ids, frames, strict=True):
        assert frame is not None
        assert set(frame["analysis_id"]) <= {analysis_id.split(":", 1)[1]}


def test_client_facade(live_api: LiveAPI) -> None:
    from opengwaspy import Client

    with Client(live_api.url, token=live_api.token) as client:
        assert client.user()["role"] == "developer"
        assert client.limits.lookup_variants >= 1
        assert client.image_digest and client.image_digest.startswith("sha256:")
        assert len(client.batches()) >= 1
