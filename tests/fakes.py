"""Test doubles shared by the unit tests."""

from __future__ import annotations


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
