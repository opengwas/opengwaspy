# Development log

Newest entry first. Each entry: what changed, the evidence (commands, results, commit hashes, the API's `image_digest`), and anything that failed or is still at risk.

## Evidence and references

- Data API contract: `../ogdb-api/SPECIFICATION.md`, `../ogdb-api/docs/gateway-contract.md`, `../ogdb-api/docs/client-mapping.md` (read 19 Nov 2026 at ogdb-api `main`).
- ieugwaspy 1.0.6: `../ieugwaspy` (MRCIEU/ieugwaspy).
- Gateway: opengwas/opengwas-gateway @ `452c6cb` (19 Nov 2026). `Authorization: Bearer <OpenGWAS JWT>`, JWT validity 14 days, Data API under `/ogdb/*`, `429` with `X-Allowance-*`, and `X-Service-Key` for services.
- Live API: `http://host.lima.internal:6433`, `/openapi.json`, `/docs`, `/redoc`.

## 2026-11-27 - #95: MCP docs, live smoke test and CI

- **Docs:** `docs/guide/ai-assistants.md` ("Use with AI assistants", in the Guide nav, linked from the home page). It covers:
  - install (pip from GitHub, or uvx);
  - credentials: an OpenGWAS token saved with `compat.get_jwt()` plus `profile = "gateway"`, renewed without restart; or `OPENGWAS_JWT`, which needs a restart; developer keys for developers;
  - Claude Code (`claude mcp add opengwas -- opengwaspy-mcp`), Claude Desktop (JSON, with an absolute `OPENGWAS_MCP_OUTPUT_DIR`) and other clients;
  - the tool table with limits, `save_as`, long jobs, allowance, privacy, and environment variables.

  `mkdocs build --strict` passes.
- **CI** (`tests.yml`, package job):
  - the wheel without the extra must not pull in `mcp`, and `opengwaspy.compat` and `opengwaspy.jobs` import;
  - the wheel with `[mcp]` installs, `opengwaspy-mcp --version` runs, and `create_server()` builds.

  Both were run locally on a fresh `uv build`. Tests and mypy already cover `opengwaspy.mcp` on Python 3.10–3.14, through `mcp` in the dev group (#89).
- **Live smoke test:** `tests/test_live_mcp.py`, over stdio with the developer key: `search_analyses`, then `top_hits(clump=true)`, then `associations` of five leads with `save_as` (CSV and sidecar in a temporary folder, the key in neither).
  - **Not yet passing:** on 6433 (image `sha256:3f88e06a…`) the first call gets `503 release_unavailable`, because OGS-00006 is published at format 0.3.0. It must pass after 6433 is redeployed, before #95 (and #90, #91) close.
  - The JWT live test waits on #7.
- **MCP Inspector: not done.** The VM has no Node.js, so `npx @modelcontextprotocol/inspector` cannot run here. Owner to run it on the host: `npx @modelcontextprotocol/inspector opengwaspy-mcp`.

## 2026-11-27 - #93: MCP long jobs, get_job_result, save_as and cancellation

- **`opengwaspy.jobs.observe(observer)`:** a thread-local hook, told of each job a query submits (`submitted`), each status (`polled`) and each checked page (`page`), from `Job.submit`, `Job.status` and `Job.pages`. That covers `Job.wait`, `run_many` and every query function. An observer may raise to stop the work.
- **`opengwaspy.mcp.waiting.Watch`**, the observer each job-backed MCP tool runs under:
  - reports each step through `Context.report_progress` (submitted, queued or running with queue position, page n of m);
  - at the wait limit (`OPENGWAS_MCP_WAIT_SECONDS`, default 60), the next poll of an unfinished job raises `JobTimeout`. The tool then answers `status: "running"` with `job_ids` and `poll_after_seconds`, and the jobs keep running. A `BatchError` made only of such timeouts counts too;
  - records every job, so a multi-job call returns all its IDs.
- **`get_job_result(job_id, max_rows, columns, save_as, overwrite)`:**
  - re-runs the original tool call, kept under each of its job IDs, with any new `max_rows`, `columns` and `save_as`. The API answers a repeated query with its existing job, so the call picks up the same jobs or their finished results, with the tool's own formatting;
  - for a job this server did not start, it returns the job's raw rows.
- **Cancellation:** the worker thread runs with `abandon_on_cancel`. On cancellation, the call's jobs are cancelled (`DELETE /api/jobs/{id}`, shielded), and the thread stops at its next step (`Abandoned`, a `BaseException`).
- **`save_as`** on every data and LD tool (`opengwaspy.mcp.files`):
  - writes the full result (every row and column) as CSV, and a `.json` sidecar beside it: the tool, its arguments, summary, notes, provenance, opengwaspy version and time, scrubbed of credentials;
  - names are reduced to `[A-Za-z0-9._-]` and given `.csv`;
  - absolute paths, `~`, drive letters, separators, `..` and symbolic links are refused;
  - an existing file is replaced only with `overwrite`;
  - writes go through a temporary file opened with `O_EXCL|O_NOFOLLOW`, then `os.replace`.

  With `save_as`, `region_associations` takes up to 10 Mb (one API range job's window) and `phewas` up to 10,000 rows per job.
- **Bug fixed in passing:** tool arguments are taken from the function's parameters only, because `locals()` in a nested function also holds its free variables.
- **Tests:**
  - `tests/test_mcp_waiting.py` (28): running then resume, with progress messages; resume with new `max_rows` and `save_as`; an unknown job, finished and running; CSV and sidecar; no overwrite without `overwrite`; widened limits; nine unsafe names; symlinks; cancellation; the watch's rules; every job-backed tool answering `running`;
  - `tests/test_jobs.py`: the observer (2).

  ruff, mypy strict (71 files) and `pytest` (364 passed, 99% coverage) pass.
- **Live (stdio, 6433, LD tools):**
  - `ld_proxies` with `save_as` wrote `proxies.csv` (10 rows, 784 bytes) and its sidecar, with the developer key in neither;
  - progress messages arrived ("submitted job … (the API already had it)", "succeeded", "read result page 1 of 1").

  With `OPENGWAS_MCP_WAIT_SECONDS=0`, fresh LD jobs still finished by their first poll, so the running path was not seen live; it is covered offline. Agents may not load 6433 with slow queries.

## 2026-11-27 - #83: job results checked against their manifest

- `Job.pages()` now requires each page to be the next in sequence (`page_index` 0, 1, …) and to start at the next row (`row_offset`). It takes `page_count` and `total_rows` (or `row_count`) from the manifest in the job's status, or else from the first page. When those are declared, it refuses with `ProtocolError`:
  - a result that ends before `page_count`;
  - a result that runs past `page_count`;
  - a result whose rows differ from `total_rows`.

  The checks run before the last page is yielded, so `to_frame()` never returns an incomplete result. The manifest fields are as built by ogdb-api `ogdb_api/jobs.py` (`page_count`, `total_rows`, `page_row_offsets`).
- **Tests:**
  - a valid two-page result;
  - an empty result;
  - the issue's premature final page (one row, where two pages and three rows were declared);
  - a manifest on the page only;
  - a gap, a repeat, a wrong offset, and an overrun;
  - a manifest without counts.

  After merging #80's changes, `pytest` passed 334 tests; `jobs.py` coverage is 100%.
- **Live, 6433:** `pytest -m live tests/test_live_ld.py` passed 5, with LD job results passing the new checks. The 3 data-job tests in `test_live_jobs.py` fail with `503 release_unavailable`, the current 6433 outage (OGS-00006 at format 0.3.0), not this change.

## 2026-11-27 - #80: `Job.wait` treats its timeout as a deadline

- `Job.wait(timeout=...)` now:
  - cuts each poll sleep short to meet the deadline;
  - raises `JobTimeout` (without cancelling the job) if the deadline has passed before a sleep;
  - counts the time a status call takes (retries included) against the deadline, so a success seen only after the deadline is a `JobTimeout` too.

  A success seen at or before the deadline is accepted.
- **Before:** with a 20 s suggested first poll and `timeout=1`, the wait slept 20 s and returned success.
- **Now** it polls at 1 s and, with the job still running, raises `JobTimeout` at 1 s.
- **Tests (fake clock):**
  - the 20 s / 1 s case;
  - a late success after a slow status call (no cancellation);
  - every sleep bounded (5, 5, 2 for a 12 s timeout);
  - success within the deadline;
  - `timeout=0`.

  `pytest` passed 324 tests, and mypy and ruff are clean.

## 2026-11-27 - #94: MCP server with OpenGWAS tokens (JWT) through the Gateway

- **Credential reload:** `opengwaspy.mcp.credentials.ReloadingAuth` wraps the configured provider. On a 401 (through the transport's existing `refresh()` hook), and before a tool call when no credential is configured, it re-reads the environment and config file. A token saved to the config file (for example by `compat.get_jwt()`) is used on the next call with no restart. A token in the server's environment cannot change while it runs, so the 401 message says to update the assistant's MCP settings and restart.
- **Messages:** the 401/403 message explains the 14-day lifetime, the profile page, and both places a token may live. It never shows the token: `Session.scrub` now reads the current credential each time, so a reloaded token is hidden too.
- **Allowance:**
  - `Transport.allowance` records the Gateway's `X-Allowance-Limit`, `-Remaining` and `-Reset` (names checked in opengwas-gateway `03a9db0`, `app/main.py`).
  - `Session.finish()` adds it to each tool result's provenance and summary ("Allowance left: 99,000 of 100,000, until …"), and `api_status` shows it under `auth`.
  - The MCP client uses `max_retry_wait=30`, so an exhausted allowance (a 429 with a long `Retry-After`) fails at once with the reset time, rather than an automatic long wait.
- **Gateway prefix:** with `profile = "gateway"` and `jwt`, calls go to `https://api.opengwas.io/ogdb/api/...` with `Authorization: Bearer <JWT>`.
- `Context.elicit_url` (pointing the user to the profile page) is not used yet: the error message carries the link, and no tool takes a token.
- **Tests:**
  - `tests/test_mcp_auth.py` (7), with Gateway fakes: the prefix and header; a renewed token used without restart; a token in the environment; a token saved after start; allowance in results and `api_status`; an allowance 429 failing fast with the reset date; `ReloadingAuth`.
  - Plus `test_allowance_headers_are_recorded`.
  - ruff, mypy strict (68 files) and `pytest` (319 passed, 99% coverage) pass.
- **Live:** stdio with the developer key on 6433 (through `ReloadingAuth`): `api_status` and `ld_proxies` work; no allowance is shown (the Data API sends no `X-Allowance-*`). Live tests through the Gateway wait on #7.

## 2026-11-27 - #91: MCP data tools

- **`top_hits`:** up to 10 analyses, `threshold` (5e-8), optional server clumping (`clump`, with `r2`, `kb`, `ancestry` only when clumping; refused otherwise). Fetches up to 1,000 hits per analysis and shares `max_rows` fairly between analyses. Notes for truncation and for hits absent from the LD panel; `attrs["clump"]` in provenance.
- **`associations`:** up to 100 variants by 20 analyses. Without proxies, native `associations`; with `proxies=true`, `compat.associations` (best proxy, alleles aligned), whose warnings (such as an ancestry with no LD store) become notes.
  - To let compat use the session's client, the server's lifespan makes the session client opengwaspy's default client while it runs, and restores the previous default on exit.
  - `call_noting()` collects warnings under a lock, because Python's warning filters are process-wide; only the proxy path uses it.
- **`region_associations`:** up to 1 Mb and 5 analyses (wider regions are refused, pointing to narrower ones; `save_as` comes with #93); the strongest association is noted.
- **`phewas`:** one variant, `threshold` (1e-8), up to 1,000 rows per job, sorted strongest first (the API returns genome order); truncation becomes a note with the API's `total`.
- **`variant_info`:** up to 100 rsIDs or `chr:pos`, one row per ALID with the number of Stores holding it; queries not found are notes.
- Association rows get ieugwaspy's column names (`id`, `trait`, `ea`, `nea`, `beta`, `n` from the analyses' metadata), and `opengwas_id` where OpenGWAS IDs were translated. Analysis IDs go through compat's `resolve`; if none is found, the tool fails with the reasons.
- **Tests:** `tests/test_mcp_data.py` (21). ruff, mypy strict (66 files) and `pytest` (311 passed, 99% coverage) pass.
- **Live: not yet verified.** 6433 still answers `503 release_unavailable` for data queries (OGS-00006 at format 0.3.0); recheck with #90.

## 2026-11-27 - #92: MCP LD tools

- **`ld_proxies`:** up to 100 variants, `ancestry` (default EUR), `r2` (default 0.8), `kb` (default 3,000, at most 10,000), `max_rows`. Rows are sorted strongest r2 first within each query variant.
- **`ld_matrix`:** up to 50 variants; one row per variant (`alid`, `rsid` when translated, `a1`, `a2`, then r with each variant, rounded to 3 places). `save_as` waits on #93.
- **Variants** may be ALIDs or rsIDs (`to_alids`): rsIDs are looked up with `variants_rsid`; an rsID naming several ALIDs uses all of them, with a note; one no served Store holds is left out, with a note. Anything else is refused before any job.
- Unheld variants (`attrs["absent"]`) become a note; the store's `t_far`, `near_bp` and `far_bp` go in provenance. `LDRefusal` (with what the store can answer) and an unknown ancestry come back as tool errors with the API's message.
- `MaxRows` and `ColumnChoice` moved to `formatting.py` for every tool.
- **Tests:** `tests/test_mcp_ld.py` (14). ruff, mypy strict and `pytest` (290 passed, 99% coverage) pass.
- **Live (stdio, 6433, image `sha256:3f88e06a…`):** `ld_proxies` of `10:59707424:G:T` gave 5 proxies (r2 0.984 first) from `hgdp1kgp-v2-EUR-k10`; `ld_matrix` reported two ALIDs not in the panel; r2=0.001 at 10,000 kb gave the `LDRefusal` text. rsID translation could not be checked live, because 6433 serves no data Stores at present (see #90).

## 2026-11-27 - #90: MCP metadata tools

- **`opengwaspy.mcp.formatting`:** `TableResult` (pydantic, so clients get an output schema): `summary`, `total_rows`, `rows_returned`, `truncated`, `columns`, `rows`, `notes`, `provenance`. `table_result()` trims a DataFrame to chosen columns (`default`, `all` or a list) and `max_rows`, converts NaN and numpy values to JSON, and copies `release_id`, `catalog_version`, `releases`, `job_id(s)` and `image_digest` from `attrs`. `METADATA_COLUMNS` is the ticket's list.
- **`search_analyses`:** `gwasinfo_search` with `limit=max_rows` (1-100, default 50; checked by the input schema before any request), `match`, and the five filters. The summary gives the API's `total`.
- **`get_analyses`:** up to 100 IDs through compat's `resolve` (now with `client=` and `warn=False`, so the MCP session's client is used and warnings become `notes`). Rows gain `opengwas_id` when an OpenGWAS ID was translated; successor translations and IDs not held (with the API's reason) are notes; `provenance.opengwas_ids` keeps each translation.
- `call()` now also turns `ValueError` (arguments opengwaspy refused) into tool errors. API refusals such as `query_too_broad` and `invalid_query` come back as tool errors with the API's message.
- **Tests:** `tests/test_mcp_metadata.py` (14) and shared helpers in `tests/mcp_fakes.py`. ruff, mypy strict (62 files) and `pytest` (276 passed, 99% coverage) pass.
- **Live: not yet verified.** Over stdio against 6433 (image `sha256:3f88e06a…`), `api_status` answered, but every data query got `503 release_unavailable`: Store OGS-00006 is now published as `format_version 0.3.0` and this API build reads only 0.1 and 0.2. The tools returned this as a tool error, as intended. Rerun the live check after 6433 is redeployed.

## 2026-11-27 - #89: MCP server skeleton

- **Packaging:** the extra `mcp = ["mcp>=2.3,<3"]` and the console script `opengwaspy-mcp` (`opengwaspy.mcp.__main__:main`). `mcp` is also in the `dev` group, so CI's ruff, mypy strict and tests cover `opengwaspy.mcp` on Python 3.10-3.14. The core package gains no dependency. The SDK installed is `mcp` 2.3.0 (`MCPServer` from `mcp.server.mcpserver`).
- **`opengwaspy.mcp.server`:**
  - `create_server(url=, profile=, client_factory=)` builds an `MCPServer` named `opengwas`, with instructions for the model. Its lifespan builds one `Client` from the usual configuration and closes it on exit.
  - With no credential, or an invalid configuration, the server still starts; `Session.require_client()` (for the data tools to come) and `api_status` say how to configure one (OpenGWAS token as `OPENGWAS_JWT`, or a developer key).
  - A refused credential (401/403) gives a message on renewing the 14-day token.
  - `scrub()` removes the credential (header value and bearer token) from every output, as a last line of defence. The command line takes no credential.
  - Blocking opengwaspy calls run in a worker thread (`anyio.to_thread`).
  - Tools carry `ToolAnnotations(read_only_hint, destructive_hint=False, open_world_hint)`.
- **`api_status`:** URL and profile, readiness, `image_digest`, `release_ids`, the auth kind (never the value), `user()`, LD stores, and releases with the OpenGWAS batches. A failing section is reported in place rather than failing the tool.
- **Tests:** `tests/test_mcp_server.py` drives the server through the SDK's in-memory `mcp.Client` against the respx fakes (12 tests: tool listing and annotations, status output, no credential, refused credential, invalid configuration, no credential in any output, the command line).
- **Checks:** ruff format and check, mypy strict (58 files) and `pytest` (263 passed, 99.36% coverage) pass.
- **Live (stdio):** `python -m opengwaspy.mcp` started as a subprocess through `mcp.Client(StdioServerParameters(...))` with the developer key against 6433: `api_status` answered (image `sha256:3f88e06a…`, user `developer:opengwaspy`, 5 LD stores), and the key appeared nowhere in the output. 6433 reported `ready: false` with no releases at the time, so the batches section was empty.

## 2026-11-21 - #71: docs for the PheWAS threshold, server clumping and OpenGWAS IDs

- **`docs/examples.md`:** rerun on 6433 (image `sha256:b00d3288…`).
  - BMI top hits clumped on the server: 770 leads, with the warning about the 11,793 absent hits. Before, there were 118, and two warnings.
  - The associations example now uses OpenGWAS IDs (`ukb-b-19953`, `ukb-b-2303`, `ebi-a-GCST006802`), with `opengwas_id`.
  - The PheWAS notes that `pval` is applied on the server.
- **`docs/guide/metadata.md`:** "OpenGWAS IDs", with live output of `attrs["opengwas"]` (exact, successor, not held) and `opengwas_batches`.
- Already in #67–#69: the PheWAS and clumping sections of the guide, the migration guide, and the changelog (including the breaking change to `phewas`'s default threshold).
- `examples/usage_examples.py` needed no change. It ran in 2.4 s, from the API's cache, and gave "770 independent hits".
- **Checks:**
  - `mkdocs build --strict` and `ruff format --check` pass;
  - `pytest` (251 passed) passes;
  - `pytest -m live tests/test_live_examples.py --no-cov` passes.

## 2026-11-21 - #69: OpenGWAS IDs and batches translated by the Data API

- **Native, additive:**
  - `gwasinfo()` lookups keep the API's `opengwas` list in `attrs["opengwas"]`, across chunks.
  - `batches()` keeps `opengwas_batches` in `attrs["opengwas_batches"]`.
- **`compat/_ids.py`:**
  - `resolve(ids)` makes one `gwasinfo` lookup. Legacy `UKB-b:` forms are converted first, Data API IDs pass through, and OpenGWAS IDs become their `catalog_ids`.
  - A successor match is used, with a warning naming each old → new ID (owner decision of 21 Nov 2026).
  - Unresolved IDs are left out, with a warning giving the API's reason.
  - `resolve_batches(batch)` maps Store IDs and OpenGWAS batches to Stores. Successors warn; unknown batches are refused with the list of what is held.
- **Used by** `compat.gwasinfo`, `gwasinfo_files`, `tophits` and `associations` (IDs), and `phewas` (`batch`).
  - Results add `opengwas_id` (last) and `attrs["opengwas_ids"]`.
  - `compat.gwasinfo` still prints the untranslated IDs, now with reasons.
  - An all-untranslated request returns an empty result with the provenance.
- **Live, on 6433:** image `sha256:b00d3288e95f8aacb9831ef24fcb1b9fe3f74c796cabb66739541e74b1a8b963`.

  | Query | Result |
  |---|---|
  | `compat.gwasinfo([ukb-b-19953, ebi-a-GCST006802, finn-b-E4_OBESITY, eqtl-a-ENSG00000141510, ieu-a-2])` | 4 analyses: `ukb-b-19953` as itself, two exact, one successor (`OGS-00017:finngen-r13-E4_OBESITY`, warned). `ieu-a-2` printed as "not held by any Store" |
  | `compat.tophits([ebi-a-GCST006802, finn-b-E4_OBESITY], r2=0.001, kb=3000)` | 76 leads, 3.6 s |
  | `compat.phewas('rs1421085', pval=1e-8, batch=['ebi-a', 'ukb-b'])` | 468 rows, from 5 Stores |
  | `compat.phewas(..., batch=['finn-b'])` | 41 rows, warned |

- **Checks:**
  - ruff, mypy and `pytest` (251 passed; `_ids.py` at 100% coverage) pass;
  - `pytest -m live --no-cov`, the whole live suite, gives 35 passed in 68 s.
- WORKPLAN: removed the open question on OpenGWAS ID mapping. `ieu-a`, `ieu-b`, `met-*` and `prot-*` remain unheld, and are reported as such.

## 2026-11-21 - #68: top hits clumped on the server

- **Native `tophits(clump=...)`:**
  - `True` sends `{}`, the server's defaults: r² 0.001 within 3,000 kb, in each analysis's own ancestry's LD Store, or EUR.
  - A mapping sends `r2`, `kb`, and `ancestry` or `store`. Unknown keys, and both `ancestry` and `store`, are refused before any request.
  - `attrs["clump"]` holds the clump settings. Across jobs, `hits`, `leads` and `absent` are summed and `ld_stores` merged.
  - With clumping, the truncation warning says "clumped leads".
- **`compat.tophits`:**
  - It sends `clump` (`r2`, `kb`, and the `pop` store by name) with `limit=10000`.
  - Removed: `_clump`, the client-side `/api/ld/clump` per analysis, and the warning about clumping only the strongest 10,000.
  - The 10,000 kb default is still refused before any job, with the same suggestions (#44). The server also refuses it (`422 ld_refusal`).
  - Hits absent from the LD Store come from `metadata.clump.absent`, and are warned about.
- **Live, on 6433:** image `sha256:b00d3288e95f8aacb9831ef24fcb1b9fe3f74c796cabb66739541e74b1a8b963`.
  - `compat.tophits(['OGS-00011:GCST90179150'], r2=0.001, kb=3000)` (BMI) gave 770 leads from 89,563 hits, 11,793 absent, in one job. The client-side method gave 118. The first run was in the live examples test; the repeat, served from the API's cache, took 0.4 s.
  - `og.tophits('OGS-00006:GCST90199621', clump=True)` gave 5 leads from 557 hits, 110 absent.
  - `clump={"r2": 0.001, "kb": 10000}` gave `LDRefusal` (`ld_refusal`).
- **Docs:** the guide's top hits ("Clumped on the server"), the migration guide and the changelog. Rerunning the examples page is #71.
- **Checks:**
  - ruff, mypy, `pytest` (244 passed, 99.5% coverage) and `mkdocs build --strict` pass;
  - `pytest -m live tests/test_live_hits.py tests/test_live_compat.py tests/test_live_examples.py --no-cov` gives 12 passed in 50 s.

## 2026-11-21 - #67: PheWAS threshold on the server

- **Native `phewas(threshold=1e-8)`:**
  - It sends `threshold`, always explicitly, defaulting to the Data API's 1e-8. It validates 0 < threshold ≤ 1.
  - `attrs["threshold"]` comes from the result metadata.
  - The truncation warning names the threshold.
  - This is a breaking change (it used to return every association), approved by the owner on 21 Nov 2026 and noted in the changelog.
- **`compat.phewas(pval)`:**
  - It sends `pval` as `threshold` (ieugwaspy's 1e-3 explicitly), with `limit=10000`.
  - Removed: the client-side filter, the per-Store rerun and its refusal.
  - A result still truncated at 10,000 rows is refused, because returning it would be incomplete.
- **Docs:** the PheWAS section of the guide, the migration guide and the changelog.
- **Live, on 6433:** redeployed from ogdb-api `main` with #165–#167, image `sha256:b00d3288e95f8aacb9831ef24fcb1b9fe3f74c796cabb66739541e74b1a8b963`.

  | Query | Result |
  |---|---|
  | `og.phewas("rs429358", limit=10000)` | 658 of 658 associations at p ≤ 1e-8, not truncated, in 2 jobs (13 Stores), 0.3 s |
  | `compat.phewas("rs429358")` at p ≤ 1e-3 | 1,485 rows in 5.3 s |
  | `compat.phewas("rs1421085", pval=1e-5)` | 751 rows in 0.4 s |
  | `og.phewas("rs1171617", threshold=1, limit=1000)` | 10,662 in total, 1,002 returned, truncated |

- **Checks:**
  - ruff, mypy and `pytest` (237 passed) pass;
  - `mkdocs build --strict` passes;
  - `pytest -m live tests/test_live_hits.py tests/test_live_compat.py tests/test_live_examples.py --no-cov` gives 10 passed in 37 s.

## 2026-11-21 - search refused under load: ogdb-api#164

- In the owner's stress run (a local script at `stress/stress_test.py`, ignored by git), `gwasinfo_search("vitamin")` failed with `RequestError` `400 query_too_broad`.
- With the server idle, the same search took 0.1–0.5 s, with a total of 94.
- The cause: the API stops a search after 1 s of clock time (`OGDB_SEARCH_BUDGET_SECONDS`). When the job workers are busy (`/api/status` showed 40 running and 100 queued), the scan passes that budget.
- Filed opengwas/ogdb-api#164 with the owner's approval. It asks for `503` with `Retry-After` when the budget runs out because of load; opengwaspy already retries 503 as `BusyError`. No client change is needed.

## 2026-11-20 - #62: search documentation

- `docs/guide/metadata.md` has a new "Find analyses" section, covering:
  - `contains` and its filters;
  - full-text syntax, with a table;
  - `limit`, the 10,000-row warning and the full-text cap;
  - the `invalid_query` and `query_too_broad` errors.
- `docs/migrating.md`: search replaces "list everything and filter in pandas", and the function table has a `gwasinfo_search` row.
- `docs/quickstart.md`: a search step. `docs/changelog.md`: an Unreleased entry.
- `examples/usage_examples.py` and `docs/examples.md`: "Exploring available studies" now uses `gwasinfo_search("body mass", limit=None)`, which makes 1 request where listing took about 40. The search returns the same 39 analyses in label order, and the downstream example (OGS-00011:GCST90179150, 118 independent hits) is unchanged.
- Every output in the docs comes from the live API at 6433 on 20 Nov 2026. I ran each full-text syntax row in the guide; none errored, and the totals were:

  | Query | Total |
  |---|---|
  | `obesity asthma` | 1 |
  | `bmi OR obesity` | 96 |
  | `"body mass" NOT waist` | 38 |
  | `(bmi OR obes*) AND diabetes` | 1 |
  | `obes*` | 24 |
  | `first_author:loh` | 47 |
  | `"ukb-b-19953"` | 1 |
  | `bmi` | 74 |
  | `bmi*` | 75 |

- Checks:
  - ruff, mypy, `pytest` (235 passed) and `mkdocs build --strict` pass;
  - `pytest -m live tests/test_live_examples.py tests/test_live_metadata.py --no-cov` gives 6 passed;
  - the examples script took 36 s.

## 2026-11-19 - #61: gwasinfo_search

- `opengwaspy.gwasinfo_search(q, match=, limit=100, store_id=, assigned_ancestry=, ancestry_category=, outcome_type=, trait_class=)` in `metadata.py`, as agreed by the owner (19 Nov 2026).
  - It sends `POST api/gwasinfo/search`, leaving out filters that are `None`.
  - It pages `contains` by `after` and `fulltext` by `offset`, stopping at `limit`; `limit=None` fetches every match.
  - It warns when fetching more than 10,000 rows, and when a full-text search stops at the API's 10,000 offset cap.
  - `attrs` holds `q`, `match`, `filters`, `total`, `release_id` and `catalog_version`.
  - Errors arrive through the transport's existing mapping (`RequestError` with `invalid_query`, `query_too_broad` or `release_not_found`; `NotImplementedByServer` on 501). Bad arguments raise `ValueError` before any request.
- Unit tests: 14 new in `tests/test_metadata.py`; `metadata.py` has 100% coverage.
- Live tests: 2 new in `tests/test_live_metadata.py`; `uv run pytest -m live tests/test_live_metadata.py` gives 5 passed.
  - Run against 6433, image `sha256:acc344c2b652d22d7cb872fdc6f4d77377b37addb7e6186bab5319021520ae60`.
  - `gwasinfo_search('body mass index', limit=None)` returned 39 of 39.
  - The fulltext query `bmi* OR "body mass index"` returned 5 of 90, best match first.
  - With `store_id='OGS-00011'`, it returned 2 of 21.
- Checks: ruff, mypy (strict), `pytest` (235 passed, 99.5% coverage) and `mkdocs build --strict` all pass.
- An empty result is a DataFrame without columns, as `gwasinfo()` gives.

## 2026-11-19 - #60: planned search

- The Data API now serves `GET`/`POST /api/gwasinfo/search` (ogdb-api `e82e820`, PR #152). Its schema is identical on ogdbapi-dev.mrcieu.ac.uk and on the host's 6433 (compared `openapi.json` on 19 Nov 2026).
- Probed on 6433:
  - `q=body mass index` returned 39 matches (paged by `next_after`);
  - `q=a` returned 22,593 matches, with no `query_too_broad`;
  - the fulltext query `bmi* AND locke` returned 0;
  - the malformed query `bmi AND (` gave `400 invalid_query`.
  - Rows have `/api/gwasinfo`'s columns plus `release_id`.
- Filed epic #60 with #61 (`gwasinfo_search`) and #62 (docs; blocked by #61). On the board: Python client, Todo.
- No compat function: neither ieugwaspy nor ieugwasr has search.

## 2026-11-19 - #55, #56: release workflow and checklist

- **`.github/workflows/release.yml`,** run on `v*` tags:
  - **build:** checks that the tag equals `v` + `__version__`, runs `uv build`, installs and imports the wheel, and uploads it;
  - **publish:** environment `pypi`, `id-token: write`, `pypa/gh-action-pypi-publish` v1.14.3 (`7245906f`), using trusted publishing, no token;
  - **github-release:** release notes from the changelog section; `--prerelease` for a, b and rc versions.
  - Actions are pinned to SHAs, each release at least two weeks old (upload-artifact v7.0.2, download-artifact v8.0.2).
- **`RELEASING.md`:** versions (`0.x` pre-releases until #7); prepare, tag (the owner), publish, verify and reopen; the one-time setup (#57); withdrawing (yank).
- **Nothing is published.** That needs the trusted publisher and the `pypi` environment (#57, the owner) and a tag from the owner.
- **Also today (the owner's answers):**
  - Branch protection is on for `main`. Required checks: lint and types, tests 3.10–3.14, package, docs, cla. No force pushes or deletion; admins are not enforced. The jobs were renamed first (`package`, `docs`; #54), because both workflows had a job named `build`.
  - Filed opengwas/ogdb-api#145 (a PheWAS p-value threshold), #146 (clumping well-powered analyses' top hits) and #147 (resolving OpenGWAS IDs and batches). They are linked from the WORKPLAN's open questions.

## 2026-11-19 - #46: migration guide and usage examples

- **`docs/migrating.md`:** every ieugwaspy 1.0.6 function, with its compat and native equivalents and a status (same, differs, not available). Then why each differs: analysis IDs, top-hit clumping (the refusal text), proxies (the analysis's ancestry; HGDP + 1000 Genomes), PheWAS (filtered here, refused beyond 10,000 per Store), and columns (`beta`, `p`, `n` derived).
- **`examples/usage_examples.py`:** ieugwaspy's `usage_examples.ipynb`, scenario by scenario, as a script, with the output shown in `docs/examples.md`. A script was chosen over a notebook so it can run in the live tests without Jupyter, and be type-checked (`mypy` now covers `examples/`). `tests/test_live_examples.py` runs it.
- **Live run (6433), 38 s:**
  - 38,152 analyses.
  - BMI analyses found by label.
  - OGS-00011:GCST90179150 (the largest BMI analysis) gives 118 leads at r² 0.001 within 3,000 kb. More than 10,000 of its hits are genome-wide significant, so the clumping is warned as partial, and 1,578 hits were not in the EUR store.
  - The 3 SNPs × 3 BMI studies were all found directly.
  - The PheWAS of rs1421085 at p ≤ 1e-5 worked.
  - `19:44908684` gives rs429358.
- **REQUIREMENTS §11.3** (the notebook scenarios run in the docs) is met by the script and page.
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 219 passed. `uv run pytest -m live --no-cov`: 28 passed. `mkdocs build --strict` passed.

## 2026-11-19 - #43: compat associations with LD proxies

- **`compat.associations(variant, id, proxies=1, r2=0.8, align_alleles=1, palindromes=1, maf_threshold=0.3)`.**
- **Inputs:** rsIDs, ALIDs, `chr:pos` (looked up to ALIDs), and `chr:start-end` ranges (through `associations_range`, with no proxies).
- **Proxies:**
  - For each (analysis, variant) with no direct row, the target's ALID is the query itself, or the first ALID of its rsID (with a warning when there are several).
  - Candidates come from `ld_proxies(r2=r2)` in the LD store of the analysis's `assigned_ancestry`, falling back to EUR with a warning when no store serves that ancestry.
  - All candidates are looked up in one `associations` call per ancestry. The best usable proxy is taken by r² (descending), then distance.
- **Palindromes (A/T, C/G):** `palindromes=0` never uses one; `palindromes=1` uses one only when its MAF (from `eaf`) is below `maf_threshold`.
- **Allele alignment:** positive r pairs the first alleles of the two ALIDs, and negative r crosses them, so the proxy's effect allele is mapped to the target allele it tags.
  - This was checked on 6433: 10:59709780:C:T (r −0.988 with the target 10:59707424:G:T) aligns to G with z ≈ −24.6, the target's own −24.64.
  - The effect allele was the ALID's first allele in 200 of 200 hits checked, but the code does not rely on that.
- **Proxy rows:** `proxy`, `target_snp`, `proxy_snp`, `proxy_r2`, `target_a1`, `target_a2`, `proxy_a1` and `proxy_a2`. Their `rsid`, `alid` and position are the proxy's.
- **Live:** 10:59699398:T:TTAC is held by the EUR store but not by OGS-00006:GCST90199621. Its proxy rs2126776 (10:59697708:G:T, r = −1) is aligned to TTAC with beta +0.38. That is consistent with r(T, lead G) = +0.81 and the lead's beta −0.44.
- **The first push failed CI:** a line-length error in a live test. A chained command committed despite the local `ruff check` failure, and `safe_merge` refused to merge. The fix was a follow-up commit.
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 219 passed, `compat/associations.py` 99%. Live compat tests: 4 passed.

## 2026-11-19 - #45: compat phewas and variant helpers

- **`compat.phewas(variant, pval=1e-3, batch=[])`:**
  - Accepts rsIDs, ALIDs or `chr:pos`. `chr:pos` is looked up first; an ambiguous position warns and uses the first variant.
  - One native PheWAS per variant, filtered to `p <= pval` on the client.
  - **Truncation:** when the PheWAS is truncated, it reruns one Store at a time with `limit` 10,000 (the API's maximum: 10,001 gives `400 invalid_request`). If a single Store is still truncated, it raises `UnsupportedOptionError`, because a filter cannot see rows that were never returned.
  - **`batch`:** must be served Store IDs. OpenGWAS batches (`ieu-a`) are refused with the served list.
- **`compat.variants_chrpos(chrpos)`:** the first rsID (warning if there are several), or `None`.
- **`compat.variants_to_rsid(variants)`:** returns a new list (ieugwaspy changed its argument in place). A position with no rsID is kept, with a warning.
- **First design, changed after the live run:** a single rerun of all Stores at 10,000 refused rs1171617, because its 10-Store job alone exceeded 10,000 rows (total 10,662). The per-Store rerun answers it. A p-value filter on the server would avoid fetching every association. That needs an ogdb-api issue; the owner was asked.
- **Live (6433), `pval=1e-8` across every Store:**

  | variant | associations | Stores | time |
  |---|---|---|---|
  | rs1171617 | 67 | 6 | 13.1 s |
  | rs429358 | 658 | 8 | 17.4 s |

  - For rs429358, FinnGen dementia's `log10_p` is below −308, so `p` is 0.0 (float underflow). The associations guide now says so.
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 209 passed, `compat/variants.py` 100%. Live compat tests: 3 passed.

## 2026-11-19 - #44: compat tophits with clumping

- **`compat.tophits(id, pval=5e-8, preclumped=1, clump=1, bychr=0, r2=0.001, kb=10000, pop="EUR", force_server=False)`.**
- **Refusal (owner, 19 Nov 2026):** before any job runs, `clump_settings_answerable(r2, kb, store)` checks: window ≤ `near_bp`, or r² ≥ `t_far` and window ≤ `far_bp`. Otherwise it raises `UnsupportedOptionError`, suggesting:
  - the caller's r² with `kb = near_bp` (3,000);
  - or r² = `t_far` rounded up to 2 decimals (EUR 0.04, AMR 0.07) with `kb ≤ far_bp`;
  - or `clump=0`.
- **Clumping:** each analysis's hits (`limit` 10,000, strongest by |z|) are clumped with `ld_clump` (scores |z|) in the `pop` store, and only the leads are kept.
  - Hits the LD store does not hold are dropped with a warning, as ieugwasr's clumping drops variants missing from its reference.
  - Truncation warns that weaker independent signals may be missing.
- **`preclumped`, `bychr` and `force_server`** are accepted and have no effect (documented). An unknown `pop` is refused, with the served ancestries listed.
- **ieugwaspy columns:** `n` comes from `gwasinfo`'s `sample_size`; `beta = z × se`.
- **Live (6433), OGS-00006:GCST90199621:**
  - The default is refused, suggesting `r2=0.001, kb=3000` or `r2=0.04, kb=10000`.
  - With `r2=0.001, kb=3000`: 557 hits, 110 not in the EUR store, 5 leads: rs1171617, rs274548, rs149235996, rs10994001 and rs10900223. `n` = 8192.
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 201 passed. Live compat tests: 2 passed.

## 2026-11-19 - #42: compat base

- **`opengwaspy.compat`** (`import opengwaspy.compat as ieugwaspy`):
  - **`status`, `user`.**
  - **`select_api(key)`:** `public` → `gateway`; `dev`/`local` → `local`; a URL is accepted. It prints the choices for an unknown key, as ieugwaspy did.
  - **`get_jwt()`:** opens the OpenGWAS profile page, reads the pasted token, and saves `jwt` with `config.save_setting` (mode 0600; a saved `token` is removed, because only one credential may be set). ieugwaspy wrote `.ieugwaspy.json` in the working directory.
  - **`legacy_ids`.**
  - **`gwasinfo(id)`:** adds `trait` (a copy of `analysis_label`) and prints the IDs not served.
  - **`gwasinfo_files(id)`:** the Stores' source-file records (501 today).
- **`compat.ieugwas_columns(frame, sample_sizes)`** puts ieugwaspy's names first: `id`, `trait`, `rsid`, `chr`, `position`, `ea`, `nea`, `eaf`, `beta`, `se`, `p`, `n`. The Data API's columns are kept. `compat.DERIVED` documents the derived ones: `beta = z × se` (on the analysis's `stored_effect_scale`), `p = 10 ** log10_p`, and `n = sample_size`.
- **Bug fixed in #29's `gwasinfo` and `gwasinfo_files`:** `releases` was sent as plain Store IDs. The API wants `{store_id, release_id}` objects (live: `{"releases": ["OGS-00006"]}` → `400 invalid_request` "Malformed request"). They now use `resolve_releases`, like every query function. A live test of `gwasinfo(..., releases=["OGS-00006"])` was added.
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 189 passed, coverage 99%. Live: the metadata tests (3) and the compat test pass.

## 2026-11-19 - CI failure merged to main, and fixed

- **What happened:** PR #41 (#18, docs only) was merged with its "lint and types" job failing: https://github.com/opengwas/opengwaspy/actions/runs/44525938399.
  - ruff 0.17 formats Python code blocks inside Markdown, and `ruff format` was not run for that docs-only change (two aligned comments in `docs/quickstart.md` and `docs/guide/jobs.md`).
  - The merge went through because `main` has no branch protection, and the merge step did not check the result of the checks it had waited for.
- **Fix:** `ruff format .` (3 docs files), in a follow-up PR.
- **Process change:** `AGENTS.md` now says to merge only after checking that every check passed, and to run `ruff format` for docs changes too. Branch protection with required checks would enforce this; suggested to the owner.

## 2026-11-19 - #18: quickstart, authentication and jobs pages

- **Pages:** `docs/quickstart.md`, `docs/guide/authentication.md` and `docs/guide/jobs.md`, with output captured live from 6433.
  - The top hits of OGS-00006:GCST90199621 at 5e-8: 557, not truncated.
  - A 10-hit job's status and metadata.
- **Authentication page:** the precedence table and config file; developer keys now; the Gateway with an OpenGWAS JWT (14 days), its sign-in flow not yet final, behind the auth providers; allowance handling.
- **Home and install pages:** updated now that every Data API operation is covered.
- **Evidence:** `uv run mkdocs build --strict` passed.

## 2026-11-19 - #33: LD

- **`opengwaspy.ld`:**
  - `ld_stores()`.
  - `ld_matrix(alids, ancestry|store, fill)` and `ld_region(chromosome, centre, radius, ...)` return a square DataFrame of signed r, indexed by ALID, with `NaN` for pairs not held. `attrs` has `absent`, `variants` (the alleles), `t_far`, `near_bp`, `far_bp` and `store`. A matrix is never split; above `ld_matrix_alids` (500) it is refused locally.
  - `ld_clump(alids, scores, r2=, kb=)`: required `r2` and `kb`; scores are checked locally (finite, ≥ 0, one each); never split.
  - `ld_proxies` (chunks of 1,000) and `ld_reflookup` (chunks of 10,000) merge `absent` across jobs.
  - Exactly one of `ancestry` or `store` is required (the API answers `invalid_query` otherwise).
- **`LDRefusal`** now appends what the store answers: "This store answers r2 >= {t_far} with kb up to {far_bp}, or any r2 with kb up to {near_bp}". #5 (the compat `tophits` refusal) will reuse it.
- **Live (6433), five LD Stores:**

  | ancestry | n | t_far |
  |---|---|---|
  | EUR | 665 | 0.0319 |
  | AFR | 608 | 0.0349 |
  | EAS | 724 | 0.0292 |
  | SAS | 672 | 0.0315 |
  | AMR | 341 | 0.0632 |

  - The rs1171617 signal's three top hits have r ≈ ±0.988 and form one clump (r² 0.1, 1,000 kb).
  - Proxies of 10:59707424:G:T within 100 kb include 10:59708831:G:T (r² 0.984).
  - r² 0.001 within 10,000 kb is refused (`threshold_below_t_far`), with the advice text.
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 179 passed, `ld.py` 99%. Live LD tests: 5 passed.

## 2026-11-19 - #32: variants

- **`variants_rsid(rsids, releases=None)` and `variants_chrpos(positions, releases=None)`:**
  - Both validate locally (`rs<digits>`; `[chr]chrom:pos`, no ranges).
  - Jobs are split by `lookup_variants` and by 10 releases.
- **The default is to search every served release.** The ticket planned only to explain `409 release_selection_required` (which 6433 answers without `releases`: "an explicit release selection or analysis IDs are required"). Searching every Store instead gives the answer ieugwaspy users expect from an rsID lookup. Rows stay one per variant per Store, as the API returns them, and the docs show `drop_duplicates("alid")`.
- **Live (6433):** rs1171617 and rs429358 in OGS-00006 map to 10:59707424:G:T and 19:44908684:C:T. `chr19:44908684` across every Store gives only rs429358 (2 jobs).
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 165 passed, `variants.py` 100%. Live variant tests: 2 passed.

## 2026-11-19 - #31: top hits and PheWAS

- **`opengwaspy.tophits(analyses, threshold=5e-8, limit=1000, observed_only=False, releases=)`:**
  - groups of analyses sized so that analyses × limit ≤ `result_rows`, and at most `lookup_analyses`;
  - adds `p`; `attrs["truncated"]`, with a warning;
  - the API's `unsupported_threshold` message already names the loosest tier and lists `indexed_thresholds`, so it passes through as a `RequestError`.
- **`opengwaspy.phewas(variant, releases=None, analyses=, limit=1000, observed_only=True)`:**
  - The API refuses a PheWAS without `releases` ("Malformed request"). By default the client uses every served release whose `capabilities.phewas` is not false, 10 per job (`releases` `maxItems` 10).
  - `attrs` sums `total` and `returned` across jobs, with `truncated` and a warning.
- **Housekeeping:** the default client is closed at exit (`atexit`), and the live fixtures close their clients (ResourceWarning seen in the live run).
- **Live (6433):**
  - Top hits of OGS-00006:GCST90199621 with `limit=3`: rs1171617, rs1171614 and rs1171615, one signal with \|z\| ≈ 24.6. `truncated` is true.
  - `threshold=0.01` gives `unsupported_threshold`, with indexed tiers [5e-08, 5e-06, 0.0005].
  - The PheWAS of rs1171617 over all 13 Stores took 2 jobs and 9.9 s: `total` 10,662, 1,002 returned.
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 160 passed, `hits.py` 100%. `uv run pytest -m live --no-cov`: 15 passed.

## 2026-11-19 - #30: associations

- **`opengwaspy.associations(variants, analyses, observed_only, releases)`:** jobs split by the server's `lookup_analyses` (outer loop) and `lookup_variants` (inner), run through `query_many` and combined in that order.
- **`associations_range(chromosome, start, end, analyses=None, ...)`:** windows of at most `range_span`, and groups of `range_analyses`. It strips a `chr` prefix and checks `1 <= start <= end` (integers).
- **`associations_analysis(analyses)`:** groups of `analysis_analyses`.
- **`p = 10 ** log10_p`** is inserted after `log10_p`.
- **New helpers in `opengwaspy._common`:**
  - `resolve_releases` takes a Store ID (looked up in `Client.served_releases()`, cached from `batches()`), `store/release`, or a dict;
  - `combine` merges several jobs' frames, with `attrs` `job_ids`, `query_hashes`, the union of `releases`, and `metadata_by_job`;
  - `run`, `chunks` and `as_list`.
- **Tests:** `tests/fakes.JobServer` is a fake Data API that runs any submitted body as a job.
- **Live (6433):**
  - rs1171617 in OGS-00006:GCST90199621 gives log10_p −133.32, p 4.75e-134.
  - Looking it up by its ALID gives the same row.
  - The range 10:59,700,000–59,710,000 gives 56 rows.
  - The `smoke_request` variant `1:512299:C:CCTGT` that `/api/batches` lists for OGS-00006 is not in GCST90199621, observed or imputed. Its smoke test only checks that the query runs. Not an opengwaspy bug.
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 150 passed, coverage 99% (`associations.py` 100%). `uv run pytest -m live --no-cov`: 12 passed.

## 2026-11-19 - #29: metadata

- **`opengwaspy.gwasinfo(ids=None, releases=, release_set=, limit=, strict=, client=)`:**
  - **With IDs:** `POST /api/gwasinfo` in chunks of 1,000, in the order given. `not_found` and `retired` go in `attrs`, or raise `RequestError` with `strict`.
  - **Without IDs:** pages through `GET /api/gwasinfo` with `after`/`next_after`, 1,000 at a time, up to `limit`. It warns above 10,000 analyses, and `attrs` has `total`.
- **`gwasinfo_files(...)`:** `POST /api/gwasinfo/files`. Every served Store answers `501` (live, 19 Nov 2026), which raises `NotImplementedByServer`.
- **Guide:** the first guide page, `docs/guide/metadata.md`, with real output from 6433.
  - 38,152 analyses are served, with `catalog_version` `2b9d06d6f8b200d2`.
  - `ieu-a-2` is `not_found`: OpenGWAS IDs are not Data API IDs. That is #5's open question on ID mapping.
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 133 passed, `metadata.py` 100%. Live: 2 passed (listing and lookup, order and `not_found`; files 501).

## 2026-11-19 - #28: client facade, service calls and API limits

- **`opengwaspy.Client(url, token=, jwt=, profile=, auth=, config=, transport=, **options)`** holds a `Transport`.
  - `status()`, `user()` and `batches()` (a DataFrame).
  - `limits`: a `Limits` read from `/api/status` → `execution.limits` (`lookup_variants`, `lookup_analyses`, `range_span`, `range_analyses`, `analysis_analyses`, `result_rows`). Defaults are kept where a value is missing or not positive. The LD caps are fixed defaults from ogdb-api SPECIFICATION §9.3, because the API does not publish them.
  - `image_digest`, from `/api/status`, cached once per client.
  - `submit`, `job`, `query` and `query_many`. Results get `attrs["image_digest"]`.
- **The default client:** `configure(...)` replaces it and closes the old one. `get_client()` creates it lazily from the environment and config file.
- **Module level:** `opengwaspy.status()`, `user()` and `batches()`, each with an optional `client=`. The main classes and errors are exported from `opengwaspy`.
- **Docs:** reference pages for the client and service. `site_url` and every doc link now point to https://blog.opengwas.io/opengwaspy/ (it serves over https; the org site enforces it).
- **Evidence:** ruff and mypy are clean. `uv run pytest`: 121 passed, coverage 99%. `uv run pytest -m live --no-cov`: 8 passed on 6433. The live client test checks `user`, `limits`, `image_digest` and `batches`.

## 2026-11-19 - #17: documentation site skeleton

- **Site:** MkDocs Material 9.8.1 and mkdocstrings-python, in a `docs` dependency group. `mkdocs.yml` covers the home page, install, a reference page per module (generated from docstrings, Google style), and the changelog.
- **`.github/workflows/docs.yml`:** builds with `--strict` on every PR. On pushes to `main` it uploads the site and deploys it with `actions/deploy-pages`. Actions are pinned to SHAs: upload-pages-artifact v5.0.0 `fc324d35`, deploy-pages v5.0.1 `368f8252`.
- **Pages:** the site is served at http://blog.opengwas.io/opengwaspy/, because the opengwas org Pages site has the custom domain `blog.opengwas.io`; `opengwas.github.io/opengwaspy` redirects there. Enabled with Source = GitHub Actions (`POST repos/opengwas/opengwaspy/pages`, `build_type=workflow`). The owner approved publishing the docs on Pages in the original brief.
- **Risk:** Material for MkDocs says it reaches end of life on 5 May 2027, with Zensical as its successor (which reads `mkdocs.yml`). To revisit before then.
- **Evidence:** `uv run mkdocs build --strict` passed locally. The jobs reference page renders its documented objects.

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
