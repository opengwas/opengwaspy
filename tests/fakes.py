"""Test doubles shared by the unit tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from opengwaspy.client import Client


class FakeClock:
    """A clock that only moves when something sleeps."""

    def __init__(self, start: float = 1000.0, wall: float = 1_800_000_000.0) -> None:
        self.now = start
        self.wall = wall
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.wall

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        self.wall += seconds


def page(
    rows: list[dict[str, object]],
    *,
    index: int = 0,
    offset: int = 0,
    next_cursor: str | None = None,
) -> dict[str, object]:
    """A result page as the API sends it, with a correct checksum."""
    import hashlib
    import json

    text = "".join(json.dumps(row) + "\n" for row in rows)
    return {
        "schema": "ogdb.result.ndjson.v1",
        "manifest": {"releases": [{"store_id": "OGS-1", "release_id": "r1"}]},
        "page_index": index,
        "row_offset": offset,
        "row_count": len(rows),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "cursor": None,
        "next_cursor": next_cursor,
        "final": next_cursor is None,
        "ndjson": text,
    }


def status(
    job_id: str, state: str, *, poll_after: float = 0.0, **extra: object
) -> dict[str, object]:
    """A job status document."""
    body: dict[str, object] = {
        "job_id": job_id,
        "query_hash": f"sha256:{job_id}",
        "status": state,
        "endpoint": "/api/tophits",
        "status_url": f"/api/jobs/{job_id}",
        "poll_after_seconds": poll_after,
        "error": None,
        "error_kind": None,
        "result": None,
        "compute": None,
    }
    if state == "succeeded":
        body["result"] = {
            "release_id": "OGS-1/r1",
            "manifest": {"releases": [{"store_id": "OGS-1", "release_id": "r1"}]},
            "result_url": f"/api/jobs/{job_id}/result",
            "metadata": {"total": 3, "truncated": False},
        }
        body["compute"] = {"cpu_seconds": 0.5}
    body.update(extra)
    return body


def accepted(
    job_id: str,
    *,
    existing: bool = False,
    ignored: list[str] | None = None,
    poll_after: float = 0.3,
) -> dict[str, object]:
    """A JobAccepted document."""
    return {
        "job_id": job_id,
        "status_url": f"/api/jobs/{job_id}",
        "status": "queued",
        "query_hash": f"sha256:{job_id}",
        "existing": existing,
        "queue_position": None,
        "poll_after_seconds": poll_after,
        "ignored_fields": ignored or [],
    }


class JobServer:
    """A fake Data API: each submission becomes a job whose rows come from ``answer``.

    ``answer(endpoint, body)`` returns the rows for a submitted body. Jobs succeed
    at the first poll. ``bodies`` records every submitted body, in order.
    """

    def __init__(
        self,
        base: str,
        answer: Callable[[str, dict[str, Any]], list[dict[str, Any]]],
        *,
        limits: dict[str, int] | None = None,
        batches: list[dict[str, str]] | None = None,
        metadata: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        import json

        import httpx
        import respx

        self.bodies: list[tuple[str, dict[str, Any]]] = []
        self._rows: dict[str, list[dict[str, object]]] = {}
        self._meta: dict[str, dict[str, object]] = {}

        def submit(request: httpx.Request) -> httpx.Response:
            endpoint = request.url.path
            body = json.loads(request.content)
            self.bodies.append((endpoint, body))
            job = f"j{len(self.bodies)}"
            self._rows[job] = list(answer(endpoint, body))
            self._meta[job] = metadata(endpoint, body) if metadata else {}
            return httpx.Response(202, json=accepted(job, poll_after=0))

        def poll(request: httpx.Request, job: str) -> httpx.Response:
            body = status(job, "succeeded")
            body["result"]["metadata"] = self._meta[job]  # type: ignore[index]
            return httpx.Response(200, json=body)

        def result(request: httpx.Request, job: str) -> httpx.Response:
            return httpx.Response(200, json=page(self._rows[job]))

        respx.get(f"{base}/api/status").respond(
            json={
                "ready": True,
                "execution": {"image_digest": "sha256:test", "limits": limits or {}},
            }
        )
        respx.get(f"{base}/api/batches").respond(
            json={"batches": batches or [{"store_id": "OGS-1", "release_id": "OGS-1-r1"}]}
        )
        respx.post(url__regex=rf"{base}/api/(?!jobs).*").mock(side_effect=submit)
        respx.get(url__regex=rf"{base}/api/jobs/(?P<job>\w+)$").mock(side_effect=poll)
        respx.get(url__regex=rf"{base}/api/jobs/(?P<job>\w+)/result").mock(side_effect=result)


def fake_client(base: str = "http://api.test") -> Client:
    """A Client with a fake clock, for tests."""
    import httpx

    from opengwaspy.auth import DeveloperKey
    from opengwaspy.config import Config
    from opengwaspy.transport import Transport

    clock = FakeClock()
    transport = Transport(
        Config(base_url=base, auth=DeveloperKey("k")),
        client=httpx.Client(),
        sleep=clock.sleep,
        clock=clock.monotonic,
        wall_clock=clock.time,
    )
    return Client(transport=transport)
