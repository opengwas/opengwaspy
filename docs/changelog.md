# Changelog

## Unreleased

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
