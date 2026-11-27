# Workplan

## How to use this file

The [OpenGWASDB project board](https://github.com/orgs/opengwas/projects/1), Workstream **Clients** (named **Python client** until the board's workstreams were renamed), is the one tracker for this repository's work. Epics are on the board, and tickets are their sub-issues in `opengwas/opengwaspy`. The board's README sets the rules.

This file does not track status, so it never disagrees with the board. It keeps:
- pointers to the epics;
- the owner's design decisions, with the ticket each is detailed in;
- open questions waiting on the owner or on other workstreams.

`DEVLOG.md` holds the evidence. `REQUIREMENTS.md` is the product contract.

## Epics

| Epic | Summary | Tickets | Depends on |
|---|---|---|---|
| #2 **opengwaspy has a tested package skeleton and CI** | pyproject (hatchling, uv), ruff, mypy, pytest with `live` marker, CI on Python 3.10–3.14, `.env` handling, licence | #9–#11 | — |
| #3 **opengwaspy runs any Data API query as a job** | transport, errors, retries and `Retry-After`, job submit/poll/page/cancel/resume, bounded concurrency, prefix-relative URLs | #12–#16 | #2 |
| #4 **Every Data API operation has a native opengwaspy function** | service, metadata, associations (+range, +analysis), top hits, PheWAS, variants, LD; DataFrame results with provenance; chunking | filed when #3 lands | #3 |
| #5 **ieugwaspy users can migrate to opengwaspy** | the compat layer, client-side proxies and clumping through the LD operations, PheWAS `pval` filtering, rsID↔ALID mapping, refusals, migration guide, ported usage notebook | filed when #4 lands | #4 |
| #6 **opengwaspy has a published documentation site** | MkDocs Material, user guide, API reference, executed examples, GitHub Pages deployment | #17, #18 | #2 (site skeleton); grows with #4, #5 |
| #7 **opengwaspy works through the Gateway** | `/ogdb` prefix, OpenGWAS JWT provider, `X-Allowance-*` handling, the final login flow behind the auth interface, live tests through the Gateway | filed when the Gateway's auth is decided | #3; the Gateway's user auth workflow (opengwas-gateway) |
| #8 **opengwaspy is released on PyPI** | versioning, changelog, trusted publishing, release checklist, ieugwaspy pointing to its successor | filed at release | #4, #5, #6; owner approval |
| #60 **opengwaspy can find analyses by search** | `gwasinfo_search()` over the API's `/api/gwasinfo/search` (`contains` and FTS5 `fulltext`, filters, paging, typed errors); docs and examples. Proposed defaults in the epic: name `gwasinfo_search`, `limit=100`, POST | #61, #62 | #4; ogdb-api #141, #142 (served on 6433 since 19 Nov 2026) |
| #70 **opengwaspy uses the Data API's PheWAS threshold, server clumping and OpenGWAS ID resolution** | PheWAS `threshold` (#67), top hits `clump` (#68), OpenGWAS IDs and batches resolved on the server (#69), docs (#71); removes the client-side workarounds | #67–#69, #71 | ogdb-api#162 (#165–#167 merged 21 Nov 2026); 6433 redeployed from ogdb-api `main` |
| #88 **opengwaspy has an MCP server for AI assistants** | A local stdio MCP server in the `mcp` extra (`opengwaspy-mcp`): metadata, top hits, associations (+proxies), regions, PheWAS, variants and LD tools over the native functions; results capped for the model, `save_as` to a set folder, long jobs resumable; users' OpenGWAS tokens (JWT) through the Gateway as the primary credential | #89–#95 | #80, #83 (job waits, completeness); #7 for live tests with JWT |
| #107 **opengwaspy keeps pace with the Data API's 0.3.0 Stores, stored Clumps, Rho, HapMap3 and selectable LD Stores** | Follows ogdb-api#198: `tophits(clump=True)` answering from stored Clumps (#109), LD Store choice by the registry's defaults with several Stores per ancestry (#108), `rho()` (#110), HapMap3 extraction (#111) | #108–#111 | ogdb-api#197, #181 (merged 27 Nov 2026); #195, #194, #182 (open) |
| #87 **opengwaspy queries downloaded Store Releases locally through ogquery** | `og.local(paths)`: a Local Source answering the API's requests in process through ogquery's public API, with the API's rows; the `local` extra (Python 3.12+); associations (#113), top hits, PheWAS, variants and metadata (#114), stored Clumps, Rho and HapMap3 (#115), local LD Stores and Genotype Stores (#116), parity on a real Store and a guide (#117) | #113–#117 | ogquery ≥ 0.5 (PyPI); #109–#111 for #115; a redeployed 6433 for #117 |

Order: #2, then #3 and #6's skeleton, then #4, then #5. #60 any time after #4. #7 starts its interface work in #3 (the auth provider, #12), and its integration waits on the Gateway. #8 last.

## Decisions

**27 Nov 2026** (owner asked for local Store queries through ogquery; planned in #87, following opengwasr's owner decisions of 25 Nov 2026 for opengwasr#2)
- **Shape:** `og.local(paths)` returns a `LocalSource` passed as `client`. It answers the same requests the functions send to the API, through ogquery's public API, as ogdb-api's `query_operations.py` does, so frames, chunking and `attrs` are shared. Functions that need the API take a `Client` only and refuse a Local Source with `LocalUnsupported`; nothing falls back to the API silently.
- **Identity:** full paths of Store Releases, at most one per Store; analyses named `store_id:analysis_id` (or an unambiguous bare ID); OpenGWAS IDs refused locally with a pointer to `gwasinfo` on the API.
- **Packaging:** the `local` extra, `ogquery>=0.5,<0.6; python_version >= '3.12'`; Genotype Stores later through `ogquery[genotype]`. The core install and Python 3.10–3.11 are unaffected.
- **Fixtures:** three of ogquery's contract releases are vendored under `tests/data/ogquery-contract/` (about 1 MB).

**19 Nov 2026** (owner, at project setup)
- **Shape:** a native client named after the Data API's fields, plus an ieugwaspy-compatible layer (`opengwaspy.compat`) that composes server operations on the client (proxies through `ld/proxies`, clumping through `ld/clump`, `p` from `log10_p`), and refuses what it cannot honour (REQUIREMENTS §4, §7).
- **Returns:** pandas `DataFrame`s by default, with provenance and metadata attached. pandas is a required dependency.
- **Targets:** Python ≥ 3.10; pyproject with hatchling; PyPI publication later, only once the owner approves a first release.
- **Docs:** MkDocs Material with mkdocstrings, deployed to GitHub Pages by Actions.
- **Board:** a new Workstream, **Python client**. Added to the project's Workstream field and README on 19 Nov 2026; Tool integration's scope line no longer names ieugwaspy.
- **Development API:** the host's Data API at `host.lima.internal:6433`, with a developer key named `opengwaspy` (`OGDB_DEVELOPER_KEYS`), held in the untracked `opengwaspy/.env`.
- **Authentication:** a pluggable provider interface from the start, because the Gateway's user authentication workflow is not final (REQUIREMENTS §8).
- **Licence:** GPLv3 (`LICENSE`), keeping scope for dual licensing. To keep that option open, every contribution must be licensable by the copyright holder: contributors agree to a contributor licence agreement or copyright assignment before a PR from outside the core team is merged (E1 ticket).
- **Compat `tophits` default:** ieugwaspy's default clumping (r² 0.001 within 10 Mb) is refused with `LDRefusal`. The error explains that the LD Stores do not hold r² below `t_far` beyond `near_bp`, and recommends answerable settings: r² ≥ the store's `t_far` (about 0.03; AMR 0.063) with `kb=10000`, or any r² with `kb` ≤ `near_bp` (3,000 kb). It never clumps at other settings silently (E4).
- **Contributor agreements** (owner, 19 Nov 2026; #11): the copyright holder is the University of Bristol. Harmony HA-CLA-I-Any (individuals) and HA-CLA-E-Any (entities), version 1.0, with outbound Option Five (any licence, and always the licence in use on the submission date). Media is also CC BY 4.0, and the governing law is England and Wales. Individuals sign by a PR comment (CLA Assistant Lite; signatures on the `cla-signatures` branch); entities sign on paper through the maintainers.
- **Branch protection** (owner, 19 Nov 2026): `main` requires every CI check (lint and types, tests 3.10–3.14, package, docs, cla). No force pushes.
- **PyPI** (owner, 19 Nov 2026): prepare the release machinery, but do not publish. The owner configures trusted publishing and tags the first release (#57).
- **Merging:** agents may merge their own PRs once checks pass, unless the PR makes a breaking change to the public API or needs human input.

**21 Nov 2026** (owner, planning #70)
- **API for #70:** the owner redeploys 6433 from ogdb-api `main`. Until then, build with unit tests only; then run live tests on 6433. The VM's 7433 stays out of bounds.
- **Native `phewas` threshold:** default to the server's (p ≤ 1e-8), instead of returning every association. This is a breaking change, approved by the owner, and recorded in the changelog (#67).
- **`finn-b` successors in compat:** query the successor FinnGen analysis, warn naming each old → new ID, and record the mapping (`match: successor`) in `attrs` (#69).

**27 Nov 2026** (owner, planning #88)
- **The MCP server** lives in opengwaspy, as the optional extra `mcp` (`mcp>=2.3,<3`; its server class is `MCPServer`), with the console script `opengwaspy-mcp`.
- **Transport:** stdio only in v1. A hosted, multi-user server waits on the Gateway's sign-in flow (#7).
- **Files:** `save_as` writes full results only into one set folder (`OPENGWAS_MCP_OUTPUT_DIR`, default `./opengwas-results`).
- **Tool scope:** as in #88.
- **Default limits:** 50 rows, a 60 s wait, ranges up to 1 Mb.
- **Authentication:** ordinary users use an OpenGWAS token (JWT) through the Gateway; the developer key is for developers only. No tool takes a credential as an argument, and none appears in any output (#94).

## Open questions

| Question | Waiting on | Affects |
|---|---|---|
| The Gateway's final user sign-in flow (device flow, browser, API keys?) and token lifetime | opengwas-gateway | #7 |
| Under load, the API refuses ordinary searches with `400 query_too_broad` (a 1 s clock-time budget), which clients do not retry. Asked for `503` with `Retry-After` instead, which opengwaspy already retries | opengwas/ogdb-api#164 | `gwasinfo_search` |
| ieugwaspy's README and PyPI page pointing to opengwaspy | owner (MRCIEU repo) | #58 |
| PyPI trusted publisher and the `pypi` environment; the first tag | owner | #57 |

Resolved on 21 Nov 2026:
- **A PheWAS p-value filter on the server** (ogdb-api#145) and **clumping every hit on the server** (ogdb-api#146) are merged upstream. The client work is #67 and #68.

Resolved on 19 Nov 2026:
- **rsID → ALID for LD:** through `variants_rsid`, or the ALIDs association rows already carry (#33, #43).
- **`beta` and `n`:** the API serves neither. `compat` derives `beta = z × se` (on the stored effect scale) and `n` from `gwasinfo`, documented as derived (#42).
