# Contributing to opengwaspy

Thank you for helping. opengwaspy is the Python client for the OpenGWAS Data API.

## Before you start

- **Sign the Contributor License Agreement.** Every contribution from outside the University of Bristol needs one; see [CLA.md](CLA.md). The CLA bot asks you to sign on your first pull request.
- **Find or open an issue.** Planned work is tracked as issues in this repository, and on the [OpenGWASDB project board](https://github.com/orgs/opengwas/projects/1) (Workstream: Python client). For anything larger than a small fix, discuss it in an issue first.
- **Read** [REQUIREMENTS.md](REQUIREMENTS.md), the contract the package follows. One principle matters above all: the client never silently returns a different scientific answer from the one asked for. An option is either honoured or refused with a clear error.

## Development

You need [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run ruff format . && uv run ruff check .
uv run mypy
uv run pytest                    # offline unit tests, at least 90% coverage
uv run pytest -m live --no-cov   # optional: live tests, with OPENGWAS_URL and OPENGWAS_TOKEN set
```

- Add or update tests with every change in behaviour. Unit tests must not use the network.
- Every public function has a typed signature and a Google-style docstring: the documentation is generated from them.
- Never commit credentials. `.env` is gitignored.

## Pull requests

- One purpose per pull request. Name the issue (`Closes #n`).
- Every check must pass: lint, types, tests on Python 3.10–3.14, and the CLA.
- Update the documentation when behaviour changes.

## Licence

By contributing, you agree that your contribution is licensed as described in the CLA you signed. opengwaspy is released under GPL-3.0-only ([LICENSE](LICENSE)).
