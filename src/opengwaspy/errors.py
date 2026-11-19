"""Exceptions raised by opengwaspy.

Every error from the API becomes an :class:`APIError` subclass carrying the
API's stable ``error`` code, its ``message``, the HTTP ``status``, the
``request_id`` to quote when asking for help, and any extra fields the API
sent (for example ``indexed_thresholds`` or ``superseded_by``).

The classes separate what to fix from what to retry:

* :class:`RequestError` (400, 404, 409, 410, 413, 422): change the request.
* :class:`AuthError` (401, 403): check the credential.
* :class:`RateLimitError` (429) and :class:`BusyError` (503): wait and retry.
  opengwaspy retries these itself, honouring ``Retry-After``.
* :class:`NotImplementedByServer` (the exact ``501 Not yet implemented``): the
  served Stores cannot answer this operation.
* :class:`ServerError`: any other 5xx.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx

__all__ = [
    "APIError",
    "AuthError",
    "BusyError",
    "IgnoredFieldsError",
    "JobFailed",
    "LDRefusal",
    "NotImplementedByServer",
    "OpenGWASError",
    "ProtocolError",
    "RateLimitError",
    "RequestError",
    "ResultExpired",
    "RetryableError",
    "ServerError",
    "TransportError",
    "UnsupportedOptionError",
    "error_from_response",
]


class OpenGWASError(Exception):
    """Base class for every opengwaspy error."""


class TransportError(OpenGWASError):
    """The API could not be reached, or the connection failed."""


class ProtocolError(OpenGWASError):
    """The API answered with something opengwaspy cannot read."""


class UnsupportedOptionError(OpenGWASError, ValueError):
    """An option cannot be honoured faithfully, so opengwaspy refuses it.

    opengwaspy never ignores an option and returns a different answer. The
    message names the option and what to do instead.
    """


class IgnoredFieldsError(OpenGWASError):
    """The API ignored fields of a request: a bug in opengwaspy.

    Attributes:
        fields: The dotted paths the API listed in ``ignored_fields``.
    """

    def __init__(self, fields: list[str], endpoint: str) -> None:
        self.fields = list(fields)
        self.endpoint = endpoint
        super().__init__(
            f"the API ignored {', '.join(self.fields)} in a request to {endpoint}; "
            "please report this as an opengwaspy bug"
        )


class JobFailed(OpenGWASError):
    """A job finished without a result.

    Attributes:
        job_id: The job.
        status: ``failed``, ``cancelled`` or ``expired``.
        error: The API's error text, if any.
        error_kind: ``request`` (resubmitting fails the same way) or
            ``temporary`` (resubmitting runs the query again), if given.
    """

    def __init__(
        self, job_id: str, status: str, error: str | None = None, error_kind: str | None = None
    ) -> None:
        self.job_id = job_id
        self.status = status
        self.error = error
        self.error_kind = error_kind
        detail = f": {error}" if error else ""
        kind = f" ({error_kind} error)" if error_kind else ""
        super().__init__(f"job {job_id} {status}{kind}{detail}")

    @property
    def retryable(self) -> bool:
        """Whether resubmitting the query may succeed."""
        return self.error_kind == "temporary"


class APIError(OpenGWASError):
    """An error response from the API.

    Attributes:
        status: The HTTP status code.
        error: The API's stable error code, such as ``analysis_not_found``.
        message: The API's message, for people (it may change).
        request_id: The request's ``X-Request-ID``, to quote in a report.
        extra: Any other fields of the error body.
    """

    def __init__(
        self,
        status: int,
        error: str,
        message: str,
        *,
        request_id: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.error = error
        self.message = message
        self.request_id = request_id
        self.extra: dict[str, Any] = dict(extra or {})
        super().__init__(self._describe())

    def _describe(self) -> str:
        text = f"{self.status} {self.error}: {self.message}"
        if self.request_id:
            text += f" (request {self.request_id})"
        return text


class RequestError(APIError):
    """The request cannot succeed as it is: fix it before trying again."""


class ResultExpired(RequestError):
    """The job or its result was deleted (``410 result_expired``)."""


class LDRefusal(RequestError):
    """The LD Store cannot answer this request exactly (``422 ld_refusal``).

    A store holds every r² within ``near_bp`` of a variant, and only r² of at
    least ``t_far`` from there up to ``far_bp``. Ask for a smaller window, or a
    threshold of at least ``t_far``.

    Attributes:
        reason: ``invalid``, ``window_over_far``, ``threshold_below_t_far`` or
            ``region_over_far``.
        t_far: The smallest r² the store holds beyond ``near_bp``.
        near_bp: The distance within which every r² is held.
        far_bp: The largest distance the store measures.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.reason: str | None = self.extra.get("reason")
        self.t_far: float | None = self.extra.get("t_far")
        self.near_bp: int | None = self.extra.get("near_bp")
        self.far_bp: int | None = self.extra.get("far_bp")
        advice = self.answerable
        if advice:
            self.args = (f"{self.args[0]}. {advice}",)

    @property
    def answerable(self) -> str | None:
        """What this store can answer instead, in clumping and proxy terms."""
        if self.t_far is None or self.near_bp is None or self.far_bp is None:
            return None
        return (
            f"This store answers r2 >= {self.t_far:.3g} with kb up to {self.far_bp // 1000:,}, "
            f"or any r2 with kb up to {self.near_bp // 1000:,}"
        )


class AuthError(APIError):
    """The credential is missing, wrong or not allowed (401 or 403)."""


class RetryableError(APIError):
    """A refusal that says when to try again.

    Attributes:
        retry_after: Seconds the API asked us to wait, if it said.
    """

    def __init__(self, *args: Any, retry_after: float | None = None, **kwargs: Any) -> None:
        self.retry_after = retry_after
        super().__init__(*args, **kwargs)


class RateLimitError(RetryableError):
    """429: the queue, the user's share, or the Gateway's allowance is full."""


class BusyError(RetryableError):
    """503: the API is busy, paused or cannot reach a dependency."""


class NotImplementedByServer(APIError):
    """The exact ``501 Not yet implemented``: the served Stores cannot answer this."""


class ServerError(APIError):
    """Another 5xx response."""


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None  # HTTP dates are not used by the API.
    return max(seconds, 0.0)


def _class_for(status: int, code: str) -> type[APIError]:
    if code == "ld_refusal":
        return LDRefusal
    if code == "result_expired":
        return ResultExpired
    if status in (401, 403):
        return AuthError
    if status == 429:
        return RateLimitError
    if status == 503:
        return BusyError
    if status == 501:
        return NotImplementedByServer
    if 400 <= status < 500:
        return RequestError
    return ServerError


def error_from_response(response: httpx.Response) -> APIError:
    """Build the exception for an error response.

    Reads the API's JSON error body (``error``, ``message`` and extra fields;
    ``detail`` repeats them for older clients and is skipped), or a plain-text
    body such as ``Not yet implemented``.

    Args:
        response: A response with a 4xx or 5xx status.

    Returns:
        The matching :class:`APIError` subclass, not raised.
    """
    status = response.status_code
    request_id = response.headers.get("X-Request-ID")
    body: Any = None
    try:
        body = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        code = body["error"]
        message = str(body.get("message", ""))
        extra = {k: v for k, v in body.items() if k not in ("error", "message", "detail")}
    else:
        text = response.text.strip()
        code = "not_implemented" if status == 501 else f"http_{status}"
        message = text[:500] or response.reason_phrase
        extra = {}
    cls = _class_for(status, code)
    kwargs: dict[str, Any] = {"request_id": request_id, "extra": extra}
    if issubclass(cls, RetryableError):
        kwargs["retry_after"] = _retry_after(response)
    return cls(status, code, message, **kwargs)
