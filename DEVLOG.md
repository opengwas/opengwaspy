# Development log

Newest entry first. Each entry: what changed, the evidence (commands, results, commit hashes, the API's `image_digest`), and anything that failed or is still at risk.

## Evidence and references

- Data API contract: `../ogdb-api/SPECIFICATION.md`, `../ogdb-api/docs/gateway-contract.md`, `../ogdb-api/docs/client-mapping.md` (read 19 Nov 2026 at ogdb-api `main`).
- ieugwaspy 1.0.6: `../ieugwaspy` (MRCIEU/ieugwaspy).
- Gateway: opengwas/opengwas-gateway @ `452c6cb` (19 Nov 2026). `Authorization: Bearer <OpenGWAS JWT>`, JWT validity 14 days, Data API under `/ogdb/*`, `429` with `X-Allowance-*`, and `X-Service-Key` for services.
- Live API: `http://host.lima.internal:6433`, `/openapi.json`, `/docs`, `/redoc`.

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
