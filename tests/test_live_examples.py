"""Run the ported ieugwaspy usage examples against the live API."""

import importlib.util
from collections.abc import Iterator
from pathlib import Path

import pytest

import opengwaspy as og
from tests.conftest import LiveAPI

pytestmark = pytest.mark.live

SCRIPT = Path(__file__).resolve().parent.parent / "examples" / "usage_examples.py"


@pytest.fixture(autouse=True)
def default_client(live_api: LiveAPI) -> Iterator[None]:
    client = og.configure(url=live_api.url, token=live_api.token)
    yield
    client.close()


def test_usage_examples_run(capsys: pytest.CaptureFixture[str]) -> None:
    spec = importlib.util.spec_from_file_location("usage_examples", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.warns(UserWarning):
        out = module.main()
    assert len(out["bmi"]) > 0 and len(out["leads"]) > 0
    assert len(out["assocs"]) > 0
    assert (out["phewas"]["p"] <= 1e-5).all()
    assert "rs429358" in capsys.readouterr().out
