"""Live checks of the ieugwaspy-compatible layer, through the default client."""

from collections.abc import Iterator

import pytest

import opengwaspy as og
import opengwaspy.compat as compat
from tests.conftest import LiveAPI

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def default_client(live_api: LiveAPI) -> Iterator[None]:
    client = og.configure(url=live_api.url, token=live_api.token)
    yield
    client.close()


def test_gwasinfo(capsys: pytest.CaptureFixture[str]) -> None:
    frame = compat.gwasinfo(["OGS-00006:GCST90199621", "ieu-a-2"])
    assert list(frame["trait"]) == ["Carnitine levels"]
    assert "ieu-a-2" in capsys.readouterr().out
