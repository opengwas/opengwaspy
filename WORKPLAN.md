# Workplan

## How to use this file

The [OpenGWASDB project board](https://github.com/orgs/opengwas/projects/1), Workstream **Python client**, is the one tracker for this repository's work. Epics are on the board, and tickets are their sub-issues in `opengwas/opengwaspy`. The board's README sets the rules.

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

Order: #2, then #3 and #6's skeleton, then #4, then #5. #60 any time after #4. #7 starts its interface work in #3 (the auth provider, #12), and its integration waits on the Gateway. #8 last.

## Decisions

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
