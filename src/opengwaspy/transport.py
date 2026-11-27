"""HTTP transport: authentication, headers, errors and polite retries.

:class:`Transport` sends one logical call, retrying where that is safe and
useful, and returns the successful response or raises an
:mod:`opengwaspy.errors` exception.

Retries:

* **429 and 503 with ``Retry-After``**: wait as asked, then try again, until
  the call has waited ``Config.max_retry_wait`` seconds in all.
* **Transport errors, and other 5xx**: exponential backoff with jitter, up to
  ``Config.max_attempts`` attempts.
* **401**: ask the auth provider to refresh once, then retry.
* **The Gateway's allowance**: after a response with
  ``X-Allowance-Remaining: 0``, calls wait until ``X-Allowance-Reset`` (or fail
  at once if that is beyond ``max_retry_wait``).

Every attempt of one call carries the same ``X-Request-ID``. Resubmitting a
query is safe: the API returns the existing job for the same user and query.
"""

from __future__ import annotations

import json
import platform
import random
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from opengwaspy import __version__
from opengwaspy.config import Config
from opengwaspy.errors import (
    APIError,
    AuthError,
    ProtocolError,
    RateLimitError,
    RetryableError,
    ServerError,
    TransportError,
    error_from_response,
)

__all__ = ["USER_AGENT", "Transport", "json_body"]

USER_AGENT = (
    f"opengwaspy/{__version__} (python/{platform.python_version()}; httpx/{httpx.__version__})"
)

#: Longest single backoff sleep, in seconds.
MAX_BACKOFF = 30.0
#: Shortest wait on a Retry-After, in seconds, so a zero never makes a tight loop.
MIN_RETRY_AFTER = 1.0


def json_body(response: httpx.Response) -> Any:
    """The response's JSON body.

    Raises:
        ProtocolError: The body is not JSON.
    """
    try:
        return response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProtocolError(
            f"expected JSON from {response.request.method} {response.request.url}, "
            f"got {response.headers.get('content-type', 'no content type')}"
        ) from exc


class Transport:
    """Sends requests to the API.

    Args:
        config: Where the API is and how to authenticate; defaults to
            :meth:`Config.load`.
        client: An ``httpx.Client`` to use (for tests, or custom TLS or proxies).
            The transport closes only a client it created.
        sleep: Function used to wait, in seconds.
        clock: Monotonic clock, in seconds.
        wall_clock: Wall clock, in Unix seconds (for ``X-Allowance-Reset``).
        jitter: Returns a float in [0, 1), for backoff jitter.
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.config = config if config is not None else Config.load()
        self._own_client = client is None
        self._client = client if client is not None else httpx.Client(timeout=self.config.timeout)
        #: Function used to wait, in seconds (jobs poll with it too).
        self.sleep = sleep
        #: Monotonic clock, in seconds.
        self.clock = clock
        self._wall_clock = wall_clock
        self._jitter = jitter
        self._lock = threading.Lock()
        self._allowance_reset: float | None = None
        self._allowance: dict[str, float] | None = None

    def close(self) -> None:
        """Close the HTTP client, if this transport created it."""
        if self._own_client:
            self._client.close()

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"Transport(base_url={self.config.base_url!r}, auth={self.config.auth!r})"

    # Requests

    def get(self, path: str, *, params: Mapping[str, Any] | None = None) -> httpx.Response:
        """``GET`` a path; see :meth:`request`."""
        return self.request("GET", path, params=params)

    def post(self, path: str, body: Mapping[str, Any]) -> httpx.Response:
        """``POST`` a JSON body to a path; see :meth:`request`."""
        return self.request("POST", path, json=body)

    def delete(self, path: str) -> httpx.Response:
        """``DELETE`` a path; see :meth:`request`."""
        return self.request("DELETE", path)

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> httpx.Response:
        """Send one logical call, with retries, and return its 2xx response.

        Args:
            method: The HTTP method.
            path: An API path (``api/...``), a path the API returned, or a URL.
            json: A JSON body.
            params: Query parameters.
            request_id: The ``X-Request-ID`` to send; a new one by default.

        Returns:
            The successful response.

        Raises:
            APIError: An error response that retrying cannot fix, or retries ran out.
            TransportError: The API could not be reached after every attempt.
        """
        url = self.config.url(path)
        request_id = request_id or uuid.uuid4().hex
        started = self.clock()
        attempt = 0
        refreshed = False
        while True:
            self._wait_for_allowance(started)
            attempt += 1
            try:
                response = self._client.request(
                    method, url, json=json, params=params, headers=self._headers(request_id)
                )
            except httpx.TransportError as exc:
                if attempt >= self.config.max_attempts:
                    raise TransportError(
                        f"{method} {url} failed after {attempt} attempts: {exc}"
                    ) from exc
                self.sleep(self._backoff(attempt))
                continue

            self._note_allowance(response)
            if response.is_success:
                return response

            error = error_from_response(response)
            if isinstance(error, AuthError) and error.status == 401 and not refreshed:
                refreshed = True
                if self.config.auth.refresh():
                    continue
            if isinstance(error, RetryableError) and error.retry_after is not None:
                wait = max(error.retry_after, MIN_RETRY_AFTER)
                if self.clock() - started + wait > self.config.max_retry_wait:
                    raise error
                self.sleep(wait)
                continue
            if self._is_transient(error) and attempt < self.config.max_attempts:
                self.sleep(self._backoff(attempt))
                continue
            raise error

    # Internals

    def _headers(self, request_id: str) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "X-API-Source": f"opengwaspy/{__version__}",
            "X-Request-ID": request_id,
        }
        headers.update(self.config.auth.headers())
        return headers

    @staticmethod
    def _is_transient(error: APIError) -> bool:
        # Other 5xx, and 429/503 without a Retry-After. Never 501.
        return isinstance(error, (ServerError, RetryableError))

    def _backoff(self, attempt: int) -> float:
        delay: float = min(MAX_BACKOFF, 2.0 ** (attempt - 1))
        return delay / 2 + self._jitter() * delay / 2

    @property
    def allowance(self) -> dict[str, float] | None:
        """The Gateway allowance from the latest response that gave it.

        ``limit``, ``remaining`` and ``reset`` (Unix seconds), from the
        ``X-Allowance-*`` headers, where present; ``None`` before any such
        response (the Data API itself sends none).
        """
        with self._lock:
            return dict(self._allowance) if self._allowance is not None else None

    def _note_allowance(self, response: httpx.Response) -> None:
        seen: dict[str, float] = {}
        for key in ("limit", "remaining", "reset"):
            value = response.headers.get(f"X-Allowance-{key.title()}")
            try:
                seen[key] = float(value) if value is not None else float("nan")
            except ValueError:
                continue
        seen = {k: v for k, v in seen.items() if v == v}  # drop NaN
        if seen:
            with self._lock:
                self._allowance = seen
        if response.headers.get("X-Allowance-Remaining") != "0":
            return
        try:
            reset = float(response.headers["X-Allowance-Reset"])
        except (KeyError, ValueError):
            retry_after = response.headers.get("Retry-After", "60")
            reset = self._wall_clock() + (float(retry_after) if retry_after.isdigit() else 60.0)
        with self._lock:
            self._allowance_reset = reset

    def _wait_for_allowance(self, started: float) -> None:
        with self._lock:
            reset = self._allowance_reset
        if reset is None:
            return
        wait = reset - self._wall_clock()
        if wait <= 0:
            with self._lock:
                if self._allowance_reset == reset:
                    self._allowance_reset = None
            return
        if self.clock() - started + wait > self.config.max_retry_wait:
            when = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(reset))
            raise RateLimitError(
                429,
                "allowance_exhausted",
                f"your OpenGWAS allowance is used up until {when}",
                retry_after=wait,
            )
        self.sleep(wait)
