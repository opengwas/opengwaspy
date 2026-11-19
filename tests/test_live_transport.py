"""Live checks that the transport reads the real API's answers and errors."""

import pytest

from opengwaspy.auth import DeveloperKey
from opengwaspy.config import Config
from opengwaspy.errors import NotImplementedByServer, RequestError
from opengwaspy.transport import Transport, json_body
from tests.conftest import LiveAPI

pytestmark = pytest.mark.live


@pytest.fixture
def transport(live_api: LiveAPI) -> Transport:
    return Transport(Config(base_url=live_api.url, auth=DeveloperKey(live_api.token)))


def test_user(transport: Transport) -> None:
    assert json_body(transport.get("api/user"))["role"] == "developer"


def test_request_error_carries_code_and_request_id(transport: Transport) -> None:
    with pytest.raises(RequestError) as info:
        transport.post("api/associations", {"analyses": ["no-such-analysis"], "variants": ["rs1"]})
    assert info.value.status == 404
    assert info.value.error == "analysis_not_found"
    assert info.value.request_id


def test_not_yet_implemented(transport: Transport) -> None:
    with pytest.raises(NotImplementedByServer):
        transport.get("api/variants/gene/APOE")
