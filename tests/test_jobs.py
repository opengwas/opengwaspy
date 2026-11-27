import json

import httpx
import pytest
import respx

from opengwaspy.auth import DeveloperKey
from opengwaspy.config import Config
from opengwaspy.errors import IgnoredFieldsError, JobFailed, ProtocolError, ResultExpired
from opengwaspy.jobs import Job, JobStatus, JobTimeout, ResultPage
from opengwaspy.transport import Transport
from tests.fakes import FakeClock, accepted, page, status

BASE = "http://api.test"
ROWS = [{"alid": f"1:{i}:A:G", "z": float(i)} for i in range(3)]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def transport(clock: FakeClock) -> Transport:
    return Transport(
        Config(base_url=BASE, auth=DeveloperKey("k")),
        client=httpx.Client(),
        sleep=clock.sleep,
        clock=clock.monotonic,
        wall_clock=clock.time,
        jitter=lambda: 0.5,
    )


def ok(body: object, **headers: str) -> httpx.Response:
    return httpx.Response(200, json=body, headers=headers)


@respx.mock
def test_submit_poll_and_read_pages(transport: Transport, clock: FakeClock) -> None:
    submit = respx.post(f"{BASE}/api/tophits").respond(202, json=accepted("j1"))
    respx.get(f"{BASE}/api/jobs/j1").mock(
        side_effect=[
            ok(status("j1", "queued", poll_after=2.0)),
            ok(status("j1", "running", poll_after=0.1)),
            ok(status("j1", "succeeded")),
        ]
    )
    result = respx.get(f"{BASE}/api/jobs/j1/result").mock(
        side_effect=[ok(page(ROWS[:2], next_cursor="c2")), ok(page(ROWS[2:], index=1, offset=2))]
    )
    seen: list[str] = []
    job = Job.submit(transport, "/api/tophits", {"analyses": ["a"]})
    assert json.loads(submit.calls.last.request.content) == {"analyses": ["a"]}
    assert job.job_id == "j1" and job.query_hash == "sha256:j1" and not job.existing
    job.wait(progress=lambda s: seen.append(s.status))
    assert seen == ["queued", "running", "succeeded"]
    # First wait is the submission's 0.3 s, then the API's 2.0, then the 0.25 floor.
    assert clock.sleeps == [0.3, 2.0, 0.25]
    frame = job.to_frame()
    assert list(frame["alid"]) == [r["alid"] for r in ROWS]
    assert result.calls[1].request.url.params["cursor"] == "c2"
    assert frame.attrs["job_id"] == "j1"
    assert frame.attrs["metadata"] == {"total": 3, "truncated": False}
    assert frame.attrs["releases"] == [{"store_id": "OGS-1", "release_id": "r1"}]
    assert frame.attrs["release_id"] == "OGS-1/r1"
    assert frame.attrs["compute"] == {"cpu_seconds": 0.5}
    assert frame.attrs["endpoint"] == "/api/tophits"
    assert "succeeded" in repr(job)


@respx.mock
def test_existing_job_and_ignored_fields(transport: Transport) -> None:
    respx.post(f"{BASE}/api/tophits").mock(
        side_effect=[
            httpx.Response(202, json=accepted("j1", existing=True)),
            httpx.Response(202, json=accepted("j2", ignored=["observed_onyl"])),
            httpx.Response(202, json={"status": "queued"}),
        ]
    )
    assert Job.submit(transport, "api/tophits", {}).existing
    with pytest.raises(IgnoredFieldsError) as info:
        Job.submit(transport, "api/tophits", {"observed_onyl": True})
    assert info.value.fields == ["observed_onyl"]
    with pytest.raises(ProtocolError, match="did not return a job"):
        Job.submit(transport, "api/tophits", {})


@respx.mock
@pytest.mark.parametrize(
    ("state", "kind", "retryable"),
    [
        ("failed", "temporary", True),
        ("failed", "request", False),
        ("cancelled", None, False),
        ("expired", None, False),
    ],
)
def test_job_that_does_not_succeed(
    transport: Transport, state: str, kind: str | None, retryable: bool
) -> None:
    respx.get(f"{BASE}/api/jobs/j1").respond(
        json=status("j1", state, error="store timed out" if kind else None, error_kind=kind)
    )
    with pytest.raises(JobFailed) as info:
        Job.from_id(transport, "j1").wait()
    assert info.value.status == state
    assert info.value.retryable is retryable


@respx.mock
def test_timeout_leaves_job_running(transport: Transport) -> None:
    respx.get(f"{BASE}/api/jobs/j1").respond(json=status("j1", "running", poll_after=5.0))
    with pytest.raises(JobTimeout, match=r"Job.from_id\('j1'\)"):
        Job.from_id(transport, "j1").wait(timeout=12)


@respx.mock
def test_interrupt_cancels(transport: Transport) -> None:
    respx.get(f"{BASE}/api/jobs/j1").respond(json=status("j1", "running", poll_after=1.0))
    cancel = respx.delete(f"{BASE}/api/jobs/j1").respond(json=status("j1", "cancelled"))

    def interrupt(_: JobStatus) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        Job.from_id(transport, "j1").wait(progress=interrupt)
    assert cancel.called
    with pytest.raises(KeyboardInterrupt):
        Job.from_id(transport, "j1").wait(progress=interrupt, cancel_on_interrupt=False)
    assert cancel.call_count == 1


@respx.mock
def test_cancel(transport: Transport) -> None:
    respx.delete(f"{BASE}/api/jobs/j1").respond(json=status("j1", "cancelled"))
    assert Job.from_id(transport, "j1").cancel().status == "cancelled"


@respx.mock
def test_from_id_learns_endpoint_and_reads(transport: Transport) -> None:
    respx.get(f"{BASE}/api/jobs/j9").respond(json=status("j9", "succeeded"))
    respx.get(f"{BASE}/api/jobs/j9/result").respond(json=page(ROWS))
    job = Job.from_id(transport, "j9")
    assert repr(job) == "Job('j9', endpoint=None, status='unknown')"
    assert len(job.to_frame()) == 3
    assert job.endpoint == "/api/tophits"
    assert job.query_hash == "sha256:j9"


@respx.mock
def test_expired_result_is_resubmitted_once_without_repeats(transport: Transport) -> None:
    respx.post(f"{BASE}/api/tophits").mock(
        side_effect=[
            httpx.Response(202, json=accepted("j1", poll_after=0)),
            httpx.Response(202, json=accepted("j2", poll_after=0)),
        ]
    )
    respx.get(f"{BASE}/api/jobs/j1").respond(json=status("j1", "succeeded"))
    respx.get(f"{BASE}/api/jobs/j2").respond(json=status("j2", "succeeded"))
    expired = httpx.Response(410, json={"error": "result_expired", "message": "gone"})
    respx.get(f"{BASE}/api/jobs/j1/result").mock(
        side_effect=[ok(page(ROWS[:2], next_cursor="c2")), expired]
    )
    respx.get(f"{BASE}/api/jobs/j2/result").respond(json=page(ROWS))
    job = Job.submit(transport, "api/tophits", {"analyses": ["a"]})
    frame = job.to_frame()
    assert list(frame["alid"]) == [r["alid"] for r in ROWS]
    assert job.job_id == "j2"
    assert frame.attrs["job_id"] == "j2"


@respx.mock
def test_expired_twice_or_unknown_query_raises(transport: Transport) -> None:
    expired = httpx.Response(410, json={"error": "result_expired", "message": "gone"})
    respx.get(f"{BASE}/api/jobs/j1").respond(json=status("j1", "succeeded"))
    respx.get(f"{BASE}/api/jobs/j1/result").mock(return_value=expired)
    with pytest.raises(ResultExpired):
        list(Job.from_id(transport, "j1").rows())
    respx.post(f"{BASE}/api/tophits").respond(202, json=accepted("j1", poll_after=0))
    with pytest.raises(ResultExpired):
        list(Job.submit(transport, "api/tophits", {}).rows())


@respx.mock
def test_empty_result(transport: Transport) -> None:
    respx.get(f"{BASE}/api/jobs/j1").respond(json=status("j1", "succeeded"))
    respx.get(f"{BASE}/api/jobs/j1/result").respond(json=page([]))
    frame = Job.from_id(transport, "j1").to_frame()
    assert frame.empty and frame.attrs["job_id"] == "j1"


def test_page_checks() -> None:
    good = page(ROWS)
    assert ResultPage.parse(good).rows == ROWS
    assert ResultPage.parse({**good, "sha256": "sha256:" + str(good["sha256"])}).final
    with pytest.raises(ProtocolError, match="checksum mismatch"):
        ResultPage.parse({**good, "sha256": "0" * 64})
    with pytest.raises(ProtocolError, match="missing"):
        ResultPage.parse({"ndjson": ""})
    bad = {**good, "ndjson": "{nope\n", "sha256": ""}
    with pytest.raises(ProtocolError, match="invalid NDJSON"):
        ResultPage.parse(bad)


@respx.mock
def test_non_final_page_without_cursor(transport: Transport) -> None:
    respx.get(f"{BASE}/api/jobs/j1").respond(json=status("j1", "succeeded"))
    broken = {**page(ROWS), "final": False}
    respx.get(f"{BASE}/api/jobs/j1/result").respond(json=broken)
    with pytest.raises(ProtocolError, match="no next cursor"):
        list(Job.from_id(transport, "j1").rows())


def test_status_defaults() -> None:
    s = JobStatus({"job_id": "j", "status": "running"})
    assert s.job_id == "j"
    assert (s.poll_after, s.result, s.metadata, s.finished) == (0.0, {}, {}, False)


def declared(pages: int, rows: int) -> dict[str, object]:
    return {"releases": [], "page_count": pages, "total_rows": rows, "row_count": rows}


def finished_job(transport: Transport, manifest: dict[str, object] | None) -> Job:
    body = status("j1", "succeeded")
    if manifest is not None:
        body["result"]["manifest"] = manifest  # type: ignore[index]
    respx.get(f"{BASE}/api/jobs/j1").respond(json=body)
    return Job.from_id(transport, "j1")


def with_manifest(body: dict[str, object], manifest: dict[str, object]) -> dict[str, object]:
    return {**body, "manifest": manifest}


@respx.mock
def test_valid_multi_page_result_matches_its_manifest(transport: Transport) -> None:
    respx.get(f"{BASE}/api/jobs/j1/result").mock(
        side_effect=[ok(page(ROWS[:2], next_cursor="c2")), ok(page(ROWS[2:], index=1, offset=2))]
    )
    frame = finished_job(transport, declared(2, 3)).to_frame()
    assert len(frame) == 3


@respx.mock
def test_empty_result_with_declared_counts(transport: Transport) -> None:
    respx.get(f"{BASE}/api/jobs/j1/result").respond(json=page([]))
    assert finished_job(transport, declared(1, 0)).to_frame().empty


@respx.mock
def test_premature_final_page_is_refused(transport: Transport) -> None:
    # A checksum-valid first page marked final, though two pages and three rows are declared.
    respx.get(f"{BASE}/api/jobs/j1/result").respond(json=page(ROWS[:1]))
    with pytest.raises(ProtocolError, match="ended after 1 pages, but its manifest declares 2"):
        finished_job(transport, declared(2, 3)).to_frame()


@respx.mock
def test_manifest_on_the_page_is_used_when_the_status_has_none(transport: Transport) -> None:
    respx.get(f"{BASE}/api/jobs/j1/result").respond(
        json=with_manifest(page(ROWS[:2]), declared(1, 3))
    )
    with pytest.raises(ProtocolError, match="holds 2 rows, but its manifest declares 3"):
        finished_job(transport, None).to_frame()


@pytest.mark.parametrize(
    ("second", "message"),
    [
        (page(ROWS[2:], index=2, offset=2), "expected result page 1, got page 2"),
        (page(ROWS[:2], index=0, offset=0), "expected result page 1, got page 0"),
        (page(ROWS[2:], index=1, offset=5), "starts at row 5, expected row 2"),
        (page(ROWS[2:], index=1, offset=2, next_cursor="c3"), "more than the 2 pages"),
    ],
)
@respx.mock
def test_gaps_repeats_and_overruns_are_refused(
    transport: Transport, second: dict[str, object], message: str
) -> None:
    respx.get(f"{BASE}/api/jobs/j1/result").mock(
        side_effect=[
            ok(page(ROWS[:2], next_cursor="c2")),
            ok(second),
            ok(page([], index=2, offset=3)),
        ]
    )
    with pytest.raises(ProtocolError, match=message):
        finished_job(transport, declared(2, 3)).to_frame()


@respx.mock
def test_without_declared_counts_only_the_sequence_is_checked(transport: Transport) -> None:
    respx.get(f"{BASE}/api/jobs/j1/result").mock(
        side_effect=[ok(page(ROWS[:2], next_cursor="c2")), ok(page(ROWS[2:], index=1, offset=2))]
    )
    assert len(finished_job(transport, {"releases": [], "page_count": "2"}).to_frame()) == 3


def test_declared_counts_of_no_manifest() -> None:
    from opengwaspy.jobs import _declared_counts

    assert _declared_counts(None) == (None, None)
    assert _declared_counts({"row_count": 4, "page_count": True}) == (None, 4)


@respx.mock
def test_timeout_is_a_deadline_not_a_minimum(transport: Transport, clock: FakeClock) -> None:
    # The submission suggests a 20 s first poll; the caller allows 1 s (#80).
    respx.post(f"{BASE}/api/tophits").respond(202, json=accepted("j1", poll_after=20.0))
    respx.get(f"{BASE}/api/jobs/j1").mock(
        side_effect=[ok(status("j1", "running", poll_after=20.0)), ok(status("j1", "succeeded"))]
    )
    job = Job.submit(transport, "/api/tophits", {"analyses": ["a"]})
    started = clock.now
    with pytest.raises(JobTimeout, match="still running after 1 s"):
        job.wait(timeout=1)
    # It polled at the deadline, not after the suggested 20 s, and did not poll again.
    assert clock.now - started == pytest.approx(1.0)
    assert clock.sleeps == [1.0]


@respx.mock
def test_late_success_is_a_timeout_and_the_job_is_not_cancelled(
    transport: Transport, clock: FakeClock
) -> None:
    def slow_status(request: httpx.Request) -> httpx.Response:
        clock.now += 5.0  # the status call itself takes 5 s
        return ok(status("j1", "succeeded"))

    respx.get(f"{BASE}/api/jobs/j1").mock(side_effect=slow_status)
    cancel = respx.delete(f"{BASE}/api/jobs/j1").respond(json=status("j1", "cancelled"))
    with pytest.raises(JobTimeout, match="still succeeded"):
        Job.from_id(transport, "j1").wait(timeout=2)
    assert not cancel.called


@respx.mock
def test_deadline_bounds_every_sleep(transport: Transport, clock: FakeClock) -> None:
    respx.get(f"{BASE}/api/jobs/j1").respond(json=status("j1", "running", poll_after=5.0))
    with pytest.raises(JobTimeout, match="still running"):
        Job.from_id(transport, "j1").wait(timeout=12)
    assert clock.sleeps == [5.0, 5.0, 2.0]


@respx.mock
def test_success_within_the_deadline(transport: Transport, clock: FakeClock) -> None:
    respx.get(f"{BASE}/api/jobs/j1").mock(
        side_effect=[ok(status("j1", "running", poll_after=1.0)), ok(status("j1", "succeeded"))]
    )
    assert Job.from_id(transport, "j1").wait(timeout=1).status == "succeeded"
    assert clock.sleeps == [1.0]


@respx.mock
def test_zero_timeout_never_sleeps(transport: Transport, clock: FakeClock) -> None:
    respx.post(f"{BASE}/api/tophits").respond(202, json=accepted("j1", poll_after=2.0))
    job = Job.submit(transport, "/api/tophits", {"analyses": ["a"]})
    with pytest.raises(JobTimeout, match="still queued after 0 s"):
        job.wait(timeout=0)
    assert clock.sleeps == []
