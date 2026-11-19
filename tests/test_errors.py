import httpx
import pytest

from opengwaspy.errors import (
    APIError,
    AuthError,
    BusyError,
    IgnoredFieldsError,
    JobFailed,
    LDRefusal,
    NotImplementedByServer,
    RateLimitError,
    RequestError,
    ResultExpired,
    ServerError,
    error_from_response,
)


def response(
    status: int, body: object = None, text: str | None = None, **headers: str
) -> httpx.Response:
    request = httpx.Request("POST", "http://api/api/x")
    if text is not None:
        return httpx.Response(status, text=text, headers=headers, request=request)
    return httpx.Response(status, json=body, headers=headers, request=request)


def api_body(code: str, message: str = "m", **extra: object) -> dict[str, object]:
    return {"error": code, "message": message, "detail": {"error": code}, **extra}


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (400, "invalid_query", RequestError),
        (404, "analysis_not_found", RequestError),
        (409, "ambiguous_analysis", RequestError),
        (410, "result_expired", ResultExpired),
        (410, "analysis_retired", RequestError),
        (413, "request_too_large", RequestError),
        (422, "ld_refusal", LDRefusal),
        (401, "unauthorized", AuthError),
        (403, "forbidden", AuthError),
        (429, "server_busy", RateLimitError),
        (503, "intake_paused", BusyError),
        (500, "internal", ServerError),
    ],
)
def test_error_classes(status: int, code: str, cls: type[APIError]) -> None:
    error = error_from_response(response(status, api_body(code), **{"X-Request-ID": "rid-1"}))
    assert type(error) is cls
    assert (error.status, error.error, error.message, error.request_id) == (
        status,
        code,
        "m",
        "rid-1",
    )
    assert "detail" not in error.extra
    assert str(error) == f"{status} {code}: m (request rid-1)"


def test_extra_fields_and_retry_after() -> None:
    error = error_from_response(
        response(429, api_body("queue_wait_too_long", jobs_ahead=3), **{"Retry-After": "7"})
    )
    assert isinstance(error, RateLimitError)
    assert error.retry_after == 7.0
    assert error.extra == {"jobs_ahead": 3}


@pytest.mark.parametrize(("value", "expected"), [("x", None), ("-3", 0.0), ("2.5", 2.5)])
def test_retry_after_parsing(value: str, expected: float | None) -> None:
    error = error_from_response(response(503, api_body("busy"), **{"Retry-After": value}))
    assert isinstance(error, BusyError)
    assert error.retry_after == expected


def test_no_retry_after() -> None:
    error = error_from_response(response(503, api_body("busy")))
    assert isinstance(error, BusyError) and error.retry_after is None


def test_ld_refusal_facts() -> None:
    body = api_body(
        "ld_refusal",
        reason="threshold_below_t_far",
        t_far=0.0319,
        near_bp=3_000_000,
        far_bp=10_000_000,
    )
    error = error_from_response(response(422, body))
    assert isinstance(error, LDRefusal)
    assert (error.reason, error.t_far, error.near_bp, error.far_bp) == (
        "threshold_below_t_far",
        0.0319,
        3_000_000,
        10_000_000,
    )


def test_plain_text_501() -> None:
    error = error_from_response(response(501, text="Not yet implemented"))
    assert isinstance(error, NotImplementedByServer)
    assert (error.error, error.message) == ("not_implemented", "Not yet implemented")


def test_non_api_bodies() -> None:
    error = error_from_response(response(502, text="<html>bad gateway</html>"))
    assert isinstance(error, ServerError) and error.error == "http_502"
    empty = error_from_response(response(500, text=""))
    assert empty.message == "Internal Server Error"
    odd = error_from_response(response(400, {"error": 5}))
    assert odd.error == "http_400"


def test_job_failed() -> None:
    error = JobFailed("j1", "failed", "store timed out", "temporary")
    assert error.retryable
    assert str(error) == "job j1 failed (temporary error): store timed out"
    assert not JobFailed("j2", "cancelled").retryable
    assert str(JobFailed("j2", "cancelled")) == "job j2 cancelled"


def test_ignored_fields() -> None:
    error = IgnoredFieldsError(["observed_onyl"], "/api/associations")
    assert error.fields == ["observed_onyl"]
    assert "observed_onyl" in str(error) and "bug" in str(error)
