import httpx
import pytest
import respx

from opengwaspy.auth import DeveloperKey
from opengwaspy.batch import BatchError, Progress, run_many
from opengwaspy.config import Config
from opengwaspy.errors import JobFailed, RequestError
from opengwaspy.transport import Transport
from tests.fakes import FakeClock, accepted, page, status

BASE = "http://api.test"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def transport(clock: FakeClock) -> Transport:
    return Transport(
        Config(base_url=BASE, auth=DeveloperKey("k"), max_in_flight=2),
        client=httpx.Client(),
        sleep=clock.sleep,
        clock=clock.monotonic,
        wall_clock=clock.time,
        jitter=lambda: 0.5,
    )


class FakeAPI:
    """Jobs that finish after a set number of polls, tracking how many are in flight."""

    def __init__(
        self,
        polls: dict[str, int],
        fail: frozenset[str] = frozenset(),
        interrupt: frozenset[str] = frozenset(),
        cancel_status: int = 200,
    ) -> None:
        self.polls = dict(polls)
        self.fail = fail
        self.interrupt = interrupt
        self.cancel_status = cancel_status
        self.in_flight: set[str] = set()
        self.peak = 0
        self.cancelled: list[str] = []

    def submit(self, request: httpx.Request) -> httpx.Response:
        name = request.read().decode().split('"')[3]
        if name == "bad":
            return httpx.Response(404, json={"error": "analysis_not_found", "message": "bad"})
        self.in_flight.add(name)
        self.peak = max(self.peak, len(self.in_flight))
        return httpx.Response(202, json=accepted(name, poll_after=1.0))

    def poll(self, request: httpx.Request, job: str) -> httpx.Response:
        if job in self.interrupt:
            raise KeyboardInterrupt
        self.polls[job] -= 1
        if self.polls[job] > 0:
            return httpx.Response(200, json=status(job, "running", poll_after=2.0))
        self.in_flight.discard(job)
        if job in self.fail:
            return httpx.Response(
                200, json=status(job, "failed", error="boom", error_kind="request")
            )
        return httpx.Response(200, json=status(job, "succeeded"))

    def result(self, request: httpx.Request, job: str) -> httpx.Response:
        return httpx.Response(200, json=page([{"job": job}]))

    def cancel(self, request: httpx.Request, job: str) -> httpx.Response:
        self.cancelled.append(job)
        if self.cancel_status != 200:
            return httpx.Response(self.cancel_status, json={"error": "not_found", "message": "x"})
        return httpx.Response(200, json=status(job, "cancelled"))

    def install(self) -> None:
        respx.post(f"{BASE}/api/tophits").mock(side_effect=self.submit)
        respx.get(url__regex=rf"{BASE}/api/jobs/(?P<job>\w+)$").mock(side_effect=self.poll)
        respx.get(url__regex=rf"{BASE}/api/jobs/(?P<job>\w+)/result").mock(side_effect=self.result)
        respx.delete(url__regex=rf"{BASE}/api/jobs/(?P<job>\w+)$").mock(side_effect=self.cancel)


def queries(*names: str) -> list[tuple[str, dict[str, list[str]]]]:
    return [("api/tophits", {"analyses": [name]}) for name in names]


@respx.mock
def test_results_in_order_with_bounded_concurrency(transport: Transport) -> None:
    api = FakeAPI({"a": 3, "b": 1, "c": 2, "d": 1, "e": 1})
    api.install()
    seen: list[Progress] = []
    frames = run_many(transport, queries("a", "b", "c", "d", "e"), progress=seen.append)
    assert [f.iloc[0]["job"] for f in frames if f is not None] == ["a", "b", "c", "d", "e"]
    assert api.peak == 2
    assert [p.done for p in seen] == [1, 2, 3, 4, 5]
    assert seen[-1] == Progress(done=5, failed=0, running=0, total=5)
    assert frames[0] is not None and frames[0].attrs["job_id"] == "a"


@respx.mock
def test_failures_are_collected(transport: Transport) -> None:
    api = FakeAPI({"a": 1, "c": 2}, fail=frozenset({"c"}))
    api.install()
    with pytest.raises(BatchError) as info:
        run_many(transport, queries("a", "bad", "c"))
    assert set(info.value.errors) == {1, 2}
    assert isinstance(info.value.errors[1], RequestError)
    assert isinstance(info.value.errors[2], JobFailed)
    assert info.value.frames[0] is not None and info.value.frames[2] is None
    assert "2 of 3 queries failed; the first, query 1" in str(info.value)


@respx.mock
def test_failures_can_be_returned_as_none(transport: Transport) -> None:
    FakeAPI({"a": 1}).install()
    frames = run_many(transport, queries("bad", "a"), raise_errors=False, max_in_flight=1)
    assert frames[0] is None and frames[1] is not None
    assert run_many(transport, queries("bad"), raise_errors=False) == [None]


@respx.mock
def test_interrupt_cancels_jobs_in_flight(transport: Transport) -> None:
    api = FakeAPI({"a": 5, "b": 5, "c": 5}, interrupt=frozenset({"b"}))
    api.install()
    with pytest.raises(KeyboardInterrupt):
        run_many(transport, queries("a", "b", "c"))
    assert sorted(api.cancelled) == ["a", "b"]


@respx.mock
def test_cancel_errors_are_ignored_on_interrupt(transport: Transport) -> None:
    api = FakeAPI({"a": 5}, interrupt=frozenset({"a"}), cancel_status=404)
    api.install()
    with pytest.raises(KeyboardInterrupt):
        run_many(transport, queries("a"))
    assert api.cancelled == ["a"]


def test_empty_batch_and_bad_limit(transport: Transport) -> None:
    assert run_many(transport, []) == []
    with pytest.raises(ValueError):
        run_many(transport, queries("a"), max_in_flight=-1)
