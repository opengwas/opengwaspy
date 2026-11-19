# Development log

Newest entry first. Each entry: what changed, the evidence (commands, results, commit hashes, the API's `image_digest`), and anything that failed or is still at risk.

## Evidence and references

- Data API contract: `../ogdb-api/SPECIFICATION.md`, `../ogdb-api/docs/gateway-contract.md`, `../ogdb-api/docs/client-mapping.md` (read 19 Nov 2026 at ogdb-api `main`).
- ieugwaspy 1.0.6: `../ieugwaspy` (MRCIEU/ieugwaspy).
- Gateway: opengwas/opengwas-gateway @ `452c6cb` (19 Nov 2026). `Authorization: Bearer <OpenGWAS JWT>`, JWT validity 14 days, Data API under `/ogdb/*`, `429` with `X-Allowance-*`, and `X-Service-Key` for services.
- Live API: `http://host.lima.internal:6433`, `/openapi.json`, `/docs`, `/redoc`.

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
