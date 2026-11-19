"""Run many queries as jobs, a few at a time, and gather their results in order.

The API gives each user a share of the queue. Submitting hundreds of jobs at
once only makes them wait, or be refused with ``429 user_queue_full``.
:func:`run_many` keeps at most ``max_in_flight`` jobs queued or running
(``Config.max_in_flight``, default 4), reads each result as soon as its job
finishes, and returns the results in the order of the queries.
"""

from __future__ import annotations

import contextlib
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from opengwaspy.errors import JobFailed, OpenGWASError
from opengwaspy.jobs import MIN_POLL, Job
from opengwaspy.transport import Transport

__all__ = ["BatchError", "Progress", "Query", "run_many"]

#: One query: the API path and the request body.
Query = tuple[str, Mapping[str, Any]]


@dataclass(frozen=True)
class Progress:
    """How far a batch has got.

    Attributes:
        done: Queries finished, successfully or not.
        failed: Queries that failed.
        running: Jobs queued or running now.
        total: Queries in the batch.
    """

    done: int
    failed: int
    running: int
    total: int


class BatchError(OpenGWASError):
    """Some queries in a batch failed.

    Attributes:
        errors: The error of each failed query, by its position in the batch.
        frames: The results, by position; ``None`` where the query failed.
    """

    def __init__(self, errors: dict[int, Exception], frames: list[pd.DataFrame | None]) -> None:
        self.errors = errors
        self.frames = frames
        first = min(errors)
        super().__init__(
            f"{len(errors)} of {len(frames)} queries failed; "
            f"the first, query {first}, with: {errors[first]}"
        )


def run_many(
    transport: Transport,
    queries: Iterable[Query],
    *,
    max_in_flight: int | None = None,
    progress: Callable[[Progress], None] | None = None,
    raise_errors: bool = True,
) -> list[pd.DataFrame | None]:
    """Run queries as jobs, with at most ``max_in_flight`` at a time.

    Args:
        transport: The transport to use.
        queries: ``(endpoint, body)`` pairs, such as ``("api/tophits", {...})``.
        max_in_flight: Most jobs queued or running at once; defaults to
            ``transport.config.max_in_flight``.
        progress: Called after each query finishes.
        raise_errors: Raise :class:`BatchError` at the end if any query failed.
            If false, failed queries give ``None``.

    Returns:
        One DataFrame per query, in the order given, with provenance in ``attrs``.

    Raises:
        BatchError: Some queries failed (only when ``raise_errors`` is true). Every
            other query still ran, and its result is in ``BatchError.frames``.
        KeyboardInterrupt: Interrupted; every job in flight is cancelled first.
    """
    limit = max_in_flight or transport.config.max_in_flight
    if limit < 1:
        raise ValueError("max_in_flight must be at least 1")
    pending = deque(enumerate(queries))
    total = len(pending)
    frames: list[pd.DataFrame | None] = [None] * total
    errors: dict[int, Exception] = {}
    active: dict[int, tuple[Job, float]] = {}
    done = 0

    def finish(index: int, error: Exception | None = None) -> None:
        nonlocal done
        done += 1
        if error is not None:
            errors[index] = error
        if progress is not None:
            progress(Progress(done, len(errors), len(active), total))

    try:
        while pending or active:
            while pending and len(active) < limit:
                index, (endpoint, body) = pending.popleft()
                try:
                    job = Job.submit(transport, endpoint, body)
                except OpenGWASError as exc:
                    finish(index, exc)
                    continue
                first = float(job.accepted.get("poll_after_seconds") or 0.0)
                active[index] = (job, transport.clock() + max(first, MIN_POLL))
            if not active:
                continue
            index, (job, due) = min(active.items(), key=lambda item: item[1][1])
            wait = due - transport.clock()
            if wait > 0:
                transport.sleep(wait)
            try:
                status = job.status()
                if not status.finished:
                    active[index] = (job, transport.clock() + max(status.poll_after, MIN_POLL))
                    continue
                del active[index]
                if status.status != "succeeded":
                    raise JobFailed(
                        job.job_id,
                        status.status,
                        status.raw.get("error"),
                        status.raw.get("error_kind"),
                    )
                frames[index] = job.to_frame()
                finish(index)
            except OpenGWASError as exc:
                active.pop(index, None)
                finish(index, exc)
    except KeyboardInterrupt:
        for job, _ in active.values():
            with contextlib.suppress(OpenGWASError):
                job.cancel()
        raise

    if errors and raise_errors:
        raise BatchError(errors, frames)
    return frames
