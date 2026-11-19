"""A small job end to end on the live API."""

import pytest

from opengwaspy.auth import DeveloperKey
from opengwaspy.config import Config
from opengwaspy.jobs import Job
from opengwaspy.transport import Transport, json_body
from tests.conftest import LiveAPI

pytestmark = pytest.mark.live


def test_tophits_job_end_to_end(live_api: LiveAPI) -> None:
    transport = Transport(Config(base_url=live_api.url, auth=DeveloperKey(live_api.token)))
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
