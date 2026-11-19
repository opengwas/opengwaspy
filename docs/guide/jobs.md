# Jobs and large queries

Every data query runs as a **job**. The API queues jobs fairly between users, so one person's large query cannot crowd out everyone else's. opengwaspy hides this: each function submits, waits and reads the result for you. This page is for when you want more control.

## What happens in one call

1. **Submit.** The query is sent, and the API answers with a job. Submitting the same query again returns the same job, so retrying is always safe.
2. **Wait.** opengwaspy polls the job as often as the API suggests: often while it is quick, less when the API is busy.
3. **Read.** The result comes in pages of up to 1,000 rows. Each page is checked against its SHA-256 checksum.
4. **Combine.** Large requests become several jobs, at most 4 in flight at once (`max_in_flight`). Their rows are put back together in order.

When the API is busy (`429` or `503` with `Retry-After`), opengwaspy waits as asked, for up to 10 minutes in total (`max_retry_wait`), then raises `RateLimitError` or `BusyError`. A job that fails raises `JobFailed`. Its `retryable` property says whether running it again may help.

## Working with jobs yourself

```python
import opengwaspy as og

client = og.get_client()
job = client.submit("api/tophits", {"analyses": ["OGS-00006:GCST90199621"], "limit": 10})
job                     # Job('aa4c2a29-…', endpoint='/api/tophits', status='queued')
status = job.wait(timeout=600)
status.metadata         # {'threshold': 5e-08, 'observed_only': False, 'total': 10, 'truncated': True}
frame = job.to_frame()
```

- **Resume** after a restart: `client.job("aa4c2a29-…").to_frame()`. A finished result is kept for an hour unread, and for a few minutes after it is fully read.
- **Cancel:** `job.cancel()`. Pressing Ctrl-C while waiting cancels the job for you, so it stops using shared capacity.
- **Timeout:** `wait(timeout=...)` raises `JobTimeout` and leaves the job running. Pick it up later by its ID.

## Many queries

```python
frames = client.query_many(
    [("api/tophits", {"analyses": [a], "limit": 100}) for a in analysis_ids],
    max_in_flight=4,
)
```

Results come back in the order given. If some queries fail, `BatchError` lists them by position, and still carries every result that succeeded. `og.run_many(..., raise_errors=False)` gives `None` for the failures instead.

## Errors

| Error | Means | Do |
|---|---|---|
| `RequestError` | The request cannot succeed as it is (400, 404, 409, 410, 413, 422) | Fix it; `error.error` is the API's code, such as `analysis_not_found` |
| `LDRefusal` | The LD store cannot answer exactly | Use the settings the message suggests |
| `AuthError` | Missing or wrong key | Check your settings |
| `RateLimitError`, `BusyError` | Still busy after waiting | Try later |
| `NotImplementedByServer` | The served data cannot answer this kind of query | — |
| `JobFailed` | The job ran and failed | If `retryable`, run it again |

Quote `error.request_id` when asking for help.
