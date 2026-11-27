# Changelog

## Unreleased

- An MCP server for AI assistants (preview): the `mcp` extra and the `opengwaspy-mcp` command, over stdio, with tools `api_status`, `search_analyses`, `get_analyses`, `top_hits` (optionally clumped), `associations` (optionally with LD proxies), `region_associations`, `phewas`, `variant_info`, `ld_proxies` and `ld_matrix`. OpenGWAS IDs are translated. Results are trimmed for the model (a summary, main columns, up to 100 rows) with provenance. It uses the usual configuration, and never takes or returns a credential.
- `compat` takes OpenGWAS IDs (`ukb-b`, `ebi-a`, `eqtl-a`, and `finn-b` as successors, with a warning), translated by the Data API. Results add `opengwas_id`, and `attrs["opengwas_ids"]` records each translation. `compat.phewas(batch=...)` takes OpenGWAS batches too.
- `gwasinfo()` records the API's OpenGWAS ID resolution in `attrs["opengwas"]`, and `batches()` records `attrs["opengwas_batches"]`.
- `tophits(clump=...)`: clump every hit on the server and return the leads, with `clump_size`, and the clump's counts in `attrs["clump"]`.
- `compat.tophits` clumps on the server, from every hit. It used to clump only the strongest 10,000 hits on the client (OGS-00011:GCST90179150, BMI: 770 leads now, 118 before).
- **Breaking:** `phewas()` now takes `threshold`, applied on the server, and defaults to the Data API's p ≤ 1e-8. It used to return every association; pass `threshold=1` for that. `attrs["threshold"]` records the threshold applied.
- `compat.phewas(pval=...)` sends `pval` to the server, so it no longer fetches every association, reruns truncated Stores, or refuses Stores holding more than 10,000 of a variant's associations.
- Package skeleton, CI on Python 3.10–3.14, GPL-3.0-only with Harmony contributor agreements.
- Configuration (`Config`), base URL profiles, and pluggable authentication (`DeveloperKey`, `OpenGWASToken`).
- Typed errors for every Data API error code, and an HTTP transport that retries politely.
- Jobs: submit, wait, page, verify, cancel and resume; `run_many` for batches.
- `Client`, `configure()` and a default client; `status()`, `user()` and `batches()`; the API's limits and `image_digest` in each result's provenance.
- `gwasinfo()`: look up analyses by ID, in order, or list them page by page; `gwasinfo_files()`.
- `gwasinfo_search()`: find analyses by label, or by a full-text query over label, trait, consortium, first author and IDs, with exact filters.
- `associations()`, `associations_range()` (10 Mb windows) and `associations_analysis()`, chunked within the API's published limits, with a derived `p` column.
- `tophits()` (not clumped; truncation warned) and `phewas()` (every PheWAS-capable release by default, 10 per job).
- The default client is closed at interpreter exit.
- `variants_rsid()` and `variants_chrpos()`, across every served Store by default.
- LD: `ld_stores()`, `ld_matrix()` and `ld_region()` (square r matrices), `ld_clump()`, `ld_proxies()` and `ld_reflookup()`. `LDRefusal` says what the store can answer instead.
- `opengwaspy.compat`: ieugwaspy's functions and defaults, with proxies and clumping through the LD stores, and refusals where the Data API cannot answer exactly.
- The migration guide from ieugwaspy, and ieugwaspy's usage examples, rewritten.
