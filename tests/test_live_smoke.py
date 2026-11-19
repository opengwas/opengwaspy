"""Live smoke tests: the configured API answers, and the key is accepted."""

import httpx
import pytest

from tests.conftest import LiveAPI

pytestmark = pytest.mark.live


def test_status_is_ready(live_api: LiveAPI) -> None:
    response = httpx.get(f"{live_api.url}/api/status", timeout=30)
    response.raise_for_status()
    body = response.json()
    assert body["ready"] is True
    assert body["execution"]["image_digest"].startswith("sha256:")


def test_key_is_accepted(live_api: LiveAPI) -> None:
    response = httpx.get(
        f"{live_api.url}/api/user",
        headers={"Authorization": f"Bearer {live_api.token}"},
        timeout=30,
    )
    response.raise_for_status()
    assert response.json()["role"] in {"developer", "gateway"}
