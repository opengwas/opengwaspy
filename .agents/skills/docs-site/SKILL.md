---
name: docs-site
description: "Build, check, preview and deploy opengwaspy's MkDocs Material documentation site to GitHub Pages. Use when docs, docstrings or examples change, or to publish the site."
---

# Docs site

The site is MkDocs Material with mkdocstrings (the API reference from docstrings). It is published at https://blog.opengwas.io/opengwaspy/ by `.github/workflows/docs.yml` on pushes to `main`.

## Build and check

```bash
uv sync --group docs
uv run mkdocs build --strict          # fails on broken links, missing references, bad docstrings
```

- Examples are executed during the build against recorded responses (`tests/fixtures/`), so the site builds offline and in CI.
- `OPENGWAS_LIVE=1` runs them against the live API instead. Do this through the `live-check` skill, which records the evidence.

## Preview

`uv run mkdocs serve -a 127.0.0.1:8765`. Never use 6432–6434, which lima forwards to the host. Stop the server when done.

## Content rules

- Plain, short sentences, matching the ogdb-api guide's style. Explain what a result means, not only how to get it.
- Each guide page shows the call, its real (recorded) output, and what can go wrong: the errors and refusals, and what to ask instead.
- The migration page lists every ieugwaspy 1.0.6 function. Each one is "same", "differs" (with how), or "not available" (with why and the alternative).
- A behaviour change in code updates its guide page in the same PR.

## Deploy

- Pushes to `main` deploy through the Pages workflow (`actions/deploy-pages`). Check the run with `gh run list -R opengwas/opengwaspy -w docs`.
- **First publication:** ask the owner before enabling Pages. Then enable it (Source: GitHub Actions) with `gh api -X POST repos/opengwas/opengwaspy/pages -f build_type=workflow`, or the owner enables it in Settings → Pages.
- After a deploy, fetch the site's front page and one API reference page to confirm, and record the run URL in `DEVLOG.md`.
