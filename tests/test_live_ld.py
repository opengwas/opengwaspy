"""Live LD queries against the LD Stores."""

from collections.abc import Iterator

import pytest

from opengwaspy import Client, LDRefusal
from opengwaspy.ld import ld_clump, ld_matrix, ld_proxies, ld_reflookup, ld_region, ld_stores
from tests.conftest import LiveAPI

pytestmark = pytest.mark.live

SIGNAL = ["10:59707424:G:T", "10:59709780:C:T", "10:59709332:C:T"]


@pytest.fixture
def client(live_api: LiveAPI) -> Iterator[Client]:
    with Client(live_api.url, token=live_api.token) as client:
        yield client


def test_stores(client: Client) -> None:
    assert {"EUR", "AFR"} <= set(ld_stores(client=client)["ancestry"])


def test_matrix_and_absent(client: Client) -> None:
    m = ld_matrix([*SIGNAL, "1:1:A:G"], ancestry="EUR", client=client)
    assert m.shape == (3, 3)
    assert m.loc[SIGNAL[0], SIGNAL[1]] == pytest.approx(-0.988, abs=0.01)
    assert m.attrs["absent"] == ["1:1:A:G"]


def test_region(client: Client) -> None:
    m = ld_region(10, 59_707_424, 500, ancestry="EUR", client=client)
    assert SIGNAL[0] in m.index and m.shape[0] == m.shape[1]


def test_clump_proxies_reflookup(client: Client) -> None:
    clumped = ld_clump(SIGNAL, [24.6, 24.5, 24.5], r2=0.1, kb=1000, ancestry="EUR", client=client)
    assert set(clumped["lead"]) == {SIGNAL[0]}
    proxies = ld_proxies(SIGNAL[0], kb=100, ancestry="EUR", client=client)
    assert (proxies["r2"] >= 0.8).all() and SIGNAL[2] in set(proxies["proxy"])
    ref = ld_reflookup([SIGNAL[0], "1:1:A:G"], ancestry="EUR", client=client)
    assert list(ref["present"]) == [True, False]


def test_ieugwasr_default_clump_is_refused(client: Client) -> None:
    with pytest.raises(LDRefusal, match="any r2 with kb up to 3,000") as info:
        ld_clump(SIGNAL[:1], [3.0], r2=0.001, kb=10_000, ancestry="EUR", client=client)
    assert info.value.reason == "threshold_below_t_far"
