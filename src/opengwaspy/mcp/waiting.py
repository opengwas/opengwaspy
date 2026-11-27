"""Long jobs in MCP tools: progress, a wait limit, resuming, and cancellation.

A tool runs opengwaspy's query functions under a :class:`Watch`, which sees
every job they submit, poll and read (through :func:`opengwaspy.jobs.observe`):

- each step is reported to the assistant as progress;
- once the wait limit has passed, the next poll of an unfinished job stops the
  call, and the tool answers ``status: running`` with the job IDs, rather than
  an error; the jobs keep running;
- ``get_job_result`` with any of those job IDs runs the same tool call again.
  The API answers a repeated query with the job it already has, so the call
  picks up the same jobs, or their finished results;
- if the assistant cancels the call, the call's unfinished jobs are cancelled
  on the API (``DELETE /api/jobs/{id}``).
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

import anyio
import anyio.from_thread
import anyio.to_thread

from opengwaspy.batch import BatchError
from opengwaspy.errors import OpenGWASError
from opengwaspy.jobs import Job, JobStatus, JobTimeout, ResultPage, observe

__all__ = ["DEFAULT_WAIT_SECONDS", "Abandoned", "Watch", "wait_seconds"]

log = logging.getLogger(__name__)

T = TypeVar("T")

#: Seconds a tool waits for its jobs before answering ``status: running``.
DEFAULT_WAIT_SECONDS = 60.0


def wait_seconds(environ: Mapping[str, str] | None = None) -> float:
    """The wait limit: ``OPENGWAS_MCP_WAIT_SECONDS``, or 60."""
    env = os.environ if environ is None else environ
    value = env.get("OPENGWAS_MCP_WAIT_SECONDS")
    if not value:
        return DEFAULT_WAIT_SECONDS
    try:
        seconds = float(value)
    except ValueError:
        log.warning("OPENGWAS_MCP_WAIT_SECONDS=%r is not a number; using 60", value)
        return DEFAULT_WAIT_SECONDS
    return max(seconds, 0.0)


class Abandoned(BaseException):
    """Stops a call's worker thread after the assistant cancelled the call.

    A ``BaseException``, so opengwaspy's handlers of API errors let it through.
    """


Reporter = Callable[[str], None]


@dataclass
class Watch:
    """Sees one tool call's jobs; stops the call at the wait limit, or when cancelled.

    Attributes:
        clock: A monotonic clock, in seconds.
        deadline: When to stop waiting, on ``clock``.
        report: Called with a message at each step.
        jobs: Every job the call submitted or polled, in order.
        timed_out: The wait limit stopped the call.
        cancelled: The assistant cancelled the call.
    """

    clock: Callable[[], float]
    deadline: float
    report: Reporter = field(default=lambda message: None)
    jobs: list[Job] = field(default_factory=list)
    timed_out: bool = False
    cancelled: bool = False
    poll_after: float | None = None

    @property
    def job_ids(self) -> list[str]:
        """The IDs of the call's jobs, in order, each once."""
        return list(dict.fromkeys(job.job_id for job in self.jobs))

    def submitted(self, job: Job) -> None:
        """Record a job, and report it."""
        if self.cancelled:
            raise Abandoned
        self.jobs.append(job)
        known = " (the API already had it)" if job.existing else ""
        self.report(f"submitted job {job.job_id}{known}")

    def polled(self, job: Job, status: JobStatus) -> None:
        """Report a status; stop if cancelled, or if the job is unfinished at the limit."""
        if self.cancelled:
            raise Abandoned
        if all(seen is not job for seen in self.jobs):  # picked up by ID, not submitted
            self.jobs.append(job)
        position = status.raw.get("queue_position")
        where = f", position {position} in the queue" if position is not None else ""
        self.report(f"job {job.job_id}: {status.status}{where}")
        if not status.finished and self.clock() >= self.deadline:
            self.timed_out = True
            self.poll_after = status.poll_after
            raise JobTimeout(job.job_id, status.status, 0)

    def page(self, job: Job, page: ResultPage) -> None:
        """Report a page read."""
        if self.cancelled:
            raise Abandoned
        pages = page.manifest.get("page_count") if page.manifest else None
        of = f" of {pages}" if pages else ""
        self.report(f"job {job.job_id}: read result page {page.page_index + 1}{of}")

    def cancel_jobs(self) -> None:
        """Cancel the call's jobs on the API (a finished job is left as it is)."""
        for job in self.jobs:
            with contextlib.suppress(OpenGWASError):
                job.cancel()

    def stopped_by_limit(self, exc: BaseException) -> bool:
        """Whether ``exc`` is the wait limit stopping the call."""
        if not self.timed_out:
            return False
        if isinstance(exc, JobTimeout):
            return True
        return isinstance(exc, BatchError) and all(
            isinstance(e, JobTimeout) for e in exc.errors.values()
        )


def progress_reporter(ctx: Any) -> Reporter:
    """Report progress through the MCP context, from a worker thread."""
    count = 0

    def report(message: str) -> None:
        nonlocal count
        count += 1
        try:
            anyio.from_thread.run(ctx.report_progress, count, None, message)
        except Exception:  # progress is best effort  # pragma: no cover
            log.debug("could not report progress", exc_info=True)

    return report


async def run_watched(watch: Watch, fn: Callable[[], T]) -> T:
    """Run ``fn`` in a worker thread under ``watch``.

    If the awaiting task is cancelled, the call's jobs are cancelled on the API,
    and the worker thread stops at its next step.
    """

    def run() -> T:
        with observe(watch):
            return fn()

    try:
        return await anyio.to_thread.run_sync(run, abandon_on_cancel=True)
    except anyio.get_cancelled_exc_class():
        watch.cancelled = True
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(watch.cancel_jobs)
        raise
