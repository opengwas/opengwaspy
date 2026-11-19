# opengwaspy

The Python client for the [OpenGWAS](https://opengwas.io) Data API. It queries GWAS metadata, associations, top hits, PheWAS, variants and LD, and returns pandas DataFrames.

opengwaspy succeeds [ieugwaspy](https://github.com/MRCIEU/ieugwaspy). It talks to the new, job-based Data API, and offers an ieugwaspy-compatible layer for existing code.

> **Status: pre-alpha.** Under active development; nothing is released yet. Progress is tracked on the [OpenGWASDB project board](https://github.com/orgs/opengwas/projects/1) (Workstream: Python client).

## Documentation

https://opengwas.github.io/opengwaspy/ (coming soon).

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                          # create .venv with the dev tools
uv run ruff format . && uv run ruff check .
uv run mypy
uv run pytest                    # unit tests: offline, with coverage (at least 90%)
uv run pytest -m live --no-cov   # live tests against the API (see below)
```

Live tests need `OPENGWAS_URL` and `OPENGWAS_TOKEN`, in the environment or in a `.env` file at the repository root (copy `.env.example`). `.env` is gitignored: never commit a key.

Contributors and coding agents should read [AGENTS.md](AGENTS.md), [REQUIREMENTS.md](REQUIREMENTS.md) and [WORKPLAN.md](WORKPLAN.md).

## Licence

GPL-3.0-only. See [LICENSE](LICENSE).
