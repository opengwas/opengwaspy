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


def test_tophits_default_refused_then_answerable_clumping() -> None:
    with pytest.raises(og.UnsupportedOptionError, match="kb=3000"):
        compat.tophits("OGS-00006:GCST90199621")
    leads = compat.tophits("OGS-00006:GCST90199621", r2=0.001, kb=3000)
    hits = og.tophits("OGS-00006:GCST90199621")
    assert 0 < len(leads) < len(hits)
    assert "rs1171617" in set(leads["rsid"])
    assert leads.iloc[0]["n"] == 8192
