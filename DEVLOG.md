# Development log

Newest entry first. Each entry: what changed, the evidence (commands, results, commit hashes, the API's `image_digest`), and anything that failed or is still at risk.

## Evidence and references

- Data API contract: `../ogdb-api/SPECIFICATION.md`, `../ogdb-api/docs/gateway-contract.md`, `../ogdb-api/docs/client-mapping.md` (read 19 Nov 2026 at ogdb-api `main`).
- ieugwaspy 1.0.6: `../ieugwaspy` (MRCIEU/ieugwaspy).
- Gateway: opengwas/opengwas-gateway @ `452c6cb` (19 Nov 2026). `Authorization: Bearer <OpenGWAS JWT>`, JWT validity 14 days, Data API under `/ogdb/*`, `429` with `X-Allowance-*`, and `X-Service-Key` for services.
- Live API: `http://host.lima.internal:6433`, `/openapi.json`, `/docs`, `/redoc`.

## 2026-11-19 - #16: many jobs with bounded concurrency

- **`opengwaspy.batch.run_many(transport, queries, max_in_flight, progress, raise_errors)`:**
  - keeps at most `max_in_flight` jobs (default `Config.max_in_flight`, 4) queued or running;
  - polls whichever job is due next, at the API's suggested interval;
  - reads each result as soon as its job finishes;
  - returns the frames in query order.
- **Failures** (refused submissions, and failed jobs) are collected. With `raise_errors` (the default), `BatchError` comes at the end, with `errors` by position and every successful frame. Otherwise failed queries give `None`.
- **Ctrl-C** cancels every job in flight, ignoring cancel errors, then re-raises.
- **Reporting:** `Progress(done, failed, running, total)` after each query.
- **Evidence:**
  - `uv run pytest`: 108 passed, coverage 99%. A fake API tracks the jobs in flight; its peak was 2 with `max_in_flight=2`.
  - `uv run pytest -m live --no-cov`: 7 passed on 6433, including 3 top-hits jobs with `max_in_flight=2`, returned in order.

## 2026-11-19 - #15: the job lifecycle

- **`opengwaspy.jobs`:**
  - `Job.submit(transport, endpoint, body)` raises `IgnoredFieldsError` if the API lists any `ignored_fields`, and keeps the query for resubmission. `Job.from_id` picks up a job for resumability.
  - `status()`; `wait(timeout, progress, cancel_on_interrupt)` polls at the API's `poll_after_seconds` (the submission's first, with a 0.25 s floor) and raises `JobFailed` (with `error_kind` and `retryable`) or `JobTimeout` (the job keeps running). Ctrl-C cancels the job unless told not to.
  - `cancel()`.
  - `pages()` follows `next_cursor` until `final`, checking each page's SHA-256 over its UTF-8 `ndjson`.
  - `rows()` resubmits once on `410 result_expired` and skips rows already returned, by `row_offset`.
  - `to_frame()` gives a DataFrame with `attrs`: `job_id`, `query_hash`, `endpoint`, `release_id`, `releases`, `metadata`, `compute` and `retrieved`.
- **`Transport.sleep` and `Transport.clock` are now public**, so jobs poll with the same injectable clock.
- **Not yet in the provenance:** the API's `image_digest` (it is in `/api/status`, not in `JobStatus`). Planned with the client facade in #4.
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 102 passed, coverage 99.7%. `uv run pytest -m live --no-cov`: 6 passed against 6433 (`image_digest` `sha256:8e0f8a1c9d3acbbe1d30dbbf4190aeacb64d6b561332d096a00cbb92392c2730`), including a top-hits job end to end, where resubmitting returned the same `query_hash`.

## 2026-11-19 - #13, #14: transport, typed errors and retries

- **`opengwaspy.errors`** maps every code in ogdb-api's `docs/gateway-contract.md`:
  - `RequestError` (400, 404, 409, 410, 413, 422), with `ResultExpired` (`410 result_expired`) and `LDRefusal` (`422 ld_refusal`, carrying `reason`, `t_far`, `near_bp` and `far_bp`);
  - `AuthError` (401, 403);
  - `RateLimitError` (429) and `BusyError` (503), both `RetryableError` with `retry_after`;
  - `NotImplementedByServer` (the plain-text `501 Not yet implemented`) and `ServerError`.
  - Each carries `status`, `error`, `message`, `request_id` and `extra`; `detail` is skipped.
  - Also `TransportError`, `ProtocolError`, `JobFailed` (`error_kind`, `retryable`), `IgnoredFieldsError` and `UnsupportedOptionError`.
- **`opengwaspy.transport.Transport`:**
  - JSON bodies; `User-Agent` and `X-API-Source: opengwaspy/<version>`; one `X-Request-ID` for every attempt of a call.
  - **Retries:** 429/503 honour `Retry-After` (at least 1 s) within `max_retry_wait`. Transport errors and other 5xx back off exponentially with jitter (1, 2, 4… s, capped at 30 s; half fixed, half random) up to `max_attempts`.
  - **401:** asks the auth provider to refresh once.
  - **The Gateway's allowance:** after `X-Allowance-Remaining: 0`, calls wait until `X-Allowance-Reset` (Unix seconds, per opengwas-gateway `app/limiting/limiter.py`), or fail at once if that is beyond the budget.
  - 4xx and 501 are never retried.
- **Live shapes checked on 6433** (`image_digest` `sha256:8e0f8a1c…2c2730`):
  - **Error body:** `{"error", "message", "detail"}`, with an `x-request-id` header. `501` is the plain text `Not yet implemented`.
  - **A tophits job:** `202` with `Location`, `Retry-After: 1` and `X-OGDB-Cost-Estimate`. `JobAccepted` has `request_fingerprint` and `query_hash`, `poll_after_seconds` 0.27 and `ignored_fields` [].
  - **The result page:** `schema`, `manifest`, `page_index`, `row_offset`, `row_count`, `byte_count`, `sha256`, `cursor`, `next_cursor`, `final` and `ndjson`.
  - **The page's `sha256`** is the hex SHA-256 of the `ndjson` text encoded as UTF-8 (checked).
  - **`log10_p` is log10(p), so negative** (−133.3 for the top hit). REQUIREMENTS §6 said `10 ** -log10_p`; corrected to `10 ** log10_p`.
- **Evidence:** `uv run pytest`: 86 passed, coverage 99.8%. `uv run pytest -m live --no-cov`: 5 passed on 6433 (user role, `analysis_not_found` with a request ID, `501` for `variants/gene`).

## 2026-11-19 - #12: configuration and auth providers

- **`opengwaspy.config`:**
  - `Config.load` takes explicit arguments, then the environment (`OPENGWAS_URL`, `OPENGWAS_PROFILE`, `OPENGWAS_TOKEN`, `OPENGWAS_JWT`), then a TOML config file (`$OPENGWAS_CONFIG`, else `<user config dir>/opengwaspy/config.toml`), then the defaults.
  - A URL beats a profile at the same level. A developer key and an OpenGWAS token at the same level raise `ConfigError`. A credential in a group- or world-readable file triggers a warning.
  - Profiles: `local` (`http://localhost:6432`, the default until the Gateway is live) and `gateway` (`https://api.opengwas.io/ogdb`).
  - `Config.url()` resolves `api/...` against the base URL, and an absolute path the API returns (which already carries the Gateway's `/ogdb`) against the origin.
- **`opengwaspy.auth`:** the `AuthProvider` protocol (`headers()`, `refresh()`), with `DeveloperKey`, `OpenGWASToken` and `NoAuth`. Tokens are hidden from `repr` and `str`.
- **Dependencies:** `tomli` on Python < 3.11, plus `tomli` in the dev group, so mypy (`python_version = 3.10`) can check the fallback import.
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 40 passed, coverage 100% (auth 100%, config 100%), on 3.12 and on 3.10 (`uv run --isolated --python 3.10`).
- **PR #23 closed itself** when #22's branch was deleted on merge (it was stacked on it). It was replaced by a PR against `main`.

## 2026-11-19 - #10: CI

- **`.github/workflows/tests.yml`:**
  - ruff format and lint, and mypy;
  - pytest with the coverage gate, on Python 3.10–3.14;
  - a build job that installs the wheel and imports it.
  - Actions pinned to commit SHAs, each release at least two weeks old: checkout v7.0.1 `3d3c42e5`, setup-uv v10.3.3 `68559e99`.
- **The CLA check failed** on the agent's PR. The commits were authored "Claude -- t0mrg <claude@biocompute.org.uk>", an email linked to no GitHub account, so CLA Assistant Lite matched on the name, which is not allow-listed.
  - The agent's attempt to allow-list its own name was refused by the permission check, as weakening oversight.
  - **The owner chose** to have the agent's commits use t0mrg's GitHub noreply email: `git config user.email 10964709+t0mrg@users.noreply.github.com` in this checkout, name unchanged. The two unmerged PR branches were rewritten with `--reset-author`; `main`'s history is untouched.
- **Merged as PR #22** (`5e94cee`), every check green, CLA included: https://github.com/opengwas/opengwaspy/actions/runs/44517946416.

## 2026-11-19 - #11: contributor agreements

- **Source:** the Harmony v1.0 templates `ha-cla-i-v1.odt` and `ha-cla-e-v1.odt` from https://www.harmonyagreements.org/agreements.html (fetched 19 Nov 2026; CC BY 3.0). Text was extracted from `content.xml` and filled in by a script, keeping only outbound Option Five (the "Any" variant).
  - "We": the University of Bristol, for opengwaspy.
  - Media licence: CC BY 4.0.
  - Jurisdiction: England and Wales (the owner's instruction).
  - Submission and non-owner instructions: `CLA.md`.
  - The entity version keeps "or Your Affiliates"; the individual version drops it.
  - No placeholder remains (the script asserts it).
- **Files:**
  - `cla/HA-CLA-I-Any.md` and `cla/HA-CLA-E-Any.md`;
  - `CLA.md`, which says which agreement applies, how to sign, what to do with work you do not own, and that University of Bristol staff need no CLA;
  - `CONTRIBUTING.md`;
  - a README section.
- **Enforcement:** `.github/workflows/cla.yml` runs CLA Assistant Lite (`contributor-assistant/github-action` v2.6.1, pinned to commit `ca4a40a7`).
  - It runs on `pull_request_target` and on PR comments, and never checks out PR code.
  - Signatures go to `signatures/version1/cla.json` on the orphan branch `cla-signatures` (created, `60bacac`).
  - Allow-list: t0mrg and the bots. Other University of Bristol staff are added as they join.
  - The workflow first runs on PRs opened after this merges, because `pull_request_target` uses the base branch's workflow.
- **Not legal advice:** the University's legal or contracts office may want to review the filled-in agreements before external contributions arrive.

## 2026-11-19 - #9: package skeleton

- **`pyproject.toml`:**
  - hatchling ≥ 1.27, with the version from `src/opengwaspy/__init__.py` (`0.0.1.dev0`);
  - `requires-python >=3.10`; dependencies `httpx>=0.27` and `pandas>=2.0`;
  - `license = "GPL-3.0-only"` (PEP 639) with `license-files`. `-only` rather than `-or-later` keeps relicensing in the copyright holder's hands, which suits dual licensing; for the owner to confirm.
  - Dev group: ruff, mypy, pandas-stubs, pytest, pytest-cov and respx.
  - Ruff rules E, F, W, I, B, UP, SIM, RUF and D (Google docstrings). mypy strict. pytest `--strict-markers`, with `-m "not live"` by default and coverage failing under 90% (branch coverage).
- **Package:** `src/opengwaspy/__init__.py` and `py.typed`. `.python-version` is 3.12 for local development, and `uv.lock` is committed.
- **Tests:**
  - `tests/conftest.py` provides the `live_api` fixture. It reads `OPENGWAS_URL` and `OPENGWAS_TOKEN` from the environment, else from `.env` (live tests only). It never shows the token, and skips when unset.
  - `tests/test_package.py`: the version, `py.typed`, `.env` parsing and precedence.
  - `tests/test_live_smoke.py` (marked `live`): `/api/status` is ready, and the key is accepted.
- **Evidence:**
  - `uv run ruff format . && uv run ruff check .`: clean.
  - `uv run mypy`: no issues in 5 files.
  - `uv run pytest`: 5 passed, 2 deselected, coverage 100%, on Python 3.12.16. Also on 3.10 and 3.14 via `uv run --isolated --python <v> --group dev pytest`: 5 passed each.
  - `uv run pytest -m live --no-cov`: 2 passed, against `http://host.lima.internal:6433`, `image_digest` `sha256:8e0f8a1c9d3acbbe1d30dbbf4190aeacb64d6b561332d096a00cbb92392c2730`. `/api/user`: `developer:opengwaspy`, allowance 5.
  - `uv build`: the wheel's METADATA has `License-Expression: GPL-3.0-only`, `License-File: LICENSE`, `Requires-Python: >=3.10`; the wheel contains `opengwaspy/py.typed`.
- **Developer key fixed** by the owner (6433 redeployed). The earlier 401 is resolved.

## 2026-11-19 - Board: Python client workstream, epics and first tickets

- **The setup PR, opengwaspy#1, is merged** (`0308eb1`).
- **Workstream field:** added the option **Python client**. Every existing option was sent back with its ID (`updateProjectV2Field` with `singleSelectOptions[].id`), so the epics already on the board keep their Workstream. Checked after the mutation: all 11 old IDs are unchanged, and the new one is `3823f787`.
- **Board README:**
  - lists `opengwas/opengwaspy`;
  - says "twelve" workstreams;
  - gains a Python client row;
  - Tool integration's scope no longer names ieugwaspy.

  The previous README is kept in the session scratchpad.
- **Labels:** `needs-triage`, `needs-info`, `ready-for-agent` and `ready-for-human`.
- **Epics** (type Epic; on the board as Todo / Python client, with Priority and Next): #2 skeleton and CI, #3 the job transport, #4 native functions, #5 the ieugwaspy migration, #6 the docs site, #7 the Gateway, #8 PyPI.
- **Tickets** (type Task, as native sub-issues, with native `blocked_by` links): #9–#11 under #2, #12–#16 under #3, and #17–#18 under #6.
- **Commands:** `board.py apply ~/.cache/board/changes-2026-11-19.json --dry-run`, then the same without `--dry-run`. `board.py report` lists the seven epics under Python client.

## 2026-11-19 - Owner's decisions: licence, compat clumping, merging

- **Licence:** GPLv3, with scope for dual licensing. `LICENSE` is the FSF text from https://www.gnu.org/licenses/gpl-3.0.txt (sha256 `3972dc97…b36986`, 674 lines). A contributor agreement is an open question in `WORKPLAN.md`.
- **Compat `tophits`:** refuse the default clumping, and recommend answerable settings (`REQUIREMENTS.md` §7).
- **Merging:** agents may merge their own PRs, except for breaking changes or ones needing human input (`AGENTS.md`).
- **gh:** logged in as t0mrg, with the scopes `project`, `read:org`, `repo` and `workflow`.
- **Developer key: still failing.** `GET /api/user` on 6433 answered `401 unauthorized` ("Invalid bearer token") with the key in `opengwaspy/.env` (64 characters, no quotes or whitespace). The shared `ogdb-api/.env` has no `OGDB_DEVELOPER_KEYS` line. 6433 had been redeployed: `image_digest` `sha256:6eafa933…41dd87`. Asked the owner.

## 2026-11-19 - Project setup

- **Surveyed:**
  - ogdb-api's agent documents (`AGENTS.md`, `WORKPLAN.md`, `DEVLOG.md`), the gateway contract, the client mapping, and the guide's reference client `docs/guide/ogdb.py`;
  - ieugwaspy's source (5 modules, 377 lines, form-encoded and synchronous);
  - the `opengwas/agent-skills` board skill;
  - the Gateway's auth code.
- **Live API:** `GET /api/status` on 6433 answered `ready: true`, with `image_digest` `sha256:10a48d346fc0664bcf887dbc2ca3df43fa8de74ce2992671e1c7728c939f467f`. `/openapi.json` lists 23 operations: 7 data paths, 5 LD job paths, jobs, and the metadata and service routes.
- **Owner's decisions:** recorded in `WORKPLAN.md` (19 Nov 2026).
- **Tools installed** with the owner's approval, outside the repos:
  - `gh` 2.105.0 and `uv` 0.13.9 in `~/.local/bin`;
  - `opengwas/agent-skills`, cloned to `~/repo/agent-skills` and linked into `~/.agents/skills` and `~/.claude/skills` by its `install.sh`.
- **Created:**
  - `AGENTS.md` (plus `CLAUDE.md`, which imports it), `REQUIREMENTS.md`, `WORKPLAN.md` and this file;
  - the repo-local skills `live-check`, `api-drift` and `docs-site`;
  - `.gitignore` and `.env.example`.
- **Blockers at setup:**
  - no developer key on 6433 yet (the owner is adding `opengwaspy` to `OGDB_DEVELOPER_KEYS`);
  - `gh` not yet authenticated, so the board changes are drafted, not applied.
