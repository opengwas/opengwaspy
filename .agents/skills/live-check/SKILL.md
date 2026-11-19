---
name: live-check
description: "Run opengwaspy's live integration tests and documentation examples against the OpenGWAS Data API (host 6433, or the Gateway later), safely, and record the evidence in DEVLOG.md. Use before closing any ticket that changes API behaviour, and after the API is redeployed."
---

# Live check

Run the client against the real API and record what answered.

## Preconditions

- `opengwaspy/.env` holds `OPENGWAS_URL` and `OPENGWAS_TOKEN` (see `.env.example`). If it is missing, stop and ask the owner. Never print the token, and never read `../ogdb-api/.env`.
- The target is the host's 6433 (`http://host.lima.internal:6433`) unless the owner names another. Never put stress or saturation load on 6433.

## Steps

1. **Identify the instance.** Fetch `GET {OPENGWAS_URL}/api/status` and note `ready`, `execution.image_digest`, `execution.backend_revision` and the served releases. If `ready` is false, stop and report it.
2. **Check for drift first.** If `/openapi.json` changed since the snapshot, run the `api-drift` skill before trusting the failures.
3. **Run the live tests, serially:** `uv run pytest -m live -p no:randomly -x -q`. Live tests must:
   - use small queries (a few analyses and variants), and read every page they create so results are freed;
   - cancel any job they abandon.
4. **Run the docs examples live**, when the docs changed: `OPENGWAS_LIVE=1 uv run mkdocs build --strict`.
5. **Record in `DEVLOG.md`**, under the ticket's entry:
   - the date, URL, `image_digest` and `backend_revision`;
   - the command, the pass/fail/skip counts, and wall time;
   - each failure: an opengwaspy bug (fix it), an API change (run `api-drift`, file or link an `opengwas/ogdb-api` issue), or an environment problem (record it plainly).

## Guardrails

- At most 4 jobs in flight from the live tests (the developer key's capacity is 5).
- Never retry a refused request in a loop: honour `Retry-After`, and give up after the configured total wait.
- A test that needs data a Store does not hold is skipped with the reason, not weakened.
