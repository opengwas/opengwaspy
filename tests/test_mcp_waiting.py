"""MCP long jobs: progress, the wait limit, get_job_result, save_as and cancellation."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import respx
from mcp import Client as MCPClient
from mcp.types import CallToolResult

from opengwaspy.jobs import Job
from opengwaspy.mcp import create_server
from opengwaspy.mcp.files import output_dir, safe_target, save_frame
from opengwaspy.mcp.waiting import Abandoned, Watch, run_watched, wait_seconds
from tests import test_compat_associations as fake
from tests.fakes import FakeClock, JobServer, accepted, page, status
from tests.mcp_fakes import BASE, SECRET, keyed, text_of

A = fake.A
ROWS = [fake.assoc(A, f"1:{i}:A:G", f"rs{i}") for i in range(1, 4)]


@pytest.fixture(autouse=True)
def folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    out = tmp_path / "results"
    monkeypatch.setenv("OPENGWAS_MCP_OUTPUT_DIR", str(out))
    monkeypatch.setenv("OPENGWAS_MCP_WAIT_SECONDS", "5")
    return out


def steps(*calls: tuple[str, dict[str, Any]], messages: list[str] | None = None) -> list[Any]:
    """Run tool calls in one server session (the fake clock is shared across them)."""
    clock = FakeClock()
    from opengwaspy.auth import DeveloperKey
    from opengwaspy.client import Client
    from opengwaspy.config import Config
    from opengwaspy.transport import Transport

    def factory() -> Client:
        return Client(
            transport=Transport(
                Config(base_url=BASE, auth=DeveloperKey(SECRET)),
                client=httpx.Client(),
                sleep=clock.sleep,
                clock=clock.monotonic,
                wall_clock=clock.time,
            )
        )

    server = create_server(client_factory=factory)

    async def note(progress: float, total: float | None, message: str | None) -> None:
        if messages is not None:
            messages.append(message or "")

    async def main() -> list[CallToolResult]:
        async with MCPClient(server) as mcp:
            return [await mcp.call_tool(n, a, progress_callback=note) for n, a in calls]

    out: list[CallToolResult] = anyio.run(main)
    return out


class SlowJob:
    """One tophits job that stays running for ``polls`` polls (2 s apart), then succeeds."""

    def __init__(self, polls: int) -> None:
        self.polls = polls
        self.submissions = 0
        respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=fake.gwasinfo)
        respx.get(f"{BASE}/api/status").respond(json={"ready": True, "execution": {}})
        respx.post(f"{BASE}/api/tophits").mock(side_effect=self.submit)
        respx.get(f"{BASE}/api/jobs/j1").mock(side_effect=self.poll)
        respx.get(f"{BASE}/api/jobs/j1/result").respond(json=page(ROWS))
        self.cancel = respx.delete(f"{BASE}/api/jobs/j1").respond(json=status("j1", "cancelled"))

    def submit(self, request: httpx.Request) -> httpx.Response:
        self.submissions += 1
        return httpx.Response(
            202, json=accepted("j1", existing=self.submissions > 1, poll_after=2.0)
        )

    def poll(self, request: httpx.Request) -> httpx.Response:
        self.polls -= 1
        if self.polls >= 0:
            return httpx.Response(200, json=status("j1", "running", poll_after=2.0))
        return httpx.Response(200, json=status("j1", "succeeded"))


@respx.mock
def test_a_long_job_answers_running_then_get_job_result_picks_it_up() -> None:
    job = SlowJob(polls=4)
    progress: list[str] = []
    running, done = steps(
        ("top_hits", {"analysis_ids": [A], "max_rows": 2}),
        ("get_job_result", {"job_id": "j1"}),
        messages=progress,
    )
    assert not running.is_error, text_of(running)
    first = running.structured_content
    assert first is not None
    assert first["status"] == "running" and first["job_ids"] == ["j1"]
    assert first["poll_after_seconds"] == 2.0 and first["rows"] == []
    assert "get_job_result" in first["summary"]
    assert not job.cancel.called  # the job keeps running
    second = done.structured_content
    assert second is not None, text_of(done)
    assert second["status"] == "done" and second["rows_returned"] == 2  # max_rows kept
    assert job.submissions == 2  # the same query again: the API returned the same job
    assert "submitted job j1" in progress and "job j1: running" in progress
    assert any(p.startswith("job j1: read result page 1") for p in progress)


@respx.mock
def test_get_job_result_replaces_max_rows_and_saves() -> None:
    SlowJob(polls=4)
    _, done = steps(
        ("top_hits", {"analysis_ids": [A]}),
        ("get_job_result", {"job_id": "j1", "max_rows": 1, "save_as": "hits"}),
    )
    out = done.structured_content
    assert out is not None and out["rows_returned"] == 1
    assert out["saved"]["rows"] == 3 and out["saved"]["path"].endswith("hits.csv")


@respx.mock
def test_get_job_result_for_a_job_this_server_did_not_start() -> None:
    respx.get(f"{BASE}/api/status").respond(json={"ready": True, "execution": {}})
    respx.get(f"{BASE}/api/jobs/j9").respond(json=status("j9", "succeeded"))
    respx.get(f"{BASE}/api/jobs/j9/result").respond(json=page(ROWS))
    (result,) = steps(("get_job_result", {"job_id": "j9", "max_rows": 2}))
    out = result.structured_content
    assert out is not None, text_of(result)
    assert out["summary"] == "3 rows from job j9." and out["rows_returned"] == 2
    assert "z" in out["columns"]


@respx.mock
def test_an_unknown_job_still_running_answers_running() -> None:
    respx.get(f"{BASE}/api/jobs/j9").respond(json=status("j9", "running", poll_after=3.0))
    (result,) = steps(("get_job_result", {"job_id": "j9"}))
    out = result.structured_content
    assert out is not None and out["status"] == "running"


@respx.mock
def test_save_as_writes_csv_and_sidecar(folders: Path) -> None:
    respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=fake.gwasinfo)
    JobServer(BASE, fake.answer)
    (result,) = steps(
        ("associations", {"variants": ["rs500"], "analysis_ids": [A], "save_as": "my rs500!"})
    )
    out = result.structured_content
    assert out is not None, text_of(result)
    saved = out["saved"]
    assert Path(saved["path"]) == (folders / "my_rs500_.csv").resolve()
    csv = Path(saved["path"]).read_text()
    assert csv.splitlines()[0].startswith("id,") and saved["rows"] == 1
    assert saved["bytes"] == len(csv.encode())
    sidecar = json.loads(Path(saved["provenance_path"]).read_text())
    assert sidecar["tool"] == "associations" and sidecar["file"] == "my_rs500_.csv"
    assert sidecar["arguments"]["variants"] == ["rs500"] and "save_as" not in sidecar["arguments"]
    assert SECRET not in Path(saved["provenance_path"]).read_text()
    assert "Saved all 1 rows to" in out["summary"]
    (again,) = steps(
        ("associations", {"variants": ["rs500"], "analysis_ids": [A], "save_as": "my rs500!"})
    )
    assert again.is_error and "already exists" in text_of(again)
    (replaced,) = steps(
        (
            "associations",
            {"variants": ["rs500"], "analysis_ids": [A], "save_as": "my rs500!", "overwrite": True},
        )
    )
    assert not replaced.is_error


@respx.mock
def test_save_as_widens_region_and_phewas_limits() -> None:
    respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=fake.gwasinfo)
    server = JobServer(BASE, lambda e, b: [])
    region = {"chromosome": "1", "start": 1, "end": 5_000_000, "analysis_ids": [A]}
    refused, saved = steps(
        ("region_associations", region),
        ("region_associations", {**region, "save_as": "region"}),
    )
    assert refused.is_error and "10,000,000 bp with save_as" in text_of(refused)
    assert not saved.is_error, text_of(saved)
    steps(("phewas", {"variant": "rs1", "save_as": "pw"}))
    assert [b["limit"] for e, b in server.bodies if e == "/api/phewas"] == [10_000]


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", "empty"),
        ("/etc/passwd", "not a path"),
        ("~/x", "not a path"),
        ("C:evil", "not a path"),
        ("../x", "without folders"),
        ("a/b", "without folders"),
        ("a\\b", "without folders"),
        ("...", "without folders"),
        (".", "no usable characters"),
    ],
)
def test_unsafe_names_are_refused(tmp_path: Path, name: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        safe_target(name, tmp_path)


def test_names_are_cleaned_and_symlinks_refused(tmp_path: Path) -> None:
    assert safe_target("BMI hits (EUR)", tmp_path).name == "BMI_hits__EUR_.csv"
    assert safe_target("x.CSV", tmp_path).name == "x.CSV"
    outside = tmp_path / "outside.csv"
    outside.write_text("keep")
    (tmp_path / "link.csv").symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic link"):
        safe_target("link", tmp_path, overwrite=True)
    (tmp_path / "side.json").symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic link"):
        safe_target("side", tmp_path, overwrite=True)
    assert outside.read_text() == "keep"


def test_save_frame_replaces_only_with_overwrite(tmp_path: Path) -> None:
    import pandas as pd

    frame = pd.DataFrame({"a": [1, 2]})
    first = save_frame(frame, "t", {"tool": "x"}, folder=tmp_path)
    assert first.rows == 2 and Path(first.path).read_text() == "a\n1\n2\n"
    with pytest.raises(ValueError, match="already exists"):
        save_frame(frame, "t", {}, folder=tmp_path)
    save_frame(frame.head(1), "t", {}, folder=tmp_path, overwrite=True)
    assert Path(first.path).read_text() == "a\n1\n"
    assert not [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]


def test_output_dir_and_wait_seconds() -> None:
    assert output_dir({}).name == "opengwas-results"
    assert output_dir({"OPENGWAS_MCP_OUTPUT_DIR": "/data/x"}) == Path("/data/x")
    assert wait_seconds({}) == 60.0
    assert wait_seconds({"OPENGWAS_MCP_WAIT_SECONDS": "15"}) == 15.0
    assert wait_seconds({"OPENGWAS_MCP_WAIT_SECONDS": "-3"}) == 0.0
    assert wait_seconds({"OPENGWAS_MCP_WAIT_SECONDS": "soon"}) == 60.0


@respx.mock
def test_cancelling_the_call_cancels_its_jobs() -> None:
    respx.post(f"{BASE}/api/tophits").respond(202, json=accepted("j1", poll_after=0))
    respx.get(f"{BASE}/api/jobs/j1").respond(json=status("j1", "running"))
    cancel = respx.delete(f"{BASE}/api/jobs/j1").respond(json=status("j1", "cancelled"))
    client = keyed()
    watch = Watch(time.monotonic, time.monotonic() + 60)
    stopped: list[BaseException] = []

    def work() -> None:
        job = Job.submit(client.transport, "/api/tophits", {"analyses": [A]})
        try:
            while True:
                time.sleep(0.01)
                job.status()
        except Abandoned as exc:
            stopped.append(exc)
            raise

    async def main() -> None:
        with anyio.move_on_after(0.3):
            await run_watched(watch, work)
        await anyio.sleep(0.1)  # let the abandoned thread notice

    anyio.run(main)
    assert watch.cancelled and cancel.called
    assert stopped and isinstance(stopped[0], Abandoned)


def test_watch_stops_only_unfinished_jobs_at_the_limit() -> None:
    from opengwaspy.batch import BatchError
    from opengwaspy.jobs import JobStatus, JobTimeout

    clock = FakeClock()
    watch = Watch(clock.monotonic, clock.monotonic() + 1)
    finished = JobStatus(status("j1", "succeeded"))
    running = JobStatus(status("j1", "running", poll_after=3.0))
    dummy: Any = type("J", (), {"job_id": "j1", "existing": False})()
    clock.now += 2
    watch.polled(dummy, finished)
    assert not watch.timed_out
    with pytest.raises(JobTimeout):
        watch.polled(dummy, running)
    assert watch.timed_out and watch.poll_after == 3.0
    assert watch.stopped_by_limit(BatchError({0: JobTimeout("j1", "running", 0)}, [None]))
    assert not watch.stopped_by_limit(BatchError({0: ValueError("x")}, [None]))
    assert not watch.stopped_by_limit(ValueError("x"))
    watch.cancelled = True
    for step in (lambda: watch.submitted(dummy), lambda: watch.page(dummy, None)):
        with pytest.raises(Abandoned):
            step()


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("top_hits", {"analysis_ids": [A]}),
        ("associations", {"variants": ["rs1"], "analysis_ids": [A]}),
        ("associations", {"variants": ["1:100:A:G"], "analysis_ids": [A], "proxies": True}),
        ("region_associations", {"chromosome": "1", "start": 1, "end": 10, "analysis_ids": [A]}),
        ("phewas", {"variant": "rs1"}),
        ("variant_info", {"variants": ["rs1"]}),
        ("ld_proxies", {"variants": ["1:1:A:G"]}),
        ("ld_matrix", {"variants": ["1:1:A:G"]}),
    ],
)
@respx.mock
def test_every_job_backed_tool_answers_running(tool: str, args: dict[str, Any]) -> None:
    respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=fake.gwasinfo)
    respx.get(f"{BASE}/api/status").respond(json={"ready": True, "execution": {}})
    respx.get(f"{BASE}/api/batches").respond(
        json={"batches": [{"store_id": "OGS-1", "release_id": "r1"}]}
    )
    respx.get(f"{BASE}/api/ld/stores").respond(json={"stores": [{"ancestry": "EUR"}]})
    respx.post(url__regex=rf"{BASE}/api/(?!jobs).*").respond(
        202, json=accepted("j1", poll_after=2.0)
    )
    respx.get(f"{BASE}/api/jobs/j1").respond(json=status("j1", "queued", poll_after=2.0))
    (result,) = steps((tool, args))
    out = result.structured_content
    assert out is not None, text_of(result)
    assert out["status"] == "running" and out["job_ids"] == ["j1"]
