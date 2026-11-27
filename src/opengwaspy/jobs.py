"""Jobs: every Data API query runs as one.

Submitting a query returns a job. The job is polled until it finishes, then
its result is read in pages of NDJSON rows::

    job = Job.submit(transport, "api/tophits", {"analyses": [...]})
    frame = job.to_frame()            # waits, reads every page, checks each page

Jobs are keyed by user and query, so resubmitting the same query returns the
same job. That makes :meth:`Job.submit` safe to retry, and lets a long
pipeline pick a job up again with :meth:`Job.from_id`.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from opengwaspy.errors import (
    IgnoredFieldsError,
    JobFailed,
    OpenGWASError,
    ProtocolError,
    ResultExpired,
)
from opengwaspy.transport import Transport, json_body

__all__ = ["TERMINAL", "Job", "JobStatus", "JobTimeout", "ResultPage"]

#: Job states that will not change again.
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "expired"})
#: Shortest wait between polls, in seconds, however soon the API suggests.
MIN_POLL = 0.25


class JobTimeout(OpenGWASError):
    """A job did not finish within the time the caller allowed. It is still running."""

    def __init__(self, job_id: str, status: str, waited: float) -> None:
        self.job_id = job_id
        self.status = status
        super().__init__(
            f"job {job_id} still {status} after {waited:.0f} s; "
            f"pick it up later with Job.from_id({job_id!r})"
        )


@dataclass(frozen=True)
class JobStatus:
    """A job's state, as ``GET /api/jobs/{id}`` reports it.

    Attributes:
        raw: The whole status document.
    """

    raw: Mapping[str, Any]

    @property
    def job_id(self) -> str:
        """The job's ID."""
        return str(self.raw["job_id"])

    @property
    def status(self) -> str:
        """``queued``, ``running``, ``succeeded``, ``failed``, ``cancelled`` or ``expired``."""
        return str(self.raw["status"])

    @property
    def finished(self) -> bool:
        """Whether the job is in a terminal state."""
        return self.status in TERMINAL

    @property
    def poll_after(self) -> float:
        """Seconds the API suggests waiting before polling again."""
        return float(self.raw.get("poll_after_seconds") or 0.0)

    @property
    def result(self) -> Mapping[str, Any]:
        """The result description of a succeeded job (empty otherwise)."""
        result = self.raw.get("result")
        return result if isinstance(result, Mapping) else {}

    @property
    def metadata(self) -> dict[str, Any]:
        """Facts about the result, such as ``total`` and ``truncated``."""
        return dict(self.result.get("metadata") or {})


@dataclass(frozen=True)
class ResultPage:
    """One page of a job's result.

    Attributes:
        rows: The page's rows, decoded.
        page_index: The page's number, from 0.
        row_offset: The position of the page's first row in the whole result.
        final: Whether this is the last page.
        next_cursor: The cursor for the next page, if any.
        manifest: The result's manifest (row and page counts, releases).
    """

    rows: list[dict[str, Any]]
    page_index: int
    row_offset: int
    final: bool
    next_cursor: str | None
    manifest: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, body: Mapping[str, Any]) -> ResultPage:
        """Check a page's checksum and decode its rows.

        Raises:
            ProtocolError: The page is malformed, or its checksum does not match.
        """
        try:
            text = body["ndjson"]
            expected = body["sha256"]
            final = bool(body["final"])
        except (KeyError, TypeError) as exc:
            raise ProtocolError(f"malformed result page: missing {exc}") from exc
        actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if expected and actual != str(expected).removeprefix("sha256:"):
            raise ProtocolError(f"result page checksum mismatch: expected {expected}, got {actual}")
        try:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"result page holds invalid NDJSON: {exc}") from exc
        return cls(
            rows=rows,
            page_index=int(body.get("page_index") or 0),
            row_offset=int(body.get("row_offset") or 0),
            final=final,
            next_cursor=body.get("next_cursor"),
            manifest=body.get("manifest") or {},
        )


def _declared_counts(manifest: Mapping[str, Any] | None) -> tuple[int | None, int | None]:
    """The ``page_count`` and ``total_rows`` (or ``row_count``) a manifest declares."""
    if not manifest:
        return None, None

    def number(*keys: str) -> int | None:
        for key in keys:
            value = manifest.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    return number("page_count"), number("total_rows", "row_count")


class Job:
    """A query running as a job on the API.

    Build one with :meth:`submit` or :meth:`from_id`.

    Attributes:
        job_id: The job's ID.
        endpoint: The API path the query was submitted to, if known.
        body: The query, if known (needed to resubmit an expired result).
        accepted: The submission's answer, if this object submitted it.
    """

    def __init__(
        self,
        transport: Transport,
        job_id: str,
        *,
        endpoint: str | None = None,
        body: Mapping[str, Any] | None = None,
        accepted: Mapping[str, Any] | None = None,
        status_url: str | None = None,
    ) -> None:
        self.transport = transport
        self.job_id = job_id
        self.endpoint = endpoint
        self.body = dict(body) if body is not None else None
        self.accepted = dict(accepted) if accepted is not None else {}
        self._status_url = status_url or f"api/jobs/{job_id}"
        self._last: JobStatus | None = None

    def __repr__(self) -> str:
        state = self._last.status if self._last else self.accepted.get("status", "unknown")
        return f"Job({self.job_id!r}, endpoint={self.endpoint!r}, status={state!r})"

    # Creating

    @classmethod
    def submit(cls, transport: Transport, endpoint: str, body: Mapping[str, Any]) -> Job:
        """Submit a query as a job.

        Args:
            transport: The transport to use.
            endpoint: The query's API path, such as ``api/tophits``.
            body: The query.

        Returns:
            The job. If the same query was already submitted, the existing job.

        Raises:
            IgnoredFieldsError: The API did not use some of the query's fields.
            APIError: The API refused the query.
        """
        endpoint = endpoint.lstrip("/")
        accepted = json_body(transport.post(endpoint, body))
        if not isinstance(accepted, dict) or "job_id" not in accepted:
            raise ProtocolError(f"submission to {endpoint} did not return a job")
        ignored = accepted.get("ignored_fields") or []
        if ignored:
            raise IgnoredFieldsError(list(ignored), "/" + endpoint)
        return cls(
            transport,
            str(accepted["job_id"]),
            endpoint="/" + endpoint,
            body=body,
            accepted=accepted,
            status_url=accepted.get("status_url"),
        )

    @classmethod
    def from_id(cls, transport: Transport, job_id: str) -> Job:
        """A job submitted earlier, for example by a pipeline that restarted.

        Its result can be read until it expires. It cannot be resubmitted
        automatically, because the query is not known.
        """
        return cls(transport, job_id)

    # Status

    @property
    def query_hash(self) -> str | None:
        """The API's hash of the query."""
        value = self.accepted.get("query_hash") or (self._last and self._last.raw.get("query_hash"))
        return str(value) if value else None

    @property
    def existing(self) -> bool:
        """Whether the submission returned a job that already existed."""
        return bool(self.accepted.get("existing"))

    def status(self) -> JobStatus:
        """Fetch the job's current status."""
        status = JobStatus(json_body(self.transport.get(self._status_url)))
        self._last = status
        if self.endpoint is None and status.raw.get("endpoint"):
            self.endpoint = str(status.raw["endpoint"])
        return status

    def wait(
        self,
        timeout: float | None = None,
        *,
        progress: Callable[[JobStatus], None] | None = None,
        cancel_on_interrupt: bool = True,
    ) -> JobStatus:
        """Wait until the job finishes, polling as often as the API suggests.

        Args:
            timeout: Most seconds to wait. ``None`` waits as long as it takes.
            progress: Called with each status polled.
            cancel_on_interrupt: Cancel the job if the wait is interrupted
                (Ctrl-C), so it stops using shared capacity.

        Returns:
            The status of the succeeded job.

        Raises:
            JobFailed: The job failed, was cancelled, or expired.
            JobTimeout: ``timeout`` passed first; the job keeps running.
        """
        clock, sleep = self.transport.clock, self.transport.sleep
        started = clock()
        delay = float(self.accepted.get("poll_after_seconds") or 0.0)
        try:
            while True:
                if delay:
                    sleep(max(delay, MIN_POLL))
                status = self.status()
                if progress is not None:
                    progress(status)
                if status.finished:
                    break
                if timeout is not None and clock() - started >= timeout:
                    raise JobTimeout(self.job_id, status.status, clock() - started)
                delay = max(status.poll_after, MIN_POLL)
        except KeyboardInterrupt:
            if cancel_on_interrupt:
                self.cancel()
            raise
        if status.status != "succeeded":
            raise JobFailed(
                self.job_id,
                status.status,
                status.raw.get("error"),
                status.raw.get("error_kind"),
            )
        return status

    def cancel(self) -> JobStatus:
        """Ask the API to cancel the job. A finished job is left as it is."""
        status = JobStatus(json_body(self.transport.delete(self._status_url)))
        self._last = status
        return status

    # Results

    def pages(self) -> Iterator[ResultPage]:
        """Wait for the job, then yield every page of its result, in order.

        Each page must be the next in sequence and start at the next row. When
        the manifest (in the job's status, or else in the first page) declares
        ``page_count`` and ``total_rows``, the pages read must match them: the
        result is only complete when they do.

        Raises:
            ResultExpired: The result was deleted while being read.
            ProtocolError: A page's checksum did not match; a page was missing,
                repeated or out of order; or the result ended before (or ran
                past) what the manifest declares.
        """
        status = self._last if self._last and self._last.status == "succeeded" else self.wait()
        url = status.result.get("result_url") or f"{self._status_url}/result"
        declared: Mapping[str, Any] | None = status.result.get("manifest") or None
        params: dict[str, str] = {}
        index = rows = 0
        while True:
            page = ResultPage.parse(json_body(self.transport.get(url, params=params or None)))
            if declared is None or "page_count" not in declared:
                declared = page.manifest or declared
            page_count, total_rows = _declared_counts(declared)
            if page.page_index != index:
                raise ProtocolError(
                    f"job {self.job_id}: expected result page {index}, got page {page.page_index}"
                )
            if page.row_offset != rows:
                raise ProtocolError(
                    f"job {self.job_id}: result page {index} starts at row {page.row_offset}, "
                    f"expected row {rows}"
                )
            index += 1
            rows += len(page.rows)
            if page_count is not None and index > page_count:
                raise ProtocolError(
                    f"job {self.job_id}: the result has more than the {page_count} pages "
                    "its manifest declares"
                )
            if page.final:
                if page_count is not None and index != page_count:
                    raise ProtocolError(
                        f"job {self.job_id}: the result ended after {index} pages, but its "
                        f"manifest declares {page_count}"
                    )
                if total_rows is not None and rows != total_rows:
                    raise ProtocolError(
                        f"job {self.job_id}: the result holds {rows} rows, but its manifest "
                        f"declares {total_rows}"
                    )
            yield page
            if page.final:
                return
            if not page.next_cursor:
                raise ProtocolError("result page is not final but has no next cursor")
            params = {"cursor": page.next_cursor}

    def rows(self) -> Iterator[dict[str, Any]]:
        """Every row of the result, in order.

        If the result expires part-way (``410 result_expired``) and the query is
        known, it is resubmitted once and reading resumes after the rows already
        returned. The API orders rows deterministically, so none is repeated.
        """
        returned = 0
        resubmitted = False
        while True:
            try:
                for page in self.pages():
                    for offset, row in enumerate(page.rows, start=page.row_offset):
                        if offset >= returned:
                            returned += 1
                            yield row
                return
            except ResultExpired:
                if resubmitted or self.body is None or self.endpoint is None:
                    raise
                resubmitted = True
                self._adopt(Job.submit(self.transport, self.endpoint, self.body))

    def to_frame(self) -> pd.DataFrame:
        """The whole result as a DataFrame, with its provenance in ``.attrs``.

        ``attrs`` holds ``job_id``, ``query_hash``, ``endpoint``, ``release_id``,
        ``releases``, ``metadata`` (such as ``total`` and ``truncated``) and
        ``compute``.
        """
        rows = list(self.rows())
        frame: pd.DataFrame = pd.DataFrame.from_records(rows) if rows else pd.DataFrame()
        frame.attrs.update(self.provenance())
        return frame

    def provenance(self) -> dict[str, Any]:
        """Where the result came from: job, query, releases and metadata."""
        raw = self._last.raw if self._last else {}
        result = self._last.result if self._last else {}
        manifest = result.get("manifest") or {}
        return {
            "job_id": self.job_id,
            "query_hash": self.query_hash,
            "endpoint": self.endpoint,
            "release_id": result.get("release_id") or raw.get("release_id"),
            "releases": list(manifest.get("releases") or []),
            "metadata": self._last.metadata if self._last else {},
            "compute": dict(raw.get("compute") or {}),
            "retrieved": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _adopt(self, other: Job) -> None:
        self.job_id = other.job_id
        self.accepted = other.accepted
        self._status_url = other._status_url
        self._last = other._last
