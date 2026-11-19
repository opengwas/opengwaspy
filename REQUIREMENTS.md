# opengwaspy requirements

The product contract for `opengwaspy`, the Python client for the OpenGWAS Data API. Agents treat this file as the source of truth (see `AGENTS.md`). Changes to it are the owner's decisions, recorded with a date in `WORKPLAN.md`.

## 1. Purpose

`opengwaspy` lets Python users query OpenGWAS: its metadata, associations, top hits, PheWAS, variants and LD. It succeeds [ieugwaspy](https://github.com/MRCIEU/ieugwaspy) 1.0.6, whose functionality it must replicate, on the new job-based Data API ([ogdb-api](https://github.com/opengwas/ogdb-api)). It is first developed directly against the Data API, and then moves to the OpenGWAS Gateway, whose user authentication workflow is not yet final.

## 2. Users and use

- Researchers in notebooks and scripts, who want a table back from one call and do not want to manage jobs.
- Pipeline authors (Mendelian randomisation, colocalisation, PheWAS screens), who need predictable errors, resumable long queries and polite use of shared capacity.
- Former ieugwaspy users, who need a short, honest path from their old calls.

## 3. Scope

### 3.1 In scope

1. **Transport and jobs** (§5): authentication, base URL and prefix, JSON requests, retries, and the complete job flow: submit, poll, page, cancel and resume.
2. **The native API** (§6): one function per Data API operation, named after the Data API's own fields.
3. **The ieugwaspy-compatible layer** (§7): ieugwaspy's functions, with their defaults either honoured by composing server operations on the client, or refused.
4. **Configuration and authentication** (§8), which is pluggable so the Gateway's future login flow fits without breaking callers.
5. **Documentation** (§9), published on GitHub Pages.
6. **Packaging** (§10), for publication to PyPI when the owner approves.

### 3.2 Out of scope

- Writing to OpenGWAS (uploads, edits). The Data API is read-only.
- Re-implementing server operations locally with PLINK or reference panels (unlike ieugwasr's `bfile=`).
- Endpoints the Data API answers `501` for (`variants/gene`, `afl2`, `edit`). The client does not offer them; the migration guide says so.
- A compatibility shim that makes `import ieugwaspy` work unchanged. Callers change their import and read the migration guide.

## 4. Principles

1. **Never return different science silently.** An option is either honoured faithfully or refused with `UnsupportedOptionError`, naming the option and the alternative. It is never ignored. The client raises if the API reports `ignored_fields`, since that means a client bug.
2. **One call, one table.** Query functions block until the result is complete, and return a pandas `DataFrame`. Jobs stay available for callers who want them.
3. **Polite by construction.** Follow `poll_after_seconds` and `Retry-After`, back off with jitter, never resubmit in a tight loop, and keep chunking bounded.
4. **Provenance travels with the rows.** Every result carries the job IDs, `query_hash`, `release_id`s, the API's `image_digest` where known, and the operation's metadata (`truncated`, `not_found`, `absent`).
5. **Stable public API.** Semantic versioning; deprecations warn for at least one minor release.

## 5. Transport and jobs

### 5.1 Requests

- JSON bodies only (the Data API refuses form bodies).
- Headers: `Authorization` from the auth provider (§8); `User-Agent` and `X-API-Source: opengwaspy/<version>`; an `X-Request-ID` per logical call (1–128 characters from `A-Z a-z 0-9 . _ : -`), which is surfaced in errors for support.
- Paths returned by the API (`status_url`, `result_url`, `Location`) are absolute paths without a host. They are resolved against the configured base URL's origin, so the Gateway's `/ogdb` prefix works without special cases.
- Timeouts are configurable; the defaults suit a slow link.

### 5.2 Errors

- Every API error becomes a typed exception carrying `status`, `error` (the stable code), `message`, `request_id`, and any extra fields (for example `indexed_thresholds`, `reason`, `t_far`, `superseded_by`).
- The hierarchy separates what to fix from what to retry: `RequestError` (400, 404, 409, 410, 413, 422), `AuthError` (401, 403), `RateLimitError` and `BusyError` (429, 503), `NotImplementedByServer` (the exact `501 Not yet implemented`), and `JobFailed` (with `error_kind` `request` or `temporary`).
- `ld_refusal` (422) maps to `LDRefusal`, which explains what the store can answer: any r² within `near_bp`, and r² ≥ `t_far` up to `far_bp`.

### 5.3 Retries

- **429 and 503 with `Retry-After`**: wait that long, then retry, up to a configurable total wait (default 10 minutes). `queue_wait_too_long`, `user_queue_full`, `results_quota_exceeded` and `server_busy` are all retried this way. When the total is exhausted, raise with the last body.
- **Transport errors and other 5xx**: bounded exponential backoff with jitter (default 5 attempts).
- **Resubmission is safe**, because the API keys jobs by user and `query_hash`, and returns the existing job (`existing: true`).
- **The Gateway's `X-Allowance-Remaining: 0`** blocks further calls until the reset time, as ieugwaspy did, with a clear message.

### 5.4 The job flow

- `submit(endpoint, body) -> Job`; `Job.status()`, `Job.wait(timeout=None, progress=...)`, `Job.pages()`, `Job.rows()`, `Job.to_frame()`, `Job.cancel()`.
- Polling uses `poll_after_seconds` from each status. It never polls faster than 1 s, and never slower than the API suggests.
- Pages are read with `cursor` until `final`. Each page's `sha256` is verified over its `ndjson`.
- `410 result_expired` while paging resubmits the query once, then fails clearly.
- A `KeyboardInterrupt` during `wait` offers cancellation: the job is cancelled unless the caller passed `cancel_on_interrupt=False`.
- **Many jobs:** a helper submits a list of queries, keeps at most N jobs in flight (default 4, under the API's per-user queue cap), and gathers their frames in order.
- **Resumability:** a `Job` can be rebuilt from its `job_id`, so a long pipeline can restart without resubmitting work.

## 6. The native API

One function per operation. Each takes keyword arguments named as the Data API names its fields, validates them locally (types, the API's documented limits), and returns a `Result`: a `DataFrame` subclass or wrapper whose `.attrs` carry provenance and metadata (§4.4).

| Area | Functions | Data API |
|---|---|---|
| Service | `status()`, `user()`, `batches()` | `GET /api/status`, `/api/user`, `/api/batches` |
| Metadata | `gwasinfo(ids=None, release_set=None)` (pages transparently), `gwasinfo_files(...)` | `GET`/`POST /api/gwasinfo`, `POST /api/gwasinfo/files` |
| Associations | `associations(variants=, rsids=, analyses=, observed_only=, releases=)`, `associations_range(chromosome, start, end, ...)`, `associations_analysis(analyses, ...)` | `/api/associations`, `/range`, `/analysis` |
| Top hits | `tophits(analyses, threshold=5e-8, limit=1000, observed_only=False, releases=)` | `/api/tophits` |
| PheWAS | `phewas(variant, releases, analyses=, limit=, observed_only=)` | `/api/phewas` |
| Variants | `variants_rsid(rsids, releases=)`, `variants_chrpos(positions, releases=)` | `/api/variants/rsid`, `/chrpos` |
| LD | `ld_stores()`, `ld_matrix(alids, ancestry= or store=, fill=)`, `ld_region(...)`, `ld_clump(alids, scores, r2, kb, ...)`, `ld_proxies(...)`, `ld_reflookup(...)` | `/api/ld/*` |

- **Chunking.** Requests above an operation's per-job limit (for example 100 analyses and 1,000 variants for associations, 500 ALIDs for an LD matrix) are split into jobs within the limit and merged, preserving order. Where splitting would change the answer (for example clumping, or an LD matrix), the client refuses, rather than splitting.
- **Large ranges.** `associations_range` splits a range into windows of at most 10 Mb (the API's limit for Dense and Hybrid analyses), and whole Dense or Hybrid analyses are fetched as ranges.
- **Derived columns.** `p` is derived as `10 ** log10_p` (the API's `log10_p` is log10 of p, so it is negative or zero), and `beta` and `n` are added only when the API provides them. Each derived column is documented as derived.

## 7. The ieugwaspy-compatible layer

`opengwaspy.compat` offers ieugwaspy's functions with ieugwaspy's names, signatures and defaults: `gwasinfo`, `gwasinfo_files`, `associations`, `tophits`, `phewas`, `variants_chrpos`, `variants_to_rsid`, `legacy_ids`, `status`, `user`, `select_api` and `get_jwt`. It returns DataFrames whose columns follow the old names where a faithful equivalent exists (`id`, `trait`, `rsid`, `p`, `beta`, `se`, `eaf`, `n`, `ea`, `nea`), with the Data API's columns kept alongside.

Each default is honoured by composing server operations, or refused:

| ieugwaspy call and default | How opengwaspy honours it |
|---|---|
| `associations(proxies=1, r2=0.8)` | Look the variants up. For variants absent from an analysis, ask `ld/proxies` (r² ≥ `r2`) in the requested ancestry's LD Store, fetch the best proxy present, and align its alleles (`align_alleles=1`), dropping or inferring palindromes by `maf_threshold` as ieugwasr does. Rows are flagged as proxies (`proxy`, `target_snp`, `proxy_snp`, `proxy_r2`). |
| `tophits(clump=1, r2=0.001, kb=10000, pop="EUR")` | Fetch top hits, map them to ALIDs, and clump with `ld/clump` (scores \|z\|). The API's stores refuse r² 0.001 within 10 Mb (`threshold_below_t_far`), so the compat layer raises `LDRefusal` before submitting. The error explains why, and recommends answerable settings from the store's facts (`ld_stores()`): r² ≥ `t_far` with `kb=10000`, or any r² with `kb` ≤ `near_bp`. Answerable settings passed explicitly are honoured. |
| `tophits(preclumped=1, bychr=0, force_server=False)` | Accepted for compatibility. They no longer change the result, and this is documented. |
| `phewas(variant=[...], pval=1e-3, batch=[])` | One PheWAS job per variant. Filter to `p <= pval` on the client, and raise if the server truncated the result before the filter could see every row. `batch` maps to the corresponding releases, or is refused. |
| `variants_chrpos("chr:pos")`, `variants_to_rsid` | `variants/chrpos`, returning the first rsID as ieugwaspy did, and warning when a position has several. |
| `gwasinfo()` with no IDs | Pages through every analysis. Warns about the size. |
| `select_api(key)`, `get_jwt()` | Mapped to the configuration and auth providers of §8. |

Where the compat layer still differs from OpenGWAS (IDs, stores, available columns), the migration guide says so in a table generated from the same source as `../ogdb-api/docs/client-mapping.md`.

## 8. Configuration and authentication

- **Configuration precedence:** explicit arguments, then environment variables (`OPENGWAS_URL`, `OPENGWAS_TOKEN`, `OPENGWAS_JWT`), then a user config file in the platform config directory, then defaults. The project directory's `.env` is not read implicitly.
- **Auth providers** are an interface: `apply(request)`, and `refresh()` on 401.
  - `DeveloperKey`: a Data API developer key, as a Bearer token, used directly against the Data API.
  - `OpenGWASToken`: an OpenGWAS JWT (today issued at `api.opengwas.io/profile`, valid 14 days), sent to the Gateway.
  - `GatewayLogin` (later): the Gateway's final user flow, for example an OAuth device or browser login with token refresh. It is added without changing callers' code.
- **Base URL profiles** (as `select_api` had): `gateway` (the default once the Gateway is live, with prefix `/ogdb`), `direct` (the Data API), and `dev`. Paths are resolved as in §5.1.
- Tokens are stored only where the user chooses, with file mode 0600, and are never logged or shown in `repr`.

## 9. Documentation

A MkDocs Material site on GitHub Pages (`https://opengwas.github.io/opengwaspy/`), built and deployed by GitHub Actions from `main`:

- Install, quickstart and authentication (direct now; the Gateway when live).
- A user guide per area: metadata, associations, top hits, PheWAS, variants and LD, and jobs and large queries.
- **Migrating from ieugwaspy:** each old call, its new equivalent, and every behaviour that differs, with the reasons.
- An API reference generated from docstrings (mkdocstrings).
- Examples executed in CI against recorded responses, and against the live API in the `live-check` skill, so that published output is real.
- A changelog.

## 10. Packaging and quality

- `pyproject.toml` with hatchling; the `src/opengwaspy` layout; `py.typed`.
- Python ≥ 3.10, tested in CI on 3.10 to 3.14.
- Runtime dependencies kept small: `httpx`, `pandas`. Optional extras are allowed if a later need arises.
- ruff (lint and format) and mypy (strict on `src/`). Unit test coverage of at least 90% on `src/`.
- PyPI publishing through trusted publishing, triggered by a release tag, only once the owner approves the first release.
- Licence: GPLv3 (`LICENSE`), with scope for dual licensing; contributions need a contributor agreement (WORKPLAN, 19 Nov 2026).

## 11. Acceptance

A release is acceptable when:
1. Every row of §6's table has a function, unit tests, and a passing live test against the API.
2. Every ieugwaspy 1.0.6 public function has a documented compat equivalent or a documented, tested refusal.
3. ieugwaspy's `usage_examples.ipynb` scenarios run as a notebook in the docs, rewritten for opengwaspy.
4. Retries, `Retry-After`, expiry, cancellation and paging are covered by tests against simulated responses.
5. The docs site builds with `--strict` and is published.
6. The same code works against the Gateway with a JWT once the Gateway is reachable (the Gateway epic).
