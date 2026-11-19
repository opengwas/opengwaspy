# Workplan

## How to use this file

The [OpenGWASDB project board](https://github.com/orgs/opengwas/projects/1), Workstream **Python client**, is the one tracker for this repository's work. Epics are on the board, and tickets are their sub-issues in `opengwas/opengwaspy`. The board's README sets the rules.

This file does not track status, so it never disagrees with the board. It keeps:
- pointers to the epics;
- the owner's design decisions, with the ticket each is detailed in;
- open questions waiting on the owner or on other workstreams.

`DEVLOG.md` holds the evidence. `REQUIREMENTS.md` is the product contract.

## Epics

Issue numbers are filled in once the owner approves the board changes.

| # | Epic | Depends on |
|---|---|---|
| E1 | **opengwaspy has a tested package skeleton and CI**: pyproject (hatchling, uv), ruff, mypy, pytest with `live` marker, CI on Python 3.10–3.14, `.env` handling, licence | — |
| E2 | **opengwaspy runs any Data API query as a job**: transport, errors, retries and `Retry-After`, job submit/poll/page/cancel/resume, bounded concurrency, prefix-relative URLs | E1 |
| E3 | **Every Data API operation has a native opengwaspy function**: service, metadata, associations (+range, +analysis), top hits, PheWAS, variants, LD; DataFrame results with provenance; chunking | E2 |
| E4 | **ieugwaspy users can migrate to opengwaspy**: the compat layer, client-side proxies and clumping through the LD operations, PheWAS `pval` filtering, rsID↔ALID mapping, refusals, migration guide, ported usage notebook | E3 |
| E5 | **opengwaspy has a published documentation site**: MkDocs Material, user guide, API reference, executed examples, GitHub Pages deployment | E1 (site skeleton); grows with E3, E4 |
| E6 | **opengwaspy works through the Gateway**: `/ogdb` prefix, OpenGWAS JWT provider, `X-Allowance-*` handling, the final login flow behind the auth interface, live tests through the Gateway | E2; the Gateway's user auth workflow (opengwas-gateway) |
| E7 | **opengwaspy is released on PyPI**: versioning, changelog, trusted publishing, release checklist, ieugwaspy pointing to its successor | E3, E4, E5; owner approval |

Order: E1, then E2 and E5's skeleton, then E3, then E4. E6 starts its interface work in E2 (the auth provider), and its integration waits on the Gateway. E7 last.

## Decisions

**19 Nov 2026** (owner, at project setup)
- **Shape:** a native client named after the Data API's fields, plus an ieugwaspy-compatible layer (`opengwaspy.compat`) that composes server operations on the client (proxies through `ld/proxies`, clumping through `ld/clump`, `p` from `log10_p`), and refuses what it cannot honour (REQUIREMENTS §4, §7).
- **Returns:** pandas `DataFrame`s by default, with provenance and metadata attached. pandas is a required dependency.
- **Targets:** Python ≥ 3.10; pyproject with hatchling; PyPI publication later, only once the owner approves a first release.
- **Docs:** MkDocs Material with mkdocstrings, deployed to GitHub Pages by Actions.
- **Board:** a new Workstream, **Python client**.
- **Development API:** the host's Data API at `host.lima.internal:6433`, with a developer key named `opengwaspy` (`OGDB_DEVELOPER_KEYS`), held in the untracked `opengwaspy/.env`.
- **Authentication:** a pluggable provider interface from the start, because the Gateway's user authentication workflow is not final (REQUIREMENTS §8).

## Open questions

| Question | Waiting on | Affects |
|---|---|---|
| Licence (ieugwaspy is MIT) | owner | E1 |
| The Gateway's final user login flow (device flow, browser, API keys?) and token lifetime | opengwas-gateway | E6 |
| ieugwaspy's `tophits` default (clump at r² 0.001, 10 Mb) is refused by every LD Store. Refuse, or clump at the nearest answerable setting with a warning? | owner | E4 |
| Mapping from OpenGWAS IDs (`ieu-a-2`) and `batch` to Data API analyses and Stores | ogdb-api / Analysis Catalog | E4 |
| rsID → ALID for LD queries: through `variants/rsid` per Store, or does the LD Store need its own lookup? (ogld#79) | ogdb-api | E4 |
| Will the API return `beta` and `n` in association rows? | ogdb-api | E3, E4 |
| ieugwaspy's README and PyPI page pointing to opengwaspy | owner (MRCIEU repo) | E7 |
