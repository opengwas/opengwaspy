---
name: api-drift
description: "Compare the live Data API's OpenAPI schema with opengwaspy's recorded snapshot and request models, and report added, removed or changed operations, fields, limits and error codes. Use when live tests fail unexpectedly, after ogdb-api merges that touch the API, or before a release."
---

# API drift

opengwaspy keeps a snapshot of the API it was built against, in `tests/fixtures/openapi.json`. This skill finds what has changed since.

## Steps

1. Fetch the live schema without credentials: `curl -s {OPENGWAS_URL}/openapi.json > <scratchpad>/openapi.live.json`. Through the Gateway the path is `/ogdb/openapi.json`.
2. Compare it with the snapshot: `uv run python scripts/api_drift.py tests/fixtures/openapi.json <scratchpad>/openapi.live.json`. The script prints, per operation:
   - paths and methods added or removed;
   - request fields added, removed, or newly required;
   - response schemas changed (`JobAccepted`, `JobStatus`, `ResultPage`, `ErrorBody`, row shapes).
   If the script does not exist yet, diff `paths` and `components.schemas` by hand with `python3 -c` and `json`.
3. Read the upstream change that caused it: `git -C ../ogdb-api log --oneline -20 -- ogdb_api docs SPECIFICATION.md`, and the matching `DEVLOG.md` entries there. Do not change that checkout.
4. Classify each difference:
   - **Additive** (a new optional field or operation): file an opengwaspy ticket to support it.
   - **Breaking** (a renamed or removed field, or a changed default or limit): file an opengwaspy ticket at once. If it looks unintended, also draft an `opengwas/ogdb-api` issue for the owner to approve.
5. Update the snapshot only in the same commit as the client change that handles it, and record both in `DEVLOG.md` with the live `image_digest`.

## Report

A table of `operation | change | kind | opengwaspy impact | ticket`, plus the live and snapshot digests.
